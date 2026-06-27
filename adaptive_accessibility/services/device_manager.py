from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Callable


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    category: str
    available: bool
    details: str


class DeviceManager:
    """Detects physical and simulated input devices used by the middleware."""

    def __init__(self, camera_index: int = 0, webcam_detection_enabled: bool = True) -> None:
        self.camera_index = camera_index
        self.webcam_detection_enabled = webcam_detection_enabled
        self.logger = logging.getLogger(__name__)

    def detect_devices(self) -> list[DeviceInfo]:
        detectors: list[Callable[[], DeviceInfo]] = [
            self._detect_keyboard,
            self._detect_mouse,
            self._detect_webcam,
            self._detect_gamepad,
            self._detect_controller_mapper,
            self._detect_adaptive_controller,
        ]
        devices: list[DeviceInfo] = []
        for detector in detectors:
            try:
                devices.append(detector())
            except Exception as exc:
                self.logger.exception("Device detector failed: %s", exc)
                devices.append(
                    DeviceInfo(
                        name="Unknown device",
                        category="Detection error",
                        available=False,
                        details=str(exc),
                    )
                )
        return devices

    def _detect_keyboard(self) -> DeviceInfo:
        return DeviceInfo(
            name="Keyboard",
            category="Standard input",
            available=True,
            details="System keyboard assumed available",
        )

    def _detect_mouse(self) -> DeviceInfo:
        return DeviceInfo(
            name="Mouse",
            category="Standard input",
            available=True,
            details="System pointing device assumed available",
        )

    def _detect_webcam(self) -> DeviceInfo:
        if not self.webcam_detection_enabled:
            return DeviceInfo(
                name="Webcam",
                category="Camera",
                available=False,
                details="Webcam scan disabled because gesture recognition is disabled",
            )

        if find_spec("cv2") is None:
            return DeviceInfo(
                name="Webcam",
                category="Camera",
                available=False,
                details="OpenCV is not installed",
            )

        import cv2

        capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        available = capture.isOpened()
        capture.release()
        return DeviceInfo(
            name="Webcam",
            category="Camera",
            available=available,
            details=(
                f"Camera index {self.camera_index} ready"
                if available
                else f"No camera found at index {self.camera_index}"
            ),
        )

    def _detect_gamepad(self) -> DeviceInfo:
        if find_spec("pygame") is None:
            return DeviceInfo(
                name="Gamepad",
                category="Controller",
                available=False,
                details="pygame is not installed",
            )

        import pygame

        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        details = f"{count} joystick/gamepad device(s) detected"
        return DeviceInfo(
            name="Gamepad",
            category="Controller",
            available=count > 0,
            details=details,
        )

    def _detect_controller_mapper(self) -> DeviceInfo:
        if find_spec("pygame") is None:
            return DeviceInfo(
                name="Controller mapper",
                category="Adaptive controller input",
                available=False,
                details="pygame is not installed",
            )

        import pygame

        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            details = f"Controller ready: {joystick.get_name()}"
        else:
            details = "No controller detected"

        return DeviceInfo(
            name="Controller mapper",
            category="Keyboard and mouse bridge",
            available=count > 0,
            details=details,
        )
    def _detect_adaptive_controller(self) -> DeviceInfo:
        return DeviceInfo(
            name="Adaptive controller",
            category="Assistive input",
            available=True,
            details="Simulated adaptive controller enabled for research demo",
        )

