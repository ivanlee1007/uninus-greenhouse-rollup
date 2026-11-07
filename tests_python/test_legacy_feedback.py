"""Command-owned estimation for explicitly opted-in change-only EMOS relays."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError
from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover


class LegacyFeedbackTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.entry = SimpleNamespace(entry_id='legacy', title='Legacy', options={}, data={})
        self.data = dict(open_entity='switch.o', close_entity='switch.c',
                         open_travel_time=100, close_travel_time=100,
                         reverse_dead_time=0, off_confirmation_timeout=0.1,
                         feedback_mode='legacy_emos', auto_stop_at_travel_end=False)
        self.cover = UninusGreenhouseRollupCover(self.entry, self.data)
        self.states = {e: SimpleNamespace(state='unknown') for e in ('switch.o', 'switch.c')}
        self.calls = AsyncMock()
        self.cover.hass = SimpleNamespace(data={}, states=self.states,
            services=SimpleNamespace(async_call=self.calls), async_create_task=asyncio.create_task)
        self.cover.async_write_ha_state = Mock()
        self.cover.entity_id = 'cover.legacy'
        self.cover._context = None
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        self.cover._cancel_auto_stop_task()
        if self.cover._conflict_stop_task:
            await self.cover._conflict_stop_task
        await asyncio.sleep(0)

    async def test_unknown_start_command_estimates_and_forces_timer_despite_false_setting(self):
        self.cover._estimator.position = 20.125
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: 10)):
            await self.cover.async_open_cover()
        self.assertTrue(self.cover.available)
        self.assertIsNotNone(self.cover._auto_stop_task)
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: 20)):
            self.cover._handle_tick(None)
        self.assertAlmostEqual(self.cover._estimator.position, 30.125)
        self.assertEqual(self.cover.extra_state_attributes['feedback_mode'], 'legacy_emos')
        self.assertTrue(self.cover.extra_state_attributes['position_unverified'])
        self.assertEqual([c.args[1] for c in self.calls.await_args_list], ['turn_off', 'turn_off', 'turn_on'])
        await self.cover.async_stop_cover()
        self.assertEqual(self.cover._estimator.command_state, 'idle')

    async def test_unavailable_or_missing_never_energizes(self):
        for value in ('unavailable', None):
            self.states['switch.o'] = SimpleNamespace(state=value)
            if value is None:
                self.states.pop('switch.o')
            with self.assertRaises(HomeAssistantError):
                await self.cover.async_open_cover()
            self.assertFalse(any(c.args[1] == 'turn_on' for c in self.calls.await_args_list))

    async def test_stale_feedback_cannot_cancel_command_timer_or_restart_after_stop(self):
        self.cover._estimator.position = 50
        await self.cover.async_open_cover()
        task = self.cover._auto_stop_task
        self.states['switch.o'] = SimpleNamespace(state='off')
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='on'), new_state=SimpleNamespace(state='off'))))
        self.assertIs(self.cover._auto_stop_task, task)
        self.assertTrue(self.cover.is_opening)
        await self.cover.async_stop_cover()
        self.states['switch.o'] = SimpleNamespace(state='on')
        self.cover._handle_tick(None)
        self.assertFalse(self.cover.is_opening)
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_partial_target_timer_stops_without_off_feedback(self):
        self.cover._estimator.position = 40
        self.cover._open_travel_time = 0.02
        self.cover._estimator.open_travel_time = 0.02
        await self.cover.async_set_cover_position(position=50)
        await asyncio.sleep(0.03)
        self.assertEqual(self.cover._target_operation, 'timer_elapsed')
        self.assertEqual(self.cover._estimator.command_state, 'idle')
        self.assertFalse(self.cover.extra_state_attributes['physical_arrival_confirmed'])
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_both_on_conflict_stops(self):
        await self.cover.async_open_cover()
        for state in self.states.values():
            state.state = 'on'
        self.cover._handle_tick(None)
        await self.cover._conflict_stop_task
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_external_transition_gets_forced_timer_and_off_freezes_estimate(self):
        self.states['switch.o'].state = 'on'
        self.states['switch.c'].state = 'off'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='off'), new_state=SimpleNamespace(state='on'))))
        self.assertTrue(self.cover.is_opening)
        self.assertIsNotNone(self.cover._auto_stop_task)
        self.assertEqual(self.cover.extra_state_attributes['position_basis'], 'feedback_estimated')
        self.states['switch.o'].state = 'off'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='on'), new_state=SimpleNamespace(state='off'))))
        self.assertEqual(self.cover._estimator.command_state, 'idle')
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_on_service_failure_cleans_both_and_never_starts_estimator(self):
        async def call(domain, service, data, **kwargs):
            if service == 'turn_on':
                raise HomeAssistantError('ON failed')
        self.calls.side_effect = call
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_open_cover()
        self.assertEqual(self.cover._estimator.command_state, 'idle')
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertEqual([c.args[1] for c in self.calls.await_args_list],
                         ['turn_off', 'turn_off', 'turn_on', 'turn_off', 'turn_off'])

    async def test_cancel_during_on_cleans_both_under_command_ownership(self):
        entered = asyncio.Event()
        async def call(domain, service, data, **kwargs):
            if service == 'turn_on':
                entered.set()
                await asyncio.Event().wait()
        self.calls.side_effect = call
        task = asyncio.create_task(self.cover.async_open_cover())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertFalse(self.cover._command_lock.locked())
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_missing_source_during_full_command_fails_safe(self):
        await self.cover.async_open_cover()
        self.states.pop('switch.o')
        self.cover._handle_tick(None)
        await self.cover._conflict_stop_task
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_legacy_endpoint_is_not_calibrated_physical_confirmation(self):
        self.cover._estimator.position = 99
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: 10)):
            await self.cover.async_open_cover()
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: 12)):
            self.cover._handle_tick(None)
        self.assertEqual(self.cover.current_cover_position, 100)
        self.assertEqual(self.cover.extra_state_attributes['position_confidence'], 'estimated')

    async def test_publication_failure_does_not_leave_energized_relay_without_stop_budget(self):
        self.cover.async_write_ha_state.side_effect = RuntimeError('publish failed')
        with self.assertRaises(RuntimeError):
            await self.cover.async_open_cover()
        self.assertIsNotNone(self.cover._auto_stop_task)

    async def test_disabled_relay_never_energizes_even_with_stale_state(self):
        from homeassistant.helpers import entity_registry as er
        self.cover.hass.data[er.DATA_REGISTRY] = SimpleNamespace(
            async_get=lambda e: SimpleNamespace(disabled=True))
        self.cover._sync_from_switches()
        self.assertFalse(self.cover.available)
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_open_cover()
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.calls.await_args_list))

    async def test_timer_still_sends_off_if_state_publication_fails(self):
        self.cover._open_travel_time = 0.01
        self.cover._estimator.position = 50
        await self.cover.async_set_cover_position(position=60)
        task = self.cover._auto_stop_task
        self.cover.async_write_ha_state.side_effect = RuntimeError('publish failed')
        try:
            await task
        except RuntimeError:
            pass
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_completed_timer_clears_interrupted_flag_in_saved_snapshot(self):
        self.cover._open_travel_time = 0.01
        await self.cover.async_open_cover()
        self.assertTrue(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])
        await asyncio.sleep(0.03)
        self.assertFalse(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])

    async def test_stop_during_legacy_deadtime_prevents_late_on(self):
        self.cover._reverse_dead_time = 0.05
        command = asyncio.create_task(self.cover.async_open_cover())
        while self.calls.await_count < 2:
            await asyncio.sleep(0)
        await self.cover.async_stop_cover()
        await command
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.calls.await_args_list))
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_opposite_on_event_fails_safe_even_without_local_on_echo(self):
        await self.cover.async_open_cover()
        self.states['switch.c'].state = 'on'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.c',
            old_state=SimpleNamespace(state='off'), new_state=SimpleNamespace(state='on'))))
        await self.cover._conflict_stop_task
        self.assertEqual(self.cover._legacy_direction, 'idle')
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_unknown_partial_target_is_rejected_without_disarming_endpoint_timer(self):
        await self.cover.async_open_cover()
        task = self.cover._auto_stop_task
        before = self.calls.await_count
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_set_cover_position(position=50)
        self.assertIs(self.cover._auto_stop_task, task)
        self.assertEqual(self.calls.await_count, before)

    async def test_late_on_edge_after_local_stop_cannot_restart_estimator(self):
        await self.cover.async_open_cover()
        await self.cover.async_stop_cover()
        self.states['switch.o'].state = 'on'
        self.states['switch.c'].state = 'off'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='off'), new_state=SimpleNamespace(state='on'))))
        self.assertFalse(self.cover.is_opening)
        self.assertIsNone(self.cover._auto_stop_task)
        # A separately observed idle OFF establishes a new external baseline.
        self.states['switch.o'].state = 'off'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='on'), new_state=SimpleNamespace(state='off'))))
        self.states['switch.o'].state = 'on'
        self.cover._handle_state_event(SimpleNamespace(data=dict(entity_id='switch.o',
            old_state=SimpleNamespace(state='off'), new_state=SimpleNamespace(state='on'))))
        self.assertTrue(self.cover.is_opening)
        self.assertIsNotNone(self.cover._auto_stop_task)

    async def test_conflict_safety_is_scheduled_before_publication(self):
        await self.cover.async_open_cover()
        for state in self.states.values():
            state.state = 'on'
        self.cover.async_write_ha_state.side_effect = RuntimeError('publish failed')
        with self.assertRaises(RuntimeError):
            self.cover._handle_tick(None)
        self.assertIsNotNone(self.cover._conflict_stop_task)
        await self.cover._conflict_stop_task
        self.assertEqual([c.args[1] for c in self.calls.await_args_list][-2:], ['turn_off', 'turn_off'])

    async def test_off_failure_attempts_both_and_latches_uncertainty_until_successful_stop(self):
        await self.cover.async_open_cover()
        self.calls.side_effect = HomeAssistantError('OFF failed')
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_stop_cover()
        self.assertTrue(self.cover.extra_state_attributes['stop_command_error'])
        self.assertTrue(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])
        self.calls.side_effect = None
        await self.cover.async_stop_cover()
        self.assertFalse(self.cover.extra_state_attributes['stop_command_error'])
        self.assertFalse(self.cover.extra_restore_state_data.as_dict()['motion_interrupted'])
