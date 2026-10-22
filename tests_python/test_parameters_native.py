"""Offline native Core service, platform and durable hardware policy tests."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from homeassistant.core import HomeAssistant, Context
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant import loader
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.uninus_greenhouse_rollup.const import DOMAIN


class NativeParametersTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from unittest.mock import patch
        self.network_attempts = []
        def deny(*args, **kwargs):
            self.network_attempts.append((args, kwargs))
            raise AssertionError('Offline native test attempted network output')
        for method in ('connect', 'connect_ex', 'sendto'):
            guard = patch('socket.socket.' + method, deny)
            guard.start()
            self.addCleanup(guard.stop)
        if not getattr(type(self), '_runtime_recorded', False):
            import importlib.metadata
            import sys
            print(f'NATIVE_RUNTIME python={sys.version} homeassistant={importlib.metadata.version("homeassistant")}', flush=True)
            type(self)._runtime_recorded = True
        self.temp = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.temp.name)
        loader.async_setup(self.hass)
        from homeassistant.auth import auth_manager_from_config
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.hass.auth = await auth_manager_from_config(self.hass, [], [])
        self.writes = []

        async def switch(call):
            self.writes.append((call.service, call.data['entity_id']))
            self.hass.states.async_set(call.data['entity_id'], 'on' if call.service == 'turn_on' else 'off')
        self.hass.services.async_register('switch', 'turn_on', switch)
        self.hass.services.async_register('switch', 'turn_off', switch)
        self.hass.states.async_set('switch.open', 'off')
        self.hass.states.async_set('switch.close', 'off')
        self.entry = ConfigEntry(version=3, minor_version=1, domain=DOMAIN, title='East',
            data={'open_entity': 'switch.open', 'close_entity': 'switch.close',
                  'open_travel_time': 117, 'close_travel_time': 119, 'reverse_dead_time': 0},
            options={'open_travel_time': 123}, source='user', unique_id='pair',
            discovery_keys={}, subentries_data=[])
        self.assertTrue(await async_setup_component(self.hass, DOMAIN, {}))
        await self.hass.config_entries.async_add(self.entry)
        await self.hass.async_block_till_done()
        self.writes.clear()

    async def asyncTearDown(self):
        await self.hass.async_stop()
        self.temp.cleanup()
        self.assertEqual(self.network_attempts, [])

    async def batch(self, parameters, *, revision=None, context=None):
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        data = {'entity_id': cover.entity_id, 'parameters': parameters}
        if revision is not None:
            data['expected_revision'] = revision
        return await self.hass.services.async_call(DOMAIN, 'apply_parameters', data,
            blocking=True, return_response=True, context=context)

    async def test_native_options_reads_authority_and_numeric_save_does_not_reload(self):
        await self.batch({'open_travel_time': 151})
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        cover = manager.cover
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        defaults = {key.schema: key.default() for key in form['data_schema'].schema}
        self.assertEqual(defaults['open_travel_time'], 151)
        values = {**defaults, 'open_travel_time': 152}
        result = await self.hass.config_entries.options.async_configure(form['flow_id'], values)
        self.assertEqual(result['type'], 'create_entry')
        await self.hass.async_block_till_done()
        self.assertIs(self.hass.data[DOMAIN]['covers'][self.entry.entry_id], cover)
        self.assertEqual(manager.parameters['open_travel_time'], 152)
        self.assertEqual(self.writes, [])

    async def test_postcommit_publication_failure_blocks_direction_but_stop_works(self):
        from unittest.mock import patch
        from homeassistant.exceptions import ServiceValidationError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        with patch.object(manager, '_publish', side_effect=RuntimeError('publication fault')):
            with self.assertRaises(ServiceValidationError):
                await self.batch({'open_travel_time': 160})
        self.assertEqual(manager.revision, 1)
        self.assertEqual(manager.cover._open_travel_time, 160)
        with self.assertRaises(ServiceValidationError):
            await self.hass.services.async_call('cover', 'open_cover',
                {'entity_id': manager.cover.entity_id}, blocking=True)
        self.assertEqual(self.writes, [])
        await self.hass.services.async_call('cover', 'stop_cover',
            {'entity_id': manager.cover.entity_id}, blocking=True)
        self.assertEqual([x[0] for x in self.writes], ['turn_off', 'turn_off'])

    def numbers(self):
        return {s.attributes['parameter_key']: s for s in self.hass.states.async_all('number')
                if 'parameter_key' in s.attributes}

    async def test_reconfigure_reads_authority_and_numeric_only_save_keeps_cover(self):
        await self.batch({'close_travel_time': 166})
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        form = await self.hass.config_entries.flow.async_init(DOMAIN,
            context={'source': 'reconfigure', 'entry_id': self.entry.entry_id})
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        self.assertEqual(values['close_travel_time'], 166)
        result = await self.hass.config_entries.flow.async_configure(form['flow_id'],
            {**values, 'close_travel_time': 167})
        self.assertEqual(result['type'], 'abort')
        await self.hass.async_block_till_done()
        self.assertIs(self.hass.data[DOMAIN]['covers'][self.entry.entry_id], cover)
        self.assertEqual(cover._close_travel_time, 167)
        self.assertEqual(self.writes, [])

    async def test_strict_batch_validation_atomic_CAS_and_concurrent_single_merge(self):
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        before = Path(manager.store.path).read_bytes()
        for values in ({}, {'foreign': 3}, {'open_travel_time': True},
                       {'open_travel_time': '4'}, {'open_travel_time': float('nan')},
                       {'close_travel_time': float('inf')}, {'open_travel_time': 10 ** 1000},
                       {'reverse_dead_time': -1},
                       {'off_confirmation_timeout': 31},
                       {'open_travel_time': 145, 'close_travel_time': 0}):
            with self.subTest(values=values), self.assertRaises(HomeAssistantError):
                await self.batch(values)
            self.assertEqual(Path(manager.store.path).read_bytes(), before)
        results = await asyncio.gather(
            self.batch({'open_travel_time': 144}, revision=0),
            self.batch({'close_travel_time': 145}, revision=0), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1)
        self.assertEqual(manager.revision, 1)
        numbers = self.numbers()
        await asyncio.gather(*(self.hass.services.async_call('number', 'set_value',
            {'entity_id': numbers[key].entity_id, 'value': value}, blocking=True)
            for key, value in [('open_travel_time', 177), ('close_travel_time', 178)]))
        self.assertEqual(manager.parameters['open_travel_time'], 177)
        self.assertEqual(manager.parameters['close_travel_time'], 178)
        self.assertEqual(manager.revision, 3)
        before = Path(manager.store.path).read_bytes()
        result = await self.batch({'close_travel_time': 178})
        self.assertEqual(result['revision'], 3)
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        for revision in (True, -1, 1.0, '3'):
            with self.subTest(revision=revision), self.assertRaises(Exception):
                await self.batch({'close_travel_time': 179}, revision=revision)
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        self.assertEqual(self.writes, [])

    async def test_actual_auth_manager_admin_inactive_deleted_and_queued_revocation(self):
        from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
        from homeassistant.exceptions import HomeAssistantError
        await self.hass.auth.async_create_user('Owner', group_ids=[GROUP_ID_ADMIN])
        admin = await self.hass.auth.async_create_user('Admin', group_ids=[GROUP_ID_ADMIN])
        user = await self.hass.auth.async_create_user('User', group_ids=[GROUP_ID_USER])
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        number = self.numbers()['open_travel_time'].entity_id
        async def single(context):
            await self.hass.services.async_call('number', 'set_value',
                {'entity_id': number, 'value': 155}, blocking=True, context=context)
        before = Path(manager.store.path).read_bytes()
        for context in (Context(user_id=user.id), Context(user_id='deleted-user')):
            with self.assertRaises(HomeAssistantError):
                await single(context)
            with self.assertRaises(HomeAssistantError):
                await self.batch({'open_travel_time': 155}, context=context)
        await self.hass.auth.async_update_user(admin, is_active=False)
        with self.assertRaises(HomeAssistantError):
            await single(Context(user_id=admin.id))
        await self.hass.auth.async_update_user(admin, is_active=True)
        await manager.lock.acquire()
        task = asyncio.create_task(single(Context(user_id=admin.id)))
        for _ in range(100):
            await asyncio.sleep(0)
            if manager.lock._waiters:
                break
        self.assertTrue(manager.lock._waiters)
        await self.hass.auth.async_update_user(admin, group_ids=[GROUP_ID_USER])
        manager.lock.release()
        with self.assertRaises(HomeAssistantError):
            await task
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        self.assertEqual(self.writes, [])
        await self.hass.auth.async_update_user(admin, group_ids=[GROUP_ID_ADMIN])
        await single(Context(user_id=admin.id))
        self.assertEqual(manager.parameters['open_travel_time'], 155)

    async def test_moving_unknown_and_queued_commands_reject_without_touching_target_stop(self):
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        cover = manager.cover
        before = Path(manager.store.path).read_bytes()
        await self.hass.services.async_call('cover', 'set_cover_position',
            {'entity_id': cover.entity_id, 'position': 100}, blocking=True)
        timer = cover._auto_stop_task
        self.assertIsNotNone(timer)
        self.writes.clear()
        with self.assertRaises(HomeAssistantError):
            await self.batch({'reverse_dead_time': 1})
        self.assertIs(cover._auto_stop_task, timer)
        self.assertFalse(timer.done())
        self.assertEqual(self.writes, [])
        await cover.async_stop_cover()
        await self.hass.async_block_till_done()
        self.writes.clear()
        for value in ('unknown', 'unavailable', 'on'):
            self.hass.states.async_set('switch.open', value)
            with self.assertRaises(HomeAssistantError):
                await self.batch({'reverse_dead_time': 1})
        self.hass.states.async_set('switch.open', 'off')
        await self.hass.async_block_till_done()
        self.writes.clear()
        await cover._command_lock.acquire()
        command = asyncio.create_task(cover.async_open_cover())
        await asyncio.sleep(0)
        cover._command_lock.release()
        try:
            with self.assertRaises(HomeAssistantError):
                await self.batch({'reverse_dead_time': 1})
        finally:
            await command
            await cover.async_stop_cover()
        self.assertEqual(Path(manager.store.path).read_bytes(), before)

    async def test_deleted_entry_removes_only_owned_store_and_rejects_queued_write(self):
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        path = Path(manager.store.path)
        unrelated = path.parent / 'unrelated_policy'
        unrelated.write_text('retained')
        await manager.lock.acquire()
        pending = asyncio.create_task(self.batch({'open_travel_time': 170}))
        await asyncio.sleep(0)
        removal = asyncio.create_task(self.hass.config_entries.async_remove(self.entry.entry_id))
        for _ in range(100):
            await asyncio.sleep(0)
            if manager.closing:
                break
        self.assertTrue(manager.closing)
        manager.lock.release()
        with self.assertRaises(HomeAssistantError):
            await pending
        await removal
        self.assertFalse(path.exists())
        self.assertEqual(unrelated.read_text(), 'retained')
        self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN]['parameters'])

    async def test_travel_change_invalidates_confidence_deadtime_preserves_it_and_reload_uses_store(self):
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        cover = manager.cover
        cover._estimator.position = 42
        cover._estimator.confidence = 'estimated'
        await self.batch({'reverse_dead_time': 0.3, 'off_confirmation_timeout': 2.2})
        self.assertEqual(cover.current_cover_position, 42)
        await self.batch({'open_travel_time': 190})
        self.assertIsNone(cover.current_cover_position)
        self.assertEqual(cover._estimator.confidence, 'unknown')
        self.assertFalse(cover.extra_state_attributes['physical_arrival_confirmed'])
        ids = {s.attributes['parameter_key']: er.async_get(self.hass).async_get(s.entity_id).unique_id
               for s in self.numbers().values()}
        registry = er.async_get(self.hass)
        number = self.numbers()['open_travel_time'].entity_id
        registry.async_update_entity(number, new_entity_id='number.renamed_hardware')
        self.hass.config_entries.async_update_entry(self.entry, title='Renamed',
            options={**self.entry.options, 'open_travel_time': 9, 'close_travel_time': 8})
        self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
        await self.hass.async_block_till_done()
        new = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        self.assertEqual(new.parameters['open_travel_time'], 190)
        self.assertEqual(new.parameters['close_travel_time'], 119)
        self.assertEqual(new.revision, 2)
        self.assertEqual(self.numbers()['open_travel_time'].entity_id, 'number.renamed_hardware')
        self.assertEqual(ids, {s.attributes['parameter_key']: registry.async_get(s.entity_id).unique_id
                              for s in self.numbers().values()})

    async def test_native_swallowed_write_and_readback_failures_never_false_success(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        from homeassistant.helpers.storage import WriteError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        old = Path(manager.store.path).read_bytes()
        with patch.object(manager.store, '_async_write_data', side_effect=WriteError('owned provider failure')):
            with self.assertLogs('homeassistant.helpers.storage', level='ERROR') as logs:
                with self.assertRaises(HomeAssistantError):
                    await self.hass.services.async_call('number', 'set_value',
                        {'entity_id': self.numbers()['open_travel_time'].entity_id, 'value': 181},
                        blocking=True)
            self.assertIn('owned provider failure', '\n'.join(logs.output))
            print('EXPECTED_STORAGE_FAILURE ' + '\n'.join(logs.output), flush=True)
        self.assertEqual(Path(manager.store.path).read_bytes(), old)
        self.assertEqual(manager.cover._open_travel_time, 123)
        self.assertEqual(float(self.numbers()['open_travel_time'].state), 123)
        original_read = manager._read
        calls = 0
        async def postcommit_failure():
            nonlocal calls
            calls += 1
            if calls > 1:  # First read now validates active authority before write.
                raise OSError('readback fault')
            return await original_read()
        with patch.object(manager, '_read', postcommit_failure):
            with self.assertRaises(HomeAssistantError):
                await self.batch({'open_travel_time': 182})
        self.assertIsNotNone(manager.fault)
        actual = json.loads(Path(manager.store.path).read_text())['data']
        self.assertEqual(actual['parameters']['open_travel_time'], 182)
        with self.assertRaises(HomeAssistantError):
            await self.batch({'open_travel_time': 183})
        self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
        await self.hass.async_block_till_done()
        new = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        self.assertEqual(new.parameters['open_travel_time'], 182)
        self.assertEqual(new.revision, 1)
        self.assertIsNone(new.fault)

    async def test_bootstrap_numbers_does_not_wait_for_cover_registration(self):
        from unittest.mock import patch
        from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover
        await self.hass.config_entries.async_unload(self.entry.entry_id)
        original = UninusGreenhouseRollupCover.async_added_to_hass
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(cover):
            entered.set()
            await release.wait()
            await original(cover)
        with patch.object(UninusGreenhouseRollupCover, 'async_added_to_hass', delayed):
            task = asyncio.create_task(self.hass.config_entries.async_setup(self.entry.entry_id))
            await asyncio.wait_for(entered.wait(), 3)
            for _ in range(100):
                if len([s for s in self.numbers().values() if s.state != 'unavailable']) == 4:
                    break
                await asyncio.sleep(0.01)
            try:
                self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN]['covers'])
                self.assertEqual(len([s for s in self.numbers().values() if s.state != 'unavailable']), 4)
            finally:
                release.set()
                self.assertTrue(await task)

    async def test_native_cover_passthrough_has_no_hardware_numbers_or_foreign_ownership(self):
        from homeassistant.exceptions import HomeAssistantError
        foreign = 'cover.foreign'
        self.hass.states.async_set(foreign, 'closed')
        native = ConfigEntry(version=3, minor_version=1, domain=DOMAIN, title='Native',
            data={'actuator_mode': 'native_cover', 'cover_entity': foreign}, options={},
            source='user', unique_id='native', discovery_keys={}, subentries_data=[])
        await self.hass.config_entries.async_add(native)
        self.assertNotIn(native.entry_id, self.hass.data[DOMAIN]['parameters'])
        self.assertEqual(len(self.numbers()), 4)
        with self.assertRaises(HomeAssistantError):
            await self.hass.services.async_call(DOMAIN, 'apply_parameters',
                {'entity_id': foreign, 'parameters': {'open_travel_time': 10}}, blocking=True)
        await self.hass.config_entries.async_remove(native.entry_id)
        self.assertEqual(self.hass.states.get(foreign).state, 'closed')
        self.assertEqual(self.writes, [])

    async def test_actual_postcommit_transient_readback_failure_preserves_committed_policy(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager._read
        calls = 0
        async def transient():
            nonlocal calls
            calls += 1
            if calls == 2:  # First read is preflight; fail the committed readback.
                raise OSError('transient readback')
            return await original()
        with patch.object(manager, '_read', transient):
            with self.assertRaises(HomeAssistantError):
                await self.batch({'open_travel_time': 199})
        self.assertEqual(manager.parameters['open_travel_time'], 199)
        self.assertEqual(manager.revision, 1)
        self.assertEqual(manager.cover._open_travel_time, 199)
        self.assertIsNotNone(manager.fault)
        self.assertEqual(self.writes, [])

    async def test_restore_cannot_revalidate_old_estimate_after_travel_policy_change(self):
        from unittest.mock import patch
        from homeassistant.core import State
        from custom_components.uninus_greenhouse_rollup.cover import UninusGreenhouseRollupCover
        await self.batch({'open_travel_time': 200})
        stale = State('cover.east', 'open', {'current_position': 42,
            'position_confidence': 'estimated', 'open_travel_time': 123, 'close_travel_time': 119})
        async def restore(cover):
            return stale
        with patch.object(UninusGreenhouseRollupCover, 'async_get_last_state', restore):
            self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        self.assertIsNone(cover.current_cover_position)
        self.assertEqual(cover._estimator.confidence, 'unknown')

    async def test_actual_executor_write_retains_command_lock_and_motion_uses_committed_policy(self):
        from unittest.mock import patch
        import threading
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager.store._write_prepared_data
        entered, release = threading.Event(), threading.Event()
        def physical(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test executor release timeout')
            return original(*args)
        with patch.object(manager.store, '_write_prepared_data', physical):
            edit = asyncio.create_task(self.batch({'open_travel_time': 211}))
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            self.assertTrue(manager.lock.locked())
            self.assertTrue(manager.cover._command_lock.locked())
            command = asyncio.create_task(manager.cover.async_open_cover())
            await asyncio.sleep(0)
            self.assertEqual(self.writes, [])
            self.assertEqual(manager.cover._open_travel_time, 123)
            release.set()
            result = await edit
            await command
        self.assertEqual(result['parameters']['open_travel_time'], 211)
        self.assertEqual(manager.cover._open_travel_time, 211)
        self.assertEqual(self.writes[-1], ('turn_on', 'switch.open'))
        await manager.cover.async_stop_cover()

    async def test_corrupt_and_unsupported_existing_storage_fail_closed_without_seed_reset(self):
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        path = Path(manager.store.path)
        original = path.read_bytes()
        self.assertTrue(await self.hass.config_entries.async_unload(self.entry.entry_id))
        self.writes.clear()
        for corrupt in ('{not json', json.dumps({'version': 2, 'data': {}}),
                        json.dumps({'version': True, 'minor_version': 1, 'key': manager.store.key,
                                    'data': {'revision': 0, 'parameters': manager.parameters}}),
                        json.dumps({'version': 1, 'key': manager.store.key,
                                    'data': {'revision': -1, 'parameters': manager.parameters}})):
            path.write_text(corrupt)
            with self.assertLogs(level='ERROR') as diagnostics:
                result = await self.hass.config_entries.async_reload(self.entry.entry_id)
                self.assertFalse(result, 'Corrupt policy must never load or reset from seeds')
            self.assertIn('Error setting up entry', '\n'.join(diagnostics.output))
            print('EXPECTED_CORRUPT_POLICY ' + '\n'.join(diagnostics.output), flush=True)
            self.assertEqual(path.read_text(), corrupt)
            self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN]['parameters'])
            self.assertEqual(self.writes, [])
        path.write_bytes(original)
        self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))

    async def test_real_core_stop_and_new_instance_reads_actual_policy_not_legacy_seeds(self):
        from homeassistant.auth import auth_manager_from_config
        await self.batch({'open_travel_time': 233, 'off_confirmation_timeout': 2.3})
        entry_id = self.entry.entry_id
        await self.hass.async_start()
        await self.hass.async_stop()
        self.hass = HomeAssistant(self.temp.name)
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.hass.auth = await auth_manager_from_config(self.hass, [], [])
        async def switch(call):
            self.hass.states.async_set(call.data['entity_id'], 'off')
        self.hass.services.async_register('switch', 'turn_off', switch)
        self.hass.states.async_set('switch.open', 'off')
        self.hass.states.async_set('switch.close', 'off')
        self.assertTrue(await async_setup_component(self.hass, DOMAIN, {}))
        await self.hass.async_block_till_done()
        manager = self.hass.data[DOMAIN]['parameters'][entry_id]
        self.assertEqual(manager.parameters['open_travel_time'], 233)
        self.assertEqual(manager.parameters['off_confirmation_timeout'], 2.3)
        self.assertEqual(manager.revision, 1)
        self.assertEqual(float(self.numbers()['open_travel_time'].state), 233)
        self.assertIsNone(manager.cover._auto_stop_task)

    async def test_queued_cover_rename_is_not_authorized_under_stale_target_identity(self):
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        before = Path(manager.store.path).read_bytes()
        old_id = manager.cover.entity_id
        await manager.lock.acquire()
        task = asyncio.create_task(self.batch({'open_travel_time': 177}))
        for _ in range(100):
            await asyncio.sleep(0)
            if manager.lock._waiters:
                break
        self.assertTrue(manager.lock._waiters)
        er.async_get(self.hass).async_update_entity(old_id, new_entity_id='cover.renamed_while_waiting')
        for _ in range(100):
            if manager.cover.entity_id != old_id:
                break
            await asyncio.sleep(0)
        self.assertNotEqual(manager.cover.entity_id, old_id)
        rename_writes = list(self.writes)
        manager.lock.release()
        with self.assertRaises(HomeAssistantError):
            await task
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        self.assertEqual(self.writes, rename_writes)
        self.assertTrue(all(service == 'turn_off' for service, _ in self.writes))
        await self.hass.async_block_till_done()
        await self.batch({'open_travel_time': 178})
        self.assertEqual(manager.parameters['open_travel_time'], 178)

    async def test_native_options_captures_http_principal_not_trusted_missing_flow_context(self):
        from aiohttp.test_utils import make_mocked_request
        from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
        from homeassistant.components.http import current_request, KEY_HASS_USER
        from homeassistant.exceptions import HomeAssistantError
        await self.hass.auth.async_create_user('Owner', group_ids=[GROUP_ID_ADMIN])
        user = await self.hass.auth.async_create_user('User', group_ids=[GROUP_ID_USER])
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        form = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        values = {key.schema: key.default() for key in form['data_schema'].schema}
        request = make_mocked_request('POST', '/api/config/config_entries/options/flow')
        request[KEY_HASS_USER] = user
        token = current_request.set(request)
        before = Path(manager.store.path).read_bytes()
        try:
            with self.assertRaises(HomeAssistantError):
                await self.hass.config_entries.options.async_configure(form['flow_id'],
                    {**values, 'open_travel_time': 244})
        finally:
            current_request.reset(token)
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        self.assertEqual(self.writes, [])

    async def test_repeated_cancellation_waits_for_owned_physical_commit_before_unlock(self):
        from unittest.mock import patch
        import threading
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager.store._write_prepared_data
        entered, release = threading.Event(), threading.Event()
        def physical(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test executor release timeout')
            return original(*args)
        with patch.object(manager.store, '_write_prepared_data', physical):
            task = asyncio.create_task(manager.async_update({'open_travel_time': 245}, Context()))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertTrue(manager.lock.locked())
                self.assertTrue(manager.cover._command_lock.locked())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(json.loads(Path(manager.store.path).read_text())['data']['revision'], 1)
        self.assertEqual(manager.revision, 1)
        self.assertEqual(manager.cover._open_travel_time, 245)
        self.assertFalse(manager.lock.locked())
        self.assertEqual(self.writes, [])

    async def test_unload_during_owned_physical_commit_never_republishes_numbers(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        import threading
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        original = manager.store._write_prepared_data
        entered, release = threading.Event(), threading.Event()
        def physical(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test executor release timeout')
            return original(*args)
        with patch.object(manager.store, '_write_prepared_data', physical), \
             patch.object(manager, '_publish', wraps=manager._publish) as publish:
            task = asyncio.create_task(self.batch({'open_travel_time': 246}))
            self.assertTrue(await asyncio.to_thread(entered.wait, 3))
            unload = asyncio.create_task(self.hass.config_entries.async_unload(self.entry.entry_id))
            for _ in range(100):
                await asyncio.sleep(0)
                if manager.closing:
                    break
            try:
                self.assertTrue(manager.closing)
                self.assertFalse(unload.done())
            finally:
                release.set()
            with self.assertRaises(HomeAssistantError):
                await task
            self.assertTrue(await unload)
            publish.assert_not_called()
        self.assertEqual(json.loads(Path(manager.store.path).read_text())['data']['parameters']['open_travel_time'], 246)
        self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN]['parameters'])
        for state in self.numbers().values():
            self.assertEqual(state.state, 'unavailable')
        await self.hass.async_block_till_done()
        self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN]['parameters'])

    async def test_native_numbers_apply_idle_to_actual_cover_without_relay_writes(self):
        numbers = self.numbers()
        self.assertEqual(set(numbers), {'open_travel_time', 'close_travel_time',
                                      'reverse_dead_time', 'off_confirmation_timeout'})
        cover = self.hass.data[DOMAIN]['covers'][self.entry.entry_id]
        self.assertEqual(float(numbers['open_travel_time'].state), 123)
        await self.hass.services.async_call('number', 'set_value',
            {'entity_id': numbers['open_travel_time'].entity_id, 'value': 150}, blocking=True)
        self.assertEqual(cover._open_travel_time, 150)
        self.assertEqual(cover._estimator.open_travel_time, 150)
        self.assertEqual(self.writes, [])
        self.assertEqual(float(self.hass.states.get(numbers['open_travel_time'].entity_id).state), 150)
        for state in self.numbers().values():
            self.assertEqual(state.attributes['policy_revision'], 1)
            self.assertEqual(state.attributes['parameter_group'], 'hardware')
            self.assertEqual(state.attributes['mode'], 'box')
            self.assertEqual(state.attributes['unit_of_measurement'], 's')
            record = er.async_get(self.hass).async_get(state.entity_id)
            self.assertEqual(record.config_entry_id, self.entry.entry_id)
            self.assertIsNotNone(record.device_id)
            self.assertEqual(record.entity_category.value, 'config')
        paths = list(Path(self.temp.name, '.storage').glob(f'{DOMAIN}.parameters.*'))
        self.assertEqual(len(paths), 1)
        envelope = json.loads(paths[0].read_text())
        self.assertEqual(envelope['data']['parameters']['open_travel_time'], 150)
        self.assertEqual(envelope['data']['revision'], 1)

    async def test_active_invalid_authority_precedes_write_noop_and_CAS(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        path = Path(manager.store.path)
        original = path.read_bytes()
        unsupported = json.loads(original)
        unsupported['version'] = 99
        for bad in (b'{active malformed JSON', json.dumps(unsupported).encode(), None):
            for changes, revision in (({'reverse_dead_time': 0.7}, None),
                                      ({'reverse_dead_time': 0}, None),
                                      ({'reverse_dead_time': 0.7}, 99)):
                with self.subTest(payload=bad, changes=changes, revision=revision):
                    if bad is None:
                        path.unlink()
                    else:
                        path.write_bytes(bad)
                    before = manager.response()
                    with patch.object(manager.store, 'async_save', wraps=manager.store.async_save) as save:
                        with self.assertRaises(HomeAssistantError):
                            await self.batch(changes, revision=revision)
                        save.assert_not_called()
                    after = path.read_bytes() if path.exists() else None
                    self.assertEqual(after, bad)
                    self.assertEqual(manager.response(), before)
                    self.assertIsNotNone(manager.fault)
                    with self.assertRaises(HomeAssistantError):
                        await manager.cover.async_open_cover()
                    self.assertEqual(self.writes, [])
                    await manager.cover.async_stop_cover()
                    self.assertEqual([service for service, _ in self.writes], ['turn_off', 'turn_off'])
                    print('B2_INVALID_BYTES before=', None if bad is None else bad.hex(),
                          'after=', None if after is None else after.hex(), flush=True)
                    path.write_bytes(original)
                    self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
                    await self.hass.async_block_till_done()
                    manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
                    self.writes.clear()

    async def test_active_valid_drift_retains_actual_policy_and_gates_until_reload(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        for disk_revision, travel in ((9, 231), (0, 232)):
            with self.subTest(disk_revision=disk_revision):
                manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
                path = Path(manager.store.path)
                envelope = json.loads(path.read_bytes())
                envelope['data']['revision'] = disk_revision
                envelope['data']['parameters']['open_travel_time'] = travel
                payload = json.dumps(envelope).encode()
                path.write_bytes(payload)
                with patch.object(manager.store, 'async_save', wraps=manager.store.async_save) as save:
                    with self.assertRaises(HomeAssistantError):
                        await self.batch({'reverse_dead_time': manager.parameters['reverse_dead_time']},
                                         revision=manager.revision)
                    save.assert_not_called()
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(manager.response(), envelope['data'])
                self.assertEqual(manager.cover._open_travel_time, travel)
                number = next(number for number in manager.numbers if number.key == 'open_travel_time')
                self.assertEqual(number.native_value, travel)
                self.assertEqual(self.hass.states.get(number.entity_id).state, 'unavailable')
                self.assertIsNotNone(manager.fault)
                with self.assertRaises(HomeAssistantError):
                    await self.batch({'reverse_dead_time': 0.8}, revision=disk_revision)
                with self.assertRaises(HomeAssistantError):
                    await manager.cover.async_open_cover()
                self.assertEqual(self.writes, [])
                await manager.cover.async_stop_cover()
                self.assertTrue(all(service == 'turn_off' for service, _ in self.writes))
                self.assertEqual(path.read_bytes(), payload)
                print('B2_DRIFT_BYTES before=', payload.hex(), 'after=', path.read_bytes().hex(), flush=True)
                self.assertTrue(await self.hass.config_entries.async_reload(self.entry.entry_id))
                await self.hass.async_block_till_done()
                manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
                result = await self.batch({'reverse_dead_time': 0.7 if disk_revision == 9 else 0.6},
                                          revision=disk_revision)
                self.assertEqual(result['revision'], disk_revision + 1)
                self.assertEqual(manager.parameters['open_travel_time'], travel)
                self.writes.clear()

    async def test_active_preflight_unreadable_does_not_write_or_claim_commit(self):
        from unittest.mock import patch
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        before = Path(manager.store.path).read_bytes()
        state = manager.response()
        with patch.object(manager, '_read', side_effect=OSError('owned preflight read unavailable')), \
             patch.object(manager.store, 'async_save', wraps=manager.store.async_save) as save:
            with self.assertRaises(HomeAssistantError):
                await self.batch({'reverse_dead_time': 0.8})
            save.assert_not_called()
        self.assertEqual(Path(manager.store.path).read_bytes(), before)
        self.assertEqual(manager.response(), state)
        self.assertIn('authority unreadable', manager.fault)
        self.assertEqual(self.writes, [])

    async def _preflight_wait_denial(self, *, admin=None):
        from unittest.mock import patch
        from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
        from homeassistant.exceptions import HomeAssistantError
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        path = Path(manager.store.path)
        original = path.read_bytes()
        owners = self.hass.data[DOMAIN]['relay_owners']
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                before = b'{corrupt while authority waits' if corrupt else original
                path.write_bytes(before)
                entered, release = asyncio.Event(), asyncio.Event()
                original_read = manager._read
                async def blocked():
                    try:
                        return await original_read()
                    finally:
                        entered.set()
                        await release.wait()
                with patch.object(manager, '_read', blocked), \
                     patch.object(manager.store, 'async_save', wraps=manager.store.async_save) as save:
                    task = asyncio.create_task(self.batch({'reverse_dead_time': 0.8},
                        context=Context(user_id=admin.id) if admin else Context()))
                    try:
                        await asyncio.wait_for(entered.wait(), 3)
                        self.assertTrue(manager.lock.locked())
                        self.assertTrue(manager.cover._command_lock.locked())
                        if admin:
                            await self.hass.auth.async_update_user(admin, group_ids=[GROUP_ID_USER])
                        else:
                            owners['switch.open'] = 'replacement-owner'
                    finally:
                        release.set()
                    with self.assertRaises(HomeAssistantError):
                        await task
                    save.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(manager.revision, 0)
                self.assertEqual(manager.parameters['reverse_dead_time'], 0)
                self.assertIsNone(manager.fault)
                self.assertEqual(self.writes, [])
                if admin:
                    await self.hass.auth.async_update_user(admin, group_ids=[GROUP_ID_ADMIN])
                else:
                    owners['switch.open'] = self.entry.entry_id
        path.write_bytes(original)
        await self.batch({'reverse_dead_time': 0.8},
            context=Context(user_id=admin.id) if admin else Context())
        self.assertEqual(manager.revision, 1)
        self.assertEqual(self.writes, [])

    async def test_preflight_read_wait_revalidates_actual_admin_before_write_or_fault(self):
        from homeassistant.auth.const import GROUP_ID_ADMIN
        await self.hass.auth.async_create_user('Owner', group_ids=[GROUP_ID_ADMIN])
        admin = await self.hass.auth.async_create_user('Admin', group_ids=[GROUP_ID_ADMIN])
        await self._preflight_wait_denial(admin=admin)

    async def test_preflight_read_wait_revalidates_current_owner_before_write_or_fault(self):
        await self._preflight_wait_denial()

    async def _number_lifecycle_wait_denial(self, action, *, preflight=False, trusted=False):
        from unittest.mock import patch
        from homeassistant.auth.const import GROUP_ID_ADMIN
        from homeassistant.exceptions import HomeAssistantError
        await self.hass.auth.async_create_user('Owner', group_ids=[GROUP_ID_ADMIN])
        admin = await self.hass.auth.async_create_user('Admin', group_ids=[GROUP_ID_ADMIN])
        context = Context() if trusted else Context(user_id=admin.id)
        manager = self.hass.data[DOMAIN]['parameters'][self.entry.entry_id]
        number = next(n for n in manager.numbers if n.key == 'open_travel_time')
        entity_id, uid = number.entity_id, number.unique_id
        platform = number.platform
        registry = er.async_get(self.hass)
        before = Path(manager.store.path).read_bytes()
        state = manager.response()
        entered, release = asyncio.Event(), asyncio.Event()
        original_read = manager._read
        async def blocked_read():
            result = await original_read()  # Actual native executor Store read.
            entered.set()
            await release.wait()
            return result
        async def settle(predicate):
            for _ in range(400):
                if predicate():
                    return
                await asyncio.sleep(0)
            self.fail('Native registry/platform lifecycle did not settle')
        if not preflight:
            await manager.lock.acquire()
        with patch.object(manager, '_read', blocked_read if preflight else original_read), \
             patch.object(manager.store, 'async_save', wraps=manager.store.async_save) as save:
            task = asyncio.create_task(self.hass.services.async_call('number', 'set_value',
                {'entity_id': entity_id, 'value': 181}, blocking=True, context=context))
            try:
                if preflight:
                    await asyncio.wait_for(entered.wait(), 3)
                    self.assertTrue(manager.lock.locked())
                    self.assertTrue(manager.cover._command_lock.locked())
                else:
                    await settle(lambda: bool(manager.lock._waiters))
                if action in ('awayback', 'rename'):
                    registry.async_update_entity(entity_id, new_entity_id='number.lifecycle_renamed')
                    await settle(lambda: self.hass.states.get('number.lifecycle_renamed') is not None)
                    if action == 'awayback':
                        registry.async_update_entity('number.lifecycle_renamed', new_entity_id=entity_id)
                        await settle(lambda: self.hass.states.get(entity_id) is not None)
                        self.assertEqual(number.entity_id, entity_id)
                elif action == 'delete':
                    registry.async_remove(entity_id)
                else:
                    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
                    if action == 'readd':
                        await settle(lambda: number not in manager.numbers and entity_id not in platform.entities)
                        registry.async_update_entity(entity_id, disabled_by=None)
                        # Native platforms re-add a fresh instance with the same UID.
                        from custom_components.uninus_greenhouse_rollup.number import HardwareNumber
                        await platform.async_add_entities([HardwareNumber(manager, number.key)])
                        await settle(lambda: any(n.entity_id == entity_id for n in manager.numbers))
                        self.assertEqual(registry.async_get(entity_id).unique_id, uid)
            finally:
                release.set()
                if not preflight:
                    manager.lock.release()
            outcome = (await asyncio.gather(task, return_exceptions=True))[0]
            # Durable invariants first: RED must expose the actual stale mutation.
            self.assertEqual(Path(manager.store.path).read_bytes(), before)
            self.assertEqual(manager.response(), state)
            self.assertIsNone(manager.fault)
            self.assertEqual(self.writes, [])
            save.assert_not_called()
            self.assertIsInstance(outcome, HomeAssistantError)
        # Stale rejection must not gate unrelated Numbers or fresh same-UID setters.
        await self.hass.services.async_call('number', 'set_value',
            {'entity_id': self.numbers()['close_travel_time'].entity_id, 'value': 184},
            blocking=True, context=context)
        self.assertEqual(manager.parameters['close_travel_time'], 184)
        if action in ('awayback', 'rename', 'readd'):
            current = 'number.lifecycle_renamed' if action == 'rename' else entity_id
            self.assertEqual(registry.async_get(current).unique_id, uid)
            await self.hass.services.async_call('number', 'set_value',
                {'entity_id': current, 'value': 182}, blocking=True, context=context)
            self.assertEqual(manager.parameters['open_travel_time'], 182)
        self.assertIsNone(manager.fault)
        self.assertEqual(self.writes, [])

    async def test_native_number_queued_registry_ABA(self):
        await self._number_lifecycle_wait_denial('awayback')

    async def test_native_number_trusted_queued_registry_readd(self):
        await self._number_lifecycle_wait_denial('readd', trusted=True)

    async def test_native_number_preflight_registry_ABA(self):
        await self._number_lifecycle_wait_denial('awayback', preflight=True)

    async def test_native_number_trusted_preflight_registry_rename(self):
        await self._number_lifecycle_wait_denial('rename', preflight=True, trusted=True)

    async def test_native_number_trusted_preflight_registry_delete(self):
        await self._number_lifecycle_wait_denial('delete', preflight=True, trusted=True)

    async def test_native_number_trusted_preflight_registry_disable(self):
        await self._number_lifecycle_wait_denial('disable', preflight=True, trusted=True)

    async def test_native_number_trusted_preflight_registry_readd(self):
        await self._number_lifecycle_wait_denial('readd', preflight=True, trusted=True)
