"""Shared test fixtures for pool_pump tests."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make `decision` importable without pulling in homeassistant.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "custom_components" / "pool_pump"),
)

from decision import Inputs, Thresholds  # noqa: E402


@pytest.fixture
def t0() -> datetime:
    """A fixed reference timestamp for deterministic tests."""
    return datetime(2026, 6, 15, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def thr() -> Thresholds:
    """Default thresholds matching the user's CS100 / Hayward VSTD setup."""
    return Thresholds()


@pytest.fixture
def base_inputs(t0: datetime) -> Inputs:
    """A 'normal afternoon' baseline: daylight, balanced grid, pump v1, no v3 history."""
    return Inputs(
        now=t0,
        daylight=True,
        grid_w=0.0,
        pump_speed=1,
        water_temp_c=22.0,
        air_temp_c=25.0,
        mode="auto",
        v3_started_at=None,
        v3_last_ended_at=None,
        force_skim_requested=False,
    )
