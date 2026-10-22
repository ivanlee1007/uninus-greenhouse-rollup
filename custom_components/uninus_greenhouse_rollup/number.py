"""Native admin-managed hardware timing Numbers for owned Covers."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .parameters import RANGES


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data.get(DOMAIN, {}).get('parameters', {}).get(entry.entry_id)
    if manager is not None:
        async_add_entities([HardwareNumber(manager, key) for key in RANGES])


class HardwareNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, manager, key):
        self.manager, self.key = manager, key
        self._identity_generation = 0
        self._identity_live = False
        self._attr_unique_id = f'{manager.entry.entry_id}:hardware:{key}'
        self._attr_translation_key = key
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = RANGES[key]
        self._attr_device_info = manager.cover.device_info

    @property
    def native_value(self):
        return self.manager.parameters[self.key]

    @property
    def available(self):
        return not self.manager.closing and not self.manager.fault and not self.manager.cover._removing

    @property
    def extra_state_attributes(self):
        return {'parameter_key': self.key, 'parameter_group': 'hardware',
                'policy_revision': self.manager.revision,
                'policy_error': self.manager.fault}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._identity_generation += 1
        self._identity_live = True
        self.manager.numbers.add(self)

    async def async_will_remove_from_hass(self):
        self._identity_live = False
        self._identity_generation += 1
        self.manager.numbers.discard(self)
        await super().async_will_remove_from_hass()

    async def async_set_native_value(self, value):
        # Freeze this native capability before any authorization/lock/I/O await.
        context, entity_id = self._context, self.entity_id
        generation, row = self._identity_generation, self.registry_entry
        platform, manager, uid = self.platform, self.manager, self.unique_id
        def identity_guard():
            current = er.async_get(self.hass).async_get(entity_id)
            if (not self._identity_live or self._identity_generation != generation
                    or self.entity_id != entity_id or self.manager is not manager
                    or self not in manager.numbers or self.platform is not platform
                    or platform.entities.get(entity_id) is not self
                    or platform.config_entry is not manager.entry
                    or current is None or current is not row or self.registry_entry is not current
                    or current.disabled or current.platform != DOMAIN
                    or current.unique_id != uid or self.unique_id != uid
                    or current.config_entry_id != manager.entry.entry_id):
                raise ServiceValidationError('Number identity changed or was removed; retry with the current entity')
        await manager.async_update({self.key: value}, context, entity_id=entity_id,
                                   number_identity_guard=identity_guard)
