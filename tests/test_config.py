from pathlib import Path

import pytest

from wrfchem_site_eval.config import build_plan, load_config
from wrfchem_site_eval.errors import ConfigError


ROOT = Path(__file__).parents[1]


def test_example_config_includes_met_at_chem_sites():
    plan = build_plan(load_config(ROOT / "configs/example_case.yaml"))
    assert plan.case_name == "BASE2020"
    assert "pm25" in plan.chem_station_variables
    assert "temperature" in plan.chem_station_variables
    assert "PM2_5_DRY" in plan.wrf_variables
    assert "T2" in plan.wrf_variables
    assert "SINALPHA" in plan.wrf_variables


def test_unknown_variable_is_rejected():
    config = {
        "case": {"name": "bad"},
        "station_groups": {"chem": {}},
        "evaluation": {"met": ["not_a_variable"], "chem": []},
    }
    with pytest.raises(ConfigError, match="Unsupported canonical variables"):
        build_plan(config)
