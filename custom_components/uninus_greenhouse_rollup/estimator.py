"""Pure timed-position estimator for a greenhouse roll-up curtain."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

CONFIDENCE_UNKNOWN = "unknown"
CONFIDENCE_ESTIMATED = "estimated"
CONFIDENCE_CALIBRATED = "calibrated"
_VALID_CONFIDENCE = {
    CONFIDENCE_UNKNOWN,
    CONFIDENCE_ESTIMATED,
    CONFIDENCE_CALIBRATED,
}


@dataclass(slots=True)
class RollupEstimator:
    """Estimate curtain position from mutually-exclusive timed relay commands.

    Position is expressed as 0 (fully closed) through 100 (fully open). When
    no starting position is known, a complete uninterrupted run establishes a
    calibrated endpoint without presenting a fabricated intermediate value.
    """

    open_travel_time: float
    close_travel_time: float
    position: float | None = None
    confidence: str = CONFIDENCE_UNKNOWN
    _direction: str = field(init=False, default="idle")
    _last_updated: float | None = field(init=False, default=None)
    _unknown_elapsed: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.open_travel_time = self._positive_time(self.open_travel_time)
        self.close_travel_time = self._positive_time(self.close_travel_time)
        self.position = self._normalize_position(self.position)
        if self.position is None:
            self.confidence = CONFIDENCE_UNKNOWN
        elif self.confidence not in _VALID_CONFIDENCE:
            self.confidence = CONFIDENCE_ESTIMATED
        self._direction = "idle"
        self._last_updated: float | None = None
        self._unknown_elapsed = 0.0

    @staticmethod
    def _positive_time(value: float) -> float:
        number = float(value)
        if number <= 0:
            raise ValueError("travel time must be greater than zero")
        return number

    @staticmethod
    def _normalize_position(value: float | None) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return max(0.0, min(100.0, numeric))

    @classmethod
    def from_snapshot(
        cls,
        open_travel_time: float,
        close_travel_time: float,
        snapshot: dict[str, Any] | None,
    ) -> "RollupEstimator":
        """Restore only durable position and confidence information."""
        snapshot = snapshot or {}
        confidence = snapshot.get("confidence", CONFIDENCE_UNKNOWN)
        position = cls._normalize_position(snapshot.get("position"))
        if confidence not in _VALID_CONFIDENCE or (
            snapshot.get("position") is not None and position is None
        ):
            return cls(open_travel_time, close_travel_time)
        return cls(
            open_travel_time,
            close_travel_time,
            position=position,
            confidence=confidence,
        )

    def sync(self, *, open_on: bool, close_on: bool, now: float) -> None:
        """Advance to ``now`` and synchronize the current relay commands."""
        self.advance(now)
        if open_on and close_on:
            next_direction = "conflict"
        elif open_on:
            next_direction = "opening"
        elif close_on:
            next_direction = "closing"
        else:
            next_direction = "idle"

        if next_direction != self._direction:
            if self.position is None:
                self._unknown_elapsed = 0.0
            self._direction = next_direction
        if self._last_updated is None or now >= self._last_updated:
            self._last_updated = float(now)

    def advance(self, now: float) -> None:
        """Advance the estimate, ignoring timestamps older than the last tick."""
        current = float(now)
        if self._last_updated is None:
            self._last_updated = current
            return
        if current < self._last_updated:
            return

        elapsed = current - self._last_updated
        self._last_updated = current
        if elapsed <= 0 or self._direction not in {"opening", "closing"}:
            return

        duration = (
            self.open_travel_time
            if self._direction == "opening"
            else self.close_travel_time
        )
        if self.position is None:
            self._unknown_elapsed += elapsed
            if self._unknown_elapsed >= duration:
                self.position = 100.0 if self._direction == "opening" else 0.0
                self.confidence = CONFIDENCE_CALIBRATED
            return

        delta = elapsed / duration * 100.0
        before = self.position
        if self._direction == "opening":
            self.position = min(100.0, self.position + delta)
            endpoint = 100.0
        else:
            self.position = max(0.0, self.position - delta)
            endpoint = 0.0

        if self.position == endpoint:
            self.confidence = CONFIDENCE_CALIBRATED
        elif self.position != before:
            self.confidence = CONFIDENCE_ESTIMATED

    @property
    def command_state(self) -> str:
        if self._direction == "conflict":
            return "conflict"
        if self._direction == "opening":
            return "opening_timer" if self.position == 100 else "opening"
        if self._direction == "closing":
            return "closing_timer" if self.position == 0 else "closing"
        return "idle"

    @property
    def is_opening(self) -> bool:
        return self.command_state == "opening"

    @property
    def is_closing(self) -> bool:
        return self.command_state == "closing"

    def snapshot(self) -> dict[str, float | str | None]:
        """Return the durable state stored by the Home Assistant entity."""
        return {
            "position": self.position,
            "confidence": self.confidence,
        }
