import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import AsyncMock, Mock, patch

try:
    from custom_components.uninus_greenhouse_rollup.const import (
        CONF_CLOSE_ENTITY,
        CONF_CLOSE_TRAVEL_TIME,
        CONF_OPEN_ENTITY,
        CONF_OPEN_TRAVEL_TIME,
        CONF_REVERSE_DEAD_TIME,
    )
    import custom_components.uninus_greenhouse_rollup.cover as cover_module
    from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover
except ModuleNotFoundError as error:
    if error.name and error.name.startswith("homeassistant"):
        UninusGreenhouseRollupCover = None
    else:
        raise


@skipIf(UninusGreenhouseRollupCover is None, "Home Assistant test dependency not installed")
class CoverControlTest(IsolatedAsyncioTestCase):
    def setUp(self):
        entry = SimpleNamespace(entry_id="east-entry", title="East roll-up")
        data = {
            "name": "East roll-up",
            CONF_OPEN_ENTITY: "switch.east_open",
            CONF_CLOSE_ENTITY: "switch.east_close",
            CONF_OPEN_TRAVEL_TIME: 100,
            CONF_CLOSE_TRAVEL_TIME: 110,
            CONF_REVERSE_DEAD_TIME: 0,
        }
        self.cover = UninusGreenhouseRollupCover(entry, data)
        self.services = SimpleNamespace(async_call=AsyncMock())
        self.states = {
            "switch.east_open": SimpleNamespace(state="off"),
            "switch.east_close": SimpleNamespace(state="off"),
        }
        self.cover.hass = SimpleNamespace(
            services=self.services,
            states=self.states,
            async_create_task=asyncio.create_task,
        )
        self.cover._context = None

    @staticmethod
    def _ids(calls):
        return [item.args[2]["entity_id"] for item in calls]

    async def test_open_turns_each_relay_off_before_turning_open_on(self):
        await self.cover.async_open_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close", "switch.east_open"],
        )
        self.assertEqual(
            [item.args[1] for item in self.services.async_call.await_args_list],
            ["turn_off", "turn_off", "turn_on"],
        )

    async def test_close_turns_each_relay_off_before_turning_close_on(self):
        await self.cover.async_close_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close", "switch.east_close"],
        )
        self.assertEqual(
            [item.args[1] for item in self.services.async_call.await_args_list],
            ["turn_off", "turn_off", "turn_on"],
        )

    async def test_enabled_auto_stop_turns_both_switches_off_after_open_travel_time(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 0.001
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        await asyncio.sleep(0.01)

        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_enabled_auto_stop_uses_close_travel_time_for_close_command(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._close_travel_time = 0.001
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_close_cover()
        await asyncio.sleep(0.01)

        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_close",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_direction_change_cancels_stale_timer_before_scheduling_new_one(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 60
        self.cover._close_travel_time = 0.001
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        stale_timer = self.cover._auto_stop_task
        await self.cover.async_close_cover()
        active_timer = self.cover._auto_stop_task
        await asyncio.sleep(0.01)

        self.assertIsNotNone(stale_timer)
        self.assertTrue(stale_timer.cancelled())
        self.assertIsNot(stale_timer, active_timer)
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
                "switch.east_close",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_source_event_before_target_on_confirmation_keeps_auto_stop_timer(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 60
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        auto_stop_timer = self.cover._auto_stop_task
        self.cover._handle_state_event(None)
        await asyncio.sleep(0)

        self.assertIs(self.cover._auto_stop_task, auto_stop_timer)
        self.assertFalse(auto_stop_timer.cancelled())
        auto_stop_timer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await auto_stop_timer

    async def test_target_on_to_off_event_cancels_timer_without_prior_on_callback(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 60
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        stale_timer = self.cover._auto_stop_task
        event = SimpleNamespace(
            data={
                "entity_id": "switch.east_open",
                "old_state": SimpleNamespace(state="on"),
                "new_state": SimpleNamespace(state="off"),
            }
        )
        self.cover._handle_state_event(event)
        await asyncio.sleep(0)

        self.assertIsNotNone(stale_timer)
        self.assertTrue(stale_timer.cancelled())

    async def test_direct_source_direction_change_cancels_cover_auto_stop_timer(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 60
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        stale_timer = self.cover._auto_stop_task
        self.states["switch.east_open"].state = "on"
        self.cover._handle_state_event(None)
        self.states["switch.east_open"].state = "off"
        self.states["switch.east_close"].state = "on"
        self.cover._handle_state_event(None)
        await asyncio.sleep(0)

        self.assertIsNotNone(stale_timer)
        self.assertTrue(stale_timer.cancelled())

    async def test_manual_stop_cancels_the_pending_auto_stop_timer(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 60
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = Mock()

        await self.cover.async_open_cover()
        auto_stop_task = self.cover._auto_stop_task
        await self.cover.async_stop_cover()
        await asyncio.sleep(0)

        self.assertIsNotNone(auto_stop_task)
        self.assertTrue(auto_stop_task.cancelled())
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_auto_stop_failure_still_attempts_both_switches_and_is_logged(self):
        self.cover._auto_stop_at_travel_end = True
        self.cover._open_travel_time = 0.001
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = Mock()
        self.services.async_call.side_effect = [
            None,
            None,
            None,
            RuntimeError("open relay would not turn off"),
            None,
        ]

        with self.assertLogs(cover_module._LOGGER.name, level="ERROR") as captured:
            await self.cover.async_open_cover()
            auto_stop_task = self.cover._auto_stop_task
            await auto_stop_task

        self.assertIn("Failed to auto-stop greenhouse roll-up relays", captured.output[0])
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_stop_attempts_both_direction_switches(self):
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = lambda: None
        await self.cover.async_stop_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_cancelled_direction_start_turns_both_switches_off_again(self):
        turn_on_started = asyncio.Event()

        async def apply_then_wait(_domain, service, data, **_kwargs):
            entity_id = data["entity_id"]
            if service == "turn_on":
                self.states[entity_id].state = "on"
                turn_on_started.set()
                await asyncio.Future()
            else:
                self.states[entity_id].state = "off"

        self.services.async_call.side_effect = apply_then_wait
        open_task = asyncio.create_task(self.cover.async_open_cover())
        await turn_on_started.wait()
        open_task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await open_task

        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
            ],
        )
        self.assertEqual(self.states["switch.east_open"].state, "off")
        self.assertEqual(self.states["switch.east_close"].state, "off")

    async def test_failed_direction_start_turns_both_switches_off_again(self):
        self.services.async_call.side_effect = [None, None, RuntimeError("relay failed"), None, None]
        with self.assertRaisesRegex(RuntimeError, "relay failed"):
            await self.cover.async_open_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_failed_first_stop_still_attempts_the_second_relay(self):
        self.services.async_call.side_effect = [RuntimeError("first failed"), None]
        with self.assertRaisesRegex(RuntimeError, "first failed"):
            await self.cover.async_open_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_cancelled_first_stop_still_attempts_the_second_relay(self):
        self.services.async_call.side_effect = [asyncio.CancelledError(), None]

        with self.assertRaises(asyncio.CancelledError):
            await self.cover._async_turn_both_off()

        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_opposite_commands_are_serialized(self):
        sequence = []

        async def record_call(_domain, service, data, **_kwargs):
            sequence.append((service, data["entity_id"]))
            await asyncio.sleep(0)

        self.services.async_call.side_effect = record_call
        await asyncio.gather(self.cover.async_open_cover(), self.cover.async_close_cover())
        self.assertEqual(
            sequence,
            [
                ("turn_off", "switch.east_open"),
                ("turn_off", "switch.east_close"),
                ("turn_off", "switch.east_open"),
                ("turn_off", "switch.east_close"),
                ("turn_on", "switch.east_close"),
            ],
        )

    async def test_stop_during_dead_time_cancels_delayed_direction_start(self):
        self.cover._reverse_dead_time = 0.02
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = lambda: None
        open_task = asyncio.create_task(self.cover.async_open_cover())
        await asyncio.sleep(0)
        stop_task = asyncio.create_task(self.cover.async_stop_cover())
        await asyncio.gather(open_task, stop_task)

        self.assertNotIn("turn_on", [item.args[1] for item in self.services.async_call.await_args_list])
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_close",
            ],
        )

    async def test_direction_rechecks_both_relays_after_dead_time(self):
        self.cover._reverse_dead_time = 0.001
        await self.cover.async_open_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            [
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
                "switch.east_close",
                "switch.east_open",
            ],
        )

    async def test_conflict_fail_safe_attempts_both_switches(self):
        self.cover._conflict_stop_pending = True
        await self.cover._async_fail_safe_stop()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )
        self.assertFalse(self.cover._conflict_stop_pending)

    async def test_startup_always_stops_both_relays_even_when_states_are_missing(self):
        self.states.clear()
        await self.cover._async_stop_active_relays_on_startup()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_unload_always_stops_both_and_cancels_conflict_task(self):
        self.states.clear()
        pending = asyncio.create_task(asyncio.sleep(60))
        auto_stop = asyncio.create_task(asyncio.sleep(60))
        self.cover._conflict_stop_task = pending
        self.cover._auto_stop_task = auto_stop
        with patch(
            "homeassistant.helpers.entity.Entity.async_will_remove_from_hass",
            new=AsyncMock(),
        ):
            await self.cover.async_will_remove_from_hass()
        self.assertTrue(pending.cancelled())
        self.assertTrue(auto_stop.cancelled())
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_cancelled_queued_direction_fail_safe_stops_invalidated_command(self):
        self.cover._auto_stop_at_travel_end = True
        turn_on_started = asyncio.Event()
        release_turn_on = asyncio.Event()

        async def apply_state(_domain, service, data, **_kwargs):
            entity_id = data["entity_id"]
            if service == "turn_on":
                self.states[entity_id].state = "on"
                turn_on_started.set()
                await release_turn_on.wait()
            else:
                self.states[entity_id].state = "off"

        self.services.async_call.side_effect = apply_state
        active_command = asyncio.create_task(self.cover.async_open_cover())
        await turn_on_started.wait()
        queued_command = asyncio.create_task(self.cover.async_close_cover())
        await asyncio.sleep(0)
        queued_command.cancel()
        release_turn_on.set()

        with self.assertRaises(asyncio.CancelledError):
            await queued_command
        await active_command

        self.assertEqual(self.states["switch.east_open"].state, "off")
        self.assertEqual(self.states["switch.east_close"].state, "off")
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_repeated_cancellation_cannot_interrupt_direction_cleanup(self):
        self.cover._auto_stop_at_travel_end = True
        turn_on_started = asyncio.Event()
        release_turn_on = asyncio.Event()

        async def apply_state(_domain, service, data, **_kwargs):
            entity_id = data["entity_id"]
            if service == "turn_on":
                self.states[entity_id].state = "on"
                turn_on_started.set()
                await release_turn_on.wait()
            else:
                self.states[entity_id].state = "off"

        self.services.async_call.side_effect = apply_state
        active_command = asyncio.create_task(self.cover.async_open_cover())
        await turn_on_started.wait()
        queued_command = asyncio.create_task(self.cover.async_close_cover())
        await asyncio.sleep(0)
        queued_command.cancel()
        await asyncio.sleep(0)
        queued_command.cancel()
        release_turn_on.set()

        with self.assertRaises(asyncio.CancelledError):
            await queued_command
        await active_command

        self.assertEqual(self.states["switch.east_open"].state, "off")
        self.assertEqual(self.states["switch.east_close"].state, "off")
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_cancelled_queued_stop_fail_safe_stops_invalidated_command(self):
        self.cover._auto_stop_at_travel_end = True
        turn_on_started = asyncio.Event()
        release_turn_on = asyncio.Event()

        async def apply_state(_domain, service, data, **_kwargs):
            entity_id = data["entity_id"]
            if service == "turn_on":
                self.states[entity_id].state = "on"
                turn_on_started.set()
                await release_turn_on.wait()
            else:
                self.states[entity_id].state = "off"

        self.services.async_call.side_effect = apply_state
        active_command = asyncio.create_task(self.cover.async_open_cover())
        await turn_on_started.wait()
        queued_stop = asyncio.create_task(self.cover.async_stop_cover())
        await asyncio.sleep(0)
        queued_stop.cancel()
        release_turn_on.set()

        with self.assertRaises(asyncio.CancelledError):
            await queued_stop
        await active_command

        self.assertEqual(self.states["switch.east_open"].state, "off")
        self.assertEqual(self.states["switch.east_close"].state, "off")
        self.assertIsNone(self.cover._auto_stop_task)

    async def test_cancelled_unload_still_waits_to_deenergize_both_relays(self):
        self.states["switch.east_open"].state = "on"

        async def apply_state(_domain, _service, data, **_kwargs):
            self.states[data["entity_id"]].state = "off"

        self.services.async_call.side_effect = apply_state

        await self.cover._command_lock.acquire()
        with patch.object(
            UninusGreenhouseRollupCover.__mro__[1],
            "async_will_remove_from_hass",
            new=AsyncMock(),
        ):
            unload_task = asyncio.create_task(
                self.cover.async_will_remove_from_hass()
            )
            await asyncio.sleep(0)
            unload_task.cancel()
            await asyncio.sleep(0)
            unload_task.cancel()
            self.cover._command_lock.release()

            with self.assertRaises(asyncio.CancelledError):
                await unload_task

        self.assertEqual(self.states["switch.east_open"].state, "off")
        self.assertEqual(self.states["switch.east_close"].state, "off")
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

    async def test_queued_direction_cannot_restart_relays_during_unload(self):
        self.cover._auto_stop_at_travel_end = True
        await self.cover._command_lock.acquire()

        with patch(
            "homeassistant.helpers.entity.Entity.async_will_remove_from_hass",
            new=AsyncMock(),
        ):
            unload_task = asyncio.create_task(self.cover.async_will_remove_from_hass())
            await asyncio.sleep(0)
            open_task = asyncio.create_task(self.cover.async_open_cover())
            await asyncio.sleep(0)
            self.cover._command_lock.release()
            await asyncio.gather(open_task, unload_task)

        leftover_timer = self.cover._auto_stop_task
        if leftover_timer is not None:
            leftover_timer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await leftover_timer

        self.assertNotIn(
            "turn_on",
            [item.args[1] for item in self.services.async_call.await_args_list],
        )
        self.assertIsNone(self.cover._auto_stop_task)

    def test_unavailable_transition_freezes_estimate_at_loss_time(self):
        self.cover._estimator.position = 0
        self.cover._estimator.sync(open_on=True, close_on=False, now=0)
        self.cover._relays_available = True
        self.states["switch.east_open"].state = "unavailable"
        with patch.object(cover_module.time, "monotonic", return_value=10):
            self.cover._sync_from_switches()
        self.assertAlmostEqual(self.cover._estimator.position, 10)
        self.assertEqual(self.cover._estimator.command_state, "idle")

        self.states["switch.east_open"].state = "off"
        with patch.object(cover_module.time, "monotonic", return_value=100):
            self.cover._sync_from_switches()
        self.assertAlmostEqual(self.cover._estimator.position, 10)

    def test_tick_recovers_when_sources_appear_after_startup_without_an_event(self):
        self.cover._relays_available = False
        self.cover.async_write_ha_state = Mock()

        with patch.object(cover_module.time, "monotonic", return_value=10):
            self.cover._handle_tick(None)

        self.assertTrue(self.cover._relays_available)
        self.cover.async_write_ha_state.assert_called_once_with()


if __name__ == "__main__":
    import unittest

    unittest.main()
