"""Map station coordinates to WRF mass-grid cells."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .errors import ConfigError


EARTH_RADIUS_KM = 6371.0


def read_wrf_grid(path: str | Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Read the 2-D WRF latitude/longitude mass grid and global attributes."""

    source = Path(path)
    if not source.is_file():
        raise ConfigError(f"WRF file does not exist: {source}")
    try:
        import xarray as xr
    except ImportError as exc:
        raise ConfigError("WRF grid mapping requires xarray and a NetCDF backend") from exc
    with xr.open_dataset(source, decode_times=False) as ds:
        for name in ("XLAT", "XLONG"):
            if name not in ds:
                raise ConfigError(f"WRF file has no {name}: {source}")
        lat = np.asarray(ds["XLAT"].isel(Time=0) if "Time" in ds["XLAT"].dims else ds["XLAT"])
        lon = np.asarray(ds["XLONG"].isel(Time=0) if "Time" in ds["XLONG"].dims else ds["XLONG"])
        attrs = dict(ds.attrs)
    if lat.ndim != 2 or lon.shape != lat.shape:
        raise ConfigError(f"XLAT/XLONG must be matching 2-D arrays, got {lat.shape}/{lon.shape}")
    return lat.astype(float), lon.astype(float), attrs


def _haversine_to_grid(lat0: float, lon0: float, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    lat0r = np.deg2rad(lat0)
    latr = np.deg2rad(lat)
    dlat = latr - lat0r
    dlon = np.deg2rad((lon - lon0 + 180.0) % 360.0 - 180.0)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat0r) * np.cos(latr) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def _inside_grid_boundary(lat0: float, lon0: float, lat: np.ndarray, lon: np.ndarray) -> bool:
    """Ray-cast against the outer mass-grid centers (adequate for regional WRF domains)."""

    edge_lat = np.concatenate((lat[0, :], lat[1:, -1], lat[-1, -2::-1], lat[-2:0:-1, 0]))
    edge_lon = np.concatenate((lon[0, :], lon[1:, -1], lon[-1, -2::-1], lon[-2:0:-1, 0]))
    # Unwrap longitudes around the station so the test also works near the dateline.
    x = (edge_lon - lon0 + 180.0) % 360.0 - 180.0
    y = edge_lat
    x_next = np.roll(x, -1)
    y_next = np.roll(y, -1)
    crossing = (y > lat0) != (y_next > lat0)
    x_intersection = x + (x_next - x) * (lat0 - y) / np.where(y_next == y, np.nan, y_next - y)
    return bool(np.count_nonzero(crossing & (x_intersection > 0.0)) % 2)


def map_nearest(stations: pd.DataFrame, grid_lat: np.ndarray, grid_lon: np.ndarray) -> pd.DataFrame:
    """Find the nearest WRF mass-grid center for every station."""

    records: list[dict] = []
    for row in stations.itertuples(index=False):
        distance = _haversine_to_grid(float(row.latitude), float(row.longitude), grid_lat, grid_lon)
        flat = int(np.nanargmin(distance))
        j, i = np.unravel_index(flat, grid_lat.shape)
        records.append({
            "station_id": str(row.station_id),
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
            "inside_domain": _inside_grid_boundary(
                float(row.latitude), float(row.longitude), grid_lat, grid_lon
            ),
            "nearest_j": int(j),
            "nearest_i": int(i),
            "nearest_latitude": float(grid_lat[j, i]),
            "nearest_longitude": float(grid_lon[j, i]),
            "distance_km": float(distance[j, i]),
            "interpolation": "nearest",
        })
    return pd.DataFrame.from_records(records)


def _project_grid(
    grid_lat: np.ndarray, grid_lon: np.ndarray, attrs: dict
) -> tuple[np.ndarray, np.ndarray, object]:
    map_proj = int(attrs.get("MAP_PROJ", 0))
    if map_proj == 6:
        return grid_lon, grid_lat, None
    if map_proj != 1:
        raise ConfigError("Bilinear mapping currently supports WRF Lambert (MAP_PROJ=1) or lat/lon (6)")
    try:
        from pyproj import Proj
    except ImportError as exc:
        raise ConfigError("Bilinear Lambert mapping requires pyproj") from exc
    projection = Proj(
        proj="lcc",
        lat_1=float(attrs["TRUELAT1"]),
        lat_2=float(attrs["TRUELAT2"]),
        lat_0=float(attrs.get("MOAD_CEN_LAT", attrs.get("CEN_LAT"))),
        lon_0=float(attrs["STAND_LON"]),
        R=6370000.0,
    )
    x, y = projection(grid_lon, grid_lat)
    return np.asarray(x), np.asarray(y), projection


def _bracket(axis: np.ndarray, value: float) -> tuple[int, int, float] | None:
    ascending = axis[-1] >= axis[0]
    work = axis if ascending else axis[::-1]
    if value < work[0] or value > work[-1]:
        return None
    upper = int(np.searchsorted(work, value, side="right"))
    upper = min(max(upper, 1), len(work) - 1)
    lower = upper - 1
    denom = work[upper] - work[lower]
    fraction = 0.0 if denom == 0 else float((value - work[lower]) / denom)
    if not ascending:
        lower, upper = len(axis) - 1 - upper, len(axis) - 1 - lower
    return lower, upper, fraction


def map_bilinear(
    stations: pd.DataFrame, grid_lat: np.ndarray, grid_lon: np.ndarray, attrs: dict
) -> pd.DataFrame:
    """Calculate four WRF-cell indices and bilinear weights for each station."""

    nearest = map_nearest(stations, grid_lat, grid_lon).set_index("station_id")
    x2d, y2d, projection = _project_grid(grid_lat, grid_lon, attrs)
    x_axis = np.nanmean(x2d, axis=0)
    y_axis = np.nanmean(y2d, axis=1)
    x_residual = np.nanmax(np.abs(x2d - x_axis[None, :]))
    y_residual = np.nanmax(np.abs(y2d - y_axis[:, None]))
    spacing = min(np.nanmedian(np.abs(np.diff(x_axis))), np.nanmedian(np.abs(np.diff(y_axis))))
    if spacing <= 0 or max(x_residual, y_residual) > max(1e-3, spacing * 0.02):
        raise ConfigError("WRF projected grid is not sufficiently rectilinear for bilinear weights")

    records: list[dict] = []
    for row in stations.itertuples(index=False):
        if projection is None:
            sx, sy = float(row.longitude), float(row.latitude)
        else:
            sx, sy = projection(float(row.longitude), float(row.latitude))
        xb = _bracket(x_axis, sx)
        yb = _bracket(y_axis, sy)
        base = nearest.loc[str(row.station_id)].to_dict()
        record = {
            "station_id": str(row.station_id),
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
            **base,
            "interpolation": "bilinear",
        }
        if xb is None or yb is None:
            record.update({
                "inside_domain": False,
                "j0": pd.NA, "j1": pd.NA, "i0": pd.NA, "i1": pd.NA,
                "w00": np.nan, "w01": np.nan, "w10": np.nan, "w11": np.nan,
            })
        else:
            i0, i1, fx = xb
            j0, j1, fy = yb
            record.update({
                "inside_domain": True,
                "j0": j0, "j1": j1, "i0": i0, "i1": i1,
                "w00": (1 - fx) * (1 - fy),
                "w01": fx * (1 - fy),
                "w10": (1 - fx) * fy,
                "w11": fx * fy,
            })
        records.append(record)
    return pd.DataFrame.from_records(records)


def map_stations(
    stations: pd.DataFrame,
    wrf_path: str | Path,
    method: str = "nearest",
) -> pd.DataFrame:
    grid_lat, grid_lon, attrs = read_wrf_grid(wrf_path)
    if method == "nearest":
        return map_nearest(stations, grid_lat, grid_lon)
    if method == "bilinear":
        return map_bilinear(stations, grid_lat, grid_lon, attrs)
    raise ConfigError("interpolation must be 'nearest' or 'bilinear'")
