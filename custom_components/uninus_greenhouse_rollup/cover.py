"""Remembered, time-estimated Cover entity backed by two switch entities."""

from __future__ import annotations

import asyncio
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
    CONF_CLOSE_ENTITY,
    CONF_CLOSE_TRAVEL_TIME,
    CONF_OPEN_ENTITY,
    CONF_OPEN_TRAVEL_TIME,
    CONF_REVERSE_DEAD_TIME,
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
        self._estimator = RollupEstimator(
            self._open_travel_time,
            self._close_travel_time,
        )
        self._relays_available = False
        self._command_lock = asyncio.Lock()
        self._command_generation = 0
        self._conflict_stop_pending = False
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
        self._sync_from_switches()
        self.async_write_ha_state()
        if (
            self._estimator.command_state == "conflict"
            and not self._conflict_stop_pending
        ):
            self._conflict_stop_pending = True
            self.hass.async_create_task(self._async_fail_safe_stop())

    @callback
    def _handle_tick(self, _now: Any) -> None:
        """Update estimated position while a command timer is active."""
        if not self._relays_available:
            return
        self._estimator.advance(time.monotonic())
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
        async with self._command_lock:
            await self._async_turn_both_off()
        self._sync_from_switches()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Leave both actuators in a safe state on unload or reload."""
        self._command_generation += 1
        open_state = self.hass.states.get(self._open_entity)
        close_state = self.hass.states.get(self._close_entity)
        if (open_state and open_state.state == STATE_ON) or (
            close_state and close_state.state == STATE_ON
        ):
            async with self._command_lock:
                await self._async_turn_both_off()
        await super().async_will_remove_from_hass()

    async def _async_run_direction(self, target_entity: str) -> None:
        self._command_generation += 1
        generation = self._command_generation
        async with self._command_lock:
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

    async def _async_stop_active_relays_on_startup(self) -> None:
        """Never resume a stale relay command after HA was offline."""
        open_state = self.hass.states.get(self._open_entity)
        close_state = self.hass.states.get(self._close_entity)
        if (open_state and open_state.state == STATE_ON) or (
            close_state and close_state.state == STATE_ON
        ):
            async with self._command_lock:
                await self._async_turn_both_off()

    async def _async_fail_safe_stop(self) -> None:
        self._command_generation += 1
        try:
            async with self._command_lock:
                await self._async_turn_both_off()
        except Exception:
            _LOGGER.exception("Failed to stop conflicting greenhouse roll-up relays")
        finally:
            self._conflict_stop_pending = False

    async def _async_turn_both_off(self) -> None:
        first_error: Exception | None = None
        for entity_id in (self._open_entity, self._close_entity):
            try:
                await self.hass.services.async_call(
                    SWITCH_DOMAIN,
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                    context=self._context,
                )
            except Exception as error:
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
