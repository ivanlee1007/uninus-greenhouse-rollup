"""UNiNUS greenhouse roll-up integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .const import CARD_URL, DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a greenhouse roll-up and its bundled dashboard card."""
    from homeassistant.components.http import StaticPathConfig

    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("frontend_registered"):
        card_path = Path(__file__).parent / "www" / "uninus-greenhouse-rollup-card.js"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card_path), cache_headers=True)]
        )
        domain_data["frontend_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a greenhouse roll-up entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
