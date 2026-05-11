"""DataUpdateCoordinator for the Pool Pump integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_AIR_TEMP_ENTITY,
    CONF_AIR_WARM_C,
    CONF_GRID_POWER_ENTITY,
    CONF_MIN_SPEED_DWELL_SECONDS,
    CONF_PUMP_SPEED_ENTITY,
    CONF_SAFETY_MARGIN_W,
    CONF_SOLAR_SMOOTH_ALPHA,
    CONF_TEMPO_ENTITY,
    CONF_V3_COOLDOWN_MINUTES,
    CONF_V3_MAX_MINUTES,
    CONF_WATER_TEMP_ENTITY,
    CONF_WATER_WARM_C,
    DEFAULT_AIR_WARM_C,
    DEFAULT_MIN_SPEED_DWELL_SECONDS,
    DEFAULT_SAFETY_MARGIN_W,
    DEFAULT_SOLAR_SMOOTH_ALPHA,
    DEFAULT_V3_COOLDOWN_MINUTES,
    DEFAULT_V3_MAX_MINUTES,
    DEFAULT_WATER_WARM_C,
    DOMAIN,
    MANUAL_MODES,
    MODE_AUTO,
    UPDATE_INTERVAL_SECONDS,
)
from .decision import Decision, Inputs, Thresholds, _safe_speed, decide

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SUN_ENTITY = "sun.sun"


def _storage_key(entry_id: str) -> str:
    """Per-config-entry key so multi-instance setups don't collide."""
    return f"{DOMAIN}.{entry_id}"


class PoolPumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Brain of the smart pump cycling logic."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.config_entry = entry
        self._store: Store = Store(
            hass, STORAGE_VERSION, _storage_key(entry.entry_id)
        )
        self._unsub_listeners: list[Any] = []

        self._mode: str = MODE_AUTO
        self._v3_started_at: datetime | None = None
        self._v3_last_ended_at: datetime | None = None
        self._force_skim_pending: bool = False

        # Last computed decision (for entity exposure)
        self._last_decision: Decision = Decision(
            target_speed=1, reason="initial", enter_v3=False, leave_v3=False
        )

        # Anti-flap state. Persisted to Store so restarts don't reset the EMA
        # convergence and don't forget the last speed change time.
        self._grid_smooth: float | None = None
        self._last_speed_change_at: datetime | None = None

    # --- Properties exposed to entity classes --------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def last_decision(self) -> Decision:
        return self._last_decision

    @property
    def v3_started_at(self) -> datetime | None:
        return self._v3_started_at

    @property
    def v3_last_ended_at(self) -> datetime | None:
        return self._v3_last_ended_at

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(
            safety_margin_w=self._cfg(CONF_SAFETY_MARGIN_W, DEFAULT_SAFETY_MARGIN_W),
            water_warm_c=self._cfg(CONF_WATER_WARM_C, DEFAULT_WATER_WARM_C),
            air_warm_c=self._cfg(CONF_AIR_WARM_C, DEFAULT_AIR_WARM_C),
            v3_max_minutes=int(self._cfg(CONF_V3_MAX_MINUTES, DEFAULT_V3_MAX_MINUTES)),
            v3_cooldown_minutes=int(
                self._cfg(CONF_V3_COOLDOWN_MINUTES, DEFAULT_V3_COOLDOWN_MINUTES)
            ),
        )

    # --- Mode and button entry points (called from entity classes) -----------

    async def async_set_mode(self, mode: str) -> None:
        self._mode = mode
        await self._save_state()
        await self.async_request_refresh()

    async def async_force_skim(self) -> None:
        self._force_skim_pending = True
        await self.async_request_refresh()

    async def async_reset_v3_cooldown(self) -> None:
        """Clear the v3 cooldown so a new v3 session can start immediately."""
        self._v3_last_ended_at = None
        await self._save_state()
        _LOGGER.info("Pool pump: v3 cooldown reset by user")
        await self.async_request_refresh()

    # --- Lifecycle -----------------------------------------------------------

    async def async_setup(self) -> None:
        await self._load_state()
        self._register_listeners()

    async def async_teardown(self) -> None:
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    def _register_listeners(self) -> None:
        watched = [
            SUN_ENTITY,
            self._entity(CONF_GRID_POWER_ENTITY),
            self._entity(CONF_WATER_TEMP_ENTITY),
            self._entity(CONF_AIR_TEMP_ENTITY),
            self._entity(CONF_TEMPO_ENTITY),
        ]
        watched = [e for e in watched if e]
        if watched:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass, watched, self._on_input_change
                )
            )

    @callback
    def _on_input_change(self, _event: Event) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    # --- Persistence ---------------------------------------------------------

    async def _load_state(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        self._mode = data.get("mode", MODE_AUTO)
        self._v3_started_at = _parse_iso(data.get("v3_started_at"))
        self._v3_last_ended_at = _parse_iso(data.get("v3_last_ended_at"))
        gs = data.get("grid_smooth_w")
        self._grid_smooth = float(gs) if gs is not None else None
        self._last_speed_change_at = _parse_iso(data.get("last_speed_change_at"))

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "mode": self._mode,
                "v3_started_at": _to_iso(self._v3_started_at),
                "v3_last_ended_at": _to_iso(self._v3_last_ended_at),
                "grid_smooth_w": self._grid_smooth,
                "last_speed_change_at": _to_iso(self._last_speed_change_at),
            }
        )

    # --- Config helpers ------------------------------------------------------

    @staticmethod
    def _opt(entry: ConfigEntry, key: str, default: Any = None) -> Any:
        return entry.options.get(key, entry.data.get(key, default))

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self._opt(self.config_entry, key, default)

    def _entity(self, key: str) -> str | None:
        val = self._cfg(key)
        return val if val else None

    # --- State reading helpers ----------------------------------------------

    def _get_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_int(self, entity_id: str | None, default: int = 0) -> int:
        v = self._get_float(entity_id)
        return int(v) if v is not None else default

    # --- Main control loop ---------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        pump_id = self._entity(CONF_PUMP_SPEED_ENTITY)
        grid_raw = self._get_float(self._entity(CONF_GRID_POWER_ENTITY)) or 0.0
        water = self._get_float(self._entity(CONF_WATER_TEMP_ENTITY))
        air = self._get_float(self._entity(CONF_AIR_TEMP_ENTITY))
        pump_speed_raw = self._get_int(pump_id, default=0)
        pump_speed = _safe_speed(pump_speed_raw)
        if pump_speed != pump_speed_raw:
            _LOGGER.warning(
                "Pool pump: pump speed entity reported %d, clamped to %d",
                pump_speed_raw, pump_speed,
            )

        tempo_entity = self._entity(CONF_TEMPO_ENTITY)
        tempo_color: str | None = None
        if tempo_entity:
            t_state = self.hass.states.get(tempo_entity)
            if t_state and t_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                tempo_color = t_state.state

        # EMA smoothing on grid power so a ~30–60 s cloud doesn't flap the
        # speed. First tick after a fresh install seeds from the live value;
        # restarts restore the smoothed value from Store so convergence
        # persists.
        alpha = float(self._cfg(CONF_SOLAR_SMOOTH_ALPHA, DEFAULT_SOLAR_SMOOTH_ALPHA))
        if self._grid_smooth is None:
            self._grid_smooth = grid_raw
        else:
            self._grid_smooth = alpha * grid_raw + (1.0 - alpha) * self._grid_smooth

        sun_state = self.hass.states.get(SUN_ENTITY)
        daylight = sun_state is not None and sun_state.state == "above_horizon"

        force_skim = self._force_skim_pending
        # Consume the one-shot flag the moment we evaluate it.
        self._force_skim_pending = False

        now = datetime.now(timezone.utc)
        inputs = Inputs(
            now=now,
            daylight=daylight,
            grid_w=self._grid_smooth,
            pump_speed=pump_speed,
            water_temp_c=water,
            air_temp_c=air,
            mode=self._mode,
            v3_started_at=self._v3_started_at,
            v3_last_ended_at=self._v3_last_ended_at,
            force_skim_requested=force_skim,
            tempo_color=tempo_color,
        )

        decision = decide(inputs, self.thresholds)
        self._last_decision = decision

        # Rate limit: who bypasses?
        #   - manual modes (off/v1/v2/v3) — user is sovereign, immediate effect
        #   - force-skim button — one-shot user-initiated, should fire now
        #   - v3 entry / exit — capping the high-flow window is more important
        #     than smoothing the transition
        # `auto` and `winter` modes go through the rate limit.
        bypass = (
            self._mode in MANUAL_MODES
            or force_skim
            or decision.enter_v3
            or decision.leave_v3
        )

        applied = False
        if pump_id and decision.target_speed != pump_speed:
            dwell = float(
                self._cfg(CONF_MIN_SPEED_DWELL_SECONDS, DEFAULT_MIN_SPEED_DWELL_SECONDS)
            )
            elapsed = (
                (now - self._last_speed_change_at).total_seconds()
                if self._last_speed_change_at
                else float("inf")
            )
            if bypass or elapsed >= dwell:
                _LOGGER.info(
                    "Pool pump: %d → %d (%s) | grid_raw=%.0fW grid_smooth=%.0fW",
                    pump_speed, decision.target_speed, decision.reason,
                    grid_raw, self._grid_smooth,
                )
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": pump_id, "value": float(decision.target_speed)},
                    blocking=True,
                )
                self._last_speed_change_at = now
                applied = True
            else:
                _LOGGER.debug(
                    "Pool pump: rate-limited (%.0fs < %.0fs), holding at v%d "
                    "(wanted v%d, %s)",
                    elapsed, dwell,
                    pump_speed, decision.target_speed, decision.reason,
                )

        # Stamp v3 lifecycle timestamps only AFTER the write succeeded (or was
        # bypassed). This avoids stamping a started_at when the rate limit
        # blocked the actual transition.
        state_changed_v3 = False
        if applied and decision.enter_v3:
            self._v3_started_at = now
            state_changed_v3 = True
            _LOGGER.info("Pool pump: v3 session started — %s", decision.reason)
        if applied and decision.leave_v3:
            self._v3_last_ended_at = now
            self._v3_started_at = None
            state_changed_v3 = True
            _LOGGER.info("Pool pump: v3 session ended — %s", decision.reason)

        # Persist anti-flap state every cycle (cheap; matches pergola pattern)
        # so restarts don't lose the EMA convergence or last-change timestamp.
        await self._save_state()
        if state_changed_v3:
            # already saved above; nothing extra to do
            pass

        return self._build_data(inputs, decision)

    def _build_data(self, inputs: Inputs, decision: Decision) -> dict[str, Any]:
        v3_age_s: int | None = None
        if self._v3_started_at is not None:
            v3_age_s = int(
                (inputs.now - self._v3_started_at).total_seconds()
            )

        cooldown_s = 0
        if self._v3_last_ended_at is not None:
            elapsed = (inputs.now - self._v3_last_ended_at).total_seconds()
            cooldown_s = max(0, int(self.thresholds.v3_cooldown_minutes * 60 - elapsed))

        return {
            "mode": self._mode,
            "target_speed": decision.target_speed,
            "reason": decision.reason,
            "v3_session_age_s": v3_age_s,
            "v3_cooldown_remaining_s": cooldown_s,
            "grid_smooth_w": (
                round(self._grid_smooth, 0) if self._grid_smooth is not None else None
            ),
            "grid_raw_w": round(inputs.grid_w, 0),  # smoothed grid actually used
        }


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _to_iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None
