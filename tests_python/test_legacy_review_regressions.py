"""Independent-review regressions for legacy dispatch and confirmation races."""
import asyncio
import unittest
from types import SimpleNamespace


import test_legacy_feedback as feedback_fixtures
import test_parameters_native as native_fixtures
import test_cover_restore as restore_fixtures
from custom_components.uninus_greenhouse_rollup.const import DOMAIN
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

class FeedbackProbes(unittest.IsolatedAsyncioTestCase):
    setUp = feedback_fixtures.LegacyFeedbackTest.setUp
    cleanup = feedback_fixtures.LegacyFeedbackTest.cleanup

    async def test_opposite_on_during_pending_on_must_fail_safe(self):
        async def call(domain, service, data, **kwargs):
            if service == 'turn_on':
                self.states['switch.c'].state = 'on'
                self.cover._handle_state_event(SimpleNamespace(data=dict(
                    entity_id='switch.c', old_state=SimpleNamespace(state='off'),
                    new_state=SimpleNamespace(state='on'))))
                await asyncio.sleep(0)
        self.calls.side_effect = call
        await self.cover.async_open_cover()
        self.cover._handle_tick(None)
        await asyncio.sleep(0)
        if self.cover._conflict_stop_task:
            await self.cover._conflict_stop_task
        services = [c.args[1] for c in self.calls.await_args_list]
        print('OPPOSITE_DURING_ON', {'services': services,
            'direction': self.cover._legacy_direction,
            'timer': self.cover._auto_stop_task is not None,
            'opposite': self.states['switch.c'].state}, flush=True)
        self.assertEqual(services[-2:], ['turn_off', 'turn_off'])
        self.assertEqual(self.cover._legacy_direction, 'idle')
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_failed_on_and_failed_cleanup_must_persist_uncertainty(self):
        count = 0
        async def call(domain, service, data, **kwargs):
            nonlocal count
            count += 1
            if count >= 3:
                raise HomeAssistantError('Device unreachable after ON dispatch')
        self.calls.side_effect = call
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_open_cover()
        snapshot = self.cover.extra_restore_state_data.as_dict()
        print('ON_AND_CLEANUP_FAILURE', {'snapshot': snapshot,
            'stop_error': self.cover._stop_error,
            'services': [c.args[1] for c in self.calls.await_args_list]}, flush=True)
        self.assertTrue(snapshot['motion_interrupted'])
        self.assertTrue(snapshot['stop_command_error'])
        self.assertFalse(self.cover.extra_state_attributes['physical_arrival_confirmed'])
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:],
                         ['turn_off', 'turn_off'])

    async def _opposite_on_without_yield(self, outcome):
        async def call(domain, service, data, **kwargs):
            if service != 'turn_on':
                return
            self.assertTrue(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])
            self.states['switch.c'].state = 'on'
            self.cover._handle_state_event(SimpleNamespace(data=dict(
                entity_id='switch.c', old_state=SimpleNamespace(state='off'),
                new_state=SimpleNamespace(state='on'))))
            if outcome is not None:
                raise outcome
        self.calls.side_effect = call
        if outcome is None:
            await self.cover.async_open_cover()
        else:
            with self.assertRaises(type(outcome)):
                await self.cover.async_open_cover()
        # Even before the scheduled fail-safe runs, a stale successful return
        # must not arm a timer or publish a running estimator.
        self.assertIsNone(self.cover._auto_stop_task)
        await self.cleanup()
        self.assertEqual(self.cover._legacy_starting_direction, 'idle')
        self.assertEqual(self.cover._legacy_direction, 'idle')
        self.assertEqual(self.cover._estimator.command_state, 'idle')
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:],
                         ['turn_off', 'turn_off'])
        # Neither direction may resurrect from delayed ON after the conflict.
        for entity in self.states:
            self.cover._handle_state_event(SimpleNamespace(data=dict(
                entity_id=entity, old_state=SimpleNamespace(state='off'),
                new_state=SimpleNamespace(state='on'))))
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_synchronous_opposite_on_invalidates_success_before_timer_arm(self):
        await self._opposite_on_without_yield(None)

    async def test_opposite_on_followed_by_dispatch_error_stops_both(self):
        await self._opposite_on_without_yield(HomeAssistantError('ON dispatched then failed'))

    async def test_opposite_on_followed_by_dispatch_cancel_stops_both(self):
        await self._opposite_on_without_yield(asyncio.CancelledError())

    async def test_pending_dispatch_snapshot_is_conservative_before_service_returns(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(domain, service, data, **kwargs):
            if service == 'turn_on':
                entered.set()
                await release.wait()
        self.calls.side_effect = call
        task = asyncio.create_task(self.cover.async_open_cover())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertTrue(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])
            self.assertEqual(self.cover._legacy_starting_direction, 'opening')
        finally:
            release.set()
            await task
        await self.cover.async_stop_cover()
        self.assertFalse(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])

    async def test_historical_opposite_on_does_not_block_ordinary_reversal(self):
        await self.cover.async_close_cover()
        self.states['switch.c'].state = 'on'
        # OFF services succeed without echoes; this cached ON predates the
        # reversal and must not be confused with a fresh in-flight ON event.
        await self.cover.async_open_cover()
        self.assertEqual(self.cover._legacy_direction, 'opening')
        self.assertIsNotNone(self.cover._auto_stop_task)
        self.assertEqual(self.calls.await_args_list[-1].args[1:3],
                         ('turn_on', {'entity_id': 'switch.o'}))

class ConfirmationProbe(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_fixtures.NativeParametersTest.asyncSetUp
    asyncTearDown = native_fixtures.NativeParametersTest.asyncTearDown

    async def test_native_opposite_on_during_pending_on_must_fail_safe(self):
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['feedback_mode'] = 'legacy_emos'
        confirm = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        await self.hass.config_entries.options.async_configure(confirm['flow_id'],
            {'acknowledge_legacy_risk': True})
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        async def no_echo(call):
            self.writes.append((call.service, call.data['entity_id']))
            if call.service == 'turn_on':
                self.hass.states.async_set('switch.close', 'on')
                await asyncio.sleep(0.01)
        self.hass.services.async_register('switch', 'turn_off', no_echo)
        self.hass.services.async_register('switch', 'turn_on', no_echo)
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'off')
        await self.hass.async_block_till_done()
        self.writes.clear()
        await self.hass.services.async_call('cover', 'open_cover',
            {'entity_id': cover.entity_id}, blocking=True)
        cover._handle_tick(None)
        await asyncio.sleep(0.01)
        print('NATIVE_OPPOSITE_DURING_ON', {'writes': self.writes,
            'direction': cover._legacy_direction,
            'timer': cover._auto_stop_task is not None,
            'opposite': self.hass.states.get('switch.close').state}, flush=True)
        self.assertEqual([item[0] for item in self.writes][-2:], ['turn_off', 'turn_off'])
        self.assertEqual(cover._legacy_direction, 'idle')
        self.assertIsNone(cover._auto_stop_task)

    async def test_policy_change_during_confirmation_admission_must_reject(self):
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        values['feedback_mode'] = 'legacy_emos'
        confirm = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        self.assertEqual(confirm['step_id'], 'confirm_legacy')
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager._authorize
        entered, release = asyncio.Event(), asyncio.Event()
        first = True
        async def gate(context, targets):
            nonlocal first
            if first:
                first = False
                entered.set()
                await release.wait()
            return await original(context, targets)
        manager._authorize = gate
        task = asyncio.create_task(self.hass.config_entries.options.async_configure(
            confirm['flow_id'], {'acknowledge_legacy_risk': True}))
        await asyncio.wait_for(entered.wait(), 5)
        await manager.async_update({'open_travel_time': 201}, Context())
        release.set()
        result = await task
        print('CONFIRMATION_RACE', {'result': result['type'],
            'revision': manager.revision, 'open_travel_time': manager.parameters['open_travel_time'],
            'feedback_mode': self.entry.options.get('feedback_mode'), 'writes': self.writes}, flush=True)
        self.assertNotEqual(result['type'], 'create_entry')
        self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
        self.assertEqual(manager.parameters['open_travel_time'], 201)
        self.assertEqual(self.writes, [])

    async def test_final_locked_admission_rechecks_epoch_options_and_owner(self):
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager._authorize
        for change in ('epoch', 'options', 'owner'):
            with self.subTest(change=change):
                form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
                values = {key.schema: key.default() for key in form['data_schema'].schema}
                values['feedback_mode'] = 'legacy_emos'
                confirm = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
                entered, release = asyncio.Event(), asyncio.Event()
                calls = 0
                async def gate(context, targets):
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        self.assertTrue(manager.lock.locked())
                        self.assertTrue(manager.cover._command_lock.locked())
                        entered.set()
                        await release.wait()
                    return await original(context, targets)
                manager._authorize = gate
                task = asyncio.create_task(self.hass.config_entries.options.async_configure(
                    confirm['flow_id'], {'acknowledge_legacy_risk': True}))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    if change == 'epoch':
                        manager.cover._parameter_epoch += 1
                    elif change == 'options':
                        self.hass.config_entries.async_update_entry(self.entry,
                            options={**self.entry.options, 'actuator_type': 'shade'})
                    else:
                        self.hass.data[DOMAIN]['parameters'][self.entry.entry_id] = object()
                finally:
                    release.set()
                    result = await task
                    manager._authorize = original
                    self.hass.data[DOMAIN]['parameters'][self.entry.entry_id] = manager
                self.assertNotEqual(result['type'], 'create_entry')
                self.assertNotEqual(self.entry.options.get('feedback_mode'), 'legacy_emos')
                self.assertEqual(self.writes, [])


class RestoreUncertaintyProbe(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = restore_fixtures.CoverRestoreTest.asyncSetUp
    make_cover = restore_fixtures.CoverRestoreTest.make_cover
    set_saved_state = restore_fixtures.CoverRestoreTest.set_saved_state
    add_cover = restore_fixtures.CoverRestoreTest.add_cover

    async def test_stop_error_snapshot_restores_as_uncertainty_never_motion(self):
        cover = self.make_cover()
        cover._feedback_mode = 'legacy_emos'
        self.set_saved_state(cover, dict(position=37.125, confidence='estimated',
            open_travel_time=100, close_travel_time=100,
            motion_interrupted=False, stop_command_error=True))
        await self.add_cover(cover)
        self.assertTrue(cover.extra_restore_state_data.as_dict()['stop_command_error'])
        self.assertTrue(cover.extra_restore_state_data.as_dict()['motion_interrupted'])
        self.assertEqual(cover._position_basis, 'remembered')
        self.assertEqual(cover._legacy_direction, 'idle')
        self.assertIsNone(cover._auto_stop_task)
        self.assertFalse(cover.extra_state_attributes['physical_arrival_confirmed'])
        cover._context = None
        cover.async_write_ha_state = lambda: None
        writes = []
        async def stop(call):
            writes.append(call.data['entity_id'])
        self.hass.services.async_register('switch', 'turn_off', stop)
        await cover.async_stop_cover()
        self.assertEqual(writes, ['switch.open', 'switch.close'])
        self.assertFalse(cover.extra_restore_state_data.as_dict()['stop_command_error'])
        self.assertFalse(cover.extra_restore_state_data.as_dict()['motion_interrupted'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
