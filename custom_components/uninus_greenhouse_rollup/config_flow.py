"""Config flow for UNiNUS greenhouse roll-up."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CLOSE_ENTITY,
    CONF_CLOSE_TRAVEL_TIME,
    CONF_OPEN_ENTITY,
    CONF_OPEN_TRAVEL_TIME,
    CONF_REVERSE_DEAD_TIME,
    DEFAULT_CLOSE_TRAVEL_TIME,
    DEFAULT_OPEN_TRAVEL_TIME,
    DEFAULT_REVERSE_DEAD_TIME,
    DOMAIN,
)


def _entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch"]))


def _time_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=3600,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _dead_time_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=10,
            step=0.1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _pair_unique_id(open_entity: str, close_entity: str) -> str:
    """Return a direction-independent identity for one actuator pair."""
    return "::".join(sorted((open_entity, close_entity)))


def _switches_in_use(
    entries: list[config_entries.ConfigEntry],
    open_entity: str,
    close_entity: str,
) -> bool:
    """Prevent independently locked entries from sharing actuator relays."""
    requested = {open_entity, close_entity}
    for entry in entries:
        configured = {entry.data.get(CONF_OPEN_ENTITY), entry.data.get(CONF_CLOSE_ENTITY)}
        if requested & configured:
            return True
    return False


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=values.get(CONF_NAME, "溫室捲揚")): str,
            vol.Required(CONF_OPEN_ENTITY, default=values.get(CONF_OPEN_ENTITY)): _entity_selector(),
            vol.Required(CONF_CLOSE_ENTITY, default=values.get(CONF_CLOSE_ENTITY)): _entity_selector(),
            vol.Required(
                CONF_OPEN_TRAVEL_TIME,
                default=values.get(CONF_OPEN_TRAVEL_TIME, DEFAULT_OPEN_TRAVEL_TIME),
            ): _time_selector(),
            vol.Required(
                CONF_CLOSE_TRAVEL_TIME,
                default=values.get(CONF_CLOSE_TRAVEL_TIME, DEFAULT_CLOSE_TRAVEL_TIME),
            ): _time_selector(),
            vol.Required(
                CONF_REVERSE_DEAD_TIME,
                default=values.get(CONF_REVERSE_DEAD_TIME, DEFAULT_REVERSE_DEAD_TIME),
            ): _dead_time_selector(),
        }
    )


class UninusGreenhouseRollupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one remembered cover from a pair of switch entities."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_OPEN_ENTITY] == user_input[CONF_CLOSE_ENTITY]:
                errors["base"] = "same_switch"
            elif _switches_in_use(
                self._async_current_entries(),
                user_input[CONF_OPEN_ENTITY],
                user_input[CONF_CLOSE_ENTITY],
            ):
                errors["base"] = "switch_in_use"
            else:
                unique = _pair_unique_id(
                    user_input[CONF_OPEN_ENTITY], user_input[CONF_CLOSE_ENTITY]
                )
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return RollupOptionsFlow()


class RollupOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit timing options and reload the entry exactly once."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OPEN_TRAVEL_TIME,
                    default=current[CONF_OPEN_TRAVEL_TIME],
                ): _time_selector(),
                vol.Required(
                    CONF_CLOSE_TRAVEL_TIME,
                    default=current[CONF_CLOSE_TRAVEL_TIME],
                ): _time_selector(),
                vol.Required(
                    CONF_REVERSE_DEAD_TIME,
                    default=current.get(CONF_REVERSE_DEAD_TIME, DEFAULT_REVERSE_DEAD_TIME),
                ): _dead_time_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
