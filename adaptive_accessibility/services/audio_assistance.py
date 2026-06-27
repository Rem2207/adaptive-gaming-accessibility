from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from time import sleep
from typing import Callable


@dataclass(frozen=True)
class SoundEvent:
    event_type: str
    label: str
    direction: str


class AudioAssist:
    """Simulates sound-event detection and emits visual accessibility events."""

    EVENTS = [
        SoundEvent("left_danger", "Danger detected on the left", "left"),
        SoundEvent("right_danger", "Danger detected on the right", "right"),
        SoundEvent("nearby_action", "Nearby action available", "center"),
    ]

    def __init__(self, callback: Callable[[SoundEvent], None], interval_seconds: float = 4.0) -> None:
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.enabled = True
        self.logger = logging.getLogger(__name__)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def trigger_event(self, event_type: str) -> None:
        event = next((item for item in self.EVENTS if item.event_type == event_type), None)
        if event:
            try:
                self.callback(event)
            except Exception as exc:
                self.logger.exception("Failed to dispatch sound event %s: %s", event_type, exc)

    def _run(self) -> None:
        while self._running:
            sleep(self.interval_seconds)
            if self._running and self.enabled:
                try:
                    self.callback(random.choice(self.EVENTS))
                except Exception as exc:
                    self.logger.exception("Failed to dispatch simulated sound event: %s", exc)
