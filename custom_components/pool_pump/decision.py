"""Pure decision logic for the Pool Pump smart-cycling integration.

This module is intentionally free of any `homeassistant` import so the test
suite can exercise it standalone with `pytest`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Speed → expected mains draw, in Watts. Calibrated by the user for a
# Hayward VSTD on an Antea VS box.
PUMP_W: dict[int, int] = {0: 0, 1: 160, 2: 500, 3: 1100}

MODE_AUTO = "auto"
MODE_WINTER = "winter"
MODE_OFF = "off"
MODE_V1 = "v1"
MODE_V2 = "v2"
MODE_V3 = "v3"
MODES: tuple[str, ...] = (
    MODE_AUTO,
    MODE_WINTER,
    MODE_OFF,
    MODE_V1,
    MODE_V2,
    MODE_V3,
)
MANUAL_TO_SPEED: dict[str, int] = {MODE_OFF: 0, MODE_V1: 1, MODE_V2: 2, MODE_V3: 3}

# Tempo (RTE) color values. The integration matches `Rouge` exactly to force
# the pump off for the whole Red day; other values are pass-through.
TEMPO_RED = "Rouge"


@dataclass(frozen=True)
class Inputs:
    """Snapshot of everything `decide()` needs.

    The coordinator builds this from `hass.states` on every tick.
    """

    now: datetime
    daylight: bool
    grid_w: float                       # negative = exporting solar
    pump_speed: int                     # 0..3 — what the pump is set to right now
    water_temp_c: float | None
    air_temp_c: float | None
    mode: str                           # "auto" | "winter" | "off" | "v1" | "v2" | "v3"
    v3_started_at: datetime | None      # when current/last v3 session started
    v3_last_ended_at: datetime | None   # when previous v3 session ended
    force_skim_requested: bool = False  # one-shot flag from the button entity
    tempo_color: str | None = None      # "Rouge" / "Blanc" / "Bleu" / None if unread


@dataclass(frozen=True)
class Thresholds:
    """All tunable knobs. Defaults match the user's CS100 / Hayward VSTD setup."""

    safety_margin_w: float = 200.0
    water_warm_c: float = 24.0
    air_warm_c: float = 28.0
    v3_max_minutes: int = 15
    v3_cooldown_minutes: int = 30


@dataclass(frozen=True)
class Decision:
    target_speed: int
    reason: str
    enter_v3: bool   # signal: stamp v3_started_at
    leave_v3: bool   # signal: stamp v3_last_ended_at


def _safe_speed(s: int) -> int:
    """Clamp a possibly-bogus speed reading to the valid 0..3 range."""
    if s < 0:
        return 0
    if s > 3:
        return 3
    return s


def _can_bump_to(target_speed: int, i: Inputs, thr: Thresholds) -> bool:
    """True if solar surplus would cover the bump from `i.pump_speed` to `target_speed`.

    Uses the formula:
        expected_grid_after_bump = grid_now + (target_W - current_W)
    Allows the bump only if `expected_grid_after_bump < -safety_margin`
    (i.e. still exporting after the new load is picked up).
    """
    current = _safe_speed(i.pump_speed)
    target = _safe_speed(target_speed)
    delta_w = PUMP_W[target] - PUMP_W[current]
    expected_grid = i.grid_w + delta_w
    return expected_grid < -thr.safety_margin_w


def _warm_enough(i: Inputs, thr: Thresholds) -> bool:
    water_warm = i.water_temp_c is not None and i.water_temp_c > thr.water_warm_c
    air_warm = i.air_temp_c is not None and i.air_temp_c > thr.air_warm_c
    return water_warm or air_warm


def _v3_session_age_s(i: Inputs) -> float | None:
    """Seconds since current v3 session started, or None if no active session."""
    if i.pump_speed != 3 or i.v3_started_at is None:
        return None
    return (i.now - i.v3_started_at).total_seconds()


def _v3_cooldown_remaining_s(i: Inputs, thr: Thresholds) -> float:
    """Seconds remaining before another v3 session is allowed. 0 if ready."""
    if i.v3_last_ended_at is None:
        return 0.0
    elapsed = (i.now - i.v3_last_ended_at).total_seconds()
    cooldown = thr.v3_cooldown_minutes * 60
    return max(0.0, cooldown - elapsed)


def decide(i: Inputs, thr: Thresholds) -> Decision:
    """Map (Inputs, Thresholds) to a Decision. Pure, deterministic."""
    was_v3 = i.pump_speed == 3

    # 1a. Winter mode: solar-only operation, capped at v1, force-off on Tempo Red.
    if i.mode == MODE_WINTER:
        if i.tempo_color == TEMPO_RED:
            return Decision(
                target_speed=0,
                reason="winter: Tempo Red day → off",
                enter_v3=False,
                leave_v3=was_v3,
            )
        if not i.daylight:
            return Decision(
                target_speed=0,
                reason="winter: night → off",
                enter_v3=False,
                leave_v3=was_v3,
            )
        # Solar covers the bump from current speed up to v1?
        if _can_bump_to(1, i, thr):
            return Decision(
                target_speed=1,
                reason="winter: solar surplus covers v1 → on",
                enter_v3=False,
                leave_v3=was_v3,
            )
        return Decision(
            target_speed=0,
            reason="winter: insufficient solar → off",
            enter_v3=False,
            leave_v3=was_v3,
        )

    # 1b. Manual mode is sovereign (off / v1 / v2 / v3).
    if i.mode != MODE_AUTO:
        target = MANUAL_TO_SPEED.get(i.mode, 1)
        leaving_v3 = was_v3 and target != 3
        entering_v3 = (not was_v3) and target == 3
        return Decision(
            target_speed=target,
            reason=f"manual={i.mode}",
            enter_v3=entering_v3,
            leave_v3=leaving_v3,
        )

    # 2. Force-skim button — start a v3 session now (still respects cooldown).
    if i.force_skim_requested:
        cooldown = _v3_cooldown_remaining_s(i, thr)
        if cooldown <= 0 and _can_bump_to(3, i, thr):
            return Decision(
                target_speed=3,
                reason="force-skim button → v3",
                enter_v3=not was_v3,
                leave_v3=False,
            )
        # If we cannot honour the request, fall through to normal logic.

    # 3. No daylight → v1.
    if not i.daylight:
        return Decision(
            target_speed=1,
            reason="night → v1",
            enter_v3=False,
            leave_v3=was_v3,
        )

    # 4. Currently in a v3 session.
    age = _v3_session_age_s(i)
    if age is not None:
        max_s = thr.v3_max_minutes * 60
        if age >= max_s:
            # 15-min cap reached — drop to highest sustainable speed.
            best = _best_sustainable_speed(i, thr)
            return Decision(
                target_speed=best,
                reason=f"v3 cap reached ({thr.v3_max_minutes}min) → v{best}",
                enter_v3=False,
                leave_v3=True,
            )
        if not _can_bump_to(3, i, thr):
            # Mid-session abort: surplus dropped (e.g. cloud).
            best = _best_sustainable_speed(i, thr)
            return Decision(
                target_speed=best,
                reason=f"v3 surplus lost mid-session → v{best}",
                enter_v3=False,
                leave_v3=True,
            )
        return Decision(
            target_speed=3,
            reason=f"v3 holding ({age/60:.1f}/{thr.v3_max_minutes}min)",
            enter_v3=False,
            leave_v3=False,
        )

    # 5. v3 candidate — daylight + cooldown elapsed + warm + surplus covers.
    cooldown = _v3_cooldown_remaining_s(i, thr)
    if cooldown <= 0 and _warm_enough(i, thr) and _can_bump_to(3, i, thr):
        return Decision(
            target_speed=3,
            reason="solar surplus covers v3 + warm → v3 skim session",
            enter_v3=True,
            leave_v3=False,
        )

    # 6. v2 candidate — surplus covers v2 bump AND it's warm enough to justify it.
    #    v2 is sustained-flow, so we only run it when extra filtration is useful.
    if _can_bump_to(2, i, thr) and _warm_enough(i, thr):
        return Decision(
            target_speed=2,
            reason="solar surplus covers v2 + warm → v2",
            enter_v3=False,
            leave_v3=was_v3,
        )

    # 7. Default.
    return Decision(
        target_speed=1,
        reason="default → v1 baseline",
        enter_v3=False,
        leave_v3=was_v3,
    )


def _best_sustainable_speed(i: Inputs, thr: Thresholds) -> int:
    """When dropping out of v3, pick the highest still-affordable speed.

    v2 also requires warmth — same gate as the candidate path — so we don't
    leave the pump at v2 with no filtration justification.
    """
    if _can_bump_to(2, i, thr) and _warm_enough(i, thr):
        return 2
    return 1
