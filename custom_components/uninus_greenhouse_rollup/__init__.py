"""UNiNUS greenhouse roll-up integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    ACTUATOR_MODE_DUAL_SWITCH,
    ACTUATOR_MODE_NATIVE_COVER,
    CARD_URL,
    CONF_ACTUATOR_MODE,
    CONF_CLOSE_ENTITY,
    CONF_OPEN_ENTITY,
    DOMAIN,
    PLATFORMS,
)

_OWNERS_KEY = "relay_owners"
_FRONTEND_LOCK_KEY = "frontend_lock"
_FRONTEND_REGISTERED_KEY = "frontend_registered"


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a greenhouse roll-up and its bundled dashboard card."""
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.exceptions import ConfigEntryError

    domain_data = hass.data.setdefault(DOMAIN, {})
    owners = domain_data.setdefault(_OWNERS_KEY, {})
    frontend_lock = domain_data.setdefault(_FRONTEND_LOCK_KEY, asyncio.Lock())
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
        async with frontend_lock:
            if not domain_data.get(_FRONTEND_REGISTERED_KEY):
                card_path = (
                    Path(__file__).parent / "www" / "uninus-greenhouse-rollup-card.js"
                )
                await hass.http.async_register_static_paths(
                    [StaticPathConfig(CARD_URL, str(card_path), cache_headers=True)]
                )
                domain_data[_FRONTEND_REGISTERED_KEY] = True

        if owns_relays:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        if owns_relays:
            _release_relay_ownership(owners, entry.entry_id)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a greenhouse roll-up entry."""
    data = {**entry.data, **entry.options}
    if _entry_mode(data) == ACTUATOR_MODE_NATIVE_COVER:
        return True
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        owners = domain_data.get(_OWNERS_KEY, {})
        _release_relay_ownership(owners, entry.entry_id)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Add an explicit actuator mode to version-one dual-switch entries."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ACTUATOR_MODE: ACTUATOR_MODE_DUAL_SWITCH},
            version=2,
        )
        return True
    return entry.version == 2
