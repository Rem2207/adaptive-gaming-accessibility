from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any


class OverlayManager:
    """Process-backed controller for the transparent audio alert overlay."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.logger = logging.getLogger(__name__)
        self.settings = self._normalize_settings(settings or {})
        self._process: subprocess.Popen[str] | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def configure(self, settings: dict[str, Any] | None = None) -> None:
        if settings:
            self.settings.update(self._normalize_settings(settings))
        if self.running:
            self._send({"type": "configure", "settings": self.settings})

    def start(self) -> None:
        if self.running:
            return
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "adaptive_accessibility.ui.overlay_process"],
                cwd=str(self._project_root()),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
            self.configure(self.settings)
        except Exception as exc:
            self.logger.exception("Could not start overlay process: %s", exc)
            self._process = None

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            self._send_to_process(process, {"type": "stop"})
            process.wait(timeout=1.2)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=0.8)
            except Exception:
                try:
                    process.kill()
                except Exception as exc:
                    self.logger.debug("Could not kill overlay process: %s", exc)

    def show_event(self, event: Any) -> None:
        if not self.running:
            self.start()
        direction = str(getattr(event, "direction", "center"))
        event_type = str(getattr(event, "event_type", "nearby_action"))
        self._send({"type": "event", "direction": direction, "event_type": event_type})

    def _send(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            self._process = None
            return
        self._send_to_process(process, payload)

    def _send_to_process(self, process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
        except Exception as exc:
            self.logger.debug("Could not send overlay command: %s", exc)

    def _normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        labels = settings.get("labels")
        if not isinstance(labels, dict):
            labels = {}
        return {
            "opacity": self._coerce_float(settings.get("opacity", 0.82), 0.1, 1.0),
            "duration": self._coerce_float(settings.get("duration", 1.4), 0.3, 8.0),
            "size": int(self._coerce_float(settings.get("size", 180), 80, 420)),
            "labels": {
                "left": str(labels.get("left", "LEFT DANGER")),
                "center": str(labels.get("center", "ACTION NEARBY")),
                "right": str(labels.get("right", "RIGHT DANGER")),
            },
        }

    def _coerce_float(self, value: Any, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        return max(minimum, min(maximum, number))

    def _project_root(self):
        return __import__("pathlib").Path(__file__).resolve().parents[2]
