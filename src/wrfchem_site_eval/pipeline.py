"""End-to-end orchestration for a configured WRF-Chem evaluation case."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from .config import build_plan, load_config
from .errors import ConfigError
from .evaluation import aggregate_time, calculate_metrics, collocate
from .extraction import discover_wrf_files, extract_wrf_timeseries, finalize_precipitation
from .observations import read_observations, station_table
from .plotting import create_evaluation_figures
from .station_mapping import map_stations


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _table_path(root: Path, name: str, fmt: str) -> Path:
    suffix = "parquet" if fmt == "parquet" else "csv"
    return root / f"{name}.{suffix}"


def _write(data: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    if path.suffix == ".parquet":
        data.to_parquet(temporary, index=False)
    else:
        data.to_csv(temporary, index=False)
    temporary.replace(path)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["time"])


def _group_settings(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get("station_groups", {}).get(name, {})
    return value if isinstance(value, dict) else {}


def _file_token(path: Path) -> str:
    stat = path.stat()
    value = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha1(value).hexdigest()[:12]


def run_case(config_path: str | Path, resume: bool = False) -> dict[str, Path]:
    """Run normalization, mapping, extraction, matching and metrics for one case."""

    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    plan = build_plan(config)
    wrf = config.get("wrf", {})
    input_dir = _resolve(config_file.parent, str(wrf.get("input_dir", "")))
    files = discover_wrf_files(input_dir, str(wrf.get("file_pattern", "wrfout_*")))
    output = config.get("output", {})
    root = _resolve(config_file.parent, str(output.get("directory", f"output/{plan.case_name}")))
    fmt = str(output.get("format", "parquet")).lower()
    if fmt not in {"csv", "parquet"}:
        raise ConfigError("output.format must be csv or parquet")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    previous_manifest: dict[str, Any] = {}
    if resume and manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous_manifest = {}
    same_wrf_inputs = previous_manifest.get("wrf_files") == [str(path) for path in files]

    observations: dict[str, pd.DataFrame] = {}
    mappings: dict[str, pd.DataFrame] = {}
    active: dict[str, tuple[pd.DataFrame, tuple[str, ...]]] = {}
    variables = {"met": plan.met_variables, "chem": plan.chem_station_variables}
    for name in ("met", "chem"):
        settings = _group_settings(config, name)
        if not settings.get("enabled", False):
            continue
        obs_config = _resolve(config_file.parent, str(settings.get("observation_config", "")))
        observations[name] = read_observations(obs_config)
        mapping_file = _table_path(root, f"station_mapping_{name}", "csv")
        current_stations = station_table(observations[name])
        reuse_mapping = False
        if resume and mapping_file.exists():
            candidate = pd.read_csv(mapping_file)
            expected_ids = set(current_stations["station_id"].astype(str))
            candidate_ids = set(candidate["station_id"].astype(str))
            expected_method = str(settings.get("interpolation", "nearest"))
            reuse_mapping = expected_ids == candidate_ids and set(candidate["interpolation"]) == {expected_method}
            if reuse_mapping:
                mappings[name] = candidate
        if not reuse_mapping:
            mappings[name] = map_stations(
                current_stations, files[0], str(settings.get("interpolation", "nearest"))
            )
            _write(mappings[name], mapping_file)
        active[name] = (mappings[name], variables[name])

    model: dict[str, pd.DataFrame] = {}
    to_extract: dict[str, tuple[pd.DataFrame, tuple[str, ...]]] = {}
    for name, definition in active.items():
        path = _table_path(root, f"model_{name}", fmt)
        if resume and same_wrf_inputs and path.exists():
            candidate = _read(path)
            if set(variables[name]).issubset(candidate.columns):
                model[name] = candidate
            else:
                to_extract[name] = definition
        else:
            to_extract[name] = definition
    if to_extract:
        checkpoint_root = root / ".checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        pieces: dict[str, list[pd.DataFrame]] = {name: [] for name in to_extract}
        for index, wrf_file in enumerate(files):
            missing: dict[str, tuple[pd.DataFrame, tuple[str, ...]]] = {}
            token = _file_token(wrf_file)
            checkpoint_paths = {
                name: _table_path(checkpoint_root, f"{index:06d}_{token}_{name}", fmt)
                for name in to_extract
            }
            for name in to_extract:
                checkpoint = checkpoint_paths[name]
                if resume and checkpoint.exists():
                    pieces[name].append(_read(checkpoint))
                else:
                    missing[name] = to_extract[name]
            if missing:
                # All missing groups are handled together, so this WRF file is opened once.
                extracted = extract_wrf_timeseries([wrf_file], missing, finalize=False)
                for name, table in extracted.items():
                    _write(table, checkpoint_paths[name])
                    pieces[name].append(table)
        for name, chunks in pieces.items():
            table = pd.concat(chunks, ignore_index=True).sort_values(["station_id", "time"])
            duplicate = table.duplicated(["station_id", "time"], keep=False)
            if duplicate.any():
                examples = table.loc[duplicate, ["station_id", "time"]].head(3).to_dict("records")
                raise ConfigError(f"Duplicate WRF station/time records; examples: {examples}")
            table = finalize_precipitation(table)
            model[name] = table
            _write(table, _table_path(root, f"model_{name}", fmt))

    products: dict[str, Path] = {}
    matching = config.get("matching", {})
    tolerance = matching.get("tolerance")
    frequency = matching.get("frequency")
    for name in active:
        obs, mod = observations[name], model[name]
        if frequency:
            common_minimum = matching.get("minimum_count")
            obs = aggregate_time(
                obs, str(frequency),
                minimum_count=matching.get("observation_minimum_count", common_minimum),
                offset=matching.get("offset"),
            )
            mod = aggregate_time(
                mod, str(frequency),
                minimum_count=matching.get("model_minimum_count", common_minimum),
                offset=matching.get("offset"),
            )
        paired = collocate(obs, mod, variables[name], tolerance=tolerance)
        paired_path = _table_path(root, f"matched_{name}", fmt)
        _write(paired, paired_path)
        metrics = calculate_metrics(paired, variables[name], plan.case_name)
        metrics_path = _table_path(root, f"metrics_{name}", fmt)
        _write(metrics, metrics_path)
        products[f"matched_{name}"] = paired_path
        products[f"metrics_{name}"] = metrics_path
        figure_settings = config.get("figures", {})
        if figure_settings.get("enabled", False):
            figures = create_evaluation_figures(
                paired, variables[name], plan.case_name, root / "figures" / name
            )
            for index, figure in enumerate(figures):
                products[f"figure_{name}_{index:02d}"] = figure

    manifest = {
        "case": plan.case_name,
        "config": str(config_file),
        "wrf_files": [str(path) for path in files],
        "products": {key: str(value) for key, value in products.items()},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    products["manifest"] = manifest_path
    return products
