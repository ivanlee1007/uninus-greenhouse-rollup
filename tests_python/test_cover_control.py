import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import AsyncMock, call, patch

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
        self.cover.hass = SimpleNamespace(services=self.services, states=self.states)
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

    async def test_stop_attempts_both_direction_switches(self):
        self.cover._sync_from_switches = lambda: None
        self.cover.async_write_ha_state = lambda: None
        await self.cover.async_stop_cover()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

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

    async def test_startup_with_an_active_relay_stops_both_before_sync(self):
        self.states["switch.east_open"].state = "on"
        await self.cover._async_stop_active_relays_on_startup()
        self.assertEqual(
            self._ids(self.services.async_call.await_args_list),
            ["switch.east_open", "switch.east_close"],
        )

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


if __name__ == "__main__":
    import unittest

    unittest.main()
