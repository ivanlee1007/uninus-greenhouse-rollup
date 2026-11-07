"""Config flow for UNiNUS greenhouse roll-up."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_FEEDBACK_MODE,
    FEEDBACK_STANDARD,
    FEEDBACK_LEGACY_EMOS,
    CONF_ACKNOWLEDGE_LEGACY_RISK,
    ACTUATOR_MODE_DUAL_SWITCH,
    ACTUATOR_MODE_NATIVE_COVER,
    ACTUATOR_TYPES,
    CONF_ACTUATOR_MODE,
    CONF_ACTUATOR_TYPE,
    CONF_AUTO_STOP_AT_TRAVEL_END,
    CONF_CLOSE_ENTITY,
    CONF_CLOSE_TRAVEL_TIME,
    CONF_OPEN_ENTITY,
    CONF_OPEN_TRAVEL_TIME,
    CONF_REVERSE_DEAD_TIME,
    CONF_OFF_CONFIRMATION_TIMEOUT,
    DEFAULT_OFF_CONFIRMATION_TIMEOUT,
    DEFAULT_ACTUATOR_TYPE,
    DEFAULT_AUTO_STOP_AT_TRAVEL_END,
    DEFAULT_CLOSE_TRAVEL_TIME,
    DEFAULT_OPEN_TRAVEL_TIME,
    DEFAULT_REVERSE_DEAD_TIME,
    DOMAIN,
)


def _mutation_context(flow):
    """Core's native HTTP flow manager does not populate user_id in flow context."""
    from homeassistant.components.http import current_request, KEY_HASS_USER
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    request = current_request.get()
    if request is not None:
        user = request.get(KEY_HASS_USER)
        if user is None:
            raise Unauthorized()
        return Context(user_id=user.id)
    return Context(user_id=flow.context.get("user_id"))


def _entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch"]))


def _actuator_type_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(ACTUATOR_TYPES),
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="actuator_type",
        )
    )


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


def _off_timeout_selector() -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=0.1, max=30, step=0.1,
        mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s",
    ))


def _switches_in_use(
    entries: list[config_entries.ConfigEntry],
    open_entity: str,
    close_entity: str,
    *,
    exclude_entry_id: str | None = None,
) -> bool:
    """Prevent independently locked entries from sharing actuator relays."""
    requested = {open_entity, close_entity}
    for entry in entries:
        if entry.entry_id == exclude_entry_id:
            continue
        configured = {entry.data.get(CONF_OPEN_ENTITY), entry.data.get(CONF_CLOSE_ENTITY)}
        if requested & configured:
            return True
    return False


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=values.get(CONF_NAME, "溫室致動器")): str,
            vol.Required(
                CONF_ACTUATOR_TYPE,
                default=values.get(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE),
            ): _actuator_type_selector(),
            vol.Required(CONF_OPEN_ENTITY, default=values.get(CONF_OPEN_ENTITY)): _entity_selector(),
            vol.Required(CONF_CLOSE_ENTITY, default=values.get(CONF_CLOSE_ENTITY)): _entity_selector(),
            vol.Required(
                CONF_OFF_CONFIRMATION_TIMEOUT,
                default=values.get(CONF_OFF_CONFIRMATION_TIMEOUT, DEFAULT_OFF_CONFIRMATION_TIMEOUT),
            ): _off_timeout_selector(),
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
            vol.Required(
                CONF_AUTO_STOP_AT_TRAVEL_END,
                default=values.get(
                    CONF_AUTO_STOP_AT_TRAVEL_END,
                    DEFAULT_AUTO_STOP_AT_TRAVEL_END,
                ),
            ): selector.BooleanSelector(),
        }
    )


class UninusGreenhouseRollupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one remembered cover from a pair of switch entities."""

    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Create one remembered Cover from a legacy pair of switches."""
        return await self.async_step_legacy_switch_pair(user_input)

    async def async_step_legacy_switch_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create one remembered Cover from a legacy pair of switches."""
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
                data = {
                    **user_input,
                    CONF_ACTUATOR_MODE: ACTUATOR_MODE_DUAL_SWITCH,
                }
                data.setdefault(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE)
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=data,
                )
        return self.async_show_form(
            step_id="legacy_switch_pair",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the complete actuator mapping and timing configuration."""
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}
        if current.get(CONF_ACTUATOR_MODE) == ACTUATOR_MODE_NATIVE_COVER:
            return self.async_abort(reason="native_cover_no_settings")
        from homeassistant.core import Context
        from homeassistant.exceptions import ServiceValidationError
        from .parameters import RANGES

        manager = self.hass.data.get(DOMAIN, {}).get("parameters", {}).get(entry.entry_id)
        if manager is None:
            return self.async_abort(reason="hardware_policy_unavailable")
        current.update(manager.parameters)
        current.setdefault(CONF_NAME, entry.title)
        current.setdefault(CONF_AUTO_STOP_AT_TRAVEL_END, DEFAULT_AUTO_STOP_AT_TRAVEL_END)
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_OPEN_ENTITY] == user_input[CONF_CLOSE_ENTITY]:
                errors["base"] = "same_switch"
            elif _switches_in_use(
                self._async_current_entries(),
                user_input[CONF_OPEN_ENTITY],
                user_input[CONF_CLOSE_ENTITY],
                exclude_entry_id=entry.entry_id,
            ):
                errors["base"] = "switch_in_use"
            else:
                try:
                    await manager.async_update(
                        {key: user_input[key] for key in RANGES if key in user_input},
                        _mutation_context(self),
                    )
                except ServiceValidationError:
                    return self.async_show_form(step_id="reconfigure", data_schema=_schema(current),
                                                errors={"base": "hardware_policy_unavailable"})
                nonnumeric_changed = any(
                    current.get(k, DEFAULT_ACTUATOR_TYPE if k == CONF_ACTUATOR_TYPE else None) != v
                    for k, v in user_input.items() if k not in RANGES
                )
                if not nonnumeric_changed:
                    return self.async_abort(reason="reconfigure_successful")
                data = {
                    **user_input,
                    CONF_ACTUATOR_MODE: ACTUATOR_MODE_DUAL_SWITCH,
                }
                data.setdefault(
                    CONF_ACTUATOR_TYPE,
                    current.get(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE),
                )
                # Reconfigure does not offer mode selection or acknowledgement;
                # never silently reset an explicitly selected compatibility mode.
                if CONF_FEEDBACK_MODE in current:
                    data[CONF_FEEDBACK_MODE] = current[CONF_FEEDBACK_MODE]
                if data.get(CONF_FEEDBACK_MODE) == FEEDBACK_LEGACY_EMOS:
                    data[CONF_AUTO_STOP_AT_TRAVEL_END] = True
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_pair_unique_id(
                        user_input[CONF_OPEN_ENTITY],
                        user_input[CONF_CLOSE_ENTITY],
                    ),
                    title=user_input[CONF_NAME],
                    data=data,
                    options={},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or current),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return RollupOptionsFlow()


class RollupOptionsFlow(config_entries.OptionsFlowWithReload):
    """Use the hardware authority; reload only nonnumeric configuration changes."""

    automatic_reload = False

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        if current.get(CONF_ACTUATOR_MODE) == ACTUATOR_MODE_NATIVE_COVER:
            return self.async_abort(reason="native_cover_no_settings")
        from homeassistant.core import Context
        from homeassistant.exceptions import ServiceValidationError
        from .parameters import RANGES

        manager = self.hass.data.get(DOMAIN, {}).get("parameters", {}).get(self.config_entry.entry_id)
        if manager is None:
            return self.async_abort(reason="hardware_policy_unavailable")
        current.update(manager.parameters)
        current.setdefault(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE)
        current.setdefault(CONF_AUTO_STOP_AT_TRAVEL_END, DEFAULT_AUTO_STOP_AT_TRAVEL_END)
        if user_input is not None:
            try:
                requested_mode = user_input.get(CONF_FEEDBACK_MODE, current.get(CONF_FEEDBACK_MODE, FEEDBACK_STANDARD))
                enabling = requested_mode == FEEDBACK_LEGACY_EMOS and current.get(CONF_FEEDBACK_MODE, FEEDBACK_STANDARD) != requested_mode
                if enabling and not getattr(self, '_legacy_confirmed', False):
                    self._legacy_input = dict(user_input)
                    self._legacy_owner = (manager, manager.cover._parameter_epoch,
                                          dict(self.config_entry.options), manager.revision)
                    return await self.async_step_confirm_legacy()
                if enabling:
                    owner, epoch, saved_options, revision = self._legacy_owner
                    if (manager is not owner or manager.cover._parameter_epoch != epoch
                            or dict(self.config_entry.options) != saved_options
                            or manager.revision != revision):
                        raise ServiceValidationError('Legacy confirmation owner changed')
                    user_input = {**user_input, CONF_AUTO_STOP_AT_TRAVEL_END: True}
                numeric = {key: user_input[key] for key in RANGES
                           if key in user_input and user_input[key] != manager.parameters[key]}
                if numeric:
                    updated = await manager.async_update(
                        numeric, _mutation_context(self),
                        expected_revision=revision if enabling else None,
                        allow_unknown=enabling)
                    if enabling:
                        revision = updated['revision']
                elif requested_mode == current.get(CONF_FEEDBACK_MODE, FEEDBACK_STANDARD) == FEEDBACK_STANDARD:
                    # Retain standard-mode no-op policy/readback validation.
                    await manager.async_update(
                        {key: user_input[key] for key in RANGES if key in user_input},
                        _mutation_context(self))
                options = await manager.async_update_options(
                    {k: v for k, v in user_input.items() if k not in RANGES},
                    _mutation_context(self),
                    expected_revision=revision if enabling else None,
                    expected_epoch=epoch if enabling else None,
                    expected_options=saved_options if enabling else None)
            except ServiceValidationError:
                self._legacy_confirmed = False
                return self.async_show_form(step_id="init", data_schema=self._options_schema(current),
                                            errors={"base": "hardware_policy_unavailable"})
            self._legacy_confirmed = False
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="init", data_schema=self._options_schema(current))

    async def async_step_confirm_legacy(self, user_input=None):
        """Require explicit acknowledgement; revalidate admission on confirmation."""
        if user_input is not None and user_input.get(CONF_ACKNOWLEDGE_LEGACY_RISK) is True:
            self._legacy_confirmed = True
            return await self.async_step_init(self._legacy_input)
        return self.async_show_form(
            step_id="confirm_legacy", data_schema=vol.Schema({
                vol.Required(CONF_ACKNOWLEDGE_LEGACY_RISK, default=False): selector.BooleanSelector(),
            }), errors={"base": "legacy_risk_ack_required"} if user_input is not None else {})

    @staticmethod
    def _options_schema(current):
        return vol.Schema(
            {
                vol.Required(CONF_FEEDBACK_MODE, default=current.get(CONF_FEEDBACK_MODE, FEEDBACK_STANDARD)):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=[FEEDBACK_STANDARD, FEEDBACK_LEGACY_EMOS],
                        translation_key="feedback_mode", mode=selector.SelectSelectorMode.DROPDOWN)),
                vol.Required(
                    CONF_OFF_CONFIRMATION_TIMEOUT,
                    default=current.get(CONF_OFF_CONFIRMATION_TIMEOUT, DEFAULT_OFF_CONFIRMATION_TIMEOUT),
                ): _off_timeout_selector(),
                vol.Required(
                    CONF_ACTUATOR_TYPE,
                    default=current.get(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE),
                ): _actuator_type_selector(),
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
                vol.Required(
                    CONF_AUTO_STOP_AT_TRAVEL_END,
                    default=current.get(
                        CONF_AUTO_STOP_AT_TRAVEL_END,
                        DEFAULT_AUTO_STOP_AT_TRAVEL_END,
                    ),
                ): selector.BooleanSelector(),
            }
        )
