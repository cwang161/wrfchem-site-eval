"""Create compact WRF files containing only evaluation variables.

This optional preprocessing step is useful when original wrfout files will be
deleted or archived.  The regular extraction engine reads the reduced files in
exactly the same way as original WRF output.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path

import numpy as np

from .errors import ConfigError
from .config import build_plan, load_config
from .extraction import discover_wrf_files
from .variables import OPTIONAL_WRF_VARIABLES


def _surface_only(data_array):
    result = data_array
    for dimension in tuple(result.dims):
        if dimension.startswith("bottom_top"):
            result = result.isel({dimension: 0}, drop=True)
    return result


def reduce_wrf_file(
    source: str | Path,
    destination: str | Path,
    variables: Iterable[str],
    *,
    overwrite: bool = False,
    compression_level: int = 2,
) -> Path:
    """Write one compact NetCDF while retaining WRF metadata and surface chemistry."""

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
    if output_path.exists() and not overwrite:
        with xr.open_dataset(output_path, decode_times=False) as existing:
            absent = [
                name for name in requested
                if name not in existing and name not in OPTIONAL_WRF_VARIABLES
                and name not in {"SINALPHA", "COSALPHA"}
            ]
            recorded_source = existing.attrs.get("WRFCHEM_SITE_EVAL_SOURCE")
            if not existing.attrs.get("WRFCHEM_SITE_EVAL_REDUCED") or absent:
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
            name: _surface_only(source_dataset[name])
            for name in requested if name in source_dataset
        }
        reduced = xr.Dataset(retained, attrs=dict(source_dataset.attrs))
        reduced.attrs["WRFCHEM_SITE_EVAL_REDUCED"] = 1
        reduced.attrs["WRFCHEM_SITE_EVAL_SOURCE"] = str(source_path)
        reduced.attrs["WRFCHEM_SITE_EVAL_SURFACE_CHEM"] = 1
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
) -> list[Path]:
    """Reduce a sequence of WRF files and write a source/output manifest."""

    sources = [Path(value).expanduser().resolve() for value in files]
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    outputs = []
    records = []
    for source in sources:
        destination = root / source.name
        output = reduce_wrf_file(
            source, destination, variables, overwrite=overwrite,
            compression_level=compression_level,
        )
        outputs.append(output)
        records.append({
            "source": str(source),
            "output": str(output),
            "source_size_bytes": source.stat().st_size,
            "output_size_bytes": output.stat().st_size,
        })
    manifest = {
        "variables": list(dict.fromkeys(str(name) for name in variables)),
        "surface_chemistry_only": True,
        "files": records,
    }
    (root / "reduced_wrf_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return outputs


def reduce_from_case_config(config_path: str | Path, *, overwrite: bool = False) -> list[Path]:
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
    output_value = settings.get("output_dir")
    if not output_value:
        raise ConfigError("'wrf.reduction.output_dir' is required for reduced WRF output")
    output_dir = Path(str(output_value)).expanduser()
    if not output_dir.is_absolute():
        output_dir = (config_file.parent / output_dir).resolve()
    return reduce_wrf_files(
        files,
        output_dir,
        plan.wrf_variables,
        overwrite=overwrite,
        compression_level=int(settings.get("compression_level", 2)),
    )
