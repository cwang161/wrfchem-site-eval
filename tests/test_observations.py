from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from wrfchem_site_eval.errors import ConfigError
from wrfchem_site_eval.observations import read_observations, station_table


def _write_yaml(path: Path, value: dict) -> Path:
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def test_read_chem_qc_masks_rejected_flags(tmp_path):
    source = tmp_path / "chem.csv"
    pd.DataFrame({
        "Time": ["2019-01-01 00:00:00", "2019-01-01 01:00:00"],
        "code": ["I000", "I000"],
        "latitude": [26.9, 26.9],
        "longitude": [75.8, 75.8],
        "pm25": [88.0, 99.0],
        "pm25_qc_flag": ["valid", "gross_error"],
    }).to_csv(source, index=False)
    config = _write_yaml(tmp_path / "chem.yaml", {
        "dataset": {"profile": "chem_qc", "file": "chem.csv", "format": "auto"},
        "columns": {
            "station_id": "code", "time": "Time",
            "latitude": "latitude", "longitude": "longitude",
        },
        "time": {"timezone": "UTC"},
        "variables": {
            "pm25": {
                "column": "pm25", "qc_flag_column": "pm25_qc_flag",
                "accepted_qc_flags": ["valid"],
            }
        },
    })
    result = read_observations(config)
    assert result.loc[0, "pm25"] == 88.0
    assert np.isnan(result.loc[1, "pm25"])
    assert result.loc[1, "pm25_qc_flag"] == "gross_error"
    assert station_table(result).to_dict("records") == [
        {"station_id": "I000", "latitude": 26.9, "longitude": 75.8}
    ]


def test_read_isd_met_scales_and_derives_rh(tmp_path):
    source = tmp_path / "met.csv"
    pd.DataFrame({
        "Time": ["2019-01-01 00:00:00"], "Site": ["360900-99999"],
        "LAT": [51.133], "LON": [93.683], "Temp": [100],
        "Dew_point": [50], "Wind_speed": [20],
    }).to_csv(source, index=False)
    config = _write_yaml(tmp_path / "met.yaml", {
        "dataset": {"profile": "isd_hourly_met", "file": "met.csv", "format": "csv"},
        "columns": {
            "station_id": "Site", "time": "Time", "latitude": "LAT", "longitude": "LON",
        },
        "time": {"timezone": "UTC"},
        "variables": {
            "temperature": {"column": "Temp", "scale": 0.1, "offset": 273.15},
            "dew_point": {"column": "Dew_point", "scale": 0.1, "offset": 273.15},
            "wind_speed": {"column": "Wind_speed", "scale": 0.1},
        },
        "derived": {
            "relative_humidity": {
                "method": "temperature_dewpoint",
                "temperature": "temperature", "dew_point": "dew_point",
            }
        },
    })
    result = read_observations(config)
    assert result.loc[0, "temperature"] == pytest.approx(283.15)
    assert result.loc[0, "wind_speed"] == pytest.approx(2.0)
    assert 0.70 < result.loc[0, "relative_humidity"] < 0.72


def test_station_table_rejects_changing_coordinates():
    observations = pd.DataFrame({
        "station_id": ["A", "A"], "time": pd.date_range("2019-01-01", periods=2, freq="h"),
        "latitude": [30.0, 31.0], "longitude": [105.0, 105.0],
    })
    with pytest.raises(ConfigError, match="change over time"):
        station_table(observations)


def test_combined_sources_coalesces_variables(tmp_path):
    pd.DataFrame({
        "Time": ["2019-01-01"], "Site": ["A"], "LAT": [10.0], "LON": [100.0], "Temp": [300.0],
    }).to_csv(tmp_path / "met.csv", index=False)
    pd.DataFrame({
        "Time": ["2019-01-01"], "Site": ["A"], "LAT": [10.0], "LON": [100.0], "Rain": [1.0],
    }).to_csv(tmp_path / "rain.csv", index=False)
    base = {
        "dataset": {"profile": "combined_wide"},
        "columns": {"station_id": "Site", "time": "Time", "latitude": "LAT", "longitude": "LON"},
        "time": {"timezone": "UTC"},
    }
    _write_yaml(tmp_path / "met.yaml", {
        **base, "dataset": {**base["dataset"], "file": "met.csv"},
        "variables": {"temperature": {"column": "Temp"}},
    })
    _write_yaml(tmp_path / "rain.yaml", {
        **base, "dataset": {**base["dataset"], "file": "rain.csv"},
        "variables": {"precipitation": {"column": "Rain", "scale": 25.4}},
    })
    combined = _write_yaml(tmp_path / "combined.yaml", {
        "dataset": {"profile": "combined_sources"}, "sources": ["met.yaml", "rain.yaml"],
    })
    result = read_observations(combined)
    assert len(result) == 1
    assert result.loc[0, "temperature"] == 300.0
    assert result.loc[0, "precipitation"] == pytest.approx(25.4)
