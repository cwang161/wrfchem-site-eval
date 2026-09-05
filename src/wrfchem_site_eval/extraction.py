"""Vectorized extraction of meteorology and chemistry at station locations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .errors import ConfigError


GAS_MOLAR_MASS = {"o3": 48.0, "no2": 46.0055, "so2": 64.066, "co": 28.01,
                  "no": 30.006, "nh3": 17.031}
CHEM_TARGET_UNITS = {"co": "mg_m-3"}
R_UNIVERSAL = 8.314462618


def discover_wrf_files(input_dir: str | Path, pattern: str) -> list[Path]:
    """Return deterministically ordered WRF files and fail early on an empty input."""

    root = Path(input_dir).expanduser()
    if not root.is_dir():
        raise ConfigError(f"WRF input directory does not exist: {root}")
    files = sorted(path for path in root.glob(pattern) if path.is_file())
    if not files:
        raise ConfigError(f"No WRF files match {root / pattern}")
    return files


def _decode_times(ds, source: Path) -> pd.DatetimeIndex:
    if "Times" in ds:
        values = np.asarray(ds["Times"].values)
        if values.ndim == 2:
            strings = []
            for row in values:
                if row.dtype.kind == "S":
                    strings.append(b"".join(row.tolist()).decode())
                else:
                    strings.append("".join(str(item) for item in row.tolist()))
        else:
            strings = [item.decode() if isinstance(item, bytes) else str(item) for item in values]
        parsed = pd.to_datetime(strings, format="%Y-%m-%d_%H:%M:%S", errors="coerce")
    elif "Time" in ds.coords and np.issubdtype(ds["Time"].dtype, np.datetime64):
        parsed = pd.to_datetime(ds["Time"].values, errors="coerce")
    else:
        match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}:\d{2}:\d{2})", source.name)
        parsed = pd.DatetimeIndex([pd.to_datetime(" ".join(match.groups()))]) if match else None
    if parsed is None or pd.isna(parsed).any():
        raise ConfigError(f"Cannot decode WRF time from {source}")
    return pd.DatetimeIndex(parsed)


def _surface(da, time_index: int) -> np.ndarray:
    if "Time" in da.dims:
        da = da.isel(Time=time_index)
    for dim in tuple(da.dims):
        if dim.startswith("bottom_top"):
            da = da.isel({dim: 0})
    values = np.asarray(da.values, dtype=float).squeeze()
    if values.ndim != 2:
        raise ConfigError(f"WRF variable {da.name} is not a 2-D mass-grid field after selection: {values.shape}")
    return values


def _raw(ds, name: str, time_index: int, *, optional: bool = False) -> np.ndarray | None:
    if name not in ds:
        if optional:
            return None
        raise ConfigError(f"WRF variable '{name}' is required but missing")
    return _surface(ds[name], time_index)


def _canonical_grid(ds, variable: str, time_index: int) -> np.ndarray:
    if variable == "temperature":
        return _raw(ds, "T2", time_index)
    if variable == "surface_temperature":
        return _raw(ds, "TSK", time_index)
    if variable == "surface_pressure":
        return _raw(ds, "PSFC", time_index)
    if variable == "pbl_height":
        return _raw(ds, "PBLH", time_index)
    if variable == "relative_humidity":
        q = _raw(ds, "Q2", time_index)
        t = _raw(ds, "T2", time_index)
        p = _raw(ds, "PSFC", time_index)
        vapor_pressure = q * p / (0.622 + 0.378 * q)
        saturation = 611.2 * np.exp(17.67 * (t - 273.15) / (t - 29.65))
        return np.clip(vapor_pressure / saturation, 0.0, 1.0)
    if variable in {"wind_speed", "wind_direction"}:
        u = _raw(ds, "U10", time_index)
        v = _raw(ds, "V10", time_index)
        sin = _raw(ds, "SINALPHA", time_index, optional=True)
        cos = _raw(ds, "COSALPHA", time_index, optional=True)
        if sin is None or cos is None:
            ue, ve = u, v
        else:
            ue = u * cos - v * sin
            ve = v * cos + u * sin
        if variable == "wind_speed":
            return np.hypot(ue, ve)
        return (270.0 - np.degrees(np.arctan2(ve, ue))) % 360.0
    if variable == "precipitation":
        rainc = _raw(ds, "RAINC", time_index)
        rainnc = _raw(ds, "RAINNC", time_index)
        rainsh = _raw(ds, "RAINSH", time_index, optional=True)
        return rainc + rainnc + (0.0 if rainsh is None else rainsh)

    raw_name = {
        "pm25": "PM2_5_DRY", "pm10": "PM10", "o3": "o3", "no2": "no2",
        "so2": "so2", "co": "co", "no": "no", "nh3": "nh3",
    }.get(variable)
    if raw_name is None:
        raise ConfigError(f"Unsupported extraction variable: {variable}")
    values = _raw(ds, raw_name, time_index)
    if variable in GAS_MOLAR_MASS:
        units = str(ds[raw_name].attrs.get("units", "ppmv")).lower().replace(" ", "")
        if units in {"ppmv", "ppm", "mol/mol", "molmol-1"}:
            pressure = _raw(ds, "PSFC", time_index)
            temperature = _raw(ds, "T2", time_index)
            values = values * GAS_MOLAR_MASS[variable] * pressure / (R_UNIVERSAL * temperature)
            if CHEM_TARGET_UNITS.get(variable) == "mg_m-3":
                values = values / 1000.0
    return values


def _sample_grid(values: np.ndarray, mapping: pd.DataFrame) -> np.ndarray:
    valid = mapping["inside_domain"].fillna(False).to_numpy(dtype=bool)
    result = np.full(len(mapping), np.nan)
    if mapping["interpolation"].iloc[0] == "nearest":
        rows = mapping.loc[valid, "nearest_j"].astype(int).to_numpy()
        cols = mapping.loc[valid, "nearest_i"].astype(int).to_numpy()
        result[valid] = values[rows, cols]
        return result
    subset = mapping.loc[valid]
    j0, j1 = subset["j0"].astype(int).to_numpy(), subset["j1"].astype(int).to_numpy()
    i0, i1 = subset["i0"].astype(int).to_numpy(), subset["i1"].astype(int).to_numpy()
    result[valid] = (
        values[j0, i0] * subset["w00"].to_numpy()
        + values[j0, i1] * subset["w01"].to_numpy()
        + values[j1, i0] * subset["w10"].to_numpy()
        + values[j1, i1] * subset["w11"].to_numpy()
    )
    return result


def finalize_precipitation(data: pd.DataFrame) -> pd.DataFrame:
    if "precipitation" not in data:
        return data
    data = data.sort_values(["station_id", "time"]).copy()
    previous = data.groupby("station_id", observed=True)["precipitation"].shift()
    increment = data["precipitation"] - previous
    # A negative difference indicates that WRF restarted its cumulative counter.
    increment = increment.where(previous.isna() | (increment >= 0.0), data["precipitation"])
    data["precipitation_accumulated"] = data["precipitation"]
    data["precipitation"] = increment
    return data


def extract_wrf_timeseries(
    files: Iterable[str | Path],
    groups: Mapping[str, tuple[pd.DataFrame, Iterable[str]]],
    finalize: bool = True,
) -> dict[str, pd.DataFrame]:
    """Open each WRF file once and extract every requested station group."""

    try:
        import xarray as xr
    except ImportError as exc:
        raise ConfigError("WRF extraction requires xarray and a NetCDF backend") from exc
    chunks: dict[str, list[pd.DataFrame]] = {name: [] for name in groups}
    for value in files:
        source = Path(value)
        with xr.open_dataset(source, decode_times=False) as ds:
            times = _decode_times(ds, source)
            for time_index, timestamp in enumerate(times):
                cache: dict[str, np.ndarray] = {}
                for name, (mapping, variables) in groups.items():
                    variables = tuple(dict.fromkeys(variables))
                    record = mapping[["station_id", "latitude", "longitude", "inside_domain"]].copy()
                    record.insert(1, "time", timestamp)
                    for variable in variables:
                        if variable not in cache:
                            cache[variable] = _canonical_grid(ds, variable, time_index)
                        record[variable] = _sample_grid(cache[variable], mapping)
                    chunks[name].append(record)
    results: dict[str, pd.DataFrame] = {}
    for name, pieces in chunks.items():
        if not pieces:
            results[name] = pd.DataFrame()
            continue
        combined = pd.concat(pieces, ignore_index=True)
        duplicate = combined.duplicated(["station_id", "time"], keep=False)
        if duplicate.any():
            examples = combined.loc[duplicate, ["station_id", "time"]].head(3).to_dict("records")
            raise ConfigError(f"Duplicate WRF station/time records; examples: {examples}")
        results[name] = finalize_precipitation(combined) if finalize else combined
    return results
