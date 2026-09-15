import numpy as np
import pandas as pd
import xarray as xr

from wrfchem_site_eval.extraction import extract_wrf_timeseries
from wrfchem_site_eval.reduce_wrf import reduce_wrf_file, reduce_wrf_files
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


def test_default_and_per_variable_vertical_levels(tmp_path):
    source = write_synthetic_wrf(tmp_path / "wrfout_d01_levels")
    reduced = tmp_path / "reduced_levels.nc"
    variables = ["Times", "XLAT", "XLONG", "PM2_5_DRY", "o3", "T2", "PSFC"]
    reduce_wrf_file(
        source,
        reduced,
        variables,
        default_levels="all",
        variable_levels={"PM2_5_DRY": 1, "o3": [0, 2]},
    )
    with xr.open_dataset(reduced, decode_times=False) as dataset:
        assert dataset["PM2_5_DRY"].dims == ("Time", "south_north", "west_east")
        assert np.all(dataset["PM2_5_DRY"].values == 30.0)
        vertical = [dim for dim in dataset["o3"].dims if dim.startswith("bottom_top")]
        assert len(vertical) == 1
        assert dataset["o3"].sizes[vertical[0]] == 2
        assert np.all(dataset["o3"].isel({vertical[0]: 0}).values == 0.05)
        assert np.all(dataset["o3"].isel({vertical[0]: 1}).values == 0.07)
        assert dataset["T2"].dims == ("Time", "south_north", "west_east")


def test_reduce_multiple_files_with_workers(tmp_path):
    (tmp_path / "input").mkdir()
    sources = [
        write_synthetic_wrf(tmp_path / f"input/wrfout_d01_2019-01-01_0{hour}:00:00")
        for hour in range(2)
    ]
    output_dir = tmp_path / "parallel"
    outputs = reduce_wrf_files(
        sources,
        output_dir,
        ["Times", "T2", "PSFC"],
        workers=2,
    )

    assert [path.name for path in outputs] == [path.name for path in sources]
    assert all(path.exists() for path in outputs)
    manifest = __import__("json").loads(
        (output_dir / "reduced_wrf_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["workers"] == 2
