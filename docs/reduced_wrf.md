# Optional reduced WRF files

The package supports two equivalent extraction paths:

```text
original wrfout -> station extraction
original wrfout -> reduced wrfout -> station extraction
```

Reduced files retain configured raw variables, WRF global projection
attributes and selected vertical levels. They are ordinary NetCDF files and
keep the original filenames. Original wrfout files are never changed or deleted.

Configure the optional stage under `wrf.reduction`:

```yaml
wrf:
  input_dir: /data/original_wrfout
  file_pattern: "wrfout_d01_*"
  reduction:
    enabled: false
    output_dir: /data/reduced_wrfout
    use_for_extraction: false
    overwrite: false
    compression_level: 2
    variables: [T2, Q2, PSFC, U10, V10, PM2_5_DRY, o3]
    levels:
      default: surface
      variables:
        o3: [0, 1, 2]
        PM2_5_DRY: {start: 0, stop: 3, step: 1}
```

## Variables and vertical levels

`reduction.variables` uses raw names exactly as they appear in wrfout and is
independent of station extraction and evaluation. `Times`, `XLAT` and `XLONG`
are always added. If the list is omitted, the minimum raw dependency set is
inferred from `extraction`. Extra variables not used for station evaluation are
allowed.

`levels.default` applies to every retained variable carrying a `bottom_top` or
`bottom_top_stag` dimension. Two-dimensional variables ignore it. It accepts:

```yaml
levels:
  default: surface       # zero-based index 0; remove the vertical dimension
```

```yaml
levels:
  default: all           # retain every level
```

```yaml
levels:
  default: 2             # retain only zero-based index 2
```

Individual raw variables can override the default:

```yaml
levels:
  default: surface
  variables:
    o3: [0, 1, 2]
    PM2_5_DRY: {start: 0, stop: 5}
    P: all
    PH: {start: 0, stop: 10, step: 2}
```

Integer lists select explicit levels. Slice mappings follow Python rules, so
`stop` is excluded. Out-of-range and empty selections fail. Variables retaining
different subsets receive independent vertical dimensions, preventing xarray
from padding one variable to another variable's level set.

If an explicit raw-variable list omits a dependency required by station
`extraction`, configuration validation reports the missing variable.

## Direct extraction

Leave both flags false. `run` reads original files and creates no reduced copy.

## Create reduced files separately

Run either command:

```bash
python -m wrfchem_site_eval reduce-wrf configs/my_case.yaml
python scripts/reduce_wrf.py configs/my_case.yaml
```

After verifying the manifest and compact NetCDF files, they can be retained
when original wrfout files are archived or deleted. To extract from them later:

```yaml
reduction:
  enabled: false
  output_dir: /data/reduced_wrfout
  use_for_extraction: true
```

In this mode `input_dir` is not accessed by the evaluation pipeline. The
reduced directory is searched with the same `file_pattern`.

## Create and immediately use reduced files

Set both `enabled` and `use_for_extraction` true. A single `run` command first
creates missing compact files and then evaluates them. Existing validated
compact files are reused; `overwrite: true` or `--overwrite` recreates them.

Each output contains provenance attributes and the directory contains
`reduced_wrf_manifest.json` with source/output paths and file sizes.
