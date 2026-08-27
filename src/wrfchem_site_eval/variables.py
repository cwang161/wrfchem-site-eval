"""Canonical evaluation variables and their raw WRF dependencies."""

from __future__ import annotations

WRF_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "temperature": ("T2",),
    "relative_humidity": ("Q2", "T2", "PSFC"),
    "wind_speed": ("U10", "V10", "SINALPHA", "COSALPHA"),
    "wind_direction": ("U10", "V10", "SINALPHA", "COSALPHA"),
    "precipitation": ("RAINC", "RAINNC", "RAINSH"),
    "surface_pressure": ("PSFC",),
    "pbl_height": ("PBLH",),
    "surface_temperature": ("TSK",),
    "pm25": ("PM2_5_DRY",),
    "pm10": ("PM10",),
    "o3": ("o3",),
    "no2": ("no2",),
    "so2": ("so2",),
    "co": ("co",),
    "no": ("no",),
    "nh3": ("nh3",),
}

OPTIONAL_WRF_VARIABLES = {"RAINSH"}
COORDINATE_VARIABLES = ("Times", "XLAT", "XLONG")


def required_wrf_variables(canonical_variables: list[str]) -> list[str]:
    unknown = sorted(set(canonical_variables) - WRF_DEPENDENCIES.keys())
    if unknown:
        supported = ", ".join(sorted(WRF_DEPENDENCIES))
        raise KeyError(f"Unsupported canonical variables: {unknown}. Supported: {supported}")

    result = set(COORDINATE_VARIABLES)
    for variable in canonical_variables:
        result.update(WRF_DEPENDENCIES[variable])
    return sorted(result)
