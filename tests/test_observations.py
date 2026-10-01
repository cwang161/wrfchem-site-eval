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
        "dataset": {"profile": "combined_wide", "file": "chem.csv", "format": "auto"},
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
        "dataset": {"profile": "combined_wide", "file": "met.csv", "format": "csv"},
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


def test_station_coordinate_tolerance_preserves_first_source():
    from wrfchem_site_eval.observations import _harmonize_station_coordinates
    data = pd.DataFrame({
        "station_id": ["A", "A"],
        "latitude": [57.19, 57.189567],
        "longitude": [65.324, 65.3243],
        "precipitation": [1.0, 2.0],
    })
    unified = _harmonize_station_coordinates(data, 100)
    assert unified["latitude"].tolist() == [57.19, 57.19]
    assert unified["longitude"].tolist() == [65.324, 65.324]
    assert unified["precipitation"].tolist() == [1.0, 2.0]
    with pytest.raises(ConfigError, match="exceed tolerance"):
        _harmonize_station_coordinates(data, 10)


def test_combined_sources_coordinate_tolerance(tmp_path):
    for name, lat, lon, value in [("isd", 57.19, 65.324, 1), ("gsod", 57.189567, 65.3243, 2)]:
        pd.DataFrame({"station": ["A"], "date": ["2019-01-01"], "lat": [lat], "lon": [lon], "rain": [value]}).to_csv(tmp_path / f"{name}.csv", index=False)
        _write_yaml(tmp_path / f"{name}.yaml", {
            "dataset": {"profile": "combined_wide", "file": f"{name}.csv"},
            "columns": {"station_id": "station", "time": "date", "latitude": "lat", "longitude": "lon"},
            "variables": {"precipitation": {"column": "rain"}},
        })
    config = {"dataset": {"profile": "combined_sources"}, "sources": ["isd.yaml", "gsod.yaml"],
              "station_coordinates": {"tolerance_m": 100, "reference": "first_source"}}
    path = _write_yaml(tmp_path / "combined.yaml", config)
    result = read_observations(path)
    assert result.loc[0, "latitude"] == 57.19
    assert result.loc[0, "precipitation"] == 1
    station_table(result)
    config["station_coordinates"]["tolerance_m"] = 10
    _write_yaml(path, config)
    with pytest.raises(ConfigError, match="exceed tolerance"):
        read_observations(path)


def test_coordinate_conflicts_use_reference_and_report_all(capsys):
    from wrfchem_site_eval.observations import _harmonize_station_coordinates
    ids = [f"S{i:02d}" for i in range(12)]
    data = pd.DataFrame({"station_id": ids + ids, "latitude": [40.] * 12 + [41.] * 12,
                         "longitude": [100.] * 24})
    result = _harmonize_station_coordinates(data, 100, on_conflict="use_reference")
    assert (result.latitude == 40).all()
    output = capsys.readouterr().out
    assert all(station in output for station in ids)
    assert "12 stations" in output


def test_coordinate_rounding_and_conflict_reporting(capsys):
    from wrfchem_site_eval.observations import _harmonize_station_coordinates
    data = pd.DataFrame({"station_id": ["A", "A", "B", "B"],
        "latitude": [57.19, 57.189567, 40.0, 40.2],
        "longitude": [65.324, 65.3243, 100., 100.]})
    result = _harmonize_station_coordinates(data, 0, on_conflict="use_reference", method="rounding")
    assert result.latitude.tolist() == [57.19, 57.19, 40., 40.]
    output = capsys.readouterr().out
    assert "1 stations" in output and "B," in output and "A," not in output
    with pytest.raises(ConfigError):
        _harmonize_station_coordinates(data, 0, method="rounding")
    assert "B," in capsys.readouterr().out


def test_rounding_uses_reference_axis_precision():
    from wrfchem_site_eval.observations import _harmonize_station_coordinates
    data = pd.DataFrame({"station_id": ["A", "A"],
                         "latitude": [57.19, 57.189567],
                         "longitude": [65.324, 65.3243]})
    data.attrs["coordinate_precision"] = {("A", "latitude"): 2, ("A", "longitude"): 3}
    result = _harmonize_station_coordinates(data, 0, method="rounding")
    assert result.longitude.tolist() == [65.324, 65.324]
    data.loc[1, "longitude"] = 65.3246
    with pytest.raises(ConfigError):
        _harmonize_station_coordinates(data, 0, method="rounding")


def test_csv_preserves_coordinate_trailing_zero_precision(tmp_path):
    (tmp_path / "obs.csv").write_text("station,date,lat,lon\nA,2019-01-01,57.190,65.32\n")
    path = _write_yaml(tmp_path / "obs.yaml", {
        "dataset": {"profile": "combined_wide", "file": "obs.csv"},
        "columns": {"station_id": "station", "time": "date", "latitude": "lat", "longitude": "lon"},
        "variables": {},
    })
    result = read_observations(path)
    assert result.attrs["coordinate_precision"][("A", "latitude")] == 3
    assert result.attrs["coordinate_precision"][("A", "longitude")] == 2


def test_trace_precipitation_conversion_and_qc(tmp_path):
    pd.DataFrame({
        'site': ['A'] * 5, 'time': pd.date_range('2019-01-01', periods=5, freq='h'),
        'lat': [30] * 5, 'lon': [110] * 5,
        'rain': [-1, 0, 12, -9999, -1], 'qc': [0, 0, 0, 0, 1],
    }).to_csv(tmp_path / 'rain.csv', index=False)
    config = {
        'dataset': {'profile': 'combined_wide', 'file': 'rain.csv'},
        'columns': {'station_id': 'site', 'time': 'time', 'latitude': 'lat', 'longitude': 'lon'},
        'missing_values': [-9999],
        'variables': {'precipitation': {
            'column': 'rain', 'source_unit': 'mm_scaled_10', 'target_unit': 'mm',
            'scale': 0.1, 'trace_values': [-1], 'trace_replacement': 0.02,
            'qc_flag_column': 'qc', 'accepted_qc_flags': [0],
        }},
    }
    result = read_observations(_write_yaml(tmp_path / 'rain.yaml', config))
    assert result.precipitation.iloc[:3].tolist() == pytest.approx([0.02, 0, 1.2])
    assert result.precipitation.iloc[3:].isna().all()
    assert result.precipitation_trace.iloc[:3].tolist() == [True, False, False]
    assert result.precipitation_trace.iloc[3:].isna().all()
    config['variables']['precipitation']['unit'] = 'mm'
    with pytest.raises(ConfigError, match='source_unit and target_unit'):
        read_observations(_write_yaml(tmp_path / 'rain.yaml', config))


@pytest.mark.parametrize('profile', ['chem_qc', 'isd_hourly_met', 'combined_long'])
def test_removed_profiles_are_rejected(tmp_path, profile):
    with pytest.raises(ConfigError, match='Supported profiles'):
        read_observations(_write_yaml(tmp_path / 'invalid.yaml', {'dataset': {'profile': profile}}))


@pytest.mark.parametrize("enabled", [True, False])
def test_gsod_eod_time_and_uppercase_flags(tmp_path, enabled):
    pd.DataFrame({"site": ["A", "B", "C"], "date": ["2026-01-01"] * 3,
                  "lat": [30] * 3, "lon": [110] * 3, "EOD": [3, 0, 24],
                  "rain": [1] * 3, "flag": ["g", "D", "f"]}).to_csv(tmp_path / "gsod.csv", index=False)
    config = {"dataset": {"profile": "combined_wide", "file": "gsod.csv"},
              "columns": {"station_id": "site", "time": "date", "latitude": "lat", "longitude": "lon"},
              "time": {"timezone": "UTC"},
              "precipitation_time": {"reset_using_eod": enabled, "eod_column": "EOD"},
              "variables": {"precipitation": {"column": "rain", "scale": 25.4,
                             "qc_flag_column": "flag", "qc_flag_case": "upper", "accepted_qc_flags": ["G", "D", "F"]}}}
    path = _write_yaml(tmp_path / "gsod.yaml", config)
    result = read_observations(path)
    expected = ["2026-01-01 03:00", "2026-01-01 00:00", "2026-01-02 00:00"] if enabled else ["2026-01-01"] * 3
    assert result.time.tolist() == pd.to_datetime(expected).tolist()
    assert result.precipitation_qc_flag.tolist() == ["G", "D", "F"]
    assert result.precipitation.tolist() == [25.4] * 3
    if enabled:
        config["precipitation_time"]["eod_column"] = "absent"
        with pytest.raises(ConfigError, match="Required EOD column"):
            read_observations(_write_yaml(path, config))
        config["precipitation_time"]["eod_column"] = "EOD"
        raw = pd.read_csv(tmp_path / "gsod.csv")
        raw.loc[0, "EOD"] = 25
        raw.to_csv(tmp_path / "gsod.csv", index=False)
        with pytest.raises(ConfigError, match="Invalid EOD"):
            read_observations(_write_yaml(path, config))


def test_gsod_missing_eod_and_zero_attributes(tmp_path, capsys):
    pd.DataFrame({'site': ['A','B','C','D'], 'date': ['2026-01-01'] * 4,
                  'lat': [30]*4, 'lon': [110]*4, 'EOD': [None,3,None,24],
                  'rain': [0,1,2,0], 'flag': ['D','G','H','H']}).to_csv(tmp_path/'gsod.csv', index=False)
    config = {'dataset': {'profile':'combined_wide','file':'gsod.csv'},
              'columns': {'station_id':'site','time':'date','latitude':'lat','longitude':'lon'},
              'time': {'timezone':'UTC'},
              'precipitation_time': {'reset_using_eod':True,'missing_eod_hours':24},
              'variables': {'precipitation': {'column':'rain','scale':25.4,
                  'qc_flag_column':'flag','qc_flag_case':'upper','accepted_qc_flags':['G','D','F']}}}
    result = read_observations(_write_yaml(tmp_path/'gsod.yaml', config))
    assert result.time.tolist() == pd.to_datetime(['2026-01-02','2026-01-01 03:00','2026-01-02','2026-01-02'], format='mixed').tolist()
    assert result.EOD.tolist() == [24,3,24,24]
    assert result.EOD_fallback.tolist() == [True,False,True,False]
    assert result.precipitation.iloc[[0,1]].tolist() == [0.0,25.4]
    assert pd.isna(result.precipitation.iloc[3])
    assert pd.isna(result.precipitation.iloc[2])
    assert 'precipitation_trace' not in result
    output = capsys.readouterr().out
    assert '1 accepted precipitation rows missing EOD' in output
    assert '2026-01-01' in output
    assert ' C ' not in output
