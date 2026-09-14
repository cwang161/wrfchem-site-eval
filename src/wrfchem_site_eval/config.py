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
    met_evaluation_variables: tuple[str, ...]
    chem_evaluation_variables: tuple[str, ...]
    met_extraction_variables: tuple[str, ...]
    chem_extraction_variables: tuple[str, ...]
    chem_station_extraction_variables: tuple[str, ...]
    wrf_variables: tuple[str, ...]

    # Backward-compatible names used by earlier package versions.
    @property
    def met_variables(self) -> tuple[str, ...]:
        return self.met_evaluation_variables

    @property
    def chem_variables(self) -> tuple[str, ...]:
        return self.chem_evaluation_variables

    @property
    def chem_station_variables(self) -> tuple[str, ...]:
        return self.chem_station_extraction_variables


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
    met_evaluation = _string_list(evaluation.get("met", []), "evaluation.met")
    chem_evaluation = _string_list(evaluation.get("chem", []), "evaluation.chem")

    extraction_value = config.get("extraction")
    if extraction_value is None:
        # Existing case files continue to work exactly as before.
        extraction: dict[str, Any] = {}
    else:
        extraction = _mapping(extraction_value, "extraction")
    met_extraction = _string_list(
        extraction.get("met", met_evaluation), "extraction.met"
    )
    chem_extraction = _string_list(
        extraction.get("chem", chem_evaluation), "extraction.chem"
    )

    station_groups = _mapping(config.get("station_groups"), "station_groups")
    chem_group = _mapping(station_groups.get("chem", {}), "station_groups.chem")
    include_met = bool(chem_group.get("include_met_at_sites", True))
    met_at_chem = _string_list(
        extraction.get("met_at_chem_sites", met_extraction),
        "extraction.met_at_chem_sites",
    ) if include_met else []
    chem_station_extraction = list(dict.fromkeys(chem_extraction + met_at_chem))

    missing_met = sorted(set(met_evaluation) - set(met_extraction))
    missing_chem = sorted(set(chem_evaluation) - set(chem_extraction))
    if missing_met:
        raise ConfigError(f"evaluation.met variables are not extracted: {missing_met}")
    if missing_chem:
        raise ConfigError(f"evaluation.chem variables are not extracted: {missing_chem}")

    requested = list(dict.fromkeys(met_extraction + chem_station_extraction))
    try:
        wrf_variables = required_wrf_variables(requested)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc

    wrf = _mapping(config.get("wrf"), "wrf")
    for key in ("input_dir", "file_pattern"):
        if not isinstance(wrf.get(key), str) or not wrf[key].strip():
            raise ConfigError(f"'wrf.{key}' must be a non-empty string")
    reduction = _mapping(wrf.get("reduction", {}), "wrf.reduction")
    if reduction.get("enabled", False) or reduction.get("use_for_extraction", False):
        if not isinstance(reduction.get("output_dir"), str) or not reduction["output_dir"].strip():
            raise ConfigError("'wrf.reduction.output_dir' must be set when reduction is enabled or used")
    compression = reduction.get("compression_level", 2)
    if not isinstance(compression, int) or not 0 <= compression <= 9:
        raise ConfigError("'wrf.reduction.compression_level' must be an integer from 0 to 9")
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
        met_evaluation_variables=tuple(met_evaluation),
        chem_evaluation_variables=tuple(chem_evaluation),
        met_extraction_variables=tuple(met_extraction),
        chem_extraction_variables=tuple(chem_extraction),
        chem_station_extraction_variables=tuple(chem_station_extraction),
        wrf_variables=tuple(wrf_variables),
    )
