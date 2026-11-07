"""Regression tests for remembered positions independent of availability."""

from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipIf
from unittest.mock import AsyncMock, Mock, patch

try:
    from homeassistant.core import HomeAssistant, State
    from homeassistant.util import dt as dt_util
    from homeassistant.helpers import restore_state
    from custom_components.uninus_greenhouse_rollup import cover as cover_module
    from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover
except ModuleNotFoundError as error:
    if error.name and error.name.startswith("homeassistant"):
        UninusGreenhouseRollupCover = None
    else:
        raise


@skipIf(UninusGreenhouseRollupCover is None, "Home Assistant test dependency not installed")
class CoverRestoreTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hass = HomeAssistant(directory.name)
        self.addAsyncCleanup(self.hass.async_stop, force=True)
        from homeassistant import loader
        from homeassistant.config_entries import ConfigEntries
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        # Core 2026.11 restore aliases consult the loaded entity registry.
        from homeassistant.helpers import device_registry as dr, entity_registry as er
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.hass.states.async_set("switch.open", "off")
        self.hass.states.async_set("switch.close", "off")

    def make_cover(self, open_travel_time=100, close_travel_time=100):
        cover = UninusGreenhouseRollupCover(
            SimpleNamespace(entry_id="restore-test", title="Restore test"),
            {
                "open_entity": "switch.open",
                "close_entity": "switch.close",
                "open_travel_time": open_travel_time,
                "close_travel_time": close_travel_time,
                "reverse_dead_time": 0,
            },
        )
        cover.entity_id = "cover.restore_test"
        cover.hass = self.hass
        cover.async_on_remove = Mock()
        cover._async_stop_active_relays_on_startup = AsyncMock()
        return cover

    async def add_cover(self, cover):
        with patch.object(cover_module, "async_track_state_change_event"), patch.object(
            cover_module, "async_track_time_interval"
        ):
            await cover.async_added_to_hass()
        cover._async_stop_active_relays_on_startup.assert_awaited_once()

    def set_saved_state(self, cover, extra_data, attributes=None):
        saved = restore_state.async_get(self.hass)
        states = saved.last_states if hasattr(saved, 'last_states') else saved.last_states_by_entity_id
        states[cover.entity_id] = (
            restore_state.StoredState(
                State(cover.entity_id, "unavailable", attributes or {}),
                restore_state.RestoredExtraData(extra_data)
                if extra_data is not None else None,
                dt_util.utcnow(),
            )
        )

    async def test_corrupt_extra_data_stays_unknown_without_blocking_startup_stop(self):
        for snapshot in (
            {"position": 50, "confidence": []},
            {"position": 50, "confidence": {}},
            {"position": 10**400, "confidence": "estimated"},
            {"position": -1, "confidence": "estimated"},
            {"position": 101, "confidence": "estimated"},
            {"position": True, "confidence": "estimated"},
            {"position": "37", "confidence": "estimated"},
            {"position": float("nan"), "confidence": "estimated"},
            {"position": float("inf"), "confidence": "estimated"},
            {"position": 50, "confidence": "invalid"},
            [50, "estimated"],
            "corrupt",
        ):
            with self.subTest(snapshot=snapshot):
                cover = self.make_cover()
                self.set_saved_state(cover, snapshot, {
                    "current_position": 91, "position_confidence": "estimated",
                })
                await self.add_cover(cover)
                self.assertIsNone(cover.current_cover_position)
                self.assertEqual(cover._estimator.confidence, "unknown")

    async def test_extra_data_preserves_precision_and_overrides_legacy_attributes(self):
        for position, confidence in ((0, "calibrated"), (100, "calibrated"),
                                     (37.125, "estimated")):
            with self.subTest(position=position):
                cover = self.make_cover()
                self.set_saved_state(
                    cover, {"position": position, "confidence": confidence},
                    {"current_position": 91, "position_confidence": "estimated"},
                )
                await self.add_cover(cover)
                self.assertEqual(cover._estimator.position, position)
                self.assertEqual(cover._estimator.confidence, confidence)
                snapshot = cover.extra_restore_state_data
                self.assertEqual(snapshot.as_dict(), {
                    "position": position, "confidence": confidence,
                    "open_travel_time": 100, "close_travel_time": 100,
                })
                cover._estimator.position = 22
                self.assertEqual(snapshot.as_dict()["position"], position)

    async def test_unknown_extra_data_does_not_revive_stale_legacy_position(self):
        cover = self.make_cover()
        self.set_saved_state(
            cover, {"position": None, "confidence": "unknown"},
            {"current_position": 91, "position_confidence": "estimated"},
        )
        await self.add_cover(cover)
        self.assertIsNone(cover.current_cover_position)
        self.assertEqual(cover._estimator.confidence, "unknown")

    async def test_legacy_attributes_are_restored_when_extra_data_is_absent(self):
        cover = self.make_cover()
        self.set_saved_state(cover, None, {
            "current_position": 42, "position_confidence": "estimated",
        })
        await self.add_cover(cover)
        self.assertEqual(cover.current_cover_position, 42)
        self.assertEqual(cover.extra_restore_state_data.as_dict(), {
            "position": 42, "confidence": "estimated",
            "open_travel_time": 100, "close_travel_time": 100,
        })

    async def test_no_saved_position_remains_uncalibrated(self):
        cover = self.make_cover()
        await self.add_cover(cover)
        self.assertIsNone(cover.current_cover_position)
        self.assertEqual(cover._estimator.confidence, "unknown")

    async def test_legacy_restore_keeps_precise_unavailable_snapshot_but_never_motion(self):
        cover = self.make_cover()
        cover._feedback_mode = 'legacy_emos'
        self.hass.states.async_set('switch.open', 'unknown')
        self.hass.states.async_set('switch.close', 'unknown')
        self.set_saved_state(cover, {'position': 37.125, 'confidence': 'estimated',
            'open_travel_time': 100, 'close_travel_time': 100, 'motion_interrupted': True})
        await self.add_cover(cover)
        self.assertEqual(cover._estimator.position, 37.125)
        self.assertTrue(cover.available)
        self.assertEqual(cover.extra_state_attributes['position_basis'], 'remembered')
        self.assertTrue(cover.extra_state_attributes['position_unverified'])
        self.assertTrue(cover.extra_state_attributes['motion_interrupted'])
        self.assertEqual(cover._estimator.command_state, 'idle')
        self.assertIsNone(cover._auto_stop_task)
        self.hass.states.async_set('switch.open', 'unavailable')
        cover._sync_from_switches()
        self.assertFalse(cover.available)
        self.assertEqual(cover.extra_restore_state_data.as_dict()['position'], 37.125)

    async def test_restored_position_survives_unavailable_sources_until_recovery(self):
        for source in ("switch.open", "switch.close"):
            for value in ("unknown", "unavailable", None):
                with self.subTest(source=source, value=value):
                    self.hass.states.async_set("switch.open", "off")
                    self.hass.states.async_set("switch.close", "off")
                    if value is None:
                        self.hass.states.async_remove(source)
                    else:
                        self.hass.states.async_set(source, value)
                    cover = self.make_cover()
                    self.set_saved_state(cover, {
                        "position": 18.25, "confidence": "estimated",
                    })
                    await self.add_cover(cover)
                    self.assertFalse(cover.available)
                    self.assertEqual(cover._async_calculate_state().state, "unavailable")
                    self.assertEqual(cover._estimator.position, 18.25)
                    self.hass.states.async_set(source, "off")
                    cover._sync_from_switches()
                    self.assertTrue(cover.available)
                    self.assertEqual(cover._estimator.position, 18.25)

    async def test_native_entity_removal_retains_unavailable_position(self):
        cover = self.make_cover()
        cover._estimator.position = 63.75
        cover._estimator.confidence = "estimated"
        self.hass.states.async_set(cover.entity_id, "unavailable")
        saved = restore_state.async_get(self.hass)
        saved.async_restore_entity_added(cover)
        await cover.async_internal_will_remove_from_hass()
        self.assertNotIn(cover.entity_id, saved.entities)
        restored = self.make_cover()
        await self.add_cover(restored)
        self.assertEqual(restored._estimator.position, 63.75)
        self.assertEqual(restored._estimator.confidence, "estimated")

    async def test_changed_travel_time_does_not_revive_old_extra_position(self):
        old = self.make_cover()
        old._estimator.position = 37.5
        old._estimator.confidence = "estimated"
        snapshot = old.extra_restore_state_data.as_dict()
        for opening, closing in ((120, 100), (100, 120)):
            with self.subTest(opening=opening, closing=closing):
                cover = self.make_cover(opening, closing)
                self.set_saved_state(cover, snapshot)
                await self.add_cover(cover)
                self.assertIsNone(cover.current_cover_position)
                self.assertEqual(cover._estimator.confidence, "unknown")

    async def test_legacy_extra_position_is_invalid_after_authority_changes_seed_times(self):
        cover = self.make_cover()
        # ParameterManager loads new authority after construction from legacy seeds.
        cover._open_travel_time = 120
        self.set_saved_state(cover, {"position": 37.5, "confidence": "estimated"})
        await self.add_cover(cover)
        self.assertIsNone(cover.current_cover_position)
        self.assertEqual(cover._estimator.confidence, "unknown")

    async def test_matching_new_travel_model_restores_after_authority_replaces_seeds(self):
        old = self.make_cover(120, 100)
        old._estimator.position = 63.75
        old._estimator.confidence = "estimated"
        cover = self.make_cover()
        cover._open_travel_time = 120
        self.set_saved_state(cover, old.extra_restore_state_data.as_dict(), {
            "current_position": 91, "open_travel_time": 100, "close_travel_time": 100,
        })
        await self.add_cover(cover)
        self.assertEqual(cover._estimator.position, 63.75)
        self.assertEqual(cover._estimator.confidence, "estimated")

    async def test_partial_or_invalid_travel_metadata_never_restores_position(self):
        for timing in (
            {"open_travel_time": 100},
            {"open_travel_time": True, "close_travel_time": 100},
            {"open_travel_time": "100", "close_travel_time": 100},
            {"open_travel_time": float("nan"), "close_travel_time": 100},
        ):
            with self.subTest(timing=timing):
                cover = self.make_cover()
                self.set_saved_state(cover, {
                    "position": 37.5, "confidence": "estimated", **timing,
                })
                await self.add_cover(cover)
                self.assertIsNone(cover.current_cover_position)

    async def test_unavailable_position_survives_native_disk_save_and_reload(self):
        cover = self.make_cover()
        cover._estimator.position = 37.5
        cover._estimator.confidence = "estimated"
        self.hass.states.async_set("switch.open", "unavailable")
        cover._sync_from_switches()
        state = cover._async_calculate_state()
        self.assertEqual(state.state, "unavailable")
        self.assertNotIn("current_position", state.attributes)
        self.assertEqual(cover._estimator.position, 37.5)
        self.hass.states.async_set(cover.entity_id, state.state, state.attributes)
        saved = restore_state.async_get(self.hass)
        saved.async_restore_entity_added(cover)
        await saved.async_dump_states()

        # Reload from real HA storage, not mocked last-state attributes.
        await saved.async_load()
        self.hass.states.async_set("switch.open", "off")
        restored = self.make_cover()
        await self.add_cover(restored)
        self.assertEqual(restored._estimator.position, 37.5)
        self.assertEqual(restored._estimator.confidence, "estimated")
        self.assertTrue(restored.available)
        self.assertFalse(restored.is_opening)
        self.assertFalse(restored.is_closing)
        self.assertEqual(restored._estimator.command_state, "idle")
