"""UNiNUS greenhouse roll-up integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import (
    CARD_URL,
    CONF_CLOSE_ENTITY,
    CONF_OPEN_ENTITY,
    DOMAIN,
    PLATFORMS,
)

_OWNERS_KEY = "relay_owners"


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
    data = {**entry.data, **entry.options}
    if not _claim_relay_ownership(
        owners,
        entry.entry_id,
        data[CONF_OPEN_ENTITY],
        data[CONF_CLOSE_ENTITY],
    ):
        raise ConfigEntryError(
            "A configured relay is already owned by another UNiNUS roll-up entry"
        )

    try:
        if not domain_data.get("frontend_registered"):
            card_path = Path(__file__).parent / "www" / "uninus-greenhouse-rollup-card.js"
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(card_path), cache_headers=True)]
            )
            domain_data["frontend_registered"] = True

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        _release_relay_ownership(owners, entry.entry_id)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a greenhouse roll-up entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        owners = domain_data.get(_OWNERS_KEY, {})
        _release_relay_ownership(owners, entry.entry_id)
    return unloaded
