from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.util import find_spec
from time import monotonic

from adaptive_accessibility.core.constants import HAND_LANDMARKER_TASK_FILE
from adaptive_accessibility.services.camera_calibration import CameraCalibrationSettings, CameraCalibrator


@dataclass(frozen=True)
class GestureFrame:
    ok: bool
    frame: object | None
    gesture: str | None
    status: str
    hand_position: tuple[float, float] | None = None
    distance_quality: str = "unknown"


class GestureRecognizer:
    """Recognizes simple hand gestures from a webcam stream."""

    def __init__(self, camera_index: int = 0, calibration_settings: CameraCalibrationSettings | None = None) -> None:
        self.camera_index = camera_index
        self.logger = logging.getLogger(__name__)
        self.capture = None
        self._cv2 = None
        self._mp_hands = None
        self._hands = None
        self._mp_tasks_hand_landmarker = None
        self._mp_image_module = None
        self._previous_x: float | None = None
        self._smoothed_x: float | None = None
        self._last_motion_gesture_at = 0.0
        self._background_frame = None
        self.calibrator = CameraCalibrator(calibration_settings)
        self.last_hand_position: tuple[float, float] | None = None
        self.last_distance_quality = "unknown"
        self._load_backends()

    @property
    def mediapipe_enabled(self) -> bool:
        return self._hands is not None or self._mp_tasks_hand_landmarker is not None

    def start(self) -> bool:
        if self._cv2 is None:
            return False
        self.capture = self._cv2.VideoCapture(self.camera_index, self._cv2.CAP_DSHOW)
        return bool(self.capture and self.capture.isOpened())

    def stop(self) -> None:
        if self.capture is not None:
            self.capture.release()
        self.capture = None
        if self._hands is not None:
            self._hands.close()
        if self._mp_tasks_hand_landmarker is not None:
            self._mp_tasks_hand_landmarker.close()

    def read(self) -> GestureFrame:
        if self.capture is None:
            return GestureFrame(False, None, None, "Camera is not running")

        ok, frame = self.capture.read()
        if not ok:
            return GestureFrame(False, None, None, "Unable to read webcam frame")

        frame = self.calibrator.process_frame(frame, self._cv2)
        if self._hands is not None:
            gesture, status = self._read_with_mediapipe(frame)
        elif self._mp_tasks_hand_landmarker is not None:
            gesture, status = self._read_with_mediapipe_tasks(frame)
        else:
            gesture, status = self._read_with_motion_fallback(frame)

        preview = self.calibrator.draw_feedback(
            frame,
            self._cv2,
            hand_position=self.last_hand_position,
            status=status,
            distance_quality=self.last_distance_quality,
        )
        return GestureFrame(True, preview, gesture, status, self.last_hand_position, self.last_distance_quality)

    def configure_calibration(self, settings: CameraCalibrationSettings) -> None:
        if settings == self.calibrator.settings:
            return
        self.calibrator.configure(settings)
        self._background_frame = None

    def encode_frame(self, frame: object) -> bytes | None:
        if self._cv2 is None or frame is None:
            return None
        ok, buffer = self._cv2.imencode(".jpg", frame, [int(self._cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return None
        return buffer.tobytes()

    def _load_backends(self) -> None:
        if find_spec("cv2") is None:
            return

        import cv2

        self._cv2 = cv2

        if find_spec("mediapipe") is None:
            return

        try:
            import mediapipe as mp
        except Exception as exc:
            self.logger.warning("MediaPipe import failed; using OpenCV fallback: %s", exc)
            return

        try:
            solutions = getattr(mp, "solutions", None)
            if solutions is None or not hasattr(solutions, "hands"):
                self._load_mediapipe_tasks(mp)
                return

            self._mp_hands = solutions.hands
            self._hands = self._mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.55,
            )
        except Exception as exc:
            self._mp_hands = None
            self._hands = None
            self._load_mediapipe_tasks(mp)
            self.logger.warning("MediaPipe Hands initialization failed; using OpenCV fallback: %s", exc)

    def _load_mediapipe_tasks(self, mp: object) -> None:
        try:
            if not HAND_LANDMARKER_TASK_FILE.exists():
                self.logger.warning("MediaPipe hand landmarker model not found: %s", HAND_LANDMARKER_TASK_FILE)
                return
            vision = mp.tasks.vision
            base_options = mp.tasks.BaseOptions
            options = vision.HandLandmarkerOptions(
                base_options=base_options(model_asset_path=str(HAND_LANDMARKER_TASK_FILE)),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.45,
                min_hand_presence_confidence=0.45,
                min_tracking_confidence=0.45,
            )
            self._mp_tasks_hand_landmarker = vision.HandLandmarker.create_from_options(options)
            self._mp_image_module = mp
        except Exception as exc:
            self._mp_tasks_hand_landmarker = None
            self.logger.warning("MediaPipe Tasks Hands API is unavailable; using OpenCV fallback: %s", exc)

    def _read_with_mediapipe(self, frame: object) -> tuple[str | None, str]:
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)

        if not result.multi_hand_landmarks:
            self._previous_x = None
            self.last_hand_position = None
            self.last_distance_quality = "unknown"
            return None, "Waiting for hand gesture"

        return self._read_landmark_gesture([hand.landmark for hand in result.multi_hand_landmarks])

    def _read_with_mediapipe_tasks(self, frame: object) -> tuple[str | None, str]:
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        image = self._mp_image_module.Image(image_format=self._mp_image_module.ImageFormat.SRGB, data=rgb)
        result = self._mp_tasks_hand_landmarker.detect(image)

        if not result.hand_landmarks:
            self._previous_x = None
            self.last_hand_position = None
            self.last_distance_quality = "unknown"
            return None, "Waiting for hand gesture"

        return self._read_landmark_gesture(result.hand_landmarks)

    def _read_landmark_gesture(self, detected_hands: list[object]) -> tuple[str | None, str]:
        if not detected_hands:
            self._previous_x = None
            self.last_hand_position = None
            self.last_distance_quality = "unknown"
            return None, "Waiting for hand gesture"

        wrists = [landmarks[0] for landmarks in detected_hands]
        center_x = sum(wrist.x for wrist in wrists) / len(wrists)
        center_y = sum(wrist.y for wrist in wrists) / len(wrists)
        self.last_hand_position = (center_x, center_y)
        self.last_distance_quality = self._combined_distance_quality(detected_hands)

        movement_gesture = self._detect_horizontal_movement(center_x)
        shape_gesture = self._detect_multi_hand_shape(detected_hands)
        raise_gesture = "hand_raise" if any(landmarks[8].y < 0.28 for landmarks in detected_hands) else None

        gesture = shape_gesture or movement_gesture or raise_gesture
        status = f"Detected {self._format_gesture(gesture)}" if gesture else "Hand tracked"
        return gesture, status

    def _detect_horizontal_movement(self, current_x: float) -> str | None:
        if self._previous_x is None:
            self._previous_x = current_x
            return None

        if self._smoothed_x is None:
            self._smoothed_x = current_x

        self._smoothed_x = (self._smoothed_x * 0.65) + (current_x * 0.35)
        delta = self._smoothed_x - self._previous_x
        if self.calibrator.settings.invert_movement:
            delta *= -1
        self._previous_x = self._smoothed_x
        now = monotonic()
        if now - self._last_motion_gesture_at < 0.8:
            return None

        if abs(delta) < 0.07:
            return None

        if delta < 0:
            self._last_motion_gesture_at = now
            return "left_movement"
        if delta > 0:
            self._last_motion_gesture_at = now
            return "right_movement"
        return None

    def _detect_hand_shape(self, landmarks: object) -> str | None:
        raised_count = self._raised_finger_count(landmarks)

        if raised_count <= 0:
            return "closed_fist"
        if 1 <= raised_count <= 5:
            return f"finger_count_{raised_count}"

        if self._looks_like_open_palm(landmarks):
            return "open_hand"
        return None

    def _detect_multi_hand_shape(self, detected_hands: list[object]) -> str | None:
        if len(detected_hands) == 1:
            return self._detect_hand_shape(detected_hands[0])

        total_raised = sum(self._raised_finger_count(landmarks) for landmarks in detected_hands)
        if total_raised <= 0:
            return "closed_fist"
        if 1 <= total_raised <= 10:
            return f"finger_count_{total_raised}"
        return None

    def _raised_finger_count(self, landmarks: object) -> int:
        finger_states = self._finger_states(landmarks)
        return sum(1 for raised in finger_states.values() if raised)

    def _looks_like_open_palm(self, landmarks: object) -> bool:
        finger_states = self._finger_states(landmarks)
        non_thumb_count = sum(1 for name in ("index", "middle", "ring", "pinky") if finger_states.get(name))
        hand_width = max(landmark.x for landmark in landmarks) - min(landmark.x for landmark in landmarks)
        hand_height = max(landmark.y for landmark in landmarks) - min(landmark.y for landmark in landmarks)
        return non_thumb_count >= 4 and hand_width > max(hand_height * 0.48, 0.16)

    def _finger_states(self, landmarks: object) -> dict[str, bool]:
        wrist = landmarks[0]
        states: dict[str, bool] = {}

        thumb_tip = landmarks[4]
        thumb_ip = landmarks[3]
        thumb_mcp = landmarks[2]
        thumb_tip_distance = self._landmark_distance(thumb_tip, wrist)
        thumb_ip_distance = self._landmark_distance(thumb_ip, wrist)
        thumb_mcp_distance = self._landmark_distance(thumb_mcp, wrist)
        thumb_horizontal_extension = abs(thumb_tip.x - wrist.x) > abs(thumb_ip.x - wrist.x) * 1.08
        states["thumb"] = thumb_tip_distance > max(thumb_ip_distance * 1.08, thumb_mcp_distance * 1.16) and thumb_horizontal_extension

        fingers = {
            "index": (8, 6, 5),
            "middle": (12, 10, 9),
            "ring": (16, 14, 13),
            "pinky": (20, 18, 17),
        }
        for name, (tip_id, pip_id, mcp_id) in fingers.items():
            tip = landmarks[tip_id]
            pip = landmarks[pip_id]
            mcp = landmarks[mcp_id]
            tip_to_wrist = self._landmark_distance(tip, wrist)
            pip_to_wrist = self._landmark_distance(pip, wrist)
            mcp_to_wrist = self._landmark_distance(mcp, wrist)
            states[name] = tip.y < pip.y and tip_to_wrist > max(pip_to_wrist * 1.04, mcp_to_wrist * 1.16)

        return states

    def _landmark_distance(self, first: object, second: object) -> float:
        dx = first.x - second.x
        dy = first.y - second.y
        dz = getattr(first, "z", 0.0) - getattr(second, "z", 0.0)
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    def _read_with_motion_fallback(self, frame: object) -> tuple[str | None, str]:
        height, width = frame.shape[:2]
        roi_top = int(height * 0.32)
        roi_bottom = int(height * 0.95)
        roi = frame[roi_top:roi_bottom, :]

        gray = self._cv2.cvtColor(roi, self._cv2.COLOR_BGR2GRAY)
        gray = self._cv2.GaussianBlur(gray, (15, 15), 0)

        if self._background_frame is None:
            self._background_frame = gray.copy()
            return None, "OpenCV fallback active; calibrating motion"

        diff = self._cv2.absdiff(self._background_frame, gray)
        _, threshold = self._cv2.threshold(diff, 36, 255, self._cv2.THRESH_BINARY)
        threshold = self._cv2.dilate(threshold, None, iterations=2)
        contours, _ = self._cv2.findContours(
            threshold,
            self._cv2.RETR_EXTERNAL,
            self._cv2.CHAIN_APPROX_SIMPLE,
        )

        if not contours:
            self._background_frame = self._cv2.addWeighted(gray, 0.08, self._background_frame, 0.92, 0)
            self.last_hand_position = None
            self.last_distance_quality = "unknown"
            return None, "OpenCV fallback active; no motion"

        candidates = []
        for contour in contours:
            area = self._cv2.contourArea(contour)
            if area < 1800:
                continue
            x, y, w, h = self._cv2.boundingRect(contour)
            if w < 35 or h < 35:
                continue
            aspect_ratio = w / max(h, 1)
            if aspect_ratio > 3.8:
                continue
            center_y = y + h / 2
            if center_y < roi.shape[0] * 0.12:
                continue
            candidates.append((area, x, y, w, h))

        if not candidates:
            self._background_frame = self._cv2.addWeighted(gray, 0.08, self._background_frame, 0.92, 0)
            self.last_hand_position = None
            self.last_distance_quality = "unknown"
            return None, "OpenCV fallback active; low motion"

        area, x, y, w, h = max(candidates, key=lambda item: item[0])
        center_x = (x + w / 2) / width
        center_y = (roi_top + y + h / 2) / height
        self.last_hand_position = (center_x, center_y)
        self.last_distance_quality = self._distance_quality_from_area(area, width * height)
        gesture = self._detect_horizontal_movement(center_x)
        self._background_frame = self._cv2.addWeighted(gray, 0.08, self._background_frame, 0.92, 0)
        return gesture, "OpenCV fallback active; move hand left or right"

    def _distance_quality_from_landmarks(self, landmarks: object) -> str:
        xs = [landmark.x for landmark in landmarks]
        ys = [landmark.y for landmark in landmarks]
        size = max(max(xs) - min(xs), max(ys) - min(ys))
        if size < 0.18:
            return "far"
        if size > 0.62:
            return "too_close"
        return "good"

    def _combined_distance_quality(self, detected_hands: list[object]) -> str:
        qualities = [self._distance_quality_from_landmarks(landmarks) for landmarks in detected_hands]
        if "too_close" in qualities:
            return "too_close"
        if "good" in qualities:
            return "good"
        if "far" in qualities:
            return "far"
        return "unknown"

    def _distance_quality_from_area(self, area: float, frame_area: float) -> str:
        ratio = area / max(frame_area, 1)
        if ratio < 0.02:
            return "far"
        if ratio > 0.22:
            return "too_close"
        return "good"

    def _format_gesture(self, gesture: str | None) -> str:
        if gesture is None:
            return "none"
        return gesture.replace("_", " ")
