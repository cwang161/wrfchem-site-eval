# wrfchem-site-eval

Configuration-driven extraction and evaluation of WRF/WRF-Chem meteorology
and chemistry against surface observations.

This repository is being developed as a replacement for a collection of
site-by-site NCO scripts. The new workflow will read each WRF output file once,
extract all requested stations together, match model and observations, and
evaluate multiple simulation cases consistently.

## Current status

Version `0.2.0` adds standardized chemistry/meteorology observation readers
and station-to-WRF mapping. Production time-series extraction and evaluation
metrics remain under development.

## Install for development

```bash
python -m pip install -e ".[test]"
```

## Inspect and validate a case

```bash
wrfchem-site-eval validate-config configs/example_case.yaml
wrfchem-site-eval show-plan configs/example_case.yaml
```

The second command reports the WRF variables required by the requested met and
chem evaluations. Chemistry stations may request meteorology at the same
locations with `include_met_at_sites: true`.

Normalize a QC-controlled chemistry file:

```bash
wrfchem-site-eval normalize-observations \
  configs/observations/chem_qc.yaml \
  --output output/chem_observations.parquet
```

Generate a station mapping from a representative WRF output file:

```bash
wrfchem-site-eval map-stations \
  configs/observations/chem_qc.yaml \
  /path/to/wrfout_d01_2019-01-01_00:00:00 \
  --method bilinear \
  --output output/station_mapping_chem.csv
```

Chemistry input is now expected in one combined-wide QC table: each row is a
station and timestamp, pollutant values occupy separate columns, coordinates
are stored as latitude/longitude, and optional `<pollutant>_qc_flag` columns
control which observations enter evaluation.

Configuration details are documented in
`docs/observation_configuration.md`.

## Planned workflow

```text
WRF output -> station mapping -> vectorized station extraction
           -> observation matching -> metrics and figures
```

See `configs/example_case.yaml` and the observation templates under
`configs/observations/` for the proposed user-facing interface.
