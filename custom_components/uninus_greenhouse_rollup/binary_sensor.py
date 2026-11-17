"""Native read-only estimate availability, not physical arrival."""
from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN
from .position import PositionEntity


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data.get(DOMAIN, {}).get('parameters', {}).get(entry.entry_id)
    if manager is not None:
        async_add_entities([PositionKnownBinarySensor(manager)])


class PositionKnownBinarySensor(PositionEntity, BinarySensorEntity):
    """An available estimate exists; remembered estimates remain unverified."""

    _attr_icon = 'mdi:help-circle-outline'

    def __init__(self, manager):
        super().__init__(manager, 'position_known')

    @property
    def is_on(self):
        return self.estimated_position is not None
