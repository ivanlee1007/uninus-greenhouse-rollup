"""Behavioral safety tests; no external HA or hardware connections."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from homeassistant.exceptions import HomeAssistantError
from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover


class TargetPositionTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.cover = UninusGreenhouseRollupCover(
            SimpleNamespace(entry_id='target-entry', title='Target actuator'),
            dict(open_entity='switch.open', close_entity='switch.close',
                 open_travel_time=10, close_travel_time=20, reverse_dead_time=0),
        )
        self.states = {key: SimpleNamespace(state='off') for key in ('switch.open', 'switch.close')}
        self.services = SimpleNamespace(async_call=AsyncMock(side_effect=self.apply))
        self.cover.hass = SimpleNamespace(states=self.states, services=self.services,
                                          data={}, async_create_task=asyncio.create_task,
                                          async_add_executor_job=AsyncMock(side_effect=lambda fn, *args: fn(*args)))
        self.cover._context = None
        self.cover.async_write_ha_state = Mock()
        self.cover._estimator.position = 20

    async def apply(self, domain, service, data, **kwargs):
        self.states[data['entity_id']].state = 'on' if service == 'turn_on' else 'off'

    async def test_invalid_target_rejected_without_output_writes(self):
        for target in (True, False, -1, 101, 1.5, float('nan'), float('inf'), '20', None):
            with self.subTest(target=target):
                with self.assertRaises(HomeAssistantError):
                    await self.cover.async_set_cover_position(position=target)
        self.services.async_call.assert_not_awaited()

    async def test_unknown_start_rejects_intermediate_without_any_output(self):
        self.cover._estimator.position = None
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_set_cover_position(position=50)
        self.services.async_call.assert_not_awaited()

    async def test_unknown_endpoint_uses_full_direction_specific_budget(self):
        from unittest.mock import patch
        for target, duration in ((100, 10), (0, 20)):
            self.cover._estimator.position = None
            with patch.object(self.cover, '_async_auto_stop_after', new=AsyncMock()) as timer:
                await self.cover.async_set_cover_position(position=target)
                await asyncio.sleep(0)
                self.assertEqual(timer.await_args.args[0], duration)
            self.assertIsNone(self.cover.current_cover_position)

    async def test_same_position_never_reenergizes(self):
        await self.cover.async_set_cover_position(position=20)
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))

    async def test_start_waits_for_asynchronous_both_off_readback(self):
        self.states['switch.close'].state = 'on'
        off_requested = asyncio.Event()
        async def delayed(domain, service, data, **kwargs):
            if service == 'turn_off':
                off_requested.set()
            else:
                self.assertTrue(all(s.state == 'off' for s in self.states.values()))
        self.services.async_call.side_effect = delayed
        task = asyncio.create_task(self.cover.async_open_cover())
        await asyncio.wait_for(off_requested.wait(), 1)
        await asyncio.sleep(0.02)
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))
        self.states['switch.close'].state = 'off'
        await asyncio.wait_for(task, 1)
        self.assertEqual(self.services.async_call.await_args.args[1], 'turn_on')

    async def test_off_confirmation_timeout_refuses_energize(self):
        self.cover._off_confirmation_timeout = 0.02
        self.states['switch.close'].state = 'on'
        self.services.async_call.side_effect = None
        with self.assertRaises(HomeAssistantError):
            await asyncio.wait_for(self.cover.async_open_cover(), 0.5)
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))

    async def test_target_timer_retains_time_estimated_motion_not_physical_arrival(self):
        self.cover._open_travel_time = 0.1
        self.cover._estimator.open_travel_time = 0.1
        await self.cover.async_set_cover_position(position=50)
        await asyncio.sleep(0.06)
        self.assertGreaterEqual(self.cover.current_cover_position, 49)
        self.assertTrue(self.cover.extra_state_attributes.get('position_is_estimated'))
        self.assertFalse(self.cover.extra_state_attributes.get('physical_arrival_confirmed', True))
        self.assertEqual(self.cover.extra_state_attributes.get('target_operation'), 'timer_elapsed')

    async def test_stop_clears_target_and_freezes_motion(self):
        await self.cover.async_set_cover_position(position=80)
        timer = self.cover._auto_stop_task
        await self.cover.async_stop_cover()
        await asyncio.sleep(0)
        self.assertTrue(timer.cancelled())
        self.assertIsNone(self.cover.extra_state_attributes['target_position'])
        self.assertEqual(self.cover.extra_state_attributes['target_operation'], 'idle')
        self.assertEqual(self.cover._estimator.command_state, 'idle')

    async def test_unknown_rejected_target_does_not_disarm_existing_endpoint_stop(self):
        self.cover._estimator.position = None
        await self.cover.async_set_cover_position(position=100)
        timer = self.cover._auto_stop_task
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_set_cover_position(position=50)
        self.assertIs(self.cover._auto_stop_task, timer)
        self.assertFalse(timer.cancelled())

    async def test_target_budget_uses_estimate_after_old_motion_is_stopped(self):
        from unittest.mock import patch
        clock = [0.0]
        self.cover._estimator.sync(open_on=True, close_on=False, now=0)
        self.states['switch.open'].state = 'on'
        async def slow_stop(domain, service, data, **kwargs):
            if service == 'turn_off' and data['entity_id'] == 'switch.open':
                clock[0] = 1.0  # Old opening moved 20 -> 30 before OFF readback.
            await self.apply(domain, service, data, **kwargs)
        self.services.async_call.side_effect = slow_stop
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: clock[0])), patch.object(self.cover, '_async_auto_stop_after', new=AsyncMock()) as timer:
            await self.cover.async_set_cover_position(position=60)
            await asyncio.sleep(0)
        self.assertAlmostEqual(timer.await_args.args[0], 3.0)

    async def test_unknown_unavailable_or_missing_readback_never_energizes(self):
        self.cover._off_confirmation_timeout = 0.01
        self.services.async_call.side_effect = None
        for state in ('unknown', 'unavailable', 'invalid', None):
            with self.subTest(state=state):
                self.services.async_call.reset_mock()
                self.states['switch.close'] = SimpleNamespace(state=state)
                if state is None:
                    self.states.pop('switch.close')
                with self.assertRaises(HomeAssistantError):
                    await asyncio.wait_for(self.cover.async_open_cover(), 0.5)
                self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))

    async def test_stop_during_target_off_wait_prevents_stale_restart(self):
        self.cover._reverse_dead_time = 0.03
        task = asyncio.create_task(self.cover.async_set_cover_position(position=80))
        await asyncio.sleep(0)
        await self.cover.async_stop_cover()
        await task
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_reversal_cancels_old_target_timer_and_uses_close_budget(self):
        from unittest.mock import patch
        await self.cover.async_set_cover_position(position=80)
        old = self.cover._auto_stop_task
        self.cover._estimator.position = 60
        with patch.object(self.cover, '_async_auto_stop_after', new=AsyncMock()) as timer:
            await self.cover.async_set_cover_position(position=30)
            await asyncio.sleep(0)
            self.assertAlmostEqual(timer.await_args.args[0], 6, delta=0.1)
        self.assertTrue(old.cancelled())
        ons = [c.args[2]['entity_id'] for c in self.services.async_call.await_args_list if c.args[1] == 'turn_on']
        self.assertEqual(ons, ['switch.open', 'switch.close'])

    async def test_unload_cancels_target_timer_and_never_resumes_it(self):
        from unittest.mock import patch
        await self.cover.async_set_cover_position(position=80)
        old = self.cover._auto_stop_task
        with patch('homeassistant.helpers.entity.Entity.async_will_remove_from_hass', new=AsyncMock()):
            await self.cover.async_will_remove_from_hass()
        before = self.services.async_call.await_count
        await self.cover.async_set_cover_position(position=70)
        await asyncio.sleep(0.02)
        self.assertEqual(self.services.async_call.await_count, before)
        self.assertTrue(old.cancelled())
        self.assertTrue(all(s.state == 'off' for s in self.states.values()))

    async def test_dead_time_rechecks_actual_off_not_only_acknowledgement(self):
        self.cover._reverse_dead_time = 0.02
        self.cover._off_confirmation_timeout = 0.01
        async def inject_external_on():
            await asyncio.sleep(0.005)
            self.states['switch.close'].state = 'on'
        self.services.async_call.side_effect = None
        other = asyncio.create_task(inject_external_on())
        with self.assertRaises(HomeAssistantError):
            await self.cover.async_open_cover()
        await other
        self.assertFalse(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))

    async def test_target_source_loss_requests_fail_safe_stop_not_only_timer_cancel(self):
        await self.cover.async_set_cover_position(position=80)
        before = self.services.async_call.await_count
        self.states['switch.open'].state = 'unavailable'
        event = SimpleNamespace(data={'entity_id': 'switch.open',
            'old_state': SimpleNamespace(state='on'), 'new_state': SimpleNamespace(state='unavailable')})
        self.cover._handle_state_event(event)
        await asyncio.sleep(0.02)
        self.assertEqual([c.args[1] for c in self.services.async_call.await_args_list[before:]], ['turn_off', 'turn_off'])
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_failed_target_stop_reports_error_not_running_or_arrived(self):
        self.cover._open_travel_time = 0.1
        self.cover._estimator.open_travel_time = 0.1
        await self.cover.async_set_cover_position(position=30)
        self.services.async_call.side_effect = RuntimeError('relay stop failed')
        with self.assertLogs('custom_components.uninus_greenhouse_rollup.cover', level='ERROR'):
            await self.cover._auto_stop_task
        self.assertEqual(self.cover.extra_state_attributes['target_operation'], 'error')
        self.assertFalse(self.cover.extra_state_attributes['physical_arrival_confirmed'])

    async def test_target_reached_during_stop_does_not_claim_running_without_timer(self):
        from unittest.mock import patch
        clock = [0.0]
        self.cover._estimator.sync(open_on=True, close_on=False, now=0)
        self.states['switch.open'].state = 'on'
        async def delayed(domain, service, data, **kwargs):
            clock[0] = 1.0
            await self.apply(domain, service, data, **kwargs)
        self.services.async_call.side_effect = delayed
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: clock[0])):
            await self.cover.async_set_cover_position(position=30)
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertEqual(self.cover.extra_state_attributes['target_operation'], 'idle')

    async def test_unknown_endpoint_keeps_full_budget_if_stop_changes_estimate(self):
        from unittest.mock import patch
        self.cover._estimator.position = None
        self.cover._estimator.sync(open_on=True, close_on=False, now=0)
        self.cover._estimator._unknown_elapsed = 9
        self.states['switch.open'].state = 'on'
        clock = [0.0]
        async def delayed(domain, service, data, **kwargs):
            clock[0] = 2.0
            await self.apply(domain, service, data, **kwargs)
        self.services.async_call.side_effect = delayed
        with patch('custom_components.uninus_greenhouse_rollup.cover.time', SimpleNamespace(monotonic=lambda: clock[0])), patch.object(self.cover, '_async_auto_stop_after', new=AsyncMock()) as timer:
            await self.cover.async_set_cover_position(position=100)
            await asyncio.sleep(0)
        self.assertTrue(any(c.args[1] == 'turn_on' for c in self.services.async_call.await_args_list))
        self.assertEqual(timer.await_args.args[0], 10)

    async def asyncTearDown(self):
        self.cover._cancel_auto_stop_task()
        await asyncio.sleep(0)

    async def test_partial_target_stops_even_when_optional_auto_stop_disabled(self):
        # 20 -> 30 is 10% of opening time: 0.01 s here.
        self.cover._open_travel_time = 0.1
        self.cover._estimator.open_travel_time = 0.1
        try:
            await self.cover.async_set_cover_position(position=30)
        except NotImplementedError:
            pass  # Baseline inherited method: assert the missing physical behavior.
        await asyncio.sleep(0.04)
        self.assertEqual([c.args[1] for c in self.services.async_call.await_args_list],
                         ['turn_off', 'turn_off', 'turn_on', 'turn_off', 'turn_off'])
        self.assertEqual(self.states['switch.open'].state, 'off')
        self.assertEqual(self.cover.extra_state_attributes.get('target_position'), 30)
