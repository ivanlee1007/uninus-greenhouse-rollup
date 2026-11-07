"""Single durable hardware policy authority for an owned dual-switch Cover.

Lock order: manager -> Cover command lock. Commands never take the manager
lock. Native config numeric fields are migration seeds ONLY. Storage is owned
per entry; readback bypasses Store's cache and checks its actual disk envelope.
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from homeassistant.auth.permissions.const import POLICY_CONTROL

from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .estimator import RollupEstimator

RANGES = {
    'open_travel_time': (1, 3600, 1),
    'close_travel_time': (1, 3600, 1),
    'reverse_dead_time': (0, 10, 0.1),
    'off_confirmation_timeout': (0.1, 30, 0.1),
}
DEFAULTS = {'open_travel_time': 120, 'close_travel_time': 120,
            'reverse_dead_time': 0.2, 'off_confirmation_timeout': 5.0}


def validate(values, *, complete=False):
    if not isinstance(values, dict) or not values or set(values) - RANGES.keys():
        raise ServiceValidationError('Unknown or empty hardware parameters')
    if complete and set(values) != set(RANGES):
        raise ServiceValidationError('Incomplete hardware policy')
    result = {}
    for key, value in values.items():
        low, high, _ = RANGES[key]
        if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
            raise ServiceValidationError(f'Invalid hardware parameter: {key}')
        result[key] = float(value)
    return result


class ParameterManager:
    """Own policy, admission and publication; never own foreign Cover timings."""

    def __init__(self, hass, entry, cover):
        self.hass, self.entry, self.cover = hass, entry, cover
        self.lock = asyncio.Lock()
        self.store = Store(hass, 1, f'{DOMAIN}.parameters.{entry.entry_id}')
        self.parameters = {}
        self.revision = 0
        self.closing = False
        self.fault = None
        self.numbers = set()

    async def _read(self):
        def read():
            path = Path(self.store.path)
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                return None
        return await self.hass.async_add_executor_job(read)

    def _decode(self, envelope):
        if (not isinstance(envelope, dict)
                or type(envelope.get('version')) is not int or envelope['version'] != 1
                or type(envelope.get('minor_version', 1)) is not int
                or envelope.get('minor_version', 1) != 1
                or envelope.get('key') != self.store.key):
            raise ServiceValidationError('Unsupported hardware policy storage envelope')
        data = envelope.get('data')
        if (not isinstance(data, dict) or set(data) != {'revision', 'parameters'}
                or type(data['revision']) is not int or data['revision'] < 0):
            raise ServiceValidationError('Corrupt hardware policy storage')
        return data['revision'], validate(data['parameters'], complete=True)

    async def async_load(self, seeds):
        envelope = await self._read()
        if envelope is None:
            values = validate({k: seeds.get(k, v) for k, v in DEFAULTS.items()}, complete=True)
            await self.store.async_save({'revision': 0, 'parameters': values})
            envelope = await self._read()
            if envelope is None or self._decode(envelope) != (0, values):
                raise ServiceValidationError('Hardware policy seed was not durably saved')
        self.revision, self.parameters = self._decode(envelope)
        self._apply()

    def _owned(self):
        domain = self.hass.data.get(DOMAIN, {})
        cover = self.cover
        data = {**self.entry.data, **self.entry.options}
        if (self.closing or cover._removing or self.fault
                or self.hass.is_stopping
                or domain.get('parameters', {}).get(self.entry.entry_id) is not self
                or domain.get('covers', {}).get(self.entry.entry_id) is not cover
                or data.get('actuator_mode', 'dual_switch') != 'dual_switch'
                or self.entry.domain != DOMAIN
                or data.get('open_entity') != cover._open_entity
                or data.get('close_entity') != cover._close_entity
                or any(domain.get('relay_owners', {}).get(e) != self.entry.entry_id
                       for e in (cover._open_entity, cover._close_entity))):
            raise ServiceValidationError(f'Hardware policy unavailable: {self.fault or "ownership/lifecycle"}')

    async def _authorize(self, context, entity_ids):
        if context.user_id is None:
            return
        user = await self.hass.auth.async_get_user(context.user_id)
        if user is None:
            raise UnknownUser(context=context)
        if not user.is_active or not user.is_admin or any(
            not user.permissions.check_entity(e, POLICY_CONTROL) for e in entity_ids
        ):
            raise Unauthorized(context=context)

    def _idle(self, *, allow_unknown=False):
        cover = self.cover
        if (cover._pending_direction_commands or cover._pending_stop_commands
                or cover._conflict_stop_pending or cover._auto_stop_task is not None
                or cover._target_operation == 'running'
                or cover._estimator.command_state != 'idle'):
            raise ServiceValidationError('Hardware edit requires idle command/timer state')
        for relay_id in (cover._open_entity, cover._close_entity):
            state = self.hass.states.get(relay_id)
            allowed = ('off', 'unknown') if allow_unknown or cover._feedback_mode == 'legacy_emos' else ('off',)
            if state is None or state.state not in allowed or cover._stop_error:
                raise ServiceValidationError('Hardware edit requires both relays known OFF')
        if allow_unknown or cover._feedback_mode == 'legacy_emos':
            cover._validate_legacy_motion()

    async def async_update_options(self, changes, context):
        """Persist and apply idle-only options without reload or relay I/O."""
        from .cover import _DEVICE_CLASS_BY_ACTUATOR_TYPE

        cover = self.cover
        epoch = cover._parameter_epoch
        targets = (cover.entity_id,)
        await self._authorize(context, targets)
        async with self.lock:
            await self._authorize(context, targets)
            self._owned()
            if cover._command_lock.locked() or epoch != cover._parameter_epoch:
                raise ServiceValidationError('Hardware command or options pending')
            async with cover._command_lock:
                mode = changes.get('feedback_mode', cover._feedback_mode)
                self._idle(allow_unknown=mode != cover._feedback_mode)
                if mode not in ('standard', 'legacy_emos'):
                    raise ServiceValidationError('Invalid feedback mode')
                if mode == 'legacy_emos' and changes.get('auto_stop_at_travel_end') is False:
                    raise ServiceValidationError('Legacy EMOS requires timer stop')
                # Disabled registry entries are not an unknown-feedback exception.
                from homeassistant.helpers import entity_registry as er
                registry = self.hass.data.get(er.DATA_REGISTRY)
                if registry is not None and any(
                    (item := registry.async_get(e)) is not None and item.disabled
                    for e in (cover._open_entity, cover._close_entity)):
                    raise ServiceValidationError('Disabled relay')
                options = {**self.entry.options, **changes}
                if mode == 'legacy_emos':
                    options['auto_stop_at_travel_end'] = True
                error = None
                try:
                    self.hass.config_entries.async_update_entry(self.entry, options=options)
                except Exception as exc:
                    error = exc
                # Reconcile actual native entry even if notification/save raised.
                actual = {**self.entry.data, **self.entry.options}
                cover._feedback_mode = actual.get('feedback_mode', 'standard')
                cover._auto_stop_at_travel_end = (
                    cover._feedback_mode == 'legacy_emos'
                    or actual.get('auto_stop_at_travel_end', False))
                cover._attr_device_class = _DEVICE_CLASS_BY_ACTUATOR_TYPE.get(
                    actual.get('actuator_type', 'rollup'))
                cover._parameter_epoch += 1
                cover._sync_from_switches()
                cover.async_write_ha_state()
                if error is not None or any(self.entry.options.get(k) != v for k, v in options.items()):
                    raise ServiceValidationError('Failed to save options') from error
                return options

    def _apply(self):
        cover = self.cover
        travel_changed = any(getattr(cover, '_' + key) != self.parameters[key]
                             for key in ('open_travel_time', 'close_travel_time'))
        for key, value in self.parameters.items():
            setattr(cover, '_' + key, value)
        if travel_changed:
            cover._estimator = RollupEstimator(self.parameters['open_travel_time'],
                                               self.parameters['close_travel_time'])

    def _publish(self):
        self.cover.async_write_ha_state()
        for number in tuple(self.numbers):
            number.async_write_ha_state()

    def _revalidate(self, targets, epoch, number_identity_guard=None, *, allow_unknown=False):
        if number_identity_guard is not None:
            number_identity_guard()
        self._owned()
        if (self.cover.entity_id != targets[-1] or self.cover._parameter_epoch != epoch
                or targets[0] != targets[-1] and not any(
                    number.entity_id == targets[0] for number in self.numbers)):
            raise ServiceValidationError('Hardware parameter target identity changed')
        self._idle(allow_unknown=allow_unknown)

    async def async_update(self, changes, context, expected_revision=None, entity_id=None,
                           number_identity_guard=None, *, allow_unknown=False):
        changes = validate(changes)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ServiceValidationError('expected_revision must be a nonnegative integer')
        # Freeze the native context and entity target before the first await.
        targets = tuple(dict.fromkeys((entity_id or self.cover.entity_id, self.cover.entity_id)))
        epoch = self.cover._parameter_epoch
        await self._authorize(context, targets)
        if number_identity_guard is not None:
            number_identity_guard()
        async with self.lock:
            await self._authorize(context, targets)
            self._revalidate(targets, epoch, number_identity_guard, allow_unknown=allow_unknown)
            # Do not queue behind active motor commands. A free acquire cannot yield.
            if self.cover._command_lock.locked():
                raise ServiceValidationError('Hardware command pending')
            async with self.cover._command_lock:
                await self._authorize(context, targets)
                self._revalidate(targets, epoch, number_identity_guard, allow_unknown=allow_unknown)
                # Store's loaded cache is not authority: inspect the active envelope
                # before CAS, no-op or merge. A failed read must never reseed it.
                actual = None
                read_error = None
                try:
                    actual = self._decode(await self._read())
                except Exception as exc:
                    read_error = exc
                # The read yielded; stale principals/owners may not even latch a fault.
                await self._authorize(context, targets)
                self._revalidate(targets, epoch, number_identity_guard, allow_unknown=allow_unknown)
                if read_error is not None:
                    self.fault = 'Hardware policy authority unreadable; reload required'
                    raise ServiceValidationError(self.fault) from read_error
                if actual != (self.revision, self.parameters):
                    self.revision, self.parameters = actual
                    self._apply()
                    self.fault = 'Hardware policy authority changed; reload required'
                    self._publish()
                    raise ServiceValidationError(self.fault)
                if expected_revision is not None and expected_revision != self.revision:
                    raise ServiceValidationError('Hardware policy revision conflict')
                candidate = {**self.parameters, **changes}
                if candidate == self.parameters:
                    return self.response()
                previous = (self.revision, dict(self.parameters))
                record = {'revision': self.revision + 1, 'parameters': candidate}
                # Admission occurs here, before the first durable effect. Retain command
                # ownership until the actual write/readback has settled, even on cancel.
                task = self.hass.async_create_task(self._commit(
                    record, previous, context, targets, epoch, number_identity_guard,
                    allow_unknown=allow_unknown))
                cancellation = None
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError as error:
                        cancellation = error
                result = task.result()
                if cancellation is not None:
                    raise cancellation
                return result

    async def _commit(self, record, previous, context, targets, epoch, number_identity_guard=None,
                      *, allow_unknown=False):
        await self._authorize(context, targets)
        self._revalidate(targets, epoch, number_identity_guard, allow_unknown=allow_unknown)
        error = None
        try:
            await self.store.async_save(record)
        except Exception as exc:
            error = exc
        try:
            envelope = await self._read()
            actual = self._decode(envelope)
        except Exception as exc:
            self.fault = 'Hardware policy commit uncertain; reload required'
            try:
                actual = self._decode(await self._read())
            except Exception:
                raise ServiceValidationError(self.fault) from exc
            self.revision, self.parameters = actual
            self._apply()
            raise ServiceValidationError(self.fault) from exc
        if actual == previous:
            raise ServiceValidationError('Hardware policy was not durably saved') from error
        self.revision, self.parameters = actual
        self._apply()
        if actual != (record['revision'], record['parameters']) or error is not None:
            self.fault = 'Hardware policy committed with persistence error; reload required'
        if self.closing or self.cover._removing:
            self.fault = 'Hardware policy committed during unload; reload required'
        if self.fault:
            raise ServiceValidationError(self.fault) from error
        try:
            self._publish()
        except Exception as exc:
            self.fault = 'Hardware policy committed but publication failed; reload required'
            raise ServiceValidationError(self.fault) from exc
        return self.response()

    def response(self):
        return {'revision': self.revision, 'parameters': dict(self.parameters)}
