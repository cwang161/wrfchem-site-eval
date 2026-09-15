from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

from wrfchem_site_eval.pipeline import run_case
from test_extraction import write_synthetic_geo, write_synthetic_wrf


def _yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_complete_case_pipeline(tmp_path):
    wrf_dir = tmp_path / "wrf"
    wrf_dir.mkdir()
    write_synthetic_wrf(
        wrf_dir / "wrfout_d01_2019-01-01_00:00:00", include_coordinates=False
    )
    second = write_synthetic_wrf(
        wrf_dir / "wrfout_d01_2019-01-01_02:00:00", include_coordinates=False
    )
    with xr.open_dataset(second, decode_times=False) as source:
        shifted = source.load()
    second_times = ["2019-01-01_02:00:00", "2019-01-01_03:00:00"]
    shifted["Times"] = (
        ("Time", "DateStrLen"),
        np.asarray([[c.encode() for c in value] for value in second_times], dtype="S1"),
    )
    shifted.to_netcdf(second, mode="w")
    write_synthetic_geo(tmp_path / "geo_em.d01.nc")
    times = [
        "2019-01-01 00:00:00", "2019-01-01 01:00:00",
        "2019-01-01 02:00:00", "2019-01-01 03:00:00",
    ]
    pd.DataFrame({
        "Time": times, "Site": ["M1"] * 4, "LAT": [10.4] * 4, "LON": [100.4] * 4,
        "Temp": [300.0] * 4, "Wind": [5.0] * 4, "Rain": [0.0, 3.0, 3.0, 3.0],
    }).to_csv(tmp_path / "met.csv", index=False)
    pd.DataFrame({
        "Time": times, "code": ["C1"] * 4, "latitude": [10.4] * 4,
        "longitude": [100.4] * 4, "pm25": [20.0] * 4,
        "pm25_qc_flag": ["valid"] * 4, "o3": [96.22] * 4,
        "o3_qc_flag": ["valid"] * 4,
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
        "wrf": {
            "input_dir": "wrf", "file_pattern": "wrfout_d01_*", "domain": "d01",
            "grid_file": "geo_em.d01.nc",
            "grid_latitude_variable": "XLAT_M",
            "grid_longitude_variable": "XLONG_M",
            "reduction": {
                "enabled": True, "output_dir": "reduced_wrf", "use_for_extraction": True,
                "compression_level": 1,
            },
        },
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml", "interpolation": "nearest"},
            "chem": {"enabled": True, "observation_config": "chem.yaml", "interpolation": "nearest", "include_met_at_sites": True},
        },
        "evaluation": {"met": ["temperature", "wind_speed", "precipitation"], "chem": ["pm25", "o3"]},
        "matching": {"tolerance": None, "frequency": None},
        "output": {"directory": "output/SYNTHETIC", "format": "csv"},
        "figures": {"enabled": True},
    })
    products = run_case(case, workers=2)
    assert all(path.exists() for path in products.values())
    assert (tmp_path / "reduced_wrf/reduced_wrf_manifest.json").exists()
    model_chem = pd.read_csv(tmp_path / "output/SYNTHETIC/model_chem.csv")
    assert {"pm25", "o3", "temperature", "wind_speed", "precipitation"} <= set(model_chem)
    metrics_chem = pd.read_csv(products["metrics_chem"])
    overall_pm25 = metrics_chem.query("group_type == 'overall' and variable == 'pm25'").iloc[0]
    assert overall_pm25["n"] == 4
    assert abs(overall_pm25["bias"]) < 1e-12
    assert any(key.startswith("figure_chem") and path.exists() for key, path in products.items())
    # Resume reuses mappings and model tables while rebuilding matching/metrics.
    resumed = run_case(case, resume=True)
    assert resumed["manifest"].exists()

    # Caches created before projected-wind support are invalidated automatically.
    model_met_path = tmp_path / "output/SYNTHETIC/model_met.csv"
    legacy_model = pd.read_csv(model_met_path).drop(columns="grid_convergence_degrees")
    legacy_model.to_csv(model_met_path, index=False)
    for checkpoint in (tmp_path / "output/SYNTHETIC/.checkpoints").glob("*_met.csv"):
        legacy_checkpoint = pd.read_csv(checkpoint).drop(
            columns="grid_convergence_degrees"
        )
        legacy_checkpoint.to_csv(checkpoint, index=False)
    run_case(case, resume=True)
    refreshed_model = pd.read_csv(model_met_path)
    assert "grid_convergence_degrees" in refreshed_model
