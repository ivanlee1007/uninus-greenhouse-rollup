import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "uninus_greenhouse_rollup"


class IntegrationContractTest(unittest.TestCase):
    def test_manifest_declares_config_flow_and_cover_integration(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "uninus_greenhouse_rollup")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["integration_type"], "service")
        self.assertEqual(manifest["iot_class"], "calculated")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_config_flow_collects_two_switches_and_independent_travel_times(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        for marker in (
            "CONF_OPEN_ENTITY",
            "CONF_CLOSE_ENTITY",
            "CONF_OPEN_TRAVEL_TIME",
            "CONF_CLOSE_TRAVEL_TIME",
            "CONF_REVERSE_DEAD_TIME",
            "selector.EntitySelector",
            'domain=["switch"]',
        ):
            self.assertIn(marker, source)

    def test_config_flow_supports_native_cover_frontend_and_legacy_adapter_modes(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        for marker in (
            "ACTUATOR_MODE_NATIVE_COVER",
            "ACTUATOR_MODE_DUAL_SWITCH",
            "async_step_native_cover",
            "async_step_legacy_switch_pair",
            "VERSION = 2",
        ):
            self.assertIn(marker, source)

    def test_cover_uses_restore_entity_interlock_and_timed_updates(self):
        source = (INTEGRATION / "cover.py").read_text(encoding="utf-8")
        for marker in (
            "CoverEntity",
            "RestoreEntity",
            "async_track_state_change_event",
            "async_track_time_interval",
            "SERVICE_TURN_OFF",
            "SERVICE_TURN_ON",
            "async_open_cover",
            "async_close_cover",
            "async_stop_cover",
            "position_confidence",
            "command_state",
            "asyncio.Lock",
            "_async_turn_both_off",
        ):
            self.assertIn(marker, source)

    def test_integration_serves_the_bundled_card(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("async_register_static_paths", source)
        self.assertIn("uninus-greenhouse-rollup-card.js", source)
        self.assertTrue((INTEGRATION / "www" / "uninus-greenhouse-rollup-card.js").is_file())

    def test_all_translations_describe_both_hardware_paths(self):
        paths = [
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "zh-Hant.json",
        ]
        for path in paths:
            strings = json.loads(path.read_text(encoding="utf-8"))
            steps = strings["config"]["step"]
            self.assertEqual(
                set(steps["user"]["menu_options"]),
                {"native_cover", "legacy_switch_pair"},
                path.name,
            )
            self.assertIn("native_cover", steps, path.name)
            self.assertIn("legacy_switch_pair", steps, path.name)
            self.assertIn(
                "native_cover_no_settings",
                strings["config"]["abort"],
                path.name,
            )

    def test_hacs_repository_is_an_integration_not_dashboard_only(self):
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertNotIn("filename", hacs)
        self.assertTrue((INTEGRATION / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
