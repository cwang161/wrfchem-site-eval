"""Create compact WRF files containing only evaluation variables.

This optional preprocessing step is useful when original wrfout files will be
deleted or archived.  The regular extraction engine reads the reduced files in
exactly the same way as original WRF output.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from pathlib import Path
import re

import numpy as np

from .errors import ConfigError
from .config import build_plan, load_config
from .extraction import discover_wrf_files
from .variables import OPTIONAL_WRF_VARIABLES, WRF_GRID_VARIABLES


def _vertical_dimension_name(dimension: str, variable: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", variable)
    return f"{dimension}__{safe}"


def _select_vertical_levels(data_array, selection, variable: str):
    """Apply a level selection to WRF bottom_top dimensions."""

    result = data_array
    for dimension in tuple(result.dims):
        if not dimension.startswith("bottom_top") or selection == "all":
            continue
        size = result.sizes[dimension]
        if selection == "surface":
            indices = 0
        elif isinstance(selection, int):
            indices = selection
        elif isinstance(selection, list):
            indices = selection
        elif isinstance(selection, Mapping):
            level_slice = slice(
                selection.get("start"), selection.get("stop"), selection.get("step")
            )
            indices = np.arange(size)[level_slice].tolist()
        else:  # Configuration validation should normally catch this first.
            raise ConfigError(f"Invalid vertical selection for {variable}: {selection}")
        try:
            if isinstance(indices, int):
                result = result.isel({dimension: indices}, drop=True)
            else:
                if not indices:
                    raise ConfigError(f"Vertical selection for {variable} is empty")
                result = result.isel({dimension: indices})
                result = result.rename({dimension: _vertical_dimension_name(dimension, variable)})
        except IndexError as exc:
            raise ConfigError(
                f"Vertical selection {selection} is outside {variable}'s {dimension} size {size}"
            ) from exc
    return result


def reduce_wrf_file(
    source: str | Path,
    destination: str | Path,
    variables: Iterable[str],
    *,
    overwrite: bool = False,
    compression_level: int = 2,
    default_levels="surface",
    variable_levels: Mapping[str, object] | None = None,
) -> Path:
    """Write one compact NetCDF while retaining configured variables and levels."""

    try:
        import xarray as xr
    except ImportError as exc:
        raise ConfigError("WRF reduction requires xarray and netCDF4") from exc

    source_path = Path(source).expanduser().resolve()
    output_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise ConfigError(f"WRF file does not exist: {source_path}")
    if source_path == output_path:
        raise ConfigError("Reduced WRF output cannot overwrite its source path")
    requested = tuple(dict.fromkeys(str(name) for name in variables))
    overrides = dict(variable_levels or {})
    level_signature = json.dumps(
        {"default": default_levels, "variables": overrides}, sort_keys=True
    )
    if output_path.exists() and not overwrite:
        with xr.open_dataset(output_path, decode_times=False) as existing:
            absent = [
                name for name in requested
                if name not in existing and name not in OPTIONAL_WRF_VARIABLES
                and name not in {"SINALPHA", "COSALPHA"}
            ]
            recorded_source = existing.attrs.get("WRFCHEM_SITE_EVAL_SOURCE")
            recorded_levels = existing.attrs.get("WRFCHEM_SITE_EVAL_LEVELS")
            if (
                not existing.attrs.get("WRFCHEM_SITE_EVAL_REDUCED")
                or absent
                or recorded_levels != level_signature
            ):
                raise ConfigError(
                    f"Existing reduced file is incomplete: {output_path}; "
                    "rerun with --overwrite"
                )
            if recorded_source and Path(str(recorded_source)) != source_path:
                raise ConfigError(
                    f"Existing reduced file came from a different source: {output_path}; "
                    "rerun with --overwrite"
                )
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(source_path, decode_times=False) as source_dataset:
        missing = [
            name for name in requested
            if name not in source_dataset and name not in OPTIONAL_WRF_VARIABLES
            and name not in {"SINALPHA", "COSALPHA"}
        ]
        if missing:
            raise ConfigError(f"Required WRF variables missing from {source_path}: {missing}")
        retained = {
            name: _select_vertical_levels(
                source_dataset[name], overrides.get(name, default_levels), name
            )
            for name in requested if name in source_dataset
        }
        reduced = xr.Dataset(retained, attrs=dict(source_dataset.attrs))
        reduced.attrs["WRFCHEM_SITE_EVAL_REDUCED"] = 1
        reduced.attrs["WRFCHEM_SITE_EVAL_SOURCE"] = str(source_path)
        reduced.attrs["WRFCHEM_SITE_EVAL_LEVELS"] = level_signature
        encoding = {}
        for name, data_array in reduced.data_vars.items():
            if np.issubdtype(data_array.dtype, np.number):
                encoding[name] = {
                    "zlib": True,
                    "complevel": int(compression_level),
                    "shuffle": True,
                }
        temporary = output_path.with_name(f".{output_path.name}.tmp.nc")
        try:
            reduced.to_netcdf(temporary, engine="netcdf4", encoding=encoding)
            temporary.replace(output_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return output_path


def reduce_wrf_files(
    files: Iterable[str | Path],
    output_dir: str | Path,
    variables: Iterable[str],
    *,
    overwrite: bool = False,
    compression_level: int = 2,
    default_levels="surface",
    variable_levels: Mapping[str, object] | None = None,
    workers: int = 1,
) -> list[Path]:
    """Reduce WRF files, optionally in separate worker processes."""

    sources = [Path(value).expanduser().resolve() for value in files]
    if workers < 1:
        raise ConfigError("workers must be at least 1")
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    requested_variables = tuple(dict.fromkeys(str(name) for name in variables))
    jobs = [
        (
            source,
            root / source.name,
            requested_variables,
            overwrite,
            compression_level,
            default_levels,
            dict(variable_levels or {}),
        )
        for source in sources
    ]
    if workers == 1 or len(jobs) <= 1:
        outputs = [_reduce_wrf_job(job) for job in jobs]
    else:
        # executor.map preserves input order, so the manifest remains stable.
        # HDF5/netCDF libraries are not reliably fork-safe. A spawn context
        # gives every worker an independent library state.
        with ProcessPoolExecutor(
            max_workers=min(workers, len(jobs)),
            mp_context=multiprocessing.get_context("spawn"),
        ) as executor:
            outputs = list(executor.map(_reduce_wrf_job, jobs))

    records = []
    for source, output in zip(sources, outputs):
        records.append({
            "source": str(source),
            "output": str(output),
            "source_size_bytes": source.stat().st_size,
            "output_size_bytes": output.stat().st_size,
        })
    manifest = {
        "variables": list(requested_variables),
        "workers": min(workers, len(jobs)) if jobs else 0,
        "levels": {
            "default": default_levels,
            "variables": dict(variable_levels or {}),
        },
        "files": records,
    }
    (root / "reduced_wrf_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return outputs


def _reduce_wrf_job(job) -> Path:
    """Picklable process-pool entry point for one WRF file."""

    (
        source, destination, variables, overwrite, compression_level,
        default_levels, variable_levels,
    ) = job
    return reduce_wrf_file(
        source,
        destination,
        variables,
        overwrite=overwrite,
        compression_level=compression_level,
        default_levels=default_levels,
        variable_levels=variable_levels,
    )


def reduce_from_case_config(
    config_path: str | Path,
    *,
    overwrite: bool = False,
    workers: int | None = None,
) -> list[Path]:
    """Create reduced WRF files using the variables and paths in a case YAML."""

    config_file = Path(config_path).expanduser().resolve()
    config = load_config(config_file)
    plan = build_plan(config)
    wrf = config["wrf"]
    source_dir = Path(str(wrf["input_dir"])).expanduser()
    if not source_dir.is_absolute():
        source_dir = (config_file.parent / source_dir).resolve()
    files = discover_wrf_files(source_dir, str(wrf["file_pattern"]))
    settings = wrf.get("reduction", {})
    levels = settings.get("levels", {})
    output_value = settings.get("output_dir")
    if not output_value:
        raise ConfigError("'wrf.reduction.output_dir' is required for reduced WRF output")
    output_dir = Path(str(output_value)).expanduser()
    if not output_dir.is_absolute():
        output_dir = (config_file.parent / output_dir).resolve()
    reduction_variables = list(plan.reduction_variables)
    if not wrf.get("grid_file"):
        # Backward compatibility: without a static grid file, reduced outputs
        # must retain coordinates so station mapping can use the first file.
        reduction_variables = list(dict.fromkeys(
            reduction_variables + list(WRF_GRID_VARIABLES)
        ))
    configured_workers = int(settings.get("workers", 1))
    selected_workers = configured_workers if workers is None else workers
    return reduce_wrf_files(
        files,
        output_dir,
        reduction_variables,
        overwrite=overwrite,
        compression_level=int(settings.get("compression_level", 2)),
        default_levels=levels.get("default", "surface"),
        variable_levels=levels.get("variables", {}),
        workers=selected_workers,
    )
