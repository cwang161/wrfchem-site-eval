from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from wrfchem_site_eval.extraction import extract_wrf_timeseries, read_static_wind_rotation
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


def test_wind_rotation_can_come_from_geo_em(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_test")
    with xr.open_dataset(source, decode_times=False) as ds:
        without_rotation = ds.drop_vars(["SINALPHA", "COSALPHA"]).load()
    without_rotation.to_netcdf(source, mode="w")
    geo = write_synthetic_geo(tmp_path / "geo_em.d01.nc")
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
        static_fields=read_static_wind_rotation(geo),
    )["met"]
    # sin=1/cos=0 rotates grid-relative (u=3,v=4) to (ue=-4,ve=3).
    assert result["wind_speed"].tolist() == pytest.approx([5.0, 5.0])
    assert result["wind_direction"].tolist() == pytest.approx([
        126.86989764584402, 126.86989764584402
    ])
