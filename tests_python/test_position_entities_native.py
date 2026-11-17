"""Offline native publication of read-only, unverified actuator estimates."""
import unittest

from homeassistant.helpers import entity_registry as er

from custom_components.uninus_greenhouse_rollup.const import DOMAIN
import test_parameters_native as native_fixture


class NativePositionEntitiesTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_fixture.NativeParametersTest.asyncSetUp
    asyncTearDown = native_fixture.NativeParametersTest.asyncTearDown
    batch = native_fixture.NativeParametersTest.batch

    async def publish(self, position=42):
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        cover._estimator.position = position
        cover._estimator.confidence = 'estimated' if position is not None else 'unknown'
        cover.async_write_ha_state()
        await self.hass.async_block_till_done()
        return cover

    async def test_sensor_add_and_reads_during_motion_do_not_actuate_or_cancel_timer(self):
        from custom_components.uninus_greenhouse_rollup.sensor import EstimatedPositionSensor
        from custom_components.uninus_greenhouse_rollup.binary_sensor import PositionKnownBinarySensor
        cover = await self.publish(20)
        await self.hass.services.async_call('cover', 'set_cover_position',
            {'entity_id': cover.entity_id, 'position': 80}, blocking=True)
        timer = cover._auto_stop_task
        self.assertIsNotNone(timer)
        self.writes.clear()
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        for domain, key, cls in (('sensor', 'estimated_position', EstimatedPositionSensor),
                                ('binary_sensor', 'position_known', PositionKnownBinarySensor)):
            entity_id = self.entity_id(domain, key)
            old = self.hass.data[domain].get_entity(entity_id)
            platform = old.platform
            await old.async_remove()
            entity = cls(manager)
            await platform.async_add_entities([entity])
            # Do not drain Core's unrelated, deliberately active target timer.
            # Native platform add is already awaited; yield only publication callbacks.
            import asyncio
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(entity.entity_id, entity_id)
            for _ in range(3):
                self.assertTrue(entity.available)
                self.assertEqual(entity.estimated_position, cover.current_cover_position)
                self.assertFalse(entity.extra_state_attributes['physical_arrival_confirmed'])
            self.assertEqual(self.writes, [])
            self.assertIs(cover._auto_stop_task, timer)
            self.assertFalse(timer.done())
        await cover.async_stop_cover()

    async def test_travel_parameter_change_invalidates_sensor_without_io(self):
        await self.publish(42)
        await self.batch({'open_travel_time': 200})
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, 'unknown')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'off')
        self.assertEqual(self.writes, [])

    async def test_source_unavailable_retains_estimate_without_claiming_known(self):
        cover = await self.publish()
        sensor_id = self.entity_id('sensor', 'estimated_position')
        known_id = self.entity_id('binary_sensor', 'position_known')
        for value in ('unavailable', 'unknown', None):
            if value is None:
                self.hass.states.async_remove('switch.open')
            else:
                self.hass.states.async_set('switch.open', value)
            await self.hass.async_block_till_done()
            self.assertEqual(self.hass.states.get(sensor_id).state, 'unavailable')
            self.assertEqual(self.hass.states.get(known_id).state, 'unavailable')
            self.assertEqual(cover._estimator.position, 42)
            self.hass.states.async_set('switch.open', 'off')
            await self.hass.async_block_till_done()
            self.assertEqual(self.hass.states.get(sensor_id).state, '42')
            self.assertEqual(self.hass.states.get(known_id).state, 'on')
        self.assertEqual(self.writes, [])

    async def test_registry_rename_disable_reload_unload_subscription_cleanup(self):
        registry = er.async_get(self.hass)
        cover = await self.publish()
        sensor_id = self.entity_id('sensor', 'estimated_position')
        known_id = self.entity_id('binary_sensor', 'position_known')
        sensor = self.hass.data['sensor'].get_entity(sensor_id)
        known = self.hass.data['binary_sensor'].get_entity(known_id)
        registry.async_update_entity(sensor_id, new_entity_id='sensor.renamed_estimate')
        registry.async_update_entity(known_id, new_entity_id='binary_sensor.renamed_known')
        await self.hass.async_block_till_done()
        sensor_id, known_id = 'sensor.renamed_estimate', 'binary_sensor.renamed_known'
        registry.async_update_entity(cover.entity_id, new_entity_id='cover.renamed_source')
        await self.hass.async_block_till_done()
        # Cover's existing native rename lifecycle performs safety OFF; projections do not.
        self.writes.clear()
        await self.publish(63)
        self.assertEqual(self.hass.states.get(sensor_id).state, '63')
        self.assertEqual(self.hass.states.get(sensor_id).attributes['source_cover'], 'cover.renamed_source')
        self.assertEqual(self.hass.states.get(known_id).state, 'on')
        registry.async_update_entity(sensor_id, disabled_by=er.RegistryEntryDisabler.USER)
        registry.async_update_entity(known_id, disabled_by=er.RegistryEntryDisabler.USER)
        await self.hass.async_block_till_done()
        self.assertIsNone(self.hass.data['sensor'].get_entity(sensor_id))
        self.assertIsNone(self.hass.data['binary_sensor'].get_entity(known_id))
        from unittest.mock import patch
        with patch.object(sensor, 'async_write_ha_state') as sensor_write, \
             patch.object(known, 'async_write_ha_state') as known_write:
            await self.publish(64)
            sensor_write.assert_not_called()
            known_write.assert_not_called()
        self.assertEqual(self.writes, [])
        registry.async_update_entity(sensor_id, disabled_by=None)
        registry.async_update_entity(known_id, disabled_by=None)
        self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
        await self.hass.async_block_till_done()
        await self.publish(65)
        self.assertEqual(self.entity_id('sensor', 'estimated_position'), sensor_id)
        self.assertEqual(self.entity_id('binary_sensor', 'position_known'), known_id)
        self.assertEqual(self.hass.states.get(sensor_id).state, '65')
        self.assertEqual(self.hass.states.get(known_id).state, 'on')
        sensor = self.hass.data['sensor'].get_entity(sensor_id)
        known = self.hass.data['binary_sensor'].get_entity(known_id)
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(sensor_id).state, 'unavailable')
        self.assertEqual(self.hass.states.get(known_id).state, 'unavailable')
        with patch.object(sensor, 'async_write_ha_state') as sensor_write, \
             patch.object(known, 'async_write_ha_state') as known_write:
            cover.async_write_ha_state()
            await self.hass.async_block_till_done()
            sensor_write.assert_not_called()
            known_write.assert_not_called()

    async def test_source_cover_disabled_and_removed_never_uses_stale_estimate(self):
        cover = await self.publish()
        registry = er.async_get(self.hass)
        registry.async_update_entity(cover.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, 'unavailable')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'unavailable')
        registry.async_remove(cover.entity_id)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, 'unavailable')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'unavailable')

    async def test_real_core_restart_exposes_remembered_unverified_not_arrival(self):
        await native_fixture.NativeParametersTest.test_standalone_target_service_and_unavailable_position_survive_new_core(self)
        sensor = self.hass.states.get(self.entity_id('sensor', 'estimated_position'))
        known = self.hass.states.get(self.entity_id('binary_sensor', 'position_known'))
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        self.assertEqual(float(sensor.state), cover.current_cover_position)
        self.assertEqual(known.state, 'on')
        for state in (sensor, known):
            self.assertEqual(state.attributes['position_basis'], 'remembered')
            self.assertTrue(state.attributes['position_unverified'])
            self.assertFalse(state.attributes['physical_arrival_confirmed'])

    async def test_legacy_unknown_feedback_and_native_passthrough_ownership(self):
        from homeassistant.config_entries import ConfigEntry
        await self.hass.config_entries.async_unload(self.entry.entry_id)
        self.hass.config_entries.async_update_entry(self.entry, data={
            **self.entry.data, 'feedback_mode': 'legacy_emos', 'acknowledge_legacy_risk': True})
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'unknown')
        self.assertTrue(await self.hass.config_entries.async_setup(self.entry.entry_id))
        await self.hass.async_block_till_done()
        self.writes.clear()
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, 'unknown')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'off')
        await self.publish(50)
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, '50')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'on')
        self.hass.states.async_set('switch.open', 'unavailable')
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.states.get(self.entity_id('sensor', 'estimated_position')).state, 'unavailable')
        self.assertEqual(self.hass.states.get(self.entity_id('binary_sensor', 'position_known')).state, 'unavailable')
        native = ConfigEntry(version=3, minor_version=1, domain=DOMAIN, title='Foreign',
            data={'actuator_mode': 'native_cover', 'cover_entity': 'cover.foreign'}, options={},
            source='user', unique_id='foreign', discovery_keys={}, subentries_data=[])
        self.hass.states.async_set('cover.foreign', 'closed')
        await self.hass.config_entries.async_add(native)
        await self.hass.async_block_till_done()
        rows = [row for row in er.async_get(self.hass).entities.values()
                if row.config_entry_id == native.entry_id]
        self.assertEqual(rows, [])
        self.assertEqual(self.hass.states.get('cover.foreign').state, 'closed')
        self.assertEqual(self.writes, [])


    def entity_id(self, domain, key):
        return er.async_get(self.hass).async_get_entity_id(
            domain, DOMAIN, f'{self.entry.entry_id}:{key}')

    async def test_estimated_position_unknown_and_numeric_publication_without_io(self):
        sensor_id = self.entity_id('sensor', 'estimated_position')
        known_id = self.entity_id('binary_sensor', 'position_known')
        sensor = self.hass.states.get(sensor_id) if sensor_id else None
        known = self.hass.states.get(known_id) if known_id else None
        self.assertIsNotNone(sensor, 'Owned estimated position must be published as a native Sensor')
        self.assertIsNotNone(known, 'Owned position-known must be published as a native BinarySensor')
        self.assertEqual(sensor.state, 'unknown')
        self.assertEqual(known.state, 'off')
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        for position in (0, 42, 100, None):
            cover._estimator.position = position
            cover._estimator.confidence = 'estimated' if position is not None else 'unknown'
            cover.async_write_ha_state()
            await self.hass.async_block_till_done()
            state = self.hass.states.get(sensor_id)
            self.assertEqual(state.state, 'unknown' if position is None else str(position))
            self.assertEqual(self.hass.states.get(known_id).state, 'off' if position is None else 'on')
            self.assertEqual(state.attributes['unit_of_measurement'], '%')
            self.assertTrue(state.attributes['position_is_estimated'])
            self.assertTrue(state.attributes['position_unverified'])
            self.assertFalse(state.attributes['physical_arrival_confirmed'])
        self.assertEqual(self.writes, [])
        for domain, entity_id in (('sensor', sensor_id), ('binary_sensor', known_id)):
            row = er.async_get(self.hass).async_get(entity_id)
            self.assertEqual(row.config_entry_id, self.entry.entry_id)
            self.assertEqual(row.platform, DOMAIN)
            self.assertEqual(row.device_id, er.async_get(self.hass).async_get(cover.entity_id).device_id)
            self.assertIsNone(row.config_subentry_id)
            self.assertEqual(row.domain, domain)
