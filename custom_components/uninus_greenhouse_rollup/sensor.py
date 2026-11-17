"""Native read-only estimated opening position."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE

from .const import DOMAIN
from .position import PositionEntity


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data.get(DOMAIN, {}).get('parameters', {}).get(entry.entry_id)
    if manager is not None:
        async_add_entities([EstimatedPositionSensor(manager)])


class EstimatedPositionSensor(PositionEntity, SensorEntity):
    """Opening percentage, never physical arrival confirmation."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = 'mdi:blinds-horizontal'

    def __init__(self, manager):
        super().__init__(manager, 'estimated_position')

    @property
    def native_value(self):
        return self.estimated_position
