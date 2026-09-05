# Changelog

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
