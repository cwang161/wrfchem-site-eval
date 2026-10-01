# Changelog

## Observation configuration update

- Support only combined_wide and combined_sources observation profiles.
- Use source_unit and target_unit instead of unit.
- Recognize raw trace precipitation codes before conversion and retain trace flags.
- Use the supplied ISD-lite configuration.

## 1.9.0 - 2026-09-30

- Interpolate `T2`, `Q2`, and `PSFC` before deriving station relative humidity.
- Retain the established package RH formula after interpolation.
- Keep nearest-neighbor humidity behavior and add a bilinear regression test.

## 1.8.0 - 2026-09-15

- Keep WRF `U10`/`V10` and derived model winds in projected-grid coordinates.
- Interpolate grid-relative U/V components before deriving bilinear wind speed and direction.
- Calculate the Lambert projection convergence angle directly at each station.
- Rotate observed earth-relative wind direction into WRF grid coordinates at collocation.
- Apply the same observation rotation for nearest and bilinear comparisons.

## 1.7.0 - 2026-09-15

- Read static `SINALPHA` and `COSALPHA` wind-rotation fields from `geo_em`.
- Allow reduced and original wrfout files to omit static rotation fields.
- Share one static rotation grid across all extraction workers.
- Add configurable geo_em rotation variable names and regression tests.

## 1.6.0 - 2026-09-15

- Add `run --workers N` for file-level parallel station extraction.
- Extract met and chemistry station groups together while opening each WRF file once.
- Use spawned processes for safer parallel NetCDF/HDF5 access.
- Preserve resumable per-file checkpoints and bilinear interpolation behavior.

## 1.5.0 - 2026-09-15

- Add `reduce-wrf --workers N` for file-level parallel reduction.
- Support `wrf.reduction.workers` in complete case runs.
- Use independent spawned processes for safer parallel NetCDF/HDF5 access.
- Record the effective worker count in the reduction manifest.

## 1.4.0 - 2026-09-15

- Allow station mapping from `geo_em` XLAT_M/XLONG_M.
- Remove XLAT/XLONG from universal wrfout extraction dependencies.
- Avoid copying grid coordinates into reduced files when a static grid is configured.
- Preserve backward compatibility with wrfout XLAT/XLONG when no grid file is set.

## 1.3.0 - 2026-09-15

- Allow `wrf.reduction.variables` to select raw WRF variables independently.
- Add a default vertical-level selection and per-variable overrides.
- Support surface, all, one index, index lists and start/stop/step slices.
- Preserve distinct variable-specific subsets without alignment padding.
- Validate reduced variables against station-extraction dependencies.

## 1.2.0 - 2026-09-14

- Separate WRF extraction variable lists from evaluation variable lists.
- Add independent met, chemistry and met-at-chem-site extraction controls.
- Keep existing configurations backward compatible when `extraction` is absent.
- Validate that every evaluated variable is available in extracted outputs.

## 1.1.0 - 2026-09-14

- Add optional compact WRF preprocessing without modifying original files.
- Retain only configured dependencies and `bottom_top=0` chemistry.
- Support direct, create-and-use, and reuse-existing reduced-file modes.
- Add `reduce-wrf` CLI, standalone script, provenance manifest and equivalence tests.

## 1.0.0 - 2026-09-05

- Add end-to-end WRF/WRF-Chem extraction, matching and evaluation.
- Open each WRF file once for all station groups with resumable checkpoints.
- Derive RH, rotated winds and interval precipitation; convert gas units.
- Add consolidated met/chem products, metrics, figures and case comparison.

## 0.2.0 - 2026-09-05

- Add configurable combined-wide chemistry and ISD meteorology readers.
- Preserve pollutant QC flags and support configurable accepted flags.
- Standardize station IDs, timestamps, coordinates, units, and metadata.
- Add nearest-grid and Lambert/lat-lon bilinear station mapping.
- Add observation normalization and station mapping CLI commands.

## 0.1.0 - 2026-08-27

- Add installable Python package and command-line entry point.
- Add YAML case and observation configuration examples.
- Add canonical met/chem variable dependency planning.
- Include meteorology at chemistry stations through configuration.
- Add initial configuration validation tests.
