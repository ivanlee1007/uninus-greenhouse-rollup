"""Offline native Options and service admission for compatibility mode."""
import unittest
import test_parameters_native as native
from homeassistant.exceptions import ServiceValidationError
from custom_components.uninus_greenhouse_rollup.const import DOMAIN


class LegacyOptionsTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native.NativeParametersTest.asyncSetUp
    asyncTearDown = native.NativeParametersTest.asyncTearDown

    async def select(self):
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['feedback_mode'] = 'legacy_emos'
        return await self.hass.config_entries.options.async_configure(form['flow_id'], values)

    async def enable(self):
        form = await self.select()
        self.assertEqual(form['type'], 'form')
        self.assertEqual(form['step_id'], 'confirm_legacy')
        return await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})

    async def test_confirmation_required_then_unknown_feedback_enable_without_reload_or_output(self):
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        cover._estimator.position = 37.125
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'unknown')
        await self.hass.async_block_till_done()
        form = await self.select()
        self.assertEqual(form['step_id'], 'confirm_legacy')
        self.assertNotIn('feedback_mode', self.entry.options)
        rejected = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': False})
        self.assertEqual(rejected['type'], 'form')
        result = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertEqual(result['type'], 'create_entry')
        await self.hass.async_block_till_done()
        self.assertEqual(self.entry.options['feedback_mode'], 'legacy_emos')
        self.assertIs(self.hass.data[DOMAIN]['covers'][self.entry.entry_id], cover)
        self.assertEqual(cover._estimator.position, 37.125)
        self.assertTrue(cover._auto_stop_at_travel_end)
        self.assertEqual(self.writes, [])

    async def test_confirmation_rechecks_busy_hardware(self):
        form = await self.select()
        self.assertEqual(form['step_id'], 'confirm_legacy')
        self.hass.states.async_set('switch.open', 'on')
        result = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertEqual(result['type'], 'form')
        self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
        self.assertEqual(self.writes, [])

    async def test_service_and_options_cannot_disable_legacy_auto_stop(self):
        self.assertEqual((await self.enable())['type'], 'create_entry')
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        with self.assertRaises(ServiceValidationError):
            await self.hass.services.async_call(DOMAIN, 'set_auto_stop_at_travel_end',
                {'entity_id': cover.entity_id, 'enabled': False}, blocking=True)
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['auto_stop_at_travel_end'] = False
        result = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        self.assertEqual(result['type'], 'form')
        self.assertTrue(cover._auto_stop_at_travel_end)
        self.assertEqual(self.writes, [])

    async def test_acknowledged_mode_enable_can_update_timings_with_unknown_feedback(self):
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values.update(feedback_mode='legacy_emos', open_travel_time=200)
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'unknown')
        await self.hass.async_block_till_done()
        confirm = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        result = await self.hass.config_entries.options.async_configure(confirm['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(self.hass.data[DOMAIN]['parameters'][self.entry.entry_id].parameters['open_travel_time'], 200)
        self.assertEqual(self.entry.options['feedback_mode'], 'legacy_emos')
        self.assertEqual(self.writes, [])

    async def test_confirmation_cannot_overwrite_new_hardware_policy(self):
        from homeassistant.core import Context
        form = await self.select()
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        await manager.async_update({'open_travel_time': 201}, Context())
        result = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertNotEqual(result['type'], 'create_entry')
        self.assertEqual(manager.parameters['open_travel_time'], 201)
        self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
        self.assertEqual(self.writes, [])

    async def test_confirmation_cannot_outlive_runtime_owner(self):
        form = await self.select()
        self.assertEqual(form['step_id'], 'confirm_legacy')
        await self.hass.config_entries.async_reload(self.entry.entry_id)
        await self.hass.async_block_till_done()
        self.writes.clear()
        result = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertNotEqual(result['type'], 'create_entry')
        self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
        self.assertEqual(self.writes, [])

    async def test_native_unknown_startup_and_no_echo_command_use_forced_timer(self):
        import asyncio
        self.assertEqual((await self.enable())['type'], 'create_entry')
        async def no_echo(call):
            self.writes.append((call.service, call.data['entity_id']))
        self.hass.services.async_register('switch', 'turn_off', no_echo)
        self.hass.services.async_register('switch', 'turn_on', no_echo)
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'unknown')
        await self.hass.async_block_till_done()
        await self.hass.config_entries.async_reload(self.entry.entry_id)
        await self.hass.async_block_till_done()
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        self.assertTrue(cover.available)
        self.assertFalse(cover.is_opening)
        self.assertIsNone(cover._auto_stop_task)
        await self.hass.services.async_call('cover', 'open_cover',
            {'entity_id': cover.entity_id}, blocking=True)
        self.assertTrue(cover.is_opening)
        self.assertIsNotNone(cover._auto_stop_task)
        task = cover._auto_stop_task
        cover._handle_tick(None)
        self.assertIs(cover._auto_stop_task, task)
        await self.hass.services.async_call('cover', 'stop_cover',
            {'entity_id': cover.entity_id}, blocking=True)
        await asyncio.sleep(0)
        self.assertFalse(cover.is_opening)
        self.assertEqual(self.hass.states.get('switch.open').state, 'unknown')

    async def test_confirmation_rejects_unavailable_source_without_output(self):
        form = await self.select()
        self.hass.states.async_set('switch.open', 'unavailable')
        await self.hass.async_block_till_done()
        result = await self.hass.config_entries.options.async_configure(form['flow_id'],
            {'acknowledge_legacy_risk': True})
        self.assertEqual(result['type'], 'form')
        self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
        self.assertEqual(self.writes, [])

    async def test_reconfigure_preserves_explicit_legacy_mode(self):
        self.assertEqual((await self.enable())['type'], 'create_entry')
        form = await self.hass.config_entries.flow.async_init(DOMAIN,
            context={'source': 'reconfigure', 'entry_id': self.entry.entry_id})
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['name'] = 'Renamed legacy'
        await self.hass.config_entries.flow.async_configure(form['flow_id'], values)
        await self.hass.async_block_till_done()
        self.assertEqual(self.hass.data[DOMAIN]['covers'][self.entry.entry_id]._feedback_mode, 'legacy_emos')

    async def test_mode_persists_reload_but_explicit_disable_does_not_reload(self):
        self.assertEqual((await self.enable())['type'], 'create_entry')
        await self.hass.config_entries.async_reload(self.entry.entry_id)
        await self.hass.async_block_till_done()
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        self.assertEqual(cover._feedback_mode, 'legacy_emos')
        self.writes.clear()
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['feedback_mode'] = 'standard'
        result = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        self.assertEqual(result['type'], 'create_entry')
        await self.hass.async_block_till_done()
        self.assertIs(self.hass.data[DOMAIN]['covers'][self.entry.entry_id], cover)
        self.assertEqual(cover._feedback_mode, 'standard')
        self.assertEqual(self.writes, [])
