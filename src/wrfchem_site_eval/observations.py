"""Read heterogeneous observation tables into one canonical wide table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .errors import ConfigError


STANDARD_COLUMNS = ("station_id", "time", "latitude", "longitude")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ConfigError(f"Observation configuration must be a mapping: {path}")
    return value


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _read_table(path: Path, file_format: str) -> pd.DataFrame:
    if not path.is_file():
        raise ConfigError(f"Observation file does not exist: {path}")
    fmt = file_format.lower()
    if fmt == "auto":
        fmt = path.suffix.lower().lstrip(".")
    if fmt in {"csv", "txt"}:
        return pd.read_csv(path)
    if fmt in {"xlsx", "xls"}:
        return pd.read_excel(path)
    if fmt == "parquet":
        return pd.read_parquet(path)
    raise ConfigError(f"Unsupported observation format '{file_format}' for {path}")


def _canonical_time(values: pd.Series, settings: dict[str, Any]) -> pd.Series:
    parsed = pd.to_datetime(values, format=settings.get("format"), errors="coerce")
    if parsed.isna().any():
        count = int(parsed.isna().sum())
        raise ConfigError(f"Could not parse {count} observation timestamps")

    source_timezone = settings.get("timezone")
    output_timezone = settings.get("output_timezone", "UTC")
    if source_timezone:
        if parsed.dt.tz is None:
            parsed = parsed.dt.tz_localize(
                source_timezone,
                ambiguous=settings.get("ambiguous", "raise"),
                nonexistent=settings.get("nonexistent", "raise"),
            )
        parsed = parsed.dt.tz_convert(output_timezone)
        if settings.get("drop_timezone", True):
            parsed = parsed.dt.tz_localize(None)
    return parsed


def _apply_duplicate_policy(data: pd.DataFrame, policy: str) -> pd.DataFrame:
    keys = ["station_id", "time"]
    duplicate = data.duplicated(keys, keep=False)
    if not duplicate.any():
        return data
    if policy == "error":
        example = data.loc[duplicate, keys].head(3).to_dict("records")
        raise ConfigError(f"Duplicate station/time observations; examples: {example}")
    if policy in {"first", "last"}:
        return data.drop_duplicates(keys, keep=policy)
    raise ConfigError("duplicate_policy must be one of: error, first, last")


def read_observations(config_path: str | Path) -> pd.DataFrame:
    """Read a configured combined-wide observation file.

    The returned table always uses ``station_id``, ``time``, ``latitude`` and
    ``longitude`` plus canonical variable names. Per-variable QC columns are
    retained as ``<variable>_qc_flag``.
    """

    path = Path(config_path).resolve()
    config = _load_yaml(path)
    dataset = config.get("dataset", {})
    if dataset.get("profile") not in {"combined_wide", "chem_qc", "isd_hourly_met"}:
        raise ConfigError(
            "This release supports observation profiles: combined_wide, chem_qc, "
            "isd_hourly_met"
        )
    source = _resolve(path.parent, str(dataset.get("file", "")))
    raw = _read_table(source, str(dataset.get("format", "auto")))
    raw = raw.replace(config.get("missing_values", []), np.nan)

    columns = config.get("columns", {})
    required = {key: columns.get(key) for key in STANDARD_COLUMNS}
    missing_mapping = [key for key, value in required.items() if not value]
    if missing_mapping:
        raise ConfigError(f"Missing observation column mappings: {missing_mapping}")
    absent = [value for value in required.values() if value not in raw.columns]
    if absent:
        raise ConfigError(f"Observation columns not found in {source}: {absent}")

    out = pd.DataFrame({
        "station_id": raw[required["station_id"]].astype("string").str.strip(),
        "time": _canonical_time(raw[required["time"]], config.get("time", {})),
        "latitude": pd.to_numeric(raw[required["latitude"]], errors="coerce"),
        "longitude": pd.to_numeric(raw[required["longitude"]], errors="coerce"),
    })
    if out["station_id"].isna().any() or (out["station_id"] == "").any():
        raise ConfigError("Observation station_id contains missing or empty values")

    for canonical, settings in config.get("variables", {}).items():
        source_column = settings.get("column")
        if source_column not in raw.columns:
            if settings.get("required", True):
                raise ConfigError(f"Column '{source_column}' for '{canonical}' is missing")
            continue
        values = pd.to_numeric(raw[source_column], errors="coerce")
        values = values * float(settings.get("scale", 1.0))
        values = values + float(settings.get("offset", 0.0))

        flag_column = settings.get("qc_flag_column")
        if flag_column:
            if flag_column not in raw.columns:
                raise ConfigError(f"QC column '{flag_column}' for '{canonical}' is missing")
            flags = raw[flag_column].astype("string").str.strip().str.lower()
            out[f"{canonical}_qc_flag"] = flags
            accepted = settings.get("accepted_qc_flags")
            if accepted is not None:
                accepted_normalized = {str(item).strip().lower() for item in accepted}
                values = values.where(flags.isin(accepted_normalized))
        out[canonical] = values

    derived = config.get("derived", {})
    if derived.get("relative_humidity", {}).get("method") == "temperature_dewpoint":
        temp_name = derived["relative_humidity"].get("temperature", "temperature")
        dew_name = derived["relative_humidity"].get("dew_point", "dew_point")
        if temp_name not in out or dew_name not in out:
            raise ConfigError("Relative humidity derivation requires temperature and dew_point")
        temp_c = out[temp_name] - 273.15
        dew_c = out[dew_name] - 273.15
        rh = np.exp((17.67 * dew_c) / (243.5 + dew_c)) / np.exp(
            (17.67 * temp_c) / (243.5 + temp_c)
        )
        out["relative_humidity"] = rh.clip(0.0, 1.0)

    metadata = config.get("metadata", {})
    for canonical, source_column in metadata.items():
        if source_column in raw.columns:
            out[canonical] = raw[source_column].values

    out = _apply_duplicate_policy(out, config.get("duplicate_policy", "error"))
    return out.sort_values(["station_id", "time"]).reset_index(drop=True)


def station_table(observations: pd.DataFrame, tolerance_degrees: float = 1e-5) -> pd.DataFrame:
    """Return one coordinate pair per station and reject moving/inconsistent sites."""

    required = set(STANDARD_COLUMNS) - {"time"}
    missing = sorted(required - set(observations.columns))
    if missing:
        raise ConfigError(f"Cannot build station table; missing columns: {missing}")
    if observations[["latitude", "longitude"]].isna().any().any():
        raise ConfigError("Station coordinates contain missing values")

    grouped = observations.groupby("station_id", sort=True, observed=True)
    spread = grouped[["latitude", "longitude"]].agg(lambda x: x.max() - x.min())
    inconsistent = spread.max(axis=1) > tolerance_degrees
    if inconsistent.any():
        names = spread.index[inconsistent].astype(str).tolist()[:10]
        raise ConfigError(f"Station coordinates change over time: {names}")
    result = grouped[["latitude", "longitude"]].first().reset_index()
    return result
