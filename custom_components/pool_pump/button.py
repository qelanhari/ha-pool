"""Button platform: force a v3 skim session right now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
            PoolPumpForceSkimButton(coordinator, entry),
            PoolPumpResetCooldownButton(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[PoolPumpCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PoolPumpCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hayward",
            model="VSTD via Antea VS",
        )


class PoolPumpForceSkimButton(_Base):
    _attr_translation_key = "force_skim"
    _attr_icon = "mdi:filter-variant"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_force_skim"

    async def async_press(self) -> None:
        await self.coordinator.async_force_skim()


class PoolPumpResetCooldownButton(_Base):
    """Clear the v3 cooldown so a fresh v3 session can fire immediately."""

    _attr_translation_key = "reset_v3_cooldown"
    _attr_icon = "mdi:timer-refresh-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_reset_v3_cooldown"

    async def async_press(self) -> None:
        await self.coordinator.async_reset_v3_cooldown()
