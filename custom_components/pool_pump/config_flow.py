"""Config flow for the Pool Pump integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_AIR_TEMP_ENTITY,
    CONF_AIR_WARM_C,
    CONF_GRID_POWER_ENTITY,
    CONF_PUMP_SPEED_ENTITY,
    CONF_SAFETY_MARGIN_W,
    CONF_V3_COOLDOWN_MINUTES,
    CONF_V3_MAX_MINUTES,
    CONF_WATER_TEMP_ENTITY,
    CONF_WATER_WARM_C,
    DEFAULT_AIR_WARM_C,
    DEFAULT_SAFETY_MARGIN_W,
    DEFAULT_V3_COOLDOWN_MINUTES,
    DEFAULT_V3_MAX_MINUTES,
    DEFAULT_WATER_WARM_C,
    DOMAIN,
)


def _entity_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default="Pool Pump"): str,
            vol.Required(CONF_PUMP_SPEED_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="number")
            ),
            vol.Required(CONF_GRID_POWER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(CONF_WATER_TEMP_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(CONF_AIR_TEMP_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        }
    )


def _thresholds_schema(prev: dict[str, Any] | None = None) -> vol.Schema:
    p = prev or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SAFETY_MARGIN_W,
                default=p.get(CONF_SAFETY_MARGIN_W, DEFAULT_SAFETY_MARGIN_W),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=2000, step=10, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_WATER_WARM_C,
                default=p.get(CONF_WATER_WARM_C, DEFAULT_WATER_WARM_C),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=40, step=0.5, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_AIR_WARM_C,
                default=p.get(CONF_AIR_WARM_C, DEFAULT_AIR_WARM_C),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=50, step=0.5, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


def _v3_limits_schema(prev: dict[str, Any] | None = None) -> vol.Schema:
    p = prev or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_V3_MAX_MINUTES,
                default=p.get(CONF_V3_MAX_MINUTES, DEFAULT_V3_MAX_MINUTES),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=60, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_V3_COOLDOWN_MINUTES,
                default=p.get(
                    CONF_V3_COOLDOWN_MINUTES, DEFAULT_V3_COOLDOWN_MINUTES
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=240, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


class PoolPumpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_thresholds()
        return self.async_show_form(step_id="user", data_schema=_entity_schema())

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_v3_limits()
        return self.async_show_form(
            step_id="thresholds", data_schema=_thresholds_schema()
        )

    async def async_step_v3_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title=self._data.get(CONF_NAME, "Pool Pump"),
                data={k: v for k, v in self._data.items() if k != CONF_NAME},
            )
        return self.async_show_form(
            step_id="v3_limits", data_schema=_v3_limits_schema()
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return PoolPumpOptionsFlow(config_entry)


class PoolPumpOptionsFlow(OptionsFlowWithConfigEntry):
    """Edit thresholds and v3 limits after setup. Entities are pinned at install."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_thresholds()

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._stash = dict(user_input)
            return await self.async_step_v3_limits()
        prev = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="thresholds", data_schema=_thresholds_schema(prev)
        )

    async def async_step_v3_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {**getattr(self, "_stash", {}), **user_input}
            return self.async_create_entry(title="", data=options)
        prev = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="v3_limits", data_schema=_v3_limits_schema(prev)
        )
