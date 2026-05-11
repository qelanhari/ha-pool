"""Tests for the pure decision logic in pool_pump.decision."""

from dataclasses import replace
from datetime import timedelta

import pytest

from decision import (  # type: ignore[import-not-found]
    MODE_AUTO,
    MODE_OFF,
    MODE_V1,
    MODE_V2,
    MODE_V3,
    MODE_WINTER,
    TEMPO_RED,
    Decision,
    Inputs,
    decide,
)


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------


class TestManualMode:
    def test_off(self, base_inputs, thr):
        d = decide(replace(base_inputs, mode=MODE_OFF), thr)
        assert d.target_speed == 0
        assert "manual=off" in d.reason

    def test_v1(self, base_inputs, thr):
        d = decide(replace(base_inputs, mode=MODE_V1), thr)
        assert d.target_speed == 1

    def test_v2(self, base_inputs, thr):
        d = decide(replace(base_inputs, mode=MODE_V2), thr)
        assert d.target_speed == 2

    def test_v3(self, base_inputs, thr):
        d = decide(replace(base_inputs, mode=MODE_V3), thr)
        assert d.target_speed == 3
        assert d.enter_v3 is True
        assert d.leave_v3 is False

    def test_manual_overrides_no_daylight(self, base_inputs, thr):
        """Manual mode wins even at night."""
        d = decide(replace(base_inputs, mode=MODE_V2, daylight=False), thr)
        assert d.target_speed == 2

    def test_leaving_v3_via_manual_drop(self, base_inputs, thr):
        """If pump was at v3 and user picks manual=v1, mark leave_v3."""
        d = decide(
            replace(base_inputs, pump_speed=3, mode=MODE_V1),
            thr,
        )
        assert d.target_speed == 1
        assert d.leave_v3 is True


# ---------------------------------------------------------------------------
# Daylight gate
# ---------------------------------------------------------------------------


class TestDaylightGate:
    def test_night_forces_v1(self, base_inputs, thr):
        d = decide(replace(base_inputs, daylight=False, grid_w=-3000.0), thr)
        assert d.target_speed == 1
        assert "night" in d.reason

    def test_night_drops_v3(self, base_inputs, thr):
        """A v3 session at the moment night falls should leave v3."""
        d = decide(
            replace(
                base_inputs,
                daylight=False,
                pump_speed=3,
                v3_started_at=base_inputs.now - timedelta(minutes=2),
            ),
            thr,
        )
        assert d.target_speed == 1
        assert d.leave_v3 is True


# ---------------------------------------------------------------------------
# v3 candidate gating: cooldown, warm, surplus
# ---------------------------------------------------------------------------


class TestV3Candidate:
    def test_v3_when_warm_and_surplus(self, base_inputs, thr):
        # Currently at v1 (160 W). To bump to v3 (1100 W) we'd add 940 W.
        # Need grid + 940 < -200 → grid < -1140.
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=26.0,  # warm
                v3_last_ended_at=None,
            ),
            thr,
        )
        assert d.target_speed == 3
        assert d.enter_v3 is True
        assert "v3" in d.reason

    def test_no_v3_if_not_warm(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=20.0,  # not warm
                air_temp_c=20.0,
                v3_last_ended_at=None,
            ),
            thr,
        )
        # Surplus exists but neither water nor air is warm enough.
        # v2 ALSO requires warmth, so we fall all the way back to v1.
        assert d.target_speed == 1

    def test_no_v3_if_in_cooldown(self, base_inputs, thr):
        # 15 min cooldown still active (default cooldown is 30 min).
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=26.0,
                v3_last_ended_at=base_inputs.now - timedelta(minutes=15),
            ),
            thr,
        )
        assert d.target_speed == 2  # surplus enough for v2

    def test_v3_after_cooldown_expires(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=26.0,
                v3_last_ended_at=base_inputs.now - timedelta(minutes=45),
            ),
            thr,
        )
        assert d.target_speed == 3

    def test_no_v3_if_surplus_too_small(self, base_inputs, thr):
        # grid -800, pump v1 (160) → bump to v3 = -800+940 = +140 W (importing).
        # Should NOT be allowed.
        d = decide(
            replace(base_inputs, grid_w=-800.0, water_temp_c=26.0),
            thr,
        )
        assert d.target_speed != 3


# ---------------------------------------------------------------------------
# v3 session in progress
# ---------------------------------------------------------------------------


class TestV3InProgress:
    def test_hold_v3_under_cap(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,        # surplus still present (v3 already on)
                pump_speed=3,
                v3_started_at=base_inputs.now - timedelta(minutes=5),
            ),
            thr,
        )
        assert d.target_speed == 3
        assert d.enter_v3 is False
        assert d.leave_v3 is False

    def test_drop_at_15min_cap(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                pump_speed=3,
                v3_started_at=base_inputs.now - timedelta(minutes=15, seconds=1),
            ),
            thr,
        )
        assert d.target_speed != 3
        assert d.leave_v3 is True
        assert "cap" in d.reason

    def test_mid_session_abort_when_surplus_drops(self, base_inputs, thr):
        # While at v3 (1100 W), grid 100 W → if dropped to v2 we'd do 100+(500-1100)=-500 (export OK)
        # But at v3 itself, can_bump_to(3) checks delta=0 → expected = 100, not < -200 → abort.
        d = decide(
            replace(
                base_inputs,
                grid_w=100.0,
                pump_speed=3,
                v3_started_at=base_inputs.now - timedelta(minutes=3),
            ),
            thr,
        )
        assert d.target_speed != 3
        assert d.leave_v3 is True
        assert "surplus lost" in d.reason


# ---------------------------------------------------------------------------
# v2 candidate
# ---------------------------------------------------------------------------


class TestV2Candidate:
    def test_v2_with_modest_surplus(self, base_inputs, thr):
        # At v1 (160W). Bump to v2 (500W) adds 340W. Need grid + 340 < -200 → grid < -540.
        # v2 also requires warmth — provide a warm water_temp.
        d = decide(replace(base_inputs, grid_w=-700.0, water_temp_c=26.0), thr)
        assert d.target_speed == 2

    def test_no_v2_if_surplus_but_cool(self, base_inputs, thr):
        """When the day is cool, even with surplus we stay at v1 (no filtration urgency)."""
        d = decide(
            replace(base_inputs, grid_w=-700.0, water_temp_c=20.0, air_temp_c=20.0),
            thr,
        )
        assert d.target_speed == 1

    def test_v2_drops_to_v1_when_surplus_disappears(self, base_inputs, thr):
        # At v2 (500W). Bump to v2 itself = no delta. Need grid < -200 to stay.
        # grid 0 → not enough surplus to *justify* v2 but no flap mechanism here:
        # the decision is recomputed each tick, so v2 stays only if can_bump_to(2)
        # is True from the v1 baseline. From v2, asking can_bump_to(2) is delta=0,
        # condition: grid < -200. If grid >= -200, drop to v1.
        d = decide(replace(base_inputs, grid_w=0.0, pump_speed=2), thr)
        assert d.target_speed == 1


# ---------------------------------------------------------------------------
# Force skim button
# ---------------------------------------------------------------------------


class TestForceSkim:
    def test_force_skim_starts_v3(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,        # surplus available
                force_skim_requested=True,
                v3_last_ended_at=None,
            ),
            thr,
        )
        assert d.target_speed == 3
        assert d.enter_v3 is True
        assert "force-skim" in d.reason

    def test_force_skim_blocked_by_cooldown(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                force_skim_requested=True,
                water_temp_c=26.0,
                v3_last_ended_at=base_inputs.now - timedelta(minutes=10),
            ),
            thr,
        )
        # Falls through to normal logic; v3 candidate also blocked → v2.
        assert d.target_speed == 2
        assert "force-skim" not in d.reason

    def test_force_skim_blocked_by_no_surplus(self, base_inputs, thr):
        d = decide(
            replace(base_inputs, grid_w=200.0, force_skim_requested=True),
            thr,
        )
        # Falls through; default → v1.
        assert d.target_speed == 1


# ---------------------------------------------------------------------------
# Edge cases on missing temps
# ---------------------------------------------------------------------------


class TestWinterMode:
    def test_tempo_red_forces_off(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                tempo_color=TEMPO_RED,
                grid_w=-3000.0,   # huge surplus, irrelevant
            ),
            thr,
        )
        assert d.target_speed == 0
        assert "Tempo Red" in d.reason

    def test_night_forces_off(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                daylight=False,
                grid_w=-3000.0,
            ),
            thr,
        )
        assert d.target_speed == 0
        assert "night" in d.reason

    def test_v1_when_solar_covers(self, base_inputs, thr):
        # From off (0W). Bump to v1 adds 160W. grid + 160 < -200 → grid < -360.
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                pump_speed=0,
                grid_w=-500.0,    # comfortably enough surplus
            ),
            thr,
        )
        assert d.target_speed == 1
        assert "solar" in d.reason

    def test_off_when_no_solar(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                pump_speed=0,
                grid_w=200.0,     # importing
            ),
            thr,
        )
        assert d.target_speed == 0
        assert "insufficient" in d.reason

    def test_winter_caps_at_v1_even_with_huge_surplus(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                pump_speed=1,
                grid_w=-3000.0,   # plenty for v3, but winter caps at v1
                water_temp_c=26.0,
                air_temp_c=30.0,
            ),
            thr,
        )
        assert d.target_speed == 1

    def test_winter_drops_v3_to_off_via_tempo(self, base_inputs, thr):
        """If we land in winter mode while at v3, we should leave the session cleanly."""
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                pump_speed=3,
                tempo_color=TEMPO_RED,
                v3_started_at=base_inputs.now,
            ),
            thr,
        )
        assert d.target_speed == 0
        assert d.leave_v3 is True

    def test_winter_ignores_force_skim(self, base_inputs, thr):
        """Force-skim is a summer-only concept; winter ignores it."""
        d = decide(
            replace(
                base_inputs,
                mode=MODE_WINTER,
                grid_w=-3000.0,
                force_skim_requested=True,
            ),
            thr,
        )
        assert d.target_speed == 1   # at most v1 in winter


class TestMissingTemps:
    def test_missing_both_temps_blocks_v3(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=None,
                air_temp_c=None,
            ),
            thr,
        )
        # No "warm" signal possible, so neither v3 nor v2 candidate fires.
        # Falls all the way back to v1.
        assert d.target_speed == 1

    def test_one_warm_temp_is_enough(self, base_inputs, thr):
        d = decide(
            replace(
                base_inputs,
                grid_w=-1500.0,
                water_temp_c=None,
                air_temp_c=30.0,        # only the air sensor reports, and it's warm
            ),
            thr,
        )
        assert d.target_speed == 3
