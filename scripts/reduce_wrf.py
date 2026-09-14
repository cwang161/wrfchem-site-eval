#!/usr/bin/env python3
"""Optional standalone entry point for creating compact WRF evaluation files."""

from __future__ import annotations

import argparse

from wrfchem_site_eval.reduce_wrf import reduce_from_case_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Keep only configured evaluation variables and surface chemistry"
    )
    parser.add_argument("config", help="Case YAML used by wrfchem-site-eval")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing reduced files")
    args = parser.parse_args()
    outputs = reduce_from_case_config(args.config, overwrite=args.overwrite)
    print(f"Prepared {len(outputs)} reduced WRF files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
