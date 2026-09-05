from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from wrfchem_site_eval.extraction import extract_wrf_timeseries
from wrfchem_site_eval.station_mapping import map_nearest


def write_synthetic_wrf(path: Path) -> Path:
    times = ["2019-01-01_00:00:00", "2019-01-01_01:00:00"]
    chars = np.asarray([[c.encode() for c in value] for value in times], dtype="S1")
    lat = np.array([[10.0, 10.0], [11.0, 11.0]])
    lon = np.array([[100.0, 101.0], [100.0, 101.0]])
    shape = (2, 2, 2)
    ones = np.ones(shape)
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
            "PM2_5_DRY": (("Time", "bottom_top", "south_north", "west_east"), ones[:, None] * 20.0),
            "o3": (("Time", "bottom_top", "south_north", "west_east"), ones[:, None] * 0.05,
                   {"units": "ppmv"}),
        },
        attrs={"MAP_PROJ": 6},
    )
    ds.to_netcdf(path)
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
