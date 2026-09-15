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


def test_extraction_is_independent_from_evaluation():
    config = {
        "case": {"name": "separate"},
        "wrf": {"input_dir": "/tmp", "file_pattern": "wrfout_*"},
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml"},
            "chem": {
                "enabled": True, "observation_config": "chem.yaml",
                "include_met_at_sites": True,
            },
        },
        "extraction": {
            "met": ["temperature", "wind_speed", "surface_pressure"],
            "chem": ["pm25", "o3", "no2"],
            "met_at_chem_sites": ["temperature", "surface_pressure"],
        },
        "evaluation": {"met": ["temperature"], "chem": ["pm25", "o3"]},
    }
    plan = build_plan(config)
    assert plan.met_extraction_variables == ("temperature", "wind_speed", "surface_pressure")
    assert plan.met_evaluation_variables == ("temperature",)
    assert plan.chem_extraction_variables == ("pm25", "o3", "no2")
    assert plan.chem_station_extraction_variables == (
        "pm25", "o3", "no2", "temperature", "surface_pressure"
    )
    assert "no2" in plan.chem_station_extraction_variables
    assert "no2" not in plan.chem_evaluation_variables


def test_evaluation_variable_must_be_extracted():
    config = {
        "case": {"name": "missing"},
        "wrf": {"input_dir": "/tmp", "file_pattern": "wrfout_*"},
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml"},
            "chem": {},
        },
        "extraction": {"met": ["temperature"], "chem": []},
        "evaluation": {"met": ["wind_speed"], "chem": []},
    }
    with pytest.raises(ConfigError, match="not extracted"):
        build_plan(config)


def test_explicit_reduction_variables_and_level_overrides():
    config = {
        "case": {"name": "levels"},
        "wrf": {
            "input_dir": "/tmp", "file_pattern": "wrfout_*",
            "reduction": {
                "variables": ["T2", "EXTRA_3D"],
                "levels": {
                    "default": "surface",
                    "variables": {"EXTRA_3D": [0, 2, 4]},
                },
            },
        },
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml"},
            "chem": {},
        },
        "extraction": {"met": ["temperature"], "chem": []},
        "evaluation": {"met": ["temperature"], "chem": []},
    }
    plan = build_plan(config)
    assert {"Times", "XLAT", "XLONG", "T2", "EXTRA_3D"} == set(
        plan.reduction_variables
    )


def test_explicit_reduction_variables_require_extraction_dependencies():
    config = {
        "case": {"name": "missing_raw"},
        "wrf": {
            "input_dir": "/tmp", "file_pattern": "wrfout_*",
            "reduction": {"variables": ["UNRELATED"]},
        },
        "station_groups": {
            "met": {"enabled": True, "observation_config": "met.yaml"},
            "chem": {},
        },
        "extraction": {"met": ["temperature"], "chem": []},
        "evaluation": {"met": ["temperature"], "chem": []},
    }
    with pytest.raises(ConfigError, match="does not contain extraction dependencies"):
        build_plan(config)
