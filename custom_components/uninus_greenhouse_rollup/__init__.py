"""UNiNUS greenhouse roll-up integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    ACTUATOR_MODE_DUAL_SWITCH,
    ACTUATOR_MODE_NATIVE_COVER,
    CONF_ACTUATOR_MODE,
    CONF_ACTUATOR_TYPE,
    CONF_CLOSE_ENTITY,
    CONF_OPEN_ENTITY,
    DEFAULT_ACTUATOR_TYPE,
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_AUTO_STOP_AT_TRAVEL_END,
)

_OWNERS_KEY = "relay_owners"


def _config_entry_only_schema(config: dict) -> dict:
    """Validate setup without making pure estimator imports depend on HA."""
    from homeassistant.helpers import config_validation as cv

    return cv.config_entry_only_config_schema(DOMAIN)(config)


CONFIG_SCHEMA = _config_entry_only_schema


def _entry_mode(data: dict) -> str:
    """Return the entry mode, preserving version-one dual-switch entries."""
    return data.get(CONF_ACTUATOR_MODE, ACTUATOR_MODE_DUAL_SWITCH)


def _claim_relay_ownership(
    owners: dict[str, str], entry_id: str, open_entity: str, close_entity: str
) -> bool:
    """Atomically claim both relays in the event loop, or change nothing."""
    entities = (open_entity, close_entity)
    if any(
        owner not in (None, entry_id)
        for owner in (owners.get(item) for item in entities)
    ):
        return False
    for entity_id in entities:
        owners[entity_id] = entry_id
    return True


def _release_relay_ownership(owners: dict[str, str], entry_id: str) -> None:
    """Release only relays currently owned by this entry."""
    for entity_id, owner in tuple(owners.items()):
        if owner == entry_id:
            owners.pop(entity_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register card-editable settings independently of entry reloads."""
    import voluptuous as vol

    from homeassistant.auth.permissions.const import POLICY_CONTROL
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser

    from .const import CONF_AUTO_STOP_AT_TRAVEL_END
    from .cover import UninusGreenhouseRollupCover

    async def apply_parameters(call):
        from .parameters import ParameterManager

        context = call.context
        # Deny humans before protected target resolution; recheck under both locks.
        if context.user_id is not None:
            user = await hass.auth.async_get_user(context.user_id)
            if user is None:
                raise UnknownUser(context=context)
            if not user.is_active or not user.is_admin or not user.permissions.check_entity(
                call.data["entity_id"], POLICY_CONTROL
            ):
                raise Unauthorized(context=context)
        manager = next((item for item in hass.data.get(DOMAIN, {}).get("parameters", {}).values()
                        if isinstance(item, ParameterManager)
                        and item.cover.entity_id == call.data["entity_id"]), None)
        if manager is None:
            raise ServiceValidationError("Not a loaded owned dual-switch Cover")
        return await manager.async_update(call.data["parameters"], context,
                                          call.data.get("expected_revision"))

    hass.services.async_register(
        DOMAIN, "apply_parameters", apply_parameters,
        schema=vol.Schema({
            vol.Required("entity_id"): vol.All(str, vol.Match(r"\Acover\.[a-z0-9_]+\Z")),
            vol.Required("parameters"): dict,
            vol.Optional("expected_revision"): vol.All(int, vol.Range(min=0)),
        }), supports_response=SupportsResponse.OPTIONAL,
    )

    async def set_auto_stop(call):
        targets = call.data["entity_id"]
        if isinstance(targets, str):
            targets = [targets]
        targets = list(dict.fromkeys(targets))
        if call.context.user_id is not None:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None:
                raise UnknownUser(context=call.context)
            if not user.is_active:
                raise Unauthorized(context=call.context)
            for entity_id in targets:
                if not user.permissions.check_entity(entity_id, POLICY_CONTROL):
                    raise Unauthorized(
                        context=call.context, entity_id=entity_id, permission=POLICY_CONTROL
                    )

        # Resolve current ownership after the permission lookup's only suspension.
        domain_data = hass.data.get(DOMAIN, {})
        covers = []
        for entity_id in targets:
            cover = next(
                (
                    item for item in domain_data.get("covers", {}).values()
                    if isinstance(item, UninusGreenhouseRollupCover)
                    and item.entity_id == entity_id
                ),
                None,
            )
            if cover is None:
                raise ServiceValidationError(f"Not a loaded UNiNUS Cover: {entity_id}")
            entry = cover._entry
            data = {**entry.data, **entry.options}
            owners = domain_data.get(_OWNERS_KEY, {})
            if (
                entry.domain != DOMAIN
                or _entry_mode(data) != ACTUATOR_MODE_DUAL_SWITCH
                or data.get(CONF_OPEN_ENTITY) != cover._open_entity
                or data.get(CONF_CLOSE_ENTITY) != cover._close_entity
                or any(
                    owners.get(relay) != entry.entry_id
                    for relay in (cover._open_entity, cover._close_entity)
                )
            ):
                raise ServiceValidationError(f"Cover ownership changed: {entity_id}")
            cover.validate_auto_stop_change()
            covers.append(cover)

        updated = []
        acquired = []
        enabled = call.data["enabled"]
        try:
            # All locks were verified free, with pending commands rejected above.
            # asyncio.Lock.acquire on a free lock without waiters does not suspend.
            # Keep validation, acquisition, merged writes and publication in this
            # event-loop turn: never await storage/reload/relay calls in this block.
            for cover in covers:
                await cover._command_lock.acquire()
                acquired.append(cover._command_lock)
            for entity_id, cover in zip(targets, covers, strict=True):
                update_error = None
                try:
                    hass.config_entries.async_update_entry(
                        cover._entry,
                        options={**cover._entry.options, CONF_AUTO_STOP_AT_TRAVEL_END: enabled},
                    )
                except Exception as error:
                    update_error = error
                if cover._entry.options.get(CONF_AUTO_STOP_AT_TRAVEL_END) is not enabled:
                    raise ServiceValidationError(
                        f"Failed to save auto-stop for {entity_id}; updated: {updated}"
                    ) from update_error
                # An update can mutate options before save/notification fails.
                # Reconcile its actual read-back, but still report that failure.
                cover._auto_stop_at_travel_end = enabled
                updated.append(entity_id)
                try:
                    cover.async_write_ha_state()
                except Exception as error:
                    raise ServiceValidationError(
                        f"Failed to publish auto-stop for {entity_id}; updated: {updated}"
                    ) from error
                if update_error is not None:
                    raise ServiceValidationError(
                        f"Failed to save auto-stop for {entity_id}; updated: {updated}"
                    ) from update_error
        finally:
            for lock in reversed(acquired):
                lock.release()
        return {"updated": updated, "enabled": enabled}

    entity_id_schema = vol.All(str, vol.Match(r"\Acover\.[a-z0-9_]+\Z"))
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AUTO_STOP_AT_TRAVEL_END,
        set_auto_stop,
        schema=vol.Schema({
            vol.Required("entity_id"): vol.Any(
                entity_id_schema,
                vol.All([entity_id_schema], vol.Length(min=1)),
            ),
            vol.Required("enabled"): bool,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a legacy greenhouse roll-up adapter entry."""
    from homeassistant.exceptions import ConfigEntryError

    domain_data = hass.data.setdefault(DOMAIN, {})
    owners = domain_data.setdefault(_OWNERS_KEY, {})
    data = {**entry.data, **entry.options}
    mode = _entry_mode(data)
    if mode not in (ACTUATOR_MODE_DUAL_SWITCH, ACTUATOR_MODE_NATIVE_COVER):
        raise ConfigEntryError(f"Unsupported actuator mode: {mode}")
    owns_relays = mode == ACTUATOR_MODE_DUAL_SWITCH
    if owns_relays and not _claim_relay_ownership(
        owners,
        entry.entry_id,
        data[CONF_OPEN_ENTITY],
        data[CONF_CLOSE_ENTITY],
    ):
        raise ConfigEntryError(
            "A configured relay is already owned by another UNiNUS roll-up entry"
        )

    try:
        if owns_relays:
            from .cover import UninusGreenhouseRollupCover
            from .parameters import ParameterManager

            cover = UninusGreenhouseRollupCover(entry, data)
            manager = ParameterManager(hass, entry, cover)
            await manager.async_load(data)
            domain_data.setdefault("parameters", {})[entry.entry_id] = manager
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        if owns_relays:
            domain_data.get("parameters", {}).pop(entry.entry_id, None)
            _release_relay_ownership(owners, entry.entry_id)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a greenhouse roll-up entry."""
    data = {**entry.data, **entry.options}
    if _entry_mode(data) == ACTUATOR_MODE_NATIVE_COVER:
        return True
    manager = hass.data.get(DOMAIN, {}).get("parameters", {}).get(entry.entry_id)
    if manager is not None:
        manager.closing = True
        async with manager.lock:
            pass
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        owners = domain_data.get(_OWNERS_KEY, {})
        if domain_data.get("parameters", {}).get(entry.entry_id) is manager:
            domain_data["parameters"].pop(entry.entry_id, None)
        _release_relay_ownership(owners, entry.entry_id)
    elif manager is not None:
        manager.closing = False
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove exactly this entry's integration-owned hardware policy, never foreign state."""
    from pathlib import Path
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.storage import Store

    store = Store(hass, 1, f"{DOMAIN}.parameters.{entry.entry_id}")
    await store.async_remove()
    if await hass.async_add_executor_job(Path(store.path).exists):
        raise HomeAssistantError("Hardware policy deletion did not persist")


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Add explicit mode/type defaults to older dual-switch entries."""
    if entry.version in (1, 2):
        data = dict(entry.data)
        if entry.version == 1:
            data.setdefault(CONF_ACTUATOR_MODE, ACTUATOR_MODE_DUAL_SWITCH)
        data.setdefault(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=3,
        )
        return True
    return entry.version == 3
