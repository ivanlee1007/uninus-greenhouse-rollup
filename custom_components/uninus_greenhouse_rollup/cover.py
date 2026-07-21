"""Remembered, time-estimated Cover entity backed by two switch entities."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
import logging
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
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_AUTO_STOP_AT_TRAVEL_END,
    CONF_CLOSE_ENTITY,
    CONF_CLOSE_TRAVEL_TIME,
    CONF_OPEN_ENTITY,
    CONF_OPEN_TRAVEL_TIME,
    CONF_REVERSE_DEAD_TIME,
    DEFAULT_AUTO_STOP_AT_TRAVEL_END,
    DEFAULT_REVERSE_DEAD_TIME,
    DOMAIN,
)
from .estimator import CONFIDENCE_UNKNOWN, RollupEstimator

_UPDATE_INTERVAL = timedelta(seconds=1)
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the remembered cover for one switch pair."""
    data = {**entry.data, **entry.options}
    async_add_entities([UninusGreenhouseRollupCover(entry, data)])


class UninusGreenhouseRollupCover(CoverEntity, RestoreEntity):
    """Optimistic roll-up cover whose position is integrated over time."""

    _attr_assumed_state = True
    _attr_device_class = CoverDeviceClass.AWNING
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, entry: ConfigEntry, data: dict[str, Any]) -> None:
        self._entry = entry
        self._open_entity = data[CONF_OPEN_ENTITY]
        self._close_entity = data[CONF_CLOSE_ENTITY]
        self._open_travel_time = float(data[CONF_OPEN_TRAVEL_TIME])
        self._close_travel_time = float(data[CONF_CLOSE_TRAVEL_TIME])
        self._reverse_dead_time = max(
            0.0, float(data.get(CONF_REVERSE_DEAD_TIME, DEFAULT_REVERSE_DEAD_TIME))
        )
        self._auto_stop_at_travel_end = bool(
            data.get(CONF_AUTO_STOP_AT_TRAVEL_END, DEFAULT_AUTO_STOP_AT_TRAVEL_END)
        )
        self._estimator = RollupEstimator(
            self._open_travel_time,
            self._close_travel_time,
        )
        self._relays_available = False
        self._command_lock = asyncio.Lock()
        self._command_generation = 0
        self._conflict_stop_pending = False
        self._conflict_stop_task: asyncio.Task[None] | None = None
        self._auto_stop_task: asyncio.Task[None] | None = None
        self._auto_stop_target_entity: str | None = None
        self._auto_stop_target_confirmed = False
        self._removing = False
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=str(data.get(CONF_NAME, entry.title)),
            manufacturer="UNiNUS",
            model="Timed dual-switch greenhouse roll-up",
        )

    async def async_added_to_hass(self) -> None:
        """Restore position, then observe both underlying switches."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._estimator = RollupEstimator.from_snapshot(
                self._open_travel_time,
                self._close_travel_time,
                {
                    "position": last_state.attributes.get(ATTR_CURRENT_POSITION),
                    "confidence": last_state.attributes.get(
                        "position_confidence", CONFIDENCE_UNKNOWN
                    ),
                },
            )

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

    @callback
    def _handle_state_event(self, event: Event) -> None:
        """Synchronize after direct, automation, or card switch changes."""
        if self._removing:
            return
        self._cancel_auto_stop_if_source_changed(event)
        self._sync_from_switches()
        self.async_write_ha_state()
        if (
            self._estimator.command_state == "conflict"
            and not self._conflict_stop_pending
        ):
            self._conflict_stop_pending = True
            self._conflict_stop_task = self.hass.async_create_task(
                self._async_fail_safe_stop()
            )

    @callback
    def _handle_tick(self, _now: Any) -> None:
        """Resync source states and update the estimate every interval."""
        self._sync_from_switches()
        self.async_write_ha_state()

    @callback
    def _sync_from_switches(self) -> None:
        now = time.monotonic()
        open_state = self.hass.states.get(self._open_entity)
        close_state = self.hass.states.get(self._close_entity)
        invalid = {STATE_UNAVAILABLE, STATE_UNKNOWN}
        self._relays_available = bool(
            open_state
            and close_state
            and open_state.state not in invalid
            and close_state.state not in invalid
        )
        if not self._relays_available:
            self._estimator.sync(open_on=False, close_on=False, now=now)
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
        return {
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
            "auto_stop_at_travel_end": self._auto_stop_at_travel_end,
            "position_is_estimated": True,
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Turn both relays off, pause, then start opening."""
        await self._async_run_direction(self._open_entity)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Turn both relays off, pause, then start closing."""
        await self._async_run_direction(self._close_entity)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop either direction and freeze the current estimate."""
        self._command_generation += 1
        self._cancel_auto_stop_task()
        try:
            async with self._command_lock:
                await self._async_turn_both_off()
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation
        self._sync_from_switches()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Leave both actuators in a safe state on unload or reload."""
        self._removing = True
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
        if self._removing:
            return
        self._command_generation += 1
        self._cancel_auto_stop_task()
        generation = self._command_generation
        try:
            async with self._command_lock:
                await self._async_run_direction_locked(target_entity, generation)
        except asyncio.CancelledError as cancellation:
            await self._async_cleanup_cancelled_command()
            raise cancellation

    async def _async_run_direction_locked(
        self, target_entity: str, generation: int
    ) -> None:
        """Start one direction while the command lock is held."""
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
        try:
            await self._async_turn_on(target_entity)
        except Exception:
            try:
                await self._async_turn_both_off()
            except Exception:
                _LOGGER.exception("Failed to clean up relays after direction start failure")
            raise
        if (
            self._auto_stop_at_travel_end
            and not self._removing
            and generation == self._command_generation
        ):
            duration = (
                self._open_travel_time
                if target_entity == self._open_entity
                else self._close_travel_time
            )
            self._auto_stop_target_entity = target_entity
            self._auto_stop_target_confirmed = False
            self._auto_stop_task = self.hass.async_create_task(
                self._async_auto_stop_after(duration, generation)
            )

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
                await self._async_turn_both_off()
            self._sync_from_switches()
            self.async_write_ha_state()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Failed to auto-stop greenhouse roll-up relays")
        finally:
            if self._auto_stop_task is asyncio.current_task():
                self._auto_stop_task = None
                self._auto_stop_target_entity = None
                self._auto_stop_target_confirmed = False

    @callback
    def _cancel_auto_stop_if_source_changed(self, event: Event | None = None) -> None:
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
        if first_error is not None:
            raise first_error

    async def _async_turn_on(self, entity_id: str) -> None:
        await self.hass.services.async_call(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
            context=self._context,
        )
