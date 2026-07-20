"""Tests for runtime relay ownership enforcement and entry lifecycle."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

try:
    from homeassistant.exceptions import ConfigEntryError

    from custom_components.uninus_greenhouse_rollup import (
        _claim_relay_ownership,
        _release_relay_ownership,
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.uninus_greenhouse_rollup.const import DOMAIN
except ModuleNotFoundError as error:
    if error.name and error.name.startswith("homeassistant"):
        ConfigEntryError = None
        _claim_relay_ownership = None
        _release_relay_ownership = None
        async_setup_entry = None
        async_unload_entry = None
        DOMAIN = "uninus_greenhouse_rollup"
    else:
        raise


@unittest.skipIf(_claim_relay_ownership is None, "Home Assistant test dependency not installed")
class RuntimeOwnershipTest(unittest.TestCase):
    def test_shared_relay_is_rejected_and_release_is_owner_scoped(self):
        owners: dict[str, str] = {}
        self.assertTrue(
            _claim_relay_ownership(owners, "entry-a", "switch.open_a", "switch.shared")
        )
        self.assertFalse(
            _claim_relay_ownership(owners, "entry-b", "switch.shared", "switch.close_b")
        )
        self.assertEqual(
            owners,
            {"switch.open_a": "entry-a", "switch.shared": "entry-a"},
        )

        _release_relay_ownership(owners, "entry-b")
        self.assertEqual(len(owners), 2)
        _release_relay_ownership(owners, "entry-a")
        self.assertEqual(owners, {})

    def test_claim_is_idempotent_for_same_entry(self):
        owners: dict[str, str] = {}
        self.assertTrue(_claim_relay_ownership(owners, "entry-a", "switch.a", "switch.b"))
        self.assertTrue(_claim_relay_ownership(owners, "entry-a", "switch.a", "switch.b"))


@unittest.skipIf(async_setup_entry is None, "Home Assistant test dependency not installed")
class RuntimeOwnershipLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def _entry(self, entry_id: str, open_entity: str, close_entity: str):
        return SimpleNamespace(
            entry_id=entry_id,
            data={"open_entity": open_entity, "close_entity": close_entity},
            options={},
        )

    def _hass(self):
        return SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            ),
        )

    async def test_setup_rejects_shared_relay_and_unload_releases_claim(self):
        hass = self._hass()
        first = self._entry("entry-a", "switch.open_a", "switch.shared")
        second = self._entry("entry-b", "switch.shared", "switch.close_b")

        self.assertTrue(await async_setup_entry(hass, first))
        with self.assertRaises(ConfigEntryError):
            await async_setup_entry(hass, second)
        self.assertEqual(hass.config_entries.async_forward_entry_setups.await_count, 1)

        self.assertTrue(await async_unload_entry(hass, first))
        self.assertEqual(hass.data[DOMAIN]["relay_owners"], {})
        self.assertTrue(await async_setup_entry(hass, second))

    async def test_failed_setup_rolls_back_claim(self):
        hass = self._hass()
        hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("boom")
        entry = self._entry("entry-a", "switch.open", "switch.close")
        with self.assertRaises(RuntimeError):
            await async_setup_entry(hass, entry)
        self.assertEqual(hass.data[DOMAIN]["relay_owners"], {})

if __name__ == "__main__":
    unittest.main()
