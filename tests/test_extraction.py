from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from wrfchem_site_eval.extraction import extract_wrf_timeseries
from wrfchem_site_eval.station_mapping import map_nearest


def write_synthetic_wrf(path: Path, include_coordinates: bool = True) -> Path:
    times = ["2019-01-01_00:00:00", "2019-01-01_01:00:00"]
    chars = np.asarray([[c.encode() for c in value] for value in times], dtype="S1")
    lat = np.array([[10.0, 10.0], [11.0, 11.0]])
    lon = np.array([[100.0, 101.0], [100.0, 101.0]])
    shape = (2, 2, 2)
    ones = np.ones(shape)
    pm25_3d = np.stack([ones * 20.0, ones * 30.0, ones * 40.0], axis=1)
    o3_3d = np.stack([ones * 0.05, ones * 0.06, ones * 0.07], axis=1)
    ds = xr.Dataset(
        {
            "Times": (("Time", "DateStrLen"), chars),
            "XLAT": (("Time", "south_north", "west_east"), np.stack([lat, lat])),
            "XLONG": (("Time", "south_north", "west_east"), np.stack([lon, lon])),
            "T2": (("Time", "south_north", "west_east"), ones * 300.0),
            "Q2": (("Time", "south_north", "west_east"), ones * 0.01),
            "PSFC": (("Time", "south_north", "west_east"), ones * 100000.0),
            "U10": (("Time", "south_north", "west_east"), ones * 3.0),
            "V10": (("Time", "south_north", "west_east"), ones * 4.0),
            "SINALPHA": (("Time", "south_north", "west_east"), np.zeros(shape)),
            "COSALPHA": (("Time", "south_north", "west_east"), ones),
            "RAINC": (("Time", "south_north", "west_east"), np.stack([lat * 0, lat * 0 + 1])),
            "RAINNC": (("Time", "south_north", "west_east"), np.stack([lat * 0 + 2, lat * 0 + 4])),
            "PBLH": (("Time", "south_north", "west_east"), ones * 500.0),
            "PM2_5_DRY": (("Time", "bottom_top", "south_north", "west_east"), pm25_3d),
            "o3": (("Time", "bottom_top", "south_north", "west_east"), o3_3d,
                   {"units": "ppmv"}),
        },
        attrs={"MAP_PROJ": 6},
    )
    if not include_coordinates:
        ds = ds.drop_vars(["XLAT", "XLONG"])
    ds.to_netcdf(path)
    return path


def write_synthetic_geo(path: Path) -> Path:
    lat = np.array([[10.0, 10.0], [11.0, 11.0]])
    lon = np.array([[100.0, 101.0], [100.0, 101.0]])
    xr.Dataset(
        {
            "XLAT_M": (("Time", "south_north", "west_east"), lat[None, ...]),
            "XLONG_M": (("Time", "south_north", "west_east"), lon[None, ...]),
            "SINALPHA": (("Time", "south_north", "west_east"), np.ones((1, 2, 2))),
            "COSALPHA": (("Time", "south_north", "west_east"), np.zeros((1, 2, 2))),
        },
        attrs={"MAP_PROJ": 6},
    ).to_netcdf(path)
    return path


def test_vectorized_extraction_derives_variables(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_2019-01-01_00:00:00")
    stations = pd.DataFrame({"station_id": ["A"], "latitude": [10.4], "longitude": [100.4]})
    mapping = map_nearest(stations, *(
        np.array([[10.0, 10.0], [11.0, 11.0]]),
        np.array([[100.0, 101.0], [100.0, 101.0]]),
    ))
    result = extract_wrf_timeseries(
        [source], {"chem": (mapping, ["temperature", "wind_speed", "precipitation", "pm25", "o3"])}
    )["chem"]
    assert len(result) == 2
    assert result["temperature"].tolist() == [300.0, 300.0]
    assert result["wind_speed"].tolist() == [5.0, 5.0]
    assert np.isnan(result.iloc[0]["precipitation"])
    assert result.iloc[1]["precipitation"] == pytest.approx(3.0)
    assert result["pm25"].tolist() == [20.0, 20.0]
    assert result.iloc[0]["o3"] == pytest.approx(96.22, rel=1e-3)


def test_model_wind_remains_grid_relative(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_test")
    with xr.open_dataset(source, decode_times=False) as ds:
        without_rotation = ds.drop_vars(["SINALPHA", "COSALPHA"]).load()
    without_rotation.to_netcdf(source, mode="w")
    stations = pd.DataFrame({
        "station_id": ["A"], "latitude": [10.0], "longitude": [100.0]
    })
    mapping = map_nearest(
        stations,
        np.array([[10.0, 10.0], [11.0, 11.0]]),
        np.array([[100.0, 101.0], [100.0, 101.0]]),
    )
    result = extract_wrf_timeseries(
        [source],
        {"met": (mapping, ["wind_speed", "wind_direction"])},
    )["met"]
    # WRF U10/V10 are kept grid-relative; observation winds are rotated later.
    assert result["wind_speed"].tolist() == pytest.approx([5.0, 5.0])
    assert result["wind_direction"].tolist() == pytest.approx([
        216.86989764584402, 216.86989764584402
    ])


def test_bilinear_wind_interpolates_components_before_speed_and_direction(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_bilinear_wind")
    with xr.open_dataset(source, decode_times=False) as ds:
        changed = ds.load()
    directions = np.deg2rad(np.array([[350.0, 10.0], [350.0, 10.0]]))
    changed["U10"].values[:] = -np.sin(directions)
    changed["V10"].values[:] = -np.cos(directions)
    changed.to_netcdf(source, mode="w")
    mapping = pd.DataFrame({
        "station_id": ["A"], "latitude": [10.5], "longitude": [100.5],
        "inside_domain": [True], "interpolation": ["bilinear"],
        "j0": [0], "j1": [1], "i0": [0], "i1": [1],
        "w00": [0.25], "w01": [0.25], "w10": [0.25], "w11": [0.25],
    })
    result = extract_wrf_timeseries(
        [source], {"met": (mapping, ["wind_speed", "wind_direction"])}
    )["met"]
    assert result["wind_direction"].tolist() == pytest.approx([0.0, 0.0], abs=1e-12)
    assert result["wind_speed"].tolist() == pytest.approx([
        np.cos(np.deg2rad(10.0)), np.cos(np.deg2rad(10.0))
    ])
