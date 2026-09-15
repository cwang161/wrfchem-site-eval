"""Canonical evaluation variables and their raw WRF dependencies."""

from __future__ import annotations

WRF_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "temperature": ("T2",),
    "relative_humidity": ("Q2", "T2", "PSFC"),
    "wind_speed": ("U10", "V10"),
    "wind_direction": ("U10", "V10"),
    "precipitation": ("RAINC", "RAINNC", "RAINSH"),
    "surface_pressure": ("PSFC",),
    "pbl_height": ("PBLH",),
    "surface_temperature": ("TSK",),
    "pm25": ("PM2_5_DRY",),
    "pm10": ("PM10",),
    # Surface pressure and temperature are retained because ppmv gases are
    # converted to mass concentration at each grid cell and time.
    "o3": ("o3", "PSFC", "T2"),
    "no2": ("no2", "PSFC", "T2"),
    "so2": ("so2", "PSFC", "T2"),
    "co": ("co", "PSFC", "T2"),
    "no": ("no", "PSFC", "T2"),
    "nh3": ("nh3", "PSFC", "T2"),
}

OPTIONAL_WRF_VARIABLES = {"RAINSH"}
# Station extraction needs WRF time, but spatial coordinates may instead come
# from a static geo_em file. XLAT/XLONG are therefore not universal wrfout
# dependencies.
TIME_VARIABLES = ("Times",)
WRF_GRID_VARIABLES = ("XLAT", "XLONG")


def required_wrf_variables(canonical_variables: list[str]) -> list[str]:
    unknown = sorted(set(canonical_variables) - WRF_DEPENDENCIES.keys())
    if unknown:
        supported = ", ".join(sorted(WRF_DEPENDENCIES))
        raise KeyError(f"Unsupported canonical variables: {unknown}. Supported: {supported}")

    result = set(TIME_VARIABLES)
    for variable in canonical_variables:
        result.update(WRF_DEPENDENCIES[variable])
    return sorted(result)
