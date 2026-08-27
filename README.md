# wrfchem-site-eval

Configuration-driven extraction and evaluation of WRF/WRF-Chem meteorology
and chemistry against surface observations.

This repository is being developed as a replacement for a collection of
site-by-site NCO scripts. The new workflow will read each WRF output file once,
extract all requested stations together, match model and observations, and
evaluate multiple simulation cases consistently.

## Current status

Version `0.1.0` defines the package, configuration interface, variable
dependency planner, and command-line interface. It intentionally does not yet
implement production WRF extraction or evaluation. Those algorithms will be
added after the configuration interface has been reviewed.

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

## Planned workflow

```text
WRF output -> station mapping -> vectorized station extraction
           -> observation matching -> metrics and figures
```

See `configs/example_case.yaml` and the observation templates under
`configs/observations/` for the proposed user-facing interface.
