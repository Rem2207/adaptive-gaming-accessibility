from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.util import find_spec
from time import monotonic

from adaptive_accessibility.core.constants import DEFAULT_GESTURE_MAPPINGS


@dataclass(frozen=True)
class MappingResult:
    gesture: str
    command: str
    executed: bool
    message: str


class InputMapper:
    """Converts recognized gestures into keyboard commands for the game."""

    def __init__(
        self,
        simulate_inputs: bool = True,
        cooldown_seconds: float = 0.65,
        mappings: dict[str, str] | None = None,
    ) -> None:
        self.simulate_inputs = simulate_inputs
        self.cooldown_seconds = cooldown_seconds
        self.mappings = {**DEFAULT_GESTURE_MAPPINGS, **dict(mappings or {})}
        self.logger = logging.getLogger(__name__)
        self._last_sent_at: dict[str, float] = {}
        self._keyboard = None
        self._key_lookup = {}
        self._load_keyboard_backend()

    @property
    def backend_available(self) -> bool:
        return self._keyboard is not None

    def set_simulation(self, enabled: bool) -> None:
        self.simulate_inputs = enabled

    def set_mappings(self, mappings: dict[str, str]) -> None:
        self.mappings = {**DEFAULT_GESTURE_MAPPINGS, **dict(mappings)}

    def map_gesture(self, gesture: str) -> MappingResult | None:
        command = self.mappings.get(gesture)
        if command is None:
            return None

        now = monotonic()
        if now - self._last_sent_at.get(gesture, 0.0) < self.cooldown_seconds:
            return None

        self._last_sent_at[gesture] = now

        if self.simulate_inputs:
            return MappingResult(
                gesture=gesture,
                command=command,
                executed=False,
                message=f"Simulated command: {gesture} -> {command.upper()}",
            )

        if self._keyboard is None:
            return MappingResult(
                gesture=gesture,
                command=command,
                executed=False,
                message="pynput unavailable; command logged only",
            )

        key = self._key_lookup.get(command, command)
        try:
            self._keyboard.press(key)
            self._keyboard.release(key)
        except Exception as exc:
            self.logger.exception("Failed to send keyboard command for %s: %s", gesture, exc)
            return MappingResult(
                gesture=gesture,
                command=command,
                executed=False,
                message=f"Failed to send command: {gesture} -> {command.upper()}",
            )

        return MappingResult(
            gesture=gesture,
            command=command,
            executed=True,
            message=f"Sent command: {gesture} -> {command.upper()}",
        )

    def _load_keyboard_backend(self) -> None:
        if find_spec("pynput") is None:
            return

        try:
            from pynput.keyboard import Controller, Key
        except Exception as exc:
            self.logger.exception("Failed to initialize pynput keyboard backend: %s", exc)
            return

        self._keyboard = Controller()
        self._key_lookup = {
            "space": Key.space,
            "enter": Key.enter,
        }
