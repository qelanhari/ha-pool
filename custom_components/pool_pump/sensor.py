"""Sensor platform: pool pump diagnostics (target speed, reason, v3 timers)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolPumpCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PoolPumpCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PoolPumpTargetSpeedSensor(coordinator, entry),
            PoolPumpReasonSensor(coordinator, entry),
            PoolPumpV3SessionAgeSensor(coordinator, entry),
            PoolPumpV3CooldownSensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[PoolPumpCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PoolPumpCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hayward",
            model="VSTD via Antea VS",
        )


class PoolPumpTargetSpeedSensor(_Base):
    _attr_translation_key = "target_speed"
    _attr_icon = "mdi:speedometer"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_target_speed"

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data.get("target_speed") if data else None


class PoolPumpReasonSensor(_Base):
    _attr_translation_key = "decision_reason"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_reason"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return data.get("reason") if data else None


class PoolPumpV3SessionAgeSensor(_Base):
    _attr_translation_key = "v3_session_age"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_v3_session_age"

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data.get("v3_session_age_s") if data else None


class PoolPumpV3CooldownSensor(_Base):
    _attr_translation_key = "v3_cooldown_remaining"
    _attr_icon = "mdi:timer-pause-outline"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_v3_cooldown_remaining"

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return data.get("v3_cooldown_remaining_s") if data else None
