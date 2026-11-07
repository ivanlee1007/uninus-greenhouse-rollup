"""Remembered, time-estimated Cover entity backed by two switch entities."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
import logging
import math
import time
from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    CONF_FEEDBACK_MODE,
    FEEDBACK_STANDARD,
    FEEDBACK_LEGACY_EMOS,
    ACTUATOR_TYPE_ROLLUP,
    ACTUATOR_TYPE_SHADE,
    ACTUATOR_TYPE_SKYLIGHT,
    CONF_ACTUATOR_TYPE,
    CONF_AUTO_STOP_AT_TRAVEL_END,
    CONF_CLOSE_ENTITY,
    CONF_CLOSE_TRAVEL_TIME,
    CONF_OFF_CONFIRMATION_TIMEOUT,
    CONF_OPEN_ENTITY,
    CONF_OPEN_TRAVEL_TIME,
    CONF_REVERSE_DEAD_TIME,
    DEFAULT_ACTUATOR_TYPE,
    DEFAULT_AUTO_STOP_AT_TRAVEL_END,
    DEFAULT_OFF_CONFIRMATION_TIMEOUT,
    DEFAULT_REVERSE_DEAD_TIME,
    DOMAIN,
)
from .estimator import CONFIDENCE_UNKNOWN, RollupEstimator

_UPDATE_INTERVAL = timedelta(seconds=1)
_LOGGER = logging.getLogger(__name__)

_DEVICE_CLASS_BY_ACTUATOR_TYPE = {
    ACTUATOR_TYPE_ROLLUP: CoverDeviceClass.AWNING,
    ACTUATOR_TYPE_SKYLIGHT: CoverDeviceClass.WINDOW,
    ACTUATOR_TYPE_SHADE: CoverDeviceClass.SHADE,
}


@dataclass(frozen=True)
class RollupExtraStoredData(ExtraStoredData):
    """Remember estimator data even when public Cover attributes are unavailable."""

    position: float | None
    confidence: str
    open_travel_time: float
    close_travel_time: float
    motion_interrupted: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return durable position and the travel model that produced it."""
        result = {
            "position": self.position,
            "confidence": self.confidence,
            CONF_OPEN_TRAVEL_TIME: self.open_travel_time,
            CONF_CLOSE_TRAVEL_TIME: self.close_travel_time,
        }
        if self.motion_interrupted is not None:
            result["motion_interrupted"] = self.motion_interrupted
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remembered cover for one switch pair."""
    data = {**entry.data, **entry.options}
    manager = hass.data.get(DOMAIN, {}).get("parameters", {}).get(entry.entry_id)
    async_add_entities([manager.cover if manager else UninusGreenhouseRollupCover(entry, data)])


class UninusGreenhouseRollupCover(CoverEntity, RestoreEntity):
    """Optimistic roll-up cover whose position is integrated over time."""

    _attr_assumed_state = True
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, entry: ConfigEntry, data: dict[str, Any]) -> None:
        self._entry = entry
        self._feedback_mode = data.get(CONF_FEEDBACK_MODE, FEEDBACK_STANDARD)
        if self._feedback_mode not in (FEEDBACK_STANDARD, FEEDBACK_LEGACY_EMOS):
            raise ValueError("Unsupported feedback_mode")
        self._legacy_direction = "idle"
        self._legacy_feedback_quarantine: set[str] = set()
        self._position_basis = "unknown"
        self._interrupted_motion = False
        self._stop_error = False
        self._attr_device_class = _DEVICE_CLASS_BY_ACTUATOR_TYPE.get(
            data.get(CONF_ACTUATOR_TYPE, DEFAULT_ACTUATOR_TYPE),
            CoverDeviceClass.AWNING,
        )
        self._open_entity = data[CONF_OPEN_ENTITY]
        self._close_entity = data[CONF_CLOSE_ENTITY]
        self._open_travel_time = float(data[CONF_OPEN_TRAVEL_TIME])
        self._close_travel_time = float(data[CONF_CLOSE_TRAVEL_TIME])
        self._restore_seed_travel_times = (
            self._open_travel_time, self._close_travel_time
        )
        self._reverse_dead_time = max(
            0.0, float(data.get(CONF_REVERSE_DEAD_TIME, DEFAULT_REVERSE_DEAD_TIME))
        )
        self._auto_stop_at_travel_end = bool(
            data.get(CONF_AUTO_STOP_AT_TRAVEL_END, DEFAULT_AUTO_STOP_AT_TRAVEL_END)
        )
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            self._auto_stop_at_travel_end = True
        self._estimator = RollupEstimator(
            self._open_travel_time,
            self._close_travel_time,
        )
        self._relays_available = False
        timeout = data.get(CONF_OFF_CONFIRMATION_TIMEOUT, DEFAULT_OFF_CONFIRMATION_TIMEOUT)
        self._off_confirmation_timeout = float(timeout)
        if (
            isinstance(timeout, bool)
            or not math.isfinite(self._off_confirmation_timeout)
            or not 0.1 <= self._off_confirmation_timeout <= 30
        ):
            raise ValueError("off_confirmation_timeout must be between 0.1 and 30 seconds")
        self._command_lock = asyncio.Lock()
        self._pending_direction_commands = 0
        self._pending_stop_commands = 0
        self._command_generation = 0
        self._conflict_stop_pending = False
        self._conflict_stop_task: asyncio.Task[None] | None = None
        self._auto_stop_task: asyncio.Task[None] | None = None
        self._auto_stop_target_entity: str | None = None
        self._auto_stop_target_confirmed = False
        self._removing = False
        self._parameter_epoch = 0
        self._target_position: int | None = None
        self._target_operation = "idle"
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=str(data.get(CONF_NAME, entry.title)),
            manufacturer="UNiNUS",
            model="Timed dual-switch cover actuator",
        )

    async def async_added_to_hass(self) -> None:
        """Restore position, then observe both underlying switches."""
        self._removing = False
        await super().async_added_to_hass()
        extra_data = await self.async_get_last_extra_data()
        last_state = await self.async_get_last_state()
        attributes = last_state.attributes if last_state is not None else {}
        snapshot = (
            extra_data.as_dict() if extra_data is not None else {
                "position": attributes.get(ATTR_CURRENT_POSITION),
                "confidence": attributes.get("position_confidence", CONFIDENCE_UNKNOWN),
            }
        )
        if isinstance(snapshot, dict):
            self._interrupted_motion = snapshot.get("motion_interrupted", False) is True
            keys = (CONF_OPEN_TRAVEL_TIME, CONF_CLOSE_TRAVEL_TIME)
            timing_source = snapshot if any(key in snapshot for key in keys) else attributes
            saved_times = (
                tuple(timing_source.get(key) for key in keys)
                if any(key in timing_source for key in keys)
                else self._restore_seed_travel_times
            )
            current_times = (self._open_travel_time, self._close_travel_time)
            if all(type(value) in (int, float) and value == current
                   for value, current in zip(saved_times, current_times, strict=True)):
                self._estimator = RollupEstimator.from_snapshot(
                    *current_times, snapshot
                )
                if self._estimator.position is not None:
                    self._position_basis = "remembered"

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._open_entity, self._close_entity],
                self._handle_state_event,
            )
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._handle_tick,
                _UPDATE_INTERVAL,
            )
        )
        await self._async_stop_active_relays_on_startup()
        self._sync_from_switches()
        self.hass.data.setdefault(DOMAIN, {}).setdefault("covers", {})[
            self._entry.entry_id
        ] = self

    @property
    def extra_restore_state_data(self) -> RollupExtraStoredData:
        """Persist full-precision position independently of entity availability."""
        return RollupExtraStoredData(
            self._estimator.position, self._estimator.confidence,
            self._open_travel_time, self._close_travel_time,
            self._interrupted_motion if self._feedback_mode == FEEDBACK_LEGACY_EMOS else None,
        )

    @callback
    def _handle_state_event(self, event: Event | None) -> None:
        """Synchronize after direct, automation, or card switch changes."""
        if self._removing:
            return
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            self._handle_legacy_feedback(event)
        target_was_running = (
            (self._target_position is not None or self._feedback_mode == FEEDBACK_LEGACY_EMOS)
            and self._auto_stop_task is not None
        )
        self._cancel_auto_stop_if_source_changed(event)
        self._sync_from_switches()
        if (
            (
                self._estimator.command_state == "conflict"
                or (target_was_running and not self._relays_available)
            )
            and not self._conflict_stop_pending
        ):
            self._conflict_stop_pending = True
            self._conflict_stop_task = self.hass.async_create_task(
                self._async_fail_safe_stop()
            )
        self.async_write_ha_state()

    @callback
    def _handle_tick(self, _now: Any) -> None:
        """Resync source states and update the estimate every interval."""
        self._handle_state_event(None)

    @callback
    def _sync_from_switches(self) -> None:
        now = time.monotonic()
        open_state = self.hass.states.get(self._open_entity)
        close_state = self.hass.states.get(self._close_entity)
        invalid = {STATE_UNAVAILABLE, STATE_UNKNOWN}
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            invalid = {STATE_UNAVAILABLE}
        self._relays_available = bool(
            open_state
            and close_state
            and open_state.state not in invalid
            and close_state.state not in invalid
        )
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            from homeassistant.helpers import entity_registry as er
            registry = self.hass.data.get(er.DATA_REGISTRY)
            self._relays_available = self._relays_available and all(
                state is not None and state.state in ("off", "on", STATE_UNKNOWN)
                for state in (open_state, close_state))
            if registry is not None and any(
                (item := registry.async_get(e)) is not None and item.disabled
                for e in (self._open_entity, self._close_entity)):
                self._relays_available = False
        if not self._relays_available:
            self._estimator.sync(open_on=False, close_on=False, now=now)
            return
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            conflict = open_state.state == STATE_ON and close_state.state == STATE_ON
            self._estimator.sync(
                open_on=conflict or self._legacy_direction == "opening",
                close_on=conflict or self._legacy_direction == "closing", now=now,
            )
            if self._estimator.position is not None:
                self._estimator.confidence = "estimated"
            return
        self._estimator.sync(
            open_on=open_state.state == STATE_ON,
            close_on=close_state.state == STATE_ON,
            now=now,
        )

    @property
    def available(self) -> bool:
        """Both actuator entities must be available for safe control."""
        return self._relays_available

    def _validate_legacy_motion(self) -> None:
        """Unknown is allowed, but missing, disabled and unavailable are not."""
        from homeassistant.exceptions import ServiceValidationError
        from homeassistant.helpers import entity_registry as er

        registry = self.hass.data.get(er.DATA_REGISTRY)
        for entity_id in (self._open_entity, self._close_entity):
            state = self.hass.states.get(entity_id)
            registered = registry.async_get(entity_id) if registry is not None else None
            if (state is None or state.state not in ("on", "off", STATE_UNKNOWN)
                    or registered is not None and registered.disabled):
                raise ServiceValidationError(f"Legacy relay unavailable: {entity_id}")
        if all(self.hass.states.get(e).state == STATE_ON
               for e in (self._open_entity, self._close_entity)):
            raise ServiceValidationError("Conflicting relay feedback")

    @callback
    def _handle_legacy_feedback(self, event: Event | None) -> None:
        """Consume transitions, never replay cached ON on ticks.

        Local commands retain their forced stop budget despite delayed OFF.
        An opposite ON remains a safety event. Only an OFF->ON edge with the
        other relay OFF starts external estimation (never unknown->ON replay).
        """
        if event is None:
            return
        data = event.data
        entity = data.get("entity_id")
        old = getattr(data.get("old_state"), "state", None)
        new = getattr(data.get("new_state"), "state", None)
        if entity not in (self._open_entity, self._close_entity) or old == new:
            return
        opening = entity == self._open_entity
        opposite = self.hass.states.get(self._close_entity if opening else self._open_entity)
        if self._legacy_direction != "idle":
            expected = self._open_entity if self._legacy_direction == "opening" else self._close_entity
            if entity != expected and new == STATE_ON and not self._conflict_stop_pending:
                self._conflict_stop_pending = True
                self._conflict_stop_task = self.hass.async_create_task(self._async_fail_safe_stop())
            if self._position_basis == "feedback_estimated" and new == "off" and entity == expected:
                self._legacy_direction = "idle"
                self._cancel_auto_stop_task()
            return
        if self._command_lock.locked() or self._pending_direction_commands or self._pending_stop_commands:
            return
        if entity in self._legacy_feedback_quarantine:
            # A delayed command echo may look like OFF->ON after local STOP.
            # Require a separately observed idle OFF before trusting that source
            # for a new external run. Ticks/cached OFF do not clear this fence.
            if new == "off":
                self._legacy_feedback_quarantine.discard(entity)
            return
        if old == "off" and new == STATE_ON and opposite is not None and opposite.state == "off":
            try:
                self._validate_legacy_motion()
            except Exception:
                return
            self._command_generation += 1
            self._legacy_direction = "opening" if opening else "closing"
            self._position_basis = "feedback_estimated"
            self._interrupted_motion = True
            duration = self._open_travel_time if opening else self._close_travel_time
            self._auto_stop_target_entity = entity
            self._auto_stop_task = self.hass.async_create_task(
                self._async_auto_stop_after(duration, self._command_generation))

    @property
    def current_cover_position(self) -> int | None:
        """Return remembered estimated position, if calibrated or restored."""
        position = self._estimator.position
        return None if position is None else round(position)

    @property
    def is_opening(self) -> bool:
        """Only report physical movement until the estimated endpoint."""
        return self._relays_available and self._estimator.is_opening

    @property
    def is_closing(self) -> bool:
        """Only report physical movement until the estimated endpoint."""
        return self._relays_available and self._estimator.is_closing

    @property
    def is_closed(self) -> bool | None:
        """Return closed only when an estimated position exists."""
        if self._estimator.position is None:
            return None
        return self._estimator.position <= 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose command-vs-motion semantics to the bundled card."""
        open_state = self.hass.states.get(self._open_entity)
        close_state = self.hass.states.get(self._close_entity)
        position = self.current_cover_position
        return {
            "feedback_mode": self._feedback_mode,
            "position_basis": self._position_basis,
            "position_unverified": True,
            "motion_interrupted": self._interrupted_motion,
            "stop_command_error": self._stop_error,
            "coverage_position": (
                100 - position if self.available and position is not None else None
            ),
            "position_confidence": self._estimator.confidence,
            "command_state": (
                self._estimator.command_state
                if self._relays_available
                else "unavailable"
            ),
            "open_switch_entity": self._open_entity,
            "close_switch_entity": self._close_entity,
            "open_switch_on": bool(open_state and open_state.state == STATE_ON),
            "close_switch_on": bool(close_state and close_state.state == STATE_ON),
            "open_travel_time": self._open_travel_time,
            "close_travel_time": self._close_travel_time,
            "reverse_dead_time": self._reverse_dead_time,
            "off_confirmation_timeout": self._off_confirmation_timeout,
            "auto_stop_at_travel_end": self._auto_stop_at_travel_end,
            "position_is_estimated": True,
            "target_position": self._target_position,
            "target_operation": self._target_operation,
            "physical_arrival_confirmed": False,
        }

    @callback
    def validate_auto_stop_change(self) -> None:
        """Require verified idle hardware, not an estimated endpoint."""
        from homeassistant.exceptions import ServiceValidationError

        state = self.hass.states.get(self.entity_id)
        if self._removing or not self.available or state is None or state.state == STATE_UNAVAILABLE:
            raise ServiceValidationError(f"Cover unavailable or removing: {self.entity_id}")
        if (
            self._command_lock.locked()
            or self._pending_direction_commands
            or self._pending_stop_commands
            or self._conflict_stop_pending
            or self._auto_stop_task is not None
        ):
            raise ServiceValidationError(f"Cover command pending: {self.entity_id}")
        for entity_id in (self._open_entity, self._close_entity):
            relay = self.hass.states.get(entity_id)
            if relay is None or relay.state != "off":
                raise ServiceValidationError(f"Relay not verified off: {entity_id}")

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Turn both relays off, pause, then start opening."""
        await self._async_run_direction(self._open_entity)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Turn both relays off, pause, then start closing."""
        await self._async_run_direction(self._close_entity)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move to a time-estimated target, always stopping after the budget."""
        from homeassistant.exceptions import ServiceValidationError

        self._validate_parameter_health()
        target = kwargs.get("position")
        if type(target) is not int or not 0 <= target <= 100:
            raise ServiceValidationError("position must be an integer from 0 to 100")
        self._sync_from_switches()
        if self._estimator.position is None and target not in (0, 100):
            raise ServiceValidationError("Unknown position: request an endpoint first")
        self._command_generation += 1
        generation = self._command_generation
        self._cancel_auto_stop_task()
        self._pending_direction_commands += 1
        try:
            async with self._command_lock:
                self._validate_parameter_health()
                if self._removing or generation != self._command_generation:
                    return
                self._sync_from_switches()
                position = self._estimator.position
                if position is None and target not in (0, 100):
                    raise ServiceValidationError("Unknown position: request an endpoint first")
                if position is not None and round(position) == target:
                    await self._async_turn_both_off()
                    self._target_position = target
                    self._sync_from_switches()
                    self.async_write_ha_state()
                    return
                opening = target == 100 if position is None else target > position
                direction = self._open_entity if opening else self._close_entity
                fraction = 1 if position is None else abs(target - position) / 100
                duration = fraction * (
                    self._open_travel_time if opening else self._close_travel_time
                )
                await self._async_run_direction_locked(
                    direction, generation, duration,
                    target if position is not None else None,
                )
                if generation == self._command_generation:
                    self._target_position = target
                    self._target_operation = (
                        "running" if self._auto_stop_task is not None else "idle"
                    )
                    self._sync_from_switches()
                    self.async_write_ha_state()
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation
        finally:
            self._pending_direction_commands -= 1

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop either direction and freeze the current estimate."""
        self._command_generation += 1
        self._cancel_auto_stop_task()
        self._pending_stop_commands += 1
        try:
            async with self._command_lock:
                await self._async_turn_both_off()
                if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
                    self._interrupted_motion = False
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation
        finally:
            self._pending_stop_commands -= 1
        self._sync_from_switches()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Leave both actuators in a safe state on unload or reload."""
        self._removing = True
        self._parameter_epoch += 1
        covers = self.hass.data.get(DOMAIN, {}).get("covers", {})
        if covers.get(self._entry.entry_id) is self:
            covers.pop(self._entry.entry_id)
        self._command_generation += 1
        auto_stop_task = self._auto_stop_task
        self._cancel_auto_stop_task()
        conflict_task = self._conflict_stop_task
        self._conflict_stop_task = None
        try:
            if conflict_task is not None:
                if not conflict_task.done():
                    conflict_task.cancel()
                with suppress(asyncio.CancelledError):
                    await conflict_task
            if auto_stop_task is not None:
                with suppress(asyncio.CancelledError):
                    await auto_stop_task
            stop_error: Exception | None = None
            try:
                async with self._command_lock:
                    await self._async_turn_both_off()
            except Exception as error:
                stop_error = error
            finally:
                await super().async_will_remove_from_hass()
            if stop_error is not None:
                raise stop_error
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation

    async def _async_run_direction(self, target_entity: str) -> None:
        self._validate_parameter_health()
        if self._removing:
            return
        self._command_generation += 1
        self._cancel_auto_stop_task()
        generation = self._command_generation
        self._pending_direction_commands += 1
        try:
            async with self._command_lock:
                await self._async_run_direction_locked(target_entity, generation)
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation
        finally:
            self._pending_direction_commands -= 1

    async def _async_run_direction_locked(
        self,
        target_entity: str,
        generation: int,
        duration: float | None = None,
        requested_target: int | None = None,
    ) -> None:
        """Start one direction while the command lock is held."""
        self._validate_parameter_health()
        if self._removing or generation != self._command_generation:
            return
        await self._async_turn_both_off()
        if self._reverse_dead_time:
            await asyncio.sleep(self._reverse_dead_time)
            if generation != self._command_generation:
                return
            await self._async_turn_both_off()
        if generation != self._command_generation:
            return
        await self._async_confirm_both_off(generation)
        if generation != self._command_generation or self._removing:
            return
        if requested_target is not None:
            if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
                self._validate_legacy_motion()
            self._sync_from_switches()
            position = self._estimator.position
            if position is not None:
                opening = requested_target > position
                target_entity = self._open_entity if opening else self._close_entity
                duration = abs(requested_target - position) / 100 * (
                    self._open_travel_time if opening else self._close_travel_time
                )
                if round(position) == requested_target:
                    return
        try:
            await self._async_turn_on(target_entity)
        except Exception:
            try:
                await self._async_turn_both_off()
            except Exception:
                _LOGGER.exception("Failed to clean up relays after direction start failure")
            raise
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            if generation != self._command_generation or self._removing:
                await self._async_turn_both_off()
                return
            self._legacy_direction = "opening" if target_entity == self._open_entity else "closing"
            self._position_basis = "command_estimated"
            self._interrupted_motion = True
            self._sync_from_switches()
        if (
            (duration is not None or self._auto_stop_at_travel_end or self._feedback_mode == FEEDBACK_LEGACY_EMOS)
            and not self._removing
            and generation == self._command_generation
        ):
            duration = duration if duration is not None else (
                self._open_travel_time
                if target_entity == self._open_entity
                else self._close_travel_time
            )
            self._auto_stop_target_entity = target_entity
            self._auto_stop_target_confirmed = False
            self._auto_stop_task = self.hass.async_create_task(
                self._async_auto_stop_after(duration, generation)
            )
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            # Arm safety first; publication errors may not disarm the stop.
            self.async_write_ha_state()

    async def _async_confirm_both_off(self, generation: int) -> None:
        """Require observed OFF, not only a successful service acknowledgement."""
        from homeassistant.exceptions import HomeAssistantError

        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            self._validate_legacy_motion()
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._off_confirmation_timeout
        while generation == self._command_generation and not self._removing:
            states = [
                self.hass.states.get(entity)
                for entity in (self._open_entity, self._close_entity)
            ]
            if all(state is not None and state.state == "off" for state in states):
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise HomeAssistantError("Both relays must be observed off before starting")
            await asyncio.sleep(min(0.01, remaining))

    def _validate_parameter_health(self) -> None:
        from homeassistant.exceptions import ServiceValidationError

        manager = self.hass.data.get(DOMAIN, {}).get("parameters", {}).get(self._entry.entry_id)
        if manager is not None and (manager.fault or manager.closing):
            raise ServiceValidationError(manager.fault or "Hardware policy unloading")

    async def _async_cleanup_cancelled_command(self) -> None:
        """Fail safe after a command that already invalidated the active generation."""
        cleanup_task = self.hass.async_create_task(
            self._async_turn_both_off_after_lock()
        )
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                continue
        try:
            cleanup_task.result()
        except asyncio.CancelledError:
            _LOGGER.error("Relay cleanup was cancelled after command cancellation")
        except Exception:
            _LOGGER.exception("Failed to clean up relays after command cancellation")

    async def _async_turn_both_off_after_lock(self) -> None:
        """Acquire command ownership before de-energizing both directions."""
        async with self._command_lock:
            await self._async_turn_both_off()

    async def _async_auto_stop_after(self, duration: float, generation: int) -> None:
        """De-energize both direction switches after one configured travel time."""
        try:
            await asyncio.sleep(duration)
            if generation != self._command_generation:
                return
            async with self._command_lock:
                if generation != self._command_generation:
                    return
                self._auto_stop_target_entity = None
                self._auto_stop_target_confirmed = False
                self._sync_from_switches()
                if self._target_position is not None:
                    self._target_operation = "stopping"
                    if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
                        with suppress(Exception):
                            self.async_write_ha_state()
                    else:
                        self.async_write_ha_state()
                await self._async_turn_both_off()
                if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
                    self._interrupted_motion = False
                if self._target_position is not None:
                    await self._async_confirm_both_off(generation)
                    if generation != self._command_generation or self._removing:
                        return
                    self._target_operation = "timer_elapsed"
            self._sync_from_switches()
            self.async_write_ha_state()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Failed to auto-stop greenhouse roll-up relays")
            if self._target_position is not None:
                self._target_operation = "error"
                with suppress(Exception):
                    self.async_write_ha_state()
        finally:
            if self._auto_stop_task is asyncio.current_task():
                self._auto_stop_task = None
                self._auto_stop_target_entity = None
                self._auto_stop_target_confirmed = False

    @callback
    def _cancel_auto_stop_if_source_changed(self, event: Event | None = None) -> None:
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            return
        target_entity = self._auto_stop_target_entity
        if self._auto_stop_task is None or target_entity is None:
            return
        opposite_entity = (
            self._close_entity
            if target_entity == self._open_entity
            else self._open_entity
        )
        event_data = event.data if event is not None else {}
        event_entity = event_data.get("entity_id")
        old_state = event_data.get("old_state")
        new_state = event_data.get("new_state")
        if event_entity == opposite_entity and getattr(new_state, "state", None) == STATE_ON:
            self._command_generation += 1
            self._cancel_auto_stop_task()
            return
        if event_entity == target_entity:
            old_value = getattr(old_state, "state", None)
            new_value = getattr(new_state, "state", None)
            if old_value == STATE_ON and new_value != STATE_ON:
                self._command_generation += 1
                self._cancel_auto_stop_task()
                return
            if new_value == STATE_ON:
                self._auto_stop_target_confirmed = True
                return
        target_state = self.hass.states.get(target_entity)
        opposite_state = self.hass.states.get(opposite_entity)
        if opposite_state is not None and opposite_state.state == STATE_ON:
            self._command_generation += 1
            self._cancel_auto_stop_task()
            return
        if target_state is not None and target_state.state == STATE_ON:
            self._auto_stop_target_confirmed = True
            return
        if not self._auto_stop_target_confirmed:
            return
        self._command_generation += 1
        self._cancel_auto_stop_task()

    @callback
    def _cancel_auto_stop_task(self) -> None:
        self._target_position = None
        self._target_operation = "idle"
        task = self._auto_stop_task
        self._auto_stop_task = None
        self._auto_stop_target_entity = None
        self._auto_stop_target_confirmed = False
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def _async_stop_active_relays_on_startup(self) -> None:
        """Never resume a stale or unverifiable relay command after HA was offline."""
        async with self._command_lock:
            await self._async_turn_both_off()

    async def _async_fail_safe_stop(self) -> None:
        self._command_generation += 1
        self._cancel_auto_stop_task()
        try:
            async with self._command_lock:
                await self._async_turn_both_off()
        except Exception:
            _LOGGER.exception("Failed to stop conflicting greenhouse roll-up relays")
        finally:
            self._conflict_stop_pending = False
            if self._conflict_stop_task is asyncio.current_task():
                self._conflict_stop_task = None

    async def _async_turn_both_off(self) -> None:
        self._sync_from_switches()
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            if self._legacy_direction != "idle":
                self._legacy_feedback_quarantine.add(
                    self._open_entity if self._legacy_direction == "opening" else self._close_entity)
            self._legacy_direction = "idle"
            self._estimator.sync(open_on=False, close_on=False, now=time.monotonic())
        first_error: BaseException | None = None
        for entity_id in (self._open_entity, self._close_entity):
            try:
                await self.hass.services.async_call(
                    SWITCH_DOMAIN,
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                    context=self._context,
                )
            except (Exception, asyncio.CancelledError) as error:
                if first_error is None:
                    first_error = error
        self._sync_from_switches()
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            self._stop_error = first_error is not None
        if first_error is not None:
            raise first_error

    async def _async_turn_on(self, entity_id: str) -> None:
        if self._feedback_mode == FEEDBACK_LEGACY_EMOS:
            self._legacy_feedback_quarantine.add(entity_id)
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
            context=self._context,
        )
