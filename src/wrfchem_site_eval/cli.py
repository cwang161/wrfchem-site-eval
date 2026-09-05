"""Command-line interface for configuration review and later pipeline stages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import build_plan, load_config
from .errors import ConfigError
from .observations import read_observations, station_table
from .station_mapping import map_stations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wrfchem-site-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-config", "show-plan"):
        child = subparsers.add_parser(command)
        child.add_argument("config", help="Path to a case YAML file")
    normalize = subparsers.add_parser("normalize-observations")
    normalize.add_argument("config", help="Path to an observation YAML file")
    normalize.add_argument("--output", required=True, help="Output CSV or Parquet")
    mapping = subparsers.add_parser("map-stations")
    mapping.add_argument("observation_config", help="Path to an observation YAML file")
    mapping.add_argument("wrf_file", help="Representative WRF output file")
    mapping.add_argument("--method", choices=("nearest", "bilinear"), default="nearest")
    mapping.add_argument("--output", required=True, help="Output station mapping CSV")
    return parser


def _write_table(data, output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        data.to_parquet(path, index=False)
    elif path.suffix.lower() == ".csv":
        data.to_csv(path, index=False)
    else:
        raise ConfigError("Output must end in .csv or .parquet")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"normalize-observations", "map-stations"}:
        try:
            observations = read_observations(args.config if args.command == "normalize-observations" else args.observation_config)
            if args.command == "normalize-observations":
                _write_table(observations, args.output)
                print(f"Wrote {len(observations)} normalized observations to {args.output}")
            else:
                stations = station_table(observations)
                mapping = map_stations(stations, args.wrf_file, args.method)
                _write_table(mapping, args.output)
                print(f"Wrote {len(mapping)} station mappings to {args.output}")
            return 0
        except (ConfigError, ImportError) as exc:
            print(f"Error: {exc}")
            return 2
    try:
        plan = build_plan(load_config(args.config))
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    if args.command == "validate-config":
        print(f"Configuration is valid for case: {plan.case_name}")
        return 0

    print(json.dumps({
        "case": plan.case_name,
        "met_station_variables": plan.met_variables,
        "chem_variables": plan.chem_variables,
        "chem_station_variables": plan.chem_station_variables,
        "required_wrf_variables": plan.wrf_variables,
    }, indent=2))
    return 0
