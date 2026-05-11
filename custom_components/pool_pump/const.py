"""Constants for the Pool Pump smart-cycling integration."""

from __future__ import annotations

DOMAIN = "pool_pump"

# Platforms
PLATFORMS: list[str] = ["select", "sensor", "button"]

# Manual override modes (sovereign — bypass anti-flap rate limit).
# `auto` and `winter` are auto-modes that DO respect the rate limit.
MANUAL_MODES: frozenset[str] = frozenset({"off", "v1", "v2", "v3"})

# Config keys — Step 1: entities
CONF_PUMP_SPEED_ENTITY = "pump_speed_entity"
CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_WATER_TEMP_ENTITY = "water_temp_entity"
CONF_AIR_TEMP_ENTITY = "air_temp_entity"
CONF_TEMPO_ENTITY = "tempo_entity"          # optional: RTE Tempo color sensor

# Config keys — Step 2: thresholds
CONF_SAFETY_MARGIN_W = "safety_margin_w"
CONF_WATER_WARM_C = "water_warm_c"
CONF_AIR_WARM_C = "air_warm_c"

# Config keys — Step 3: v3 session limits
CONF_V3_MAX_MINUTES = "v3_max_minutes"
CONF_V3_COOLDOWN_MINUTES = "v3_cooldown_minutes"

# Config keys — Step 4 (advanced): anti-flap tuning
CONF_SOLAR_SMOOTH_ALPHA = "solar_smooth_alpha"
CONF_MIN_SPEED_DWELL_SECONDS = "min_speed_dwell_seconds"

# Defaults
DEFAULT_SAFETY_MARGIN_W = 200.0
DEFAULT_WATER_WARM_C = 24.0
DEFAULT_AIR_WARM_C = 28.0
DEFAULT_V3_MAX_MINUTES = 15
DEFAULT_V3_COOLDOWN_MINUTES = 30

# Coordinator update cadence (between reactive triggers)
UPDATE_INTERVAL_SECONDS = 30

# Anti-flap defaults: smoothing and rate limiting on speed changes.
# - SOLAR_SMOOTH_ALPHA is the EMA weight on the latest reading. Lower = more
#   smoothing. 0.3 makes a step change reach ~95% within ~10 ticks (~5 min).
#   Cloud passes (30–60 s) barely move the smoothed value, so the brain
#   doesn't see them as "surplus disappeared".
# - MIN_SPEED_DWELL_SECONDS bars consecutive speed changes from happening
#   faster than this. Manual mode and the force-skim button bypass it.
DEFAULT_SOLAR_SMOOTH_ALPHA = 0.3
DEFAULT_MIN_SPEED_DWELL_SECONDS = 60

# Mode constants — re-exported from decision for entity layer
from .decision import (  # noqa: E402  (placement after other constants on purpose)
    MODE_AUTO,
    MODE_OFF,
    MODE_V1,
    MODE_V2,
    MODE_V3,
    MODE_WINTER,
    MODES,
    PUMP_W,
)

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "CONF_PUMP_SPEED_ENTITY",
    "CONF_GRID_POWER_ENTITY",
    "CONF_WATER_TEMP_ENTITY",
    "CONF_AIR_TEMP_ENTITY",
    "CONF_TEMPO_ENTITY",
    "CONF_SAFETY_MARGIN_W",
    "CONF_WATER_WARM_C",
    "CONF_AIR_WARM_C",
    "CONF_V3_MAX_MINUTES",
    "CONF_V3_COOLDOWN_MINUTES",
    "CONF_SOLAR_SMOOTH_ALPHA",
    "CONF_MIN_SPEED_DWELL_SECONDS",
    "DEFAULT_SAFETY_MARGIN_W",
    "DEFAULT_WATER_WARM_C",
    "DEFAULT_AIR_WARM_C",
    "DEFAULT_V3_MAX_MINUTES",
    "DEFAULT_V3_COOLDOWN_MINUTES",
    "UPDATE_INTERVAL_SECONDS",
    "MODE_AUTO",
    "MODE_OFF",
    "MODE_V1",
    "MODE_V2",
    "MODE_V3",
    "MODE_WINTER",
    "MODES",
    "PUMP_W",
]
