"""Load and validate user-facing YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .variables import required_wrf_variables


@dataclass(frozen=True)
class EvaluationPlan:
    case_name: str
    met_variables: tuple[str, ...]
    chem_variables: tuple[str, ...]
    chem_station_variables: tuple[str, ...]
    wrf_variables: tuple[str, ...]


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"'{path}' must be a mapping")
    return value


def _string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{path}' must be a list of strings")
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Configuration file does not exist: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return _mapping(data, "config")


def build_plan(config: dict[str, Any]) -> EvaluationPlan:
    case = _mapping(config.get("case"), "case")
    case_name = case.get("name")
    if not isinstance(case_name, str) or not case_name.strip():
        raise ConfigError("'case.name' must be a non-empty string")

    evaluation = _mapping(config.get("evaluation"), "evaluation")
    met_variables = _string_list(evaluation.get("met", []), "evaluation.met")
    chem_variables = _string_list(evaluation.get("chem", []), "evaluation.chem")

    station_groups = _mapping(config.get("station_groups"), "station_groups")
    chem_group = _mapping(station_groups.get("chem", {}), "station_groups.chem")
    include_met = bool(chem_group.get("include_met_at_sites", True))
    chem_station_variables = chem_variables + (met_variables if include_met else [])

    requested = list(dict.fromkeys(met_variables + chem_station_variables))
    try:
        wrf_variables = required_wrf_variables(requested)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc

    wrf = _mapping(config.get("wrf"), "wrf")
    for key in ("input_dir", "file_pattern"):
        if not isinstance(wrf.get(key), str) or not wrf[key].strip():
            raise ConfigError(f"'wrf.{key}' must be a non-empty string")
    enabled = []
    for group_name in ("met", "chem"):
        group = _mapping(station_groups.get(group_name, {}), f"station_groups.{group_name}")
        if group.get("enabled", False):
            enabled.append(group_name)
            if not isinstance(group.get("observation_config"), str):
                raise ConfigError(f"'station_groups.{group_name}.observation_config' is required")
            if group.get("interpolation", "nearest") not in {"nearest", "bilinear"}:
                raise ConfigError(f"'station_groups.{group_name}.interpolation' must be nearest or bilinear")
    if not enabled:
        raise ConfigError("At least one station group must be enabled")

    return EvaluationPlan(
        case_name=case_name,
        met_variables=tuple(met_variables),
        chem_variables=tuple(chem_variables),
        chem_station_variables=tuple(dict.fromkeys(chem_station_variables)),
        wrf_variables=tuple(wrf_variables),
    )
