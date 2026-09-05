from pathlib import Path

import pandas as pd
import yaml

from wrfchem_site_eval.pipeline import run_case
from test_extraction import write_synthetic_wrf


def _yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_complete_case_pipeline(tmp_path):
    wrf_dir = tmp_path / "wrf"
    wrf_dir.mkdir()
    write_synthetic_wrf(wrf_dir / "wrfout_d01_2019-01-01_00:00:00")
    times = ["2019-01-01 00:00:00", "2019-01-01 01:00:00"]
    pd.DataFrame({
        "Time": times, "Site": ["M1", "M1"], "LAT": [10.4, 10.4], "LON": [100.4, 100.4],
        "Temp": [300.0, 300.0], "Wind": [5.0, 5.0], "Rain": [0.0, 3.0],
    }).to_csv(tmp_path / "met.csv", index=False)
    pd.DataFrame({
        "Time": times, "code": ["C1", "C1"], "latitude": [10.4, 10.4],
        "longitude": [100.4, 100.4], "pm25": [20.0, 20.0],
        "pm25_qc_flag": ["valid", "valid"], "o3": [96.22, 96.22],
        "o3_qc_flag": ["valid", "valid"],
    }).to_csv(tmp_path / "chem.csv", index=False)
    common_columns = {"time": "Time", "latitude": "LAT", "longitude": "LON"}
    _yaml(tmp_path / "met.yaml", {
        "dataset": {"profile": "isd_hourly_met", "file": "met.csv"},
        "columns": {"station_id": "Site", **common_columns}, "time": {"timezone": "UTC"},
        "variables": {
            "temperature": {"column": "Temp"}, "wind_speed": {"column": "Wind"},
            "precipitation": {"column": "Rain"},
        },
    })
    _yaml(tmp_path / "chem.yaml", {
        "dataset": {"profile": "chem_qc", "file": "chem.csv"},
        "columns": {"station_id": "code", "time": "Time", "latitude": "latitude", "longitude": "longitude"},
        "time": {"timezone": "UTC"},
        "variables": {
            "pm25": {"column": "pm25", "qc_flag_column": "pm25_qc_flag", "accepted_qc_flags": ["valid"]},
            "o3": {"column": "o3", "qc_flag_column": "o3_qc_flag", "accepted_qc_flags": ["valid"]},
        },
    })
    case = _yaml(tmp_path / "case.yaml", {
        "case": {"name": "SYNTHETIC"},
        "wrf": {"input_dir": "wrf", "file_pattern": "wrfout_d01_*", "domain": "d01"},
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml", "interpolation": "nearest"},
            "chem": {"enabled": True, "observation_config": "chem.yaml", "interpolation": "nearest", "include_met_at_sites": True},
        },
        "evaluation": {"met": ["temperature", "wind_speed", "precipitation"], "chem": ["pm25", "o3"]},
        "matching": {"tolerance": None, "frequency": None},
        "output": {"directory": "output/SYNTHETIC", "format": "csv"},
        "figures": {"enabled": True},
    })
    products = run_case(case)
    assert all(path.exists() for path in products.values())
    model_chem = pd.read_csv(tmp_path / "output/SYNTHETIC/model_chem.csv")
    assert {"pm25", "o3", "temperature", "wind_speed", "precipitation"} <= set(model_chem)
    metrics_chem = pd.read_csv(products["metrics_chem"])
    overall_pm25 = metrics_chem.query("group_type == 'overall' and variable == 'pm25'").iloc[0]
    assert overall_pm25["n"] == 2
    assert abs(overall_pm25["bias"]) < 1e-12
    assert any(key.startswith("figure_chem") and path.exists() for key, path in products.items())
    # Resume reuses mappings and model tables while rebuilding matching/metrics.
    resumed = run_case(case, resume=True)
    assert resumed["manifest"].exists()
