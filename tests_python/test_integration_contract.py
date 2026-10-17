import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "uninus_greenhouse_rollup"


class IntegrationContractTest(unittest.TestCase):
    def test_manifest_declares_config_flow_and_cover_integration(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "uninus_greenhouse_rollup")
        self.assertEqual(manifest["name"], "UNiNUS Greenhouse Cover Actuator")
        self.assertEqual(manifest["version"], "3.2.0")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["integration_type"], "service")
        self.assertEqual(manifest["iot_class"], "calculated")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")

        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(hacs["name"], manifest["name"])

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

    def test_auto_stop_at_travel_end_is_an_explicit_config_and_options_setting(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("CONF_AUTO_STOP_AT_TRAVEL_END", source)
        self.assertIn("DEFAULT_AUTO_STOP_AT_TRAVEL_END", source)

        for path in (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "zh-Hant.json",
        ):
            strings = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(
                "auto_stop_at_travel_end",
                strings["config"]["step"]["legacy_switch_pair"]["data"],
                path.name,
            )
            self.assertIn(
                "auto_stop_at_travel_end",
                strings["config"]["step"]["reconfigure"]["data"],
                path.name,
            )
            self.assertIn(
                "auto_stop_at_travel_end",
                strings["options"]["step"]["init"]["data"],
                path.name,
            )

    def test_auto_stop_service_metadata_and_translations_match_runtime_contract(self):
        import yaml
        service = "set_auto_stop_at_travel_end"
        definitions = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(definitions), {service})
        fields = definitions[service]["fields"]
        self.assertEqual(set(fields), {"entity_id", "enabled"})
        self.assertNotIn("target", definitions[service])
        self.assertTrue(fields["entity_id"]["required"])
        self.assertEqual(fields["entity_id"]["selector"]["entity"],
                         {"integration": "uninus_greenhouse_rollup", "domain": "cover", "multiple": True})
        self.assertTrue(fields["enabled"]["required"])
        self.assertIn("boolean", fields["enabled"]["selector"])
        for path in (INTEGRATION / "strings.json", *sorted((INTEGRATION / "translations").glob("*.json"))):
            strings = json.loads(path.read_text(encoding="utf-8"))
            translated = strings["services"][service]
            self.assertTrue(translated["name"])
            self.assertTrue(translated["description"])
            self.assertEqual(set(translated["fields"]), set(fields))
            for field in translated["fields"].values():
                self.assertTrue(field["name"])
                self.assertTrue(field["description"])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("uninus_greenhouse_rollup.set_auto_stop_at_travel_end", readme)
        self.assertIn("OptionsFlowWithReload", (INTEGRATION / "config_flow.py").read_text(encoding="utf-8"))

    def test_actuator_type_is_translated_in_every_shipped_language(self):
        for path in (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "zh-Hant.json",
        ):
            strings = json.loads(path.read_text(encoding="utf-8"))
            for step in ("legacy_switch_pair", "reconfigure"):
                self.assertIn(
                    "actuator_type",
                    strings["config"]["step"][step]["data"],
                    path.name,
                )
            self.assertIn(
                "actuator_type",
                strings["options"]["step"]["init"]["data"],
                path.name,
            )
            self.assertEqual(
                set(strings["selector"]["actuator_type"]["options"]),
                {"rollup", "skylight", "shade"},
                path.name,
            )

    def test_readme_defines_shade_open_and_close_semantics(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("開啟 = 收回", readme)
        self.assertIn("關閉 = 展開", readme)

    def test_config_flow_only_offers_the_legacy_switch_adapter(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        for marker in (
            "ACTUATOR_MODE_DUAL_SWITCH",
            "async_step_legacy_switch_pair",
            "VERSION = 3",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("async_step_native_cover", source)
        self.assertNotIn("async_show_menu", source)

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

    def test_integration_does_not_bundle_or_serve_the_card(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("async_register_static_paths", source)
        self.assertNotIn("uninus-greenhouse-rollup-card.js", source)
        self.assertFalse((INTEGRATION / "www").exists())

    def test_all_translations_describe_the_legacy_adapter(self):
        paths = [
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "zh-Hant.json",
        ]
        for path in paths:
            strings = json.loads(path.read_text(encoding="utf-8"))
            steps = strings["config"]["step"]
            self.assertNotIn("menu_options", steps["user"], path.name)
            self.assertNotIn("native_cover", steps, path.name)
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

    def test_readme_points_to_the_standalone_dashboard_card(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ivanlee1007/uninus-greenhouse-rollup-card", readme)
        self.assertIn("HACS 會自動加入卡片資源", readme)
        self.assertNotIn("/uninus-greenhouse-rollup/uninus-greenhouse-rollup-card.js?v=", readme)


if __name__ == "__main__":
    unittest.main()
