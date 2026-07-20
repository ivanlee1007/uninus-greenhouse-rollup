from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase, skipIf
from unittest.mock import AsyncMock

try:
    from custom_components.uninus_greenhouse_rollup.config_flow import (
        RollupOptionsFlow,
        UninusGreenhouseRollupConfigFlow,
        _pair_unique_id,
        _switches_in_use,
    )
except (ModuleNotFoundError, ImportError) as error:
    if (
        isinstance(error, ModuleNotFoundError)
        and error.name
        and (error.name.startswith("homeassistant") or error.name == "voluptuous")
    ):
        _pair_unique_id = None
        _switches_in_use = None
        UninusGreenhouseRollupConfigFlow = None
        RollupOptionsFlow = None
    elif isinstance(error, ImportError):
        raise
    else:
        raise


@skipIf(_pair_unique_id is None, "Home Assistant test dependency not installed")
class ConfigFlowHelperTest(TestCase):
    def test_pair_identity_is_independent_of_direction_order(self):
        self.assertEqual(
            _pair_unique_id("switch.a", "switch.b"),
            _pair_unique_id("switch.b", "switch.a"),
        )

    def test_any_reused_source_switch_is_rejected(self):
        entries = [
            SimpleNamespace(
                entry_id="existing",
                data={"open_entity": "switch.a", "close_entity": "switch.b"},
                options={},
            )
        ]
        self.assertTrue(_switches_in_use(entries, "switch.c", "switch.a"))
        self.assertTrue(_switches_in_use(entries, "switch.b", "switch.a"))
        self.assertFalse(_switches_in_use(entries, "switch.c", "switch.d"))

    def test_reconfigure_excludes_the_entry_being_edited(self):
        entries = [
            SimpleNamespace(
                entry_id="current",
                data={"open_entity": "switch.a", "close_entity": "switch.b"},
                options={},
            ),
            SimpleNamespace(
                entry_id="other",
                data={"open_entity": "switch.c", "close_entity": "switch.d"},
                options={},
            ),
        ]

        self.assertFalse(
            _switches_in_use(
                entries,
                "switch.a",
                "switch.b",
                exclude_entry_id="current",
            )
        )
        self.assertTrue(
            _switches_in_use(
                entries,
                "switch.a",
                "switch.c",
                exclude_entry_id="current",
            )
        )


@skipIf(UninusGreenhouseRollupConfigFlow is None, "Home Assistant test dependency not installed")
class ReconfigureFlowTest(IsolatedAsyncioTestCase):
    async def test_user_step_opens_the_legacy_switch_form_directly(self):
        flow = UninusGreenhouseRollupConfigFlow()

        result = await flow.async_step_user()

        self.assertEqual(result["type"].value, "form")
        self.assertEqual(result["step_id"], "legacy_switch_pair")

    async def test_native_support_entry_has_no_relay_reconfigure_form(self):
        entry = SimpleNamespace(
            entry_id="native-support",
            data={"actuator_mode": "native_cover"},
            options={},
        )
        flow = UninusGreenhouseRollupConfigFlow()
        flow._get_reconfigure_entry = lambda: entry

        result = await flow.async_step_reconfigure()

        self.assertEqual(result["type"].value, "abort")
        self.assertEqual(result["reason"], "native_cover_no_settings")

    async def test_native_support_entry_has_no_timing_options_form(self):
        entry = SimpleNamespace(
            data={"actuator_mode": "native_cover"},
            options={},
        )
        flow = RollupOptionsFlow()
        flow.handler = "native-support"
        flow.hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_get_known_entry=lambda _entry_id: entry,
            )
        )

        result = await flow.async_step_init()

        self.assertEqual(result["type"].value, "abort")
        self.assertEqual(result["reason"], "native_cover_no_settings")

    async def test_reconfigure_updates_identity_sources_and_timings_in_one_flow(self):
        entry = SimpleNamespace(
            entry_id="current",
            title="Old rollup",
            data={
                "name": "Old rollup",
                "open_entity": "switch.old_open",
                "close_entity": "switch.old_close",
                "open_travel_time": 120,
                "close_travel_time": 120,
                "reverse_dead_time": 0.2,
            },
            options={"open_travel_time": 90},
        )
        flow = UninusGreenhouseRollupConfigFlow()
        flow._get_reconfigure_entry = lambda: entry
        flow._async_current_entries = lambda: [entry]
        captured = {}

        def update_reload(updated_entry, **kwargs):
            captured.update(entry=updated_entry, **kwargs)
            return {"type": "abort", "reason": "reconfigure_successful"}

        flow.async_update_reload_and_abort = update_reload
        user_input = {
            "name": "East rollup",
            "open_entity": "switch.new_open",
            "close_entity": "switch.new_close",
            "open_travel_time": 130,
            "close_travel_time": 140,
            "reverse_dead_time": 0.5,
        }

        result = await flow.async_step_reconfigure(user_input)

        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertIs(captured["entry"], entry)
        self.assertEqual(captured["title"], "East rollup")
        self.assertEqual(captured["unique_id"], "switch.new_close::switch.new_open")
        self.assertEqual(
            captured["data"],
            {**user_input, "actuator_mode": "dual_switch"},
        )
        self.assertEqual(captured["options"], {})


if __name__ == "__main__":
    import unittest

    unittest.main()
