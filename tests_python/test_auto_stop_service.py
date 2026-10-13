"""Card-editable auto-stop service behavior and safety regressions."""

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from homeassistant.core import Context, ServiceCall

import custom_components.uninus_greenhouse_rollup as integration
from custom_components.uninus_greenhouse_rollup.const import DOMAIN
from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover


class AutoStopServiceTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.entries = []
        self.covers = {}
        self.states = {}
        self.hass = SimpleNamespace(
            data={DOMAIN: {"covers": self.covers, "relay_owners": {}}},
            states=self.states,
            services=SimpleNamespace(async_call=AsyncMock(), async_register=Mock()),
            config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=self.update)),
            auth=SimpleNamespace(async_get_user=AsyncMock()),
            async_create_task=asyncio.create_task,
        )
        self.cover = self.add_cover("east")

    def update(self, entry, *, options):
        entry.options = options
        return True

    def add_cover(self, name):
        entry = SimpleNamespace(
            entry_id=name, title=name, domain=DOMAIN,
            data={"open_entity": f"switch.{name}_open", "close_entity": f"switch.{name}_close",
                  "open_travel_time": 100, "close_travel_time": 110, "reverse_dead_time": 0},
            options={"open_travel_time": 90, "unrelated": "preserved"},
        )
        self.entries.append(entry)
        cover = UninusGreenhouseRollupCover(entry, {**entry.data, **entry.options})
        cover.entity_id = f"cover.{name}"
        cover.hass = self.hass
        cover.async_write_ha_state = Mock()
        self.covers[entry.entry_id] = cover
        self.states[cover.entity_id] = SimpleNamespace(state="open")
        for relay in (cover._open_entity, cover._close_entity):
            self.states[relay] = SimpleNamespace(state="off")
            self.hass.data[DOMAIN]["relay_owners"][relay] = entry.entry_id
        cover._sync_from_switches()
        return cover

    async def call(self, targets="cover.east", enabled=True, user_id=None, response=False):
        self.assertTrue(hasattr(integration, "async_setup"), "Integration service setup is missing")
        await integration.async_setup(self.hass, {})
        args = self.hass.services.async_register.call_args
        self.assertEqual(args.args[:2], (DOMAIN, "set_auto_stop_at_travel_end"))
        data = args.kwargs["schema"]({"entity_id": targets, "enabled": enabled})
        call = ServiceCall(self.hass, DOMAIN, "set_auto_stop_at_travel_end", data,
                           context=Context(user_id=user_id), return_response=response)
        return await args.args[2](call)

    def test_setup_declares_config_entry_only_yaml_schema(self):
        self.assertTrue(callable(getattr(integration, "CONFIG_SCHEMA", None)))
        config = {"other_integration": {"example": True}}
        self.assertEqual(integration.CONFIG_SCHEMA(config), config)

    async def test_batch_dedupes_and_validates_ownership_before_any_write(self):
        second = self.add_cover("west")
        result = await self.call(["cover.east", "cover.west", "cover.east"])
        self.assertEqual(result["updated"], ["cover.east", "cover.west"])
        self.assertEqual(self.hass.config_entries.async_update_entry.call_count, 2)
        for mutation in ("missing", "wrong_domain", "native", "lost_relay", "wrong_mapping"):
            with self.subTest(mutation=mutation):
                self.hass.config_entries.async_update_entry.reset_mock()
                original_data = dict(second._entry.data)
                original_domain = second._entry.domain
                owners = dict(self.hass.data[DOMAIN]["relay_owners"])
                target = "cover.west"
                if mutation == "missing":
                    target = "cover.external"
                elif mutation == "wrong_domain":
                    second._entry.domain = "other"
                elif mutation == "native":
                    second._entry.data["actuator_mode"] = "native_cover"
                elif mutation == "lost_relay":
                    self.hass.data[DOMAIN]["relay_owners"][second._open_entity] = "other"
                else:
                    second._entry.data["open_entity"] = "switch.reconfigured"
                from homeassistant.exceptions import ServiceValidationError
                with self.assertRaises(ServiceValidationError):
                    await self.call(["cover.east", target], False)
                self.hass.config_entries.async_update_entry.assert_not_called()
                second._entry.data = original_data
                second._entry.domain = original_domain
                self.hass.data[DOMAIN]["relay_owners"] = owners

    async def test_permissions_checked_for_every_target_before_writes(self):
        from homeassistant.exceptions import Unauthorized, UnknownUser
        self.add_cover("west")
        check = Mock(side_effect=lambda entity, policy: entity == "cover.east" and policy == "control")
        user = SimpleNamespace(is_active=True, permissions=SimpleNamespace(check_entity=check))
        self.hass.auth.async_get_user.return_value = user
        with self.assertRaises(Unauthorized):
            await self.call(["cover.east", "cover.west"], user_id="restricted")
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.assertEqual(check.call_count, 2)
        self.hass.auth.async_get_user.return_value = None
        with self.assertRaises(UnknownUser):
            await self.call(user_id="deleted")
        user.is_active = False
        self.hass.auth.async_get_user.return_value = user
        with self.assertRaises(Unauthorized):
            await self.call(user_id="inactive")
        self.hass.config_entries.async_update_entry.assert_not_called()
        user.is_active = True
        check.side_effect = None
        check.return_value = True
        await self.call(user_id="allowed")
        self.assertTrue(self.cover._auto_stop_at_travel_end)

    async def test_schema_rejects_non_boolean_values_and_non_cover_targets(self):
        import voluptuous as vol
        for enabled in (1, 0, "true", "false", None, [], {}):
            with self.subTest(enabled=enabled), self.assertRaises(vol.Invalid):
                await self.call(enabled=enabled)
        for targets in ([], "", "all", "switch.open", "cover.East", "cover.east,cover.west",
                        "cover.east\n", ["cover.east", None], 1, ("cover.east",)):
            with self.subTest(targets=targets), self.assertRaises(vol.Invalid):
                await self.call(targets=targets)
        self.hass.config_entries.async_update_entry.assert_not_called()

    async def test_idle_gate_rejects_active_unavailable_pending_and_removing(self):
        from homeassistant.exceptions import ServiceValidationError
        self.add_cover("west")
        for condition in ("on", "unknown", "unavailable", "missing", "cover_unavailable",
                          "not_available", "lock", "removing", "timer", "conflict"):
            with self.subTest(condition=condition):
                self.hass.config_entries.async_update_entry.reset_mock()
                relay = self.states.get(self.cover._open_entity)
                if condition in ("on", "unknown", "unavailable"):
                    relay.state = condition
                elif condition == "missing":
                    self.states.pop(self.cover._open_entity)
                elif condition == "cover_unavailable":
                    self.states[self.cover.entity_id].state = "unavailable"
                elif condition == "not_available":
                    self.cover._relays_available = False
                elif condition == "lock":
                    await self.cover._command_lock.acquire()
                elif condition == "removing":
                    self.cover._removing = True
                elif condition == "conflict":
                    self.cover._conflict_stop_pending = True
                else:
                    self.cover._auto_stop_task = asyncio.create_task(asyncio.sleep(60))
                with self.assertRaises(ServiceValidationError):
                    await self.call(["cover.west", "cover.east"])
                self.hass.config_entries.async_update_entry.assert_not_called()
                self.assertFalse(self.cover._auto_stop_at_travel_end)
                if self.cover._auto_stop_task is not None:
                    self.cover._auto_stop_task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await self.cover._auto_stop_task
                    self.cover._auto_stop_task = None
                if self.cover._command_lock.locked():
                    self.cover._command_lock.release()
                relay.state = "off"
                self.states[self.cover._open_entity] = relay
                self.states[self.cover.entity_id].state = "open"
                self.cover._relays_available = True
                self.cover._removing = False
                self.cover._conflict_stop_pending = False
        self.hass.services.async_call.assert_not_awaited()

    async def test_released_lock_with_queued_direction_still_rejects_setting(self):
        from homeassistant.exceptions import ServiceValidationError
        await self.cover._command_lock.acquire()
        direction = asyncio.create_task(self.cover.async_open_cover())
        await asyncio.sleep(0)
        self.cover._command_lock.release()
        try:
            with self.assertRaises(ServiceValidationError):
                await self.call()
            self.hass.config_entries.async_update_entry.assert_not_called()
        finally:
            await direction
        self.assertEqual(self.cover._pending_direction_commands, 0)

    async def test_entity_lifecycle_registers_only_after_safe_startup_and_removes_exact_instance(self):
        from unittest.mock import patch
        self.covers.clear()
        self.cover.async_get_last_state = AsyncMock(return_value=None)
        self.cover.async_on_remove = Mock()
        with patch("homeassistant.components.cover.CoverEntity.async_added_to_hass", new=AsyncMock()), \
             patch("custom_components.uninus_greenhouse_rollup.cover.async_track_state_change_event"), \
             patch("custom_components.uninus_greenhouse_rollup.cover.async_track_time_interval"):
            await self.cover.async_added_to_hass()
        self.assertIs(self.covers.get("east"), self.cover)
        self.hass.services.async_call.reset_mock()
        await self.call()
        self.assertTrue(self.cover._auto_stop_at_travel_end)
        replacement = self.add_cover("east")
        with patch("homeassistant.components.cover.CoverEntity.async_will_remove_from_hass", new=AsyncMock()):
            await self.cover.async_will_remove_from_hass()
            self.assertIs(self.covers["east"], replacement)
            await replacement.async_will_remove_from_hass()
        self.assertNotIn("east", self.covers)

    async def test_service_changes_apply_to_next_command_and_never_mutate_active_timer(self):
        from homeassistant.exceptions import ServiceValidationError
        await self.call(enabled=True)
        self.assertIsNone(self.cover._auto_stop_task)
        await self.cover.async_open_cover()
        timer = self.cover._auto_stop_task
        self.assertIsNotNone(timer)
        with self.assertRaises(ServiceValidationError):
            await self.call(enabled=False)
        self.assertIs(self.cover._auto_stop_task, timer)
        self.assertTrue(self.cover._auto_stop_at_travel_end)
        await self.cover.async_stop_cover()
        with self.assertRaises(asyncio.CancelledError):
            await timer
        self.hass.services.async_call.reset_mock()
        await self.call(enabled=False)
        self.hass.services.async_call.assert_not_awaited()
        await self.cover.async_close_cover()
        self.assertIsNone(self.cover._auto_stop_task)
        self.assertFalse(self.cover.extra_state_attributes["auto_stop_at_travel_end"])

    async def test_permission_lookup_yield_rechecks_current_registry_and_hardware(self):
        from homeassistant.exceptions import ServiceValidationError
        user = SimpleNamespace(is_active=True, permissions=SimpleNamespace(check_entity=Mock(return_value=True)))

        async def lookup(user_id):
            await asyncio.sleep(0)
            self.hass.data[DOMAIN] = {"covers": {}, "relay_owners": {}}
            return user

        self.hass.auth.async_get_user.side_effect = lookup
        with self.assertRaises(ServiceValidationError):
            await self.call(user_id="allowed")
        self.hass.config_entries.async_update_entry.assert_not_called()

    async def test_idempotent_boolean_readback_false_update_result_is_success(self):
        await self.call(enabled=True)
        self.hass.config_entries.async_update_entry.side_effect = None
        self.hass.config_entries.async_update_entry.return_value = False
        result = await self.call(enabled=True)
        self.assertEqual(result, {"updated": ["cover.east"], "enabled": True})

    async def test_settings_hold_all_batch_command_locks_during_persistence(self):
        second = self.add_cover("west")

        def update(entry, *, options):
            self.assertTrue(self.cover._command_lock.locked())
            self.assertTrue(second._command_lock.locked())
            return self.update(entry, options=options)

        self.hass.config_entries.async_update_entry.side_effect = update
        await self.call(["cover.east", "cover.west"])
        self.assertFalse(self.cover._command_lock.locked())
        self.assertFalse(second._command_lock.locked())

    async def test_rejects_impostor_in_runtime_cover_registry(self):
        from homeassistant.exceptions import ServiceValidationError
        self.covers["east"] = SimpleNamespace(**self.cover.__dict__)
        self.covers["east"].validate_auto_stop_change = Mock()
        with self.assertRaises(ServiceValidationError):
            await self.call()
        self.hass.config_entries.async_update_entry.assert_not_called()

    async def test_released_lock_with_queued_stop_still_rejects_setting(self):
        from homeassistant.exceptions import ServiceValidationError
        await self.cover._command_lock.acquire()
        stop = asyncio.create_task(self.cover.async_stop_cover())
        await asyncio.sleep(0)
        self.cover._command_lock.release()
        try:
            with self.assertRaises(ServiceValidationError):
                await self.call()
            self.hass.config_entries.async_update_entry.assert_not_called()
        finally:
            await stop
        self.assertEqual(self.cover._pending_stop_commands, 0)

    async def test_persistence_failure_reports_exact_partial_update_and_releases_locks(self):
        from homeassistant.exceptions import ServiceValidationError
        second = self.add_cover("west")

        def update(entry, *, options):
            if entry is second._entry:
                raise RuntimeError("write failed")
            return self.update(entry, options=options)

        self.hass.config_entries.async_update_entry.side_effect = update
        with self.assertRaisesRegex(ServiceValidationError, "cover.west.*cover.east"):
            await self.call(["cover.east", "cover.west"])
        self.assertTrue(self.cover._auto_stop_at_travel_end)
        self.assertFalse(second._auto_stop_at_travel_end)
        self.assertFalse(self.cover._command_lock.locked())
        self.assertFalse(second._command_lock.locked())
        self.hass.services.async_call.assert_not_awaited()

    async def test_update_exception_after_option_mutation_reconciles_runtime_readback(self):
        from homeassistant.exceptions import ServiceValidationError

        def update(entry, *, options):
            entry.options = options
            raise RuntimeError("notification failed after updating options")

        self.hass.config_entries.async_update_entry.side_effect = update
        with self.assertRaisesRegex(ServiceValidationError, "cover.east.*cover.east"):
            await self.call()
        self.assertTrue(self.cover._entry.options["auto_stop_at_travel_end"])
        self.assertTrue(self.cover._auto_stop_at_travel_end)
        self.cover.async_write_ha_state.assert_called_once_with()
        self.assertFalse(self.cover._command_lock.locked())
        self.hass.services.async_call.assert_not_awaited()

    async def test_silent_persistence_failure_does_not_publish_runtime_setting(self):
        from homeassistant.exceptions import ServiceValidationError
        self.hass.config_entries.async_update_entry.side_effect = None
        self.hass.config_entries.async_update_entry.return_value = False
        with self.assertRaises(ServiceValidationError):
            await self.call()
        self.assertFalse(self.cover._auto_stop_at_travel_end)
        self.cover.async_write_ha_state.assert_not_called()

    async def test_updates_only_intended_option_live_without_reload_or_actuation(self):
        result = await self.call(response=True)
        self.assertEqual(result, {"updated": ["cover.east"], "enabled": True})
        self.assertEqual(self.entries[0].options,
                         {"open_travel_time": 90, "unrelated": "preserved", "auto_stop_at_travel_end": True})
        self.assertTrue(self.cover.extra_state_attributes["auto_stop_at_travel_end"])
        self.cover.async_write_ha_state.assert_called_once_with()
        self.hass.services.async_call.assert_not_awaited()
        self.assertIsNone(self.cover._auto_stop_task)
        restored = UninusGreenhouseRollupCover(self.entries[0],
                                              {**self.entries[0].data, **self.entries[0].options})
        self.assertTrue(restored._auto_stop_at_travel_end)
