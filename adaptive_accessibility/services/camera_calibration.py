from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TRACKING_FULL = "full"
TRACKING_LEFT = "left"
TRACKING_RIGHT = "right"
TRACKING_CUSTOM = "custom"
TRACKING_MODES = {TRACKING_FULL, TRACKING_LEFT, TRACKING_RIGHT, TRACKING_CUSTOM}
ZOOM_LEVELS = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class CameraCalibrationSettings:
    camera_index: int = 0
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    mirror: bool = True
    invert_movement: bool = False
    tracking_area: str = TRACKING_FULL


@dataclass(frozen=True)
class CalibrationResult:
    center_x: float
    center_y: float
    suggested_zoom: float
    status: str


class CameraCalibrator:
    """Applies software camera calibration before gesture recognition."""

    def __init__(self, settings: CameraCalibrationSettings | None = None) -> None:
        self.settings = settings or CameraCalibrationSettings()
        self.active_roi: tuple[int, int, int, int] | None = None

    def configure(self, settings: CameraCalibrationSettings) -> None:
        self.settings = settings

    def process_frame(self, frame: Any, cv2: Any) -> Any:
        if frame is None:
            self.active_roi = None
            return frame

        calibrated = cv2.flip(frame, 1) if self.settings.mirror else frame
        calibrated = self._apply_zoom(calibrated, cv2)
        calibrated = self._apply_tracking_area(calibrated)
        return calibrated

    def draw_feedback(
        self,
        frame: Any,
        cv2: Any,
        *,
        hand_position: tuple[float, float] | None,
        status: str,
        distance_quality: str,
    ) -> Any:
        if frame is None:
            return frame

        height, width = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (width - 1, height - 1), (37, 99, 235), 2)

        if hand_position is not None:
            x = max(0, min(width - 1, int(hand_position[0] * width)))
            y = max(0, min(height - 1, int(hand_position[1] * height)))
            cv2.circle(overlay, (x, y), 12, (22, 163, 74), -1)
            cv2.circle(overlay, (x, y), 20, (255, 255, 255), 2)

        return overlay

    def calibrate(self, hand_position: tuple[float, float] | None, distance_quality: str) -> CalibrationResult:
        if hand_position is None:
            return CalibrationResult(0.5, 0.5, self.settings.zoom, "calibration.no_hand")

        center_x, center_y = hand_position
        suggested_zoom = self.settings.zoom
        if distance_quality == "far":
            suggested_zoom = 1.5
        elif distance_quality == "too_close":
            suggested_zoom = 1.0
        elif self.settings.zoom < 1.25:
            suggested_zoom = 1.25

        return CalibrationResult(center_x, center_y, suggested_zoom, "calibration.ready")

    def _apply_zoom(self, frame: Any, cv2: Any) -> Any:
        zoom = min(ZOOM_LEVELS, key=lambda value: abs(value - self.settings.zoom))
        if zoom <= 1.0:
            return frame

        height, width = frame.shape[:2]
        crop_width = max(1, int(width / zoom))
        crop_height = max(1, int(height / zoom))
        center_x = width // 2 + int(self.settings.offset_x * (width - crop_width) / 2)
        center_y = height // 2 + int(self.settings.offset_y * (height - crop_height) / 2)
        left = max(0, min(width - crop_width, center_x - crop_width // 2))
        top = max(0, min(height - crop_height, center_y - crop_height // 2))
        cropped = frame[top : top + crop_height, left : left + crop_width]
        return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)

    def _apply_tracking_area(self, frame: Any) -> Any:
        height, width = frame.shape[:2]
        mode = self.settings.tracking_area if self.settings.tracking_area in TRACKING_MODES else TRACKING_FULL

        if mode == TRACKING_FULL:
            self.active_roi = (0, 0, width, height)
            return frame

        if mode == TRACKING_LEFT:
            left, roi_width = 0, width // 2
        elif mode == TRACKING_RIGHT:
            left, roi_width = width // 2, width - width // 2
        else:
            roi_width = max(80, int(width * 0.55))
            roi_height = max(80, int(height * 0.7))
            center_x = width // 2 + int(self.settings.offset_x * (width - roi_width) / 2)
            center_y = height // 2 + int(self.settings.offset_y * (height - roi_height) / 2)
            left = max(0, min(width - roi_width, center_x - roi_width // 2))
            top = max(0, min(height - roi_height, center_y - roi_height // 2))
            self.active_roi = (left, top, roi_width, roi_height)
            return frame[top : top + roi_height, left : left + roi_width]

        top = 0
        self.active_roi = (left, top, roi_width, height)
        return frame[top : top + height, left : left + roi_width]
