import numpy as np
import pandas as pd
import pytest
from wrfchem_site_eval.station_mapping import map_bilinear, map_nearest


@pytest.fixture
def latlon_grid():
    lat = np.array([[10.0, 10.0, 10.0], [11.0, 11.0, 11.0], [12.0, 12.0, 12.0]])
    lon = np.array([[100.0, 101.0, 102.0], [100.0, 101.0, 102.0], [100.0, 101.0, 102.0]])
    return lat, lon


def test_nearest_mapping(latlon_grid):
    lat, lon = latlon_grid
    stations = pd.DataFrame({"station_id": ["A"], "latitude": [11.1], "longitude": [100.9]})
    result = map_nearest(stations, lat, lon)
    assert result.loc[0, "nearest_j"] == 1
    assert result.loc[0, "nearest_i"] == 1
    assert bool(result.loc[0, "inside_domain"])


def test_nearest_mapping_marks_outside_domain(latlon_grid):
    lat, lon = latlon_grid
    stations = pd.DataFrame({"station_id": ["A"], "latitude": [30.0], "longitude": [120.0]})
    result = map_nearest(stations, lat, lon)
    assert not bool(result.loc[0, "inside_domain"])


def test_bilinear_mapping_weights(latlon_grid):
    lat, lon = latlon_grid
    stations = pd.DataFrame({"station_id": ["A"], "latitude": [10.25], "longitude": [100.5]})
    result = map_bilinear(stations, lat, lon, {"MAP_PROJ": 6})
    assert result.loc[0, ["w00", "w01", "w10", "w11"]].sum() == pytest.approx(1.0)
    assert result.loc[0, "w00"] == pytest.approx(0.375)
    assert result.loc[0, "w01"] == pytest.approx(0.375)
    assert result.loc[0, "w10"] == pytest.approx(0.125)
    assert result.loc[0, "w11"] == pytest.approx(0.125)
