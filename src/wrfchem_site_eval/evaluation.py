"""Observation/model collocation and reproducible evaluation statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from .errors import ConfigError


IDENTITY_COLUMNS = {"station_id", "time", "latitude", "longitude", "inside_domain"}


def collocate(
    observations: pd.DataFrame,
    model: pd.DataFrame,
    variables: Iterable[str],
    tolerance: str | None = None,
) -> pd.DataFrame:
    """Join observations to model output by station and time.

    With a tolerance, each observation is paired to the nearest model timestamp
    for the same station. Without one, timestamps must match exactly.
    """

    requested = [name for name in dict.fromkeys(variables) if name in observations]
    obs_columns = ["station_id", "time", "latitude", "longitude"] + requested
    obs_columns += [f"{name}_qc_flag" for name in requested if f"{name}_qc_flag" in observations]
    obs = observations[obs_columns].copy()
    obs = obs.rename(columns={name: f"obs_{name}" for name in requested})
    model_variables = [name for name in model.columns if name not in IDENTITY_COLUMNS]
    mod = model.drop(columns=["latitude", "longitude"], errors="ignore").rename(
        columns={name: f"model_{name}" for name in model_variables}
    )
    obs["station_id"] = obs["station_id"].astype(str)
    mod["station_id"] = mod["station_id"].astype(str)
    if tolerance is None:
        return obs.merge(mod, on=["station_id", "time"], how="inner", validate="one_to_one")
    try:
        delta = pd.Timedelta(tolerance)
    except ValueError as exc:
        raise ConfigError(f"Invalid matching tolerance: {tolerance}") from exc
    obs = obs.sort_values(["time", "station_id"])
    mod = mod.sort_values(["time", "station_id"])
    return pd.merge_asof(
        obs, mod, on="time", by="station_id", direction="nearest", tolerance=delta
    ).dropna(subset=[column for column in mod if column.startswith("model_")], how="all")


def aggregate_time(
    data: pd.DataFrame,
    frequency: str,
    precipitation: str = "sum",
    minimum_count: int | Mapping[str, int] | None = None,
    offset: str | None = None,
) -> pd.DataFrame:
    """Aggregate a canonical table per station; precipitation sums, other variables average."""

    if not frequency:
        return data
    frame = data.set_index("time")
    value_columns = [
        col for col in frame.select_dtypes(include=[np.number]).columns
        if col not in {"latitude", "longitude", "inside_domain"}
    ]
    aggregations = {
        col: (precipitation if col == "precipitation" else "last" if col == "precipitation_accumulated" else "mean")
        for col in value_columns
    }
    for col in frame.columns:
        if col not in aggregations and col != "station_id":
            aggregations[col] = "first"
    grouped = frame.groupby("station_id", observed=True).resample(frequency, offset=offset)
    result = grouped.agg(aggregations)
    if minimum_count is not None:
        counts = grouped[value_columns].count()
        for column in value_columns:
            required = (
                minimum_count.get(column, minimum_count.get("default", 1))
                if isinstance(minimum_count, Mapping) else minimum_count
            )
            result[column] = result[column].where(counts[column] >= int(required))
    return result.dropna(subset=value_columns, how="all").reset_index()


def _statistics(obs: np.ndarray, model: np.ndarray, wind_direction: bool = False) -> dict[str, float | int]:
    good = np.isfinite(obs) & np.isfinite(model)
    obs, model = obs[good], model[good]
    n = len(obs)
    if n == 0:
        return {name: np.nan for name in (
            "n", "mean_observation", "mean_model", "bias", "mae", "rmse",
            "correlation", "ioa", "nmb_percent", "nme_percent", "mfb_percent", "mfe_percent",
        )}
    difference = model - obs
    if wind_direction:
        difference = (difference + 180.0) % 360.0 - 180.0
        obs_radians, model_radians = np.deg2rad(obs), np.deg2rad(model)
        obs_center = np.arctan2(np.mean(np.sin(obs_radians)), np.mean(np.cos(obs_radians)))
        model_center = np.arctan2(np.mean(np.sin(model_radians)), np.mean(np.cos(model_radians)))
        obs_anomaly = np.sin(obs_radians - obs_center)
        model_anomaly = np.sin(model_radians - model_center)
        corr_denom = np.sqrt(np.sum(obs_anomaly ** 2) * np.sum(model_anomaly ** 2))
        corr = np.sum(obs_anomaly * model_anomaly) / corr_denom if corr_denom > 0 else np.nan
        mean_obs = np.degrees(obs_center) % 360.0
        mean_model = np.degrees(model_center) % 360.0
        observed_deviation = (obs - mean_obs + 180.0) % 360.0 - 180.0
        modeled_deviation = (model - mean_obs + 180.0) % 360.0 - 180.0
    else:
        corr = np.corrcoef(obs, model)[0, 1] if n > 1 and np.std(obs) > 0 and np.std(model) > 0 else np.nan
        mean_obs, mean_model = np.mean(obs), np.mean(model)
        observed_deviation = obs - mean_obs
        modeled_deviation = model - mean_obs
    denominator = model + obs
    usable = denominator != 0
    obs_sum = np.sum(obs)
    ioa_denom = np.sum((np.abs(modeled_deviation) + np.abs(observed_deviation)) ** 2)
    return {
        "n": int(n),
        "mean_observation": float(mean_obs),
        "mean_model": float(mean_model),
        "bias": float(np.mean(difference)),
        "mae": float(np.mean(np.abs(difference))),
        "rmse": float(np.sqrt(np.mean(difference ** 2))),
        "correlation": float(corr),
        "ioa": float(1.0 - np.sum(difference ** 2) / ioa_denom) if ioa_denom > 0 else np.nan,
        "nmb_percent": float(100.0 * np.sum(difference) / obs_sum) if obs_sum != 0 else np.nan,
        "nme_percent": float(100.0 * np.sum(np.abs(difference)) / abs(obs_sum)) if obs_sum != 0 else np.nan,
        "mfb_percent": float(200.0 * np.mean(difference[usable] / denominator[usable])) if usable.any() else np.nan,
        "mfe_percent": float(200.0 * np.mean(np.abs(difference[usable]) / np.abs(denominator[usable]))) if usable.any() else np.nan,
    }


def calculate_metrics(
    matched: pd.DataFrame,
    variables: Iterable[str],
    case_name: str,
    include_station: bool = True,
) -> pd.DataFrame:
    """Calculate overall and per-station paired statistics for requested variables."""

    records: list[dict] = []
    groups: list[tuple[str, str, pd.DataFrame]] = [("overall", "ALL", matched)]
    if include_station:
        groups.extend(("station", str(site), part) for site, part in matched.groupby("station_id", observed=True))
    for level, station, data in groups:
        for variable in variables:
            obs_name, model_name = f"obs_{variable}", f"model_{variable}"
            if obs_name not in data or model_name not in data:
                continue
            stats = _statistics(
                data[obs_name].to_numpy(dtype=float), data[model_name].to_numpy(dtype=float),
                wind_direction=variable == "wind_direction",
            )
            records.append({
                "case": case_name, "group_type": level, "station_id": station,
                "variable": variable, **stats,
            })
    return pd.DataFrame.from_records(records)


def compare_case_metrics(paths: Iterable[str], output: str | None = None) -> pd.DataFrame:
    """Combine metric tables from multiple cases into one comparison table."""

    tables = []
    for value in paths:
        path = str(value)
        tables.append(pd.read_parquet(path) if path.lower().endswith(".parquet") else pd.read_csv(path))
    result = pd.concat(tables, ignore_index=True)
    keys = ["case", "group_type", "station_id", "variable"]
    result = result.sort_values([key for key in keys if key in result]).reset_index(drop=True)
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() == ".parquet":
            result.to_parquet(destination, index=False)
        else:
            result.to_csv(destination, index=False)
    return result
