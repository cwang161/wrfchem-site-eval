# wrfchem-site-eval

Configuration-driven, end-to-end evaluation of WRF/WRF-Chem meteorology and
chemistry against surface stations. Version 1.0 replaces site-by-site NCO loops:
every WRF file is opened once and all met/chem stations are sampled together.

## Implemented workflow

```text
WRF files + met observations + chem observations
  -> standardized observations
  -> independent met/chem station mappings
  -> vectorized nearest or bilinear extraction
  -> exact or tolerance-based time matching
  -> consolidated met and chem tables
  -> overall/per-station metrics and optional figures
```

Chemistry stations can request meteorology at the same locations with
`include_met_at_sites: true`. The resulting `model_chem` and `matched_chem`
tables contain chemistry plus meteorology, while chemistry metrics use only
available chemistry observations.

## Installation

```bash
python -m pip install -e ".[test,runtime]"
python -m pytest -q
```

## Configure and run

Copy `configs/example_case.yaml` and the observation templates, then change
paths, source column names, time zones, requested variables and case name.
Internal Python modules do not need editing when observation names change.

```bash
wrfchem-site-eval validate-config my_case.yaml
wrfchem-site-eval show-plan my_case.yaml
wrfchem-site-eval run my_case.yaml
```

If an HPC job stops, restart completed extraction from checkpoints:

```bash
wrfchem-site-eval run my_case.yaml --resume
```

It can be chained directly after WRF in a batch script:

```bash
mpirun -np 80 ./wrf.exe && wrfchem-site-eval run my_case.yaml --resume
```

## Outputs

One case directory contains station mappings, `model_met.*`, `model_chem.*`,
`matched_met.*`, `matched_chem.*`, `metrics_met.*`, `metrics_chem.*`, optional
figures and `manifest.json`. `*` is CSV or Parquet. Tables are consolidated,
not one file per station; `station_id` remains available for filtering and ML.

Metrics include paired count, means, bias, MAE, RMSE, correlation, Willmott IOA,
NMB, NME, MFB and MFE. Wind-direction means, correlation and errors use circular methods. Cumulative
WRF precipitation is differenced independently for every station.

Compare simulation cases with:

```bash
wrfchem-site-eval compare-cases output/BASE/metrics_met.parquet \
  output/CASE2/metrics_met.parquet --output output/met_comparison.csv
```

Chemistry uses the combined-wide `chem_qc` profile. Column names, time zones,
scales and accepted QC flags are configured in YAML rather than internal code.
See `configs/example_case.yaml`, `configs/observations/` and
`docs/observation_configuration.md`.
