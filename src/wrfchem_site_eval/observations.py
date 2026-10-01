"""Read heterogeneous observation tables into one canonical wide table."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
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


def _read_table(path: Path, file_format: str, coordinate_columns=()) -> pd.DataFrame:
    if not path.is_file():
        raise ConfigError(f"Observation file does not exist: {path}")
    fmt = file_format.lower()
    if fmt == "auto":
        fmt = path.suffix.lower().lstrip(".")
    if fmt in {"csv", "txt"}:
        return pd.read_csv(path, low_memory=False, dtype={name: "string" for name in coordinate_columns})
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
    if dataset.get("profile") == "combined_sources":
        sources = config.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ConfigError("combined_sources requires a non-empty 'sources' list")
        tables = [read_observations(_resolve(path.parent, str(source))) for source in sources]
        precision = {}
        for table in tables:
            for key, digits in table.attrs.get("coordinate_precision", {}).items():
                precision.setdefault(key, digits)
        combined = pd.concat(tables, ignore_index=True, sort=False)
        combined.attrs["coordinate_precision"] = precision
        # Validate coordinates before coalescing coincident station/time rows.
        coordinate_settings = config.get("station_coordinates", {})
        if "tolerance_m" in coordinate_settings or coordinate_settings.get("method") == "rounding":
            combined = _harmonize_station_coordinates(
                combined, coordinate_settings.get("tolerance_m", 100),
                coordinate_settings.get("reference", "first_source"),
                coordinate_settings.get("on_conflict", "error"),
                coordinate_settings.get("method", "distance"),
            )
        else:
            station_table(combined)
        combined = combined.sort_values(["station_id", "time"], kind="stable")
        combined = combined.groupby(["station_id", "time"], observed=True, as_index=False).first()
        return combined.sort_values(["station_id", "time"]).reset_index(drop=True)
    if dataset.get("profile") not in {"combined_wide"}:
        raise ConfigError(
            "Supported profiles: combined_wide, combined_sources"
        )
    source = _resolve(path.parent, str(dataset.get("file", "")))
    columns = config.get("columns", {})
    coordinate_columns = [columns[key] for key in ("latitude", "longitude") if columns.get(key)]
    raw = _read_table(source, str(dataset.get("format", "auto")), coordinate_columns)
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
        if "unit" in settings:
            raise ConfigError(f"Use source_unit and target_unit instead of unit for {canonical}")
        source_column = settings.get("column")
        if source_column not in raw.columns:
            if settings.get("required", True):
                raise ConfigError(f"Column '{source_column}' for '{canonical}' is missing")
            continue
        values = pd.to_numeric(raw[source_column], errors="coerce")
        trace = None
        if "trace_values" in settings:
            codes = settings["trace_values"]
            if not isinstance(codes, list):
                raise ConfigError(f"trace_values for {canonical} must be a list")
            trace = values.isin(codes).astype("boolean")
        values = values * float(settings.get("scale", 1.0))
        values = values + float(settings.get("offset", 0.0))

        if trace is not None:
            replacement = float(settings.get("trace_replacement", 0.0))
            if not np.isfinite(replacement) or replacement < 0:
                raise ConfigError(f"trace_replacement for {canonical} must be finite and nonnegative")
            values = values.mask(trace, replacement)

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
        if trace is not None:
            out[f"{canonical}_trace"] = trace.where(values.notna(), pd.NA)

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

    wind_rules = config.get("quality_rules", {}).get("wind", {})
    if wind_rules and "wind_direction" in out:
        invalid = out["wind_direction"].isin(wind_rules.get("invalid_direction_values", []))
        if "wind_speed" in out and wind_rules.get("calm_speed_below") is not None:
            invalid |= out["wind_speed"] < float(wind_rules["calm_speed_below"])
        out.loc[invalid, "wind_direction"] = np.nan

    metadata = config.get("metadata", {})
    for canonical, source_column in metadata.items():
        if source_column in raw.columns:
            out[canonical] = raw[source_column].values

    precision = {}
    for axis in ("latitude", "longitude"):
        for station, value in zip(out["station_id"], raw[required[axis]]):
            if pd.notna(value):
                precision.setdefault((str(station), axis), max(0, -Decimal(str(value).strip()).as_tuple().exponent))
    out.attrs["coordinate_precision"] = precision
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


def _harmonize_station_coordinates(
    observations: pd.DataFrame, tolerance_m: float, reference: str = "first_source",
    on_conflict: str = "error", method: str = "distance"
) -> pd.DataFrame:
    """Validate spherical distance to first-source coordinates, then unify them."""

    if method not in {"distance", "rounding"}:
        raise ConfigError("station_coordinates.method must be distance or rounding")
    if on_conflict not in {"error", "use_reference"}:
        raise ConfigError("station_coordinates.on_conflict must be error or use_reference")
    if reference != "first_source":
        raise ConfigError("station_coordinates.reference must be first_source")
    try:
        tolerance = float(tolerance_m)
    except (TypeError, ValueError) as exc:
        raise ConfigError("station_coordinates.tolerance_m must be a non-negative number") from exc
    if isinstance(tolerance_m, bool) or not np.isfinite(tolerance) or tolerance < 0:
        raise ConfigError("station_coordinates.tolerance_m must be a non-negative number")
    if observations[["latitude", "longitude"]].isna().any().any():
        raise ConfigError("Station coordinates contain missing values")
    result = observations.copy()
    reference_coords = result.groupby("station_id", sort=False, observed=True)[
        ["latitude", "longitude"]
    ].transform("first")
    lat = np.deg2rad(result["latitude"].to_numpy())
    lat0 = np.deg2rad(reference_coords["latitude"].to_numpy())
    dlon = np.deg2rad(
        (result["longitude"].to_numpy() - reference_coords["longitude"].to_numpy() + 180) % 360 - 180
    )
    a = np.sin((lat - lat0) / 2)**2 + np.cos(lat) * np.cos(lat0) * np.sin(dlon / 2)**2
    distance = 2 * 6371000.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    if method == "distance":
        outside = distance > tolerance
    else:
        # Use each reference station/axis's original written precision.
        # For manually supplied tables, infer precision from the numeric value.
        precision = observations.attrs.get("coordinate_precision", {})
        outside = np.zeros(len(result), dtype=bool)
        for axis in ("latitude", "longitude"):
            for index, (station, value, ref) in enumerate(zip(
                result["station_id"], result[axis], reference_coords[axis]
            )):
                digits = precision.get((str(station), axis),
                    max(0, -Decimal(str(ref)).as_tuple().exponent))
                quantum = Decimal(1).scaleb(-digits)
                outside[index] |= (
                    Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
                    != Decimal(str(ref)).quantize(quantum, rounding=ROUND_HALF_UP)
                )
    report = result.loc[outside, ["station_id", "latitude", "longitude"]].copy()
    report["reference_latitude"] = reference_coords.loc[outside, "latitude"]
    report["reference_longitude"] = reference_coords.loc[outside, "longitude"]
    report["distance_m"] = distance[outside]
    report = report.drop_duplicates().sort_values(["station_id", "distance_m"])
    if not report.empty:
        print(f"Coordinate conflicts ({method}): {report['station_id'].nunique()} stations.")
        print(report.to_csv(index=False, float_format="%.6f"), end="")
        if on_conflict == "error":
            names = report["station_id"].astype(str).unique().tolist()
            raise ConfigError(f"Station coordinate conflicts ({method}); exceed tolerance or rounding mismatch: {names}")
    result[["latitude", "longitude"]] = reference_coords
    return result
