"""Command-line interface for configuration review and later pipeline stages."""

from __future__ import annotations

import argparse
import json

from .config import build_plan, load_config
from .errors import ConfigError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wrfchem-site-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-config", "show-plan"):
        child = subparsers.add_parser(command)
        child.add_argument("config", help="Path to a case YAML file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
