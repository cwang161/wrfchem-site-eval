import numpy as np
import pandas as pd
import xarray as xr

from wrfchem_site_eval.extraction import extract_wrf_timeseries
from wrfchem_site_eval.reduce_wrf import reduce_wrf_file
from wrfchem_site_eval.station_mapping import map_nearest
from wrfchem_site_eval.variables import required_wrf_variables
from test_extraction import write_synthetic_wrf


def test_reduced_wrf_matches_direct_extraction(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_2019-01-01_00:00:00")
    reduced = tmp_path / "reduced" / source.name
    canonical = ["temperature", "relative_humidity", "precipitation", "pm25", "o3"]
    reduce_wrf_file(source, reduced, required_wrf_variables(canonical))

    with xr.open_dataset(reduced, decode_times=False) as dataset:
        assert dataset.attrs["WRFCHEM_SITE_EVAL_REDUCED"] == 1
        assert "bottom_top" not in dataset["o3"].dims
        assert set(["T2", "Q2", "PSFC", "PM2_5_DRY", "o3"]) <= set(dataset)

    stations = pd.DataFrame({
        "station_id": ["A"], "latitude": [10.4], "longitude": [100.4]
    })
    lat = np.array([[10.0, 10.0], [11.0, 11.0]])
    lon = np.array([[100.0, 101.0], [100.0, 101.0]])
    mapping = map_nearest(stations, lat, lon)
    direct = extract_wrf_timeseries([source], {"test": (mapping, canonical)})["test"]
    compact = extract_wrf_timeseries([reduced], {"test": (mapping, canonical)})["test"]
    pd.testing.assert_frame_equal(direct, compact)
