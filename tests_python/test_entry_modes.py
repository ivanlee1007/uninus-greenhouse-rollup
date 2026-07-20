"""Tests for native MQTT Cover support and legacy entry migration."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

try:
    from custom_components.uninus_greenhouse_rollup import (
        async_migrate_entry,
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.uninus_greenhouse_rollup.const import (
        ACTUATOR_MODE_DUAL_SWITCH,
        ACTUATOR_MODE_NATIVE_COVER,
        CONF_ACTUATOR_MODE,
        DOMAIN,
    )
except (ModuleNotFoundError, ImportError) as error:
    if isinstance(error, ModuleNotFoundError) and error.name and error.name.startswith("homeassistant"):
        async_migrate_entry = None
        async_setup_entry = None
        async_unload_entry = None
        ACTUATOR_MODE_DUAL_SWITCH = "dual_switch"
        ACTUATOR_MODE_NATIVE_COVER = "native_cover"
        CONF_ACTUATOR_MODE = "actuator_mode"
        DOMAIN = "uninus_greenhouse_rollup"
    else:
        raise


@unittest.skipIf(async_setup_entry is None, "Home Assistant test dependency not installed")
class EntryModeLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def _hass(self):
        return SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
                async_update_entry=Mock(),
            ),
        )

    async def test_existing_native_cover_support_entry_remains_a_compatible_no_op(self):
        hass = self._hass()
        entry = SimpleNamespace(
            entry_id="native-support",
            data={CONF_ACTUATOR_MODE: ACTUATOR_MODE_NATIVE_COVER},
            options={},
        )

        self.assertTrue(await async_setup_entry(hass, entry))

        hass.config_entries.async_forward_entry_setups.assert_not_awaited()
        self.assertEqual(hass.data[DOMAIN]["relay_owners"], {})
        self.assertTrue(await async_unload_entry(hass, entry))
        hass.config_entries.async_unload_platforms.assert_not_awaited()

    async def test_legacy_entry_without_mode_remains_a_dual_switch_adapter(self):
        hass = self._hass()
        entry = SimpleNamespace(
            entry_id="legacy",
            data={
                "open_entity": "switch.open",
                "close_entity": "switch.close",
            },
            options={},
        )

        self.assertTrue(await async_setup_entry(hass, entry))

        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        self.assertEqual(
            hass.data[DOMAIN]["relay_owners"],
            {"switch.open": "legacy", "switch.close": "legacy"},
        )

    async def test_version_one_entry_migrates_to_explicit_dual_switch_mode(self):
        hass = self._hass()
        entry = SimpleNamespace(
            version=1,
            minor_version=1,
            data={
                "name": "East",
                "open_entity": "switch.open",
                "close_entity": "switch.close",
            },
        )

        self.assertTrue(await async_migrate_entry(hass, entry))

        hass.config_entries.async_update_entry.assert_called_once()
        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["version"], 2)
        self.assertEqual(kwargs["data"][CONF_ACTUATOR_MODE], ACTUATOR_MODE_DUAL_SWITCH)
        self.assertEqual(kwargs["data"]["open_entity"], "switch.open")


if __name__ == "__main__":
    unittest.main()
