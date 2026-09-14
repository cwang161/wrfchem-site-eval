# Optional reduced WRF files

The package supports two equivalent extraction paths:

```text
original wrfout -> station extraction
original wrfout -> reduced wrfout -> station extraction
```

Reduced files retain `Times`, `XLAT`, `XLONG`, all raw dependencies of the
configured evaluation variables, WRF global projection attributes, and only
`bottom_top=0` for chemistry. They are ordinary NetCDF files and keep the
original filenames. Original wrfout files are never changed or deleted.

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
```

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
