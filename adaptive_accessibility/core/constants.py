from __future__ import annotations

from pathlib import Path

from .i18n import DEFAULT_LANGUAGE


APP_NAME = "Adaptive Gaming Accessibility System"
APP_VERSION = "0.2.0"

BASE_DIR = Path(__file__).resolve().parents[2]
PACKAGE_DIR = BASE_DIR / "adaptive_accessibility"
CONFIG_DIR = PACKAGE_DIR / "config"
MODEL_DIR = PACKAGE_DIR / "models"
HAND_LANDMARKER_TASK_FILE = MODEL_DIR / "hand_landmarker.task"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "adaptive_accessibility.log"

DEFAULT_WINDOW_SIZE = "1280x800"
MIN_WINDOW_WIDTH = 1280
MIN_WINDOW_HEIGHT = 800

DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAMERA_CALIBRATION_SETTINGS = {
    "zoom": 1.0,
    "offset_x": 0.0,
    "offset_y": 0.0,
    "mirror": True,
    "invert_movement": False,
    "tracking_area": "full",
}
DEFAULT_AUDIO_INTERVAL_SECONDS = 4.0
DEFAULT_INPUT_COOLDOWN_SECONDS = 0.65

DEFAULT_AUDIO_DETECTION_SETTINGS = {
    "enabled": False,
    "overlay_enabled": True,
    "sensitivity": 0.18,
    "minimum_volume": 0.02,
    "detection_interval": 0.15,
    "overlay_opacity": 0.82,
    "overlay_duration": 1.4,
    "overlay_size": 180,
}

DEFAULT_GESTURE_MAPPINGS = {
    "left_movement": "a",
    "right_movement": "d",
    "finger_count_1": "1",
    "finger_count_2": "2",
    "finger_count_3": "3",
    "finger_count_4": "4",
    "finger_count_5": "5",
    "finger_count_6": "6",
    "finger_count_7": "7",
    "finger_count_8": "8",
    "finger_count_9": "9",
    "finger_count_10": "0",
    "open_hand": "space",
    "closed_fist": "enter",
}

GESTURE_MAPPING_ORDER = (
    "closed_fist",
    "finger_count_1",
    "finger_count_2",
    "finger_count_3",
    "finger_count_4",
    "finger_count_5",
    "finger_count_6",
    "finger_count_7",
    "finger_count_8",
    "finger_count_9",
    "finger_count_10",
    "open_hand",
    "left_movement",
    "right_movement",
)

DEFAULT_CONTROLLER_REPEAT_RATE = 10
DEFAULT_CONTROLLER_ACTIVATION_MODE = "tap"
DEFAULT_CONTROLLER_HOLD_MODE = "hold"

DEFAULT_CONTROLLER_BUTTON_MAPPINGS = {
    "A": {"key": "space", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "B": {"key": "enter", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "X": {"key": "e", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "Y": {"key": "f", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "LB": {"key": "q", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "RB": {"key": "r", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "LT": {"key": "mouse:right_click", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "RT": {"key": "mouse:left_click", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "Start": {"key": "escape", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "Select": {"key": "tab", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "L3": {"key": "shift", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "R3": {"key": "ctrl", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "DPad Up": {"key": "mouse:up", "mode": DEFAULT_CONTROLLER_HOLD_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "DPad Down": {"key": "mouse:down", "mode": DEFAULT_CONTROLLER_HOLD_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "DPad Left": {"key": "mouse:left", "mode": DEFAULT_CONTROLLER_HOLD_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    "DPad Right": {"key": "mouse:right", "mode": DEFAULT_CONTROLLER_HOLD_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
}

DEFAULT_CONTROLLER_STICK_SETTINGS = {
    "left_stick": {
        "mode": "mouse",
        "up": {"key": "w", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "down": {"key": "s", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "left": {"key": "a", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "right": {"key": "d", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    },
    "right_stick": {
        "mode": "disabled",
        "up": {"key": "up", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "down": {"key": "down", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "left": {"key": "left", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
        "right": {"key": "right", "mode": DEFAULT_CONTROLLER_ACTIVATION_MODE, "repeat_rate": DEFAULT_CONTROLLER_REPEAT_RATE},
    },
}

DEFAULT_CONTROLLER_MOUSE_SETTINGS = {
    "x_sensitivity": 18.0,
    "y_sensitivity": 18.0,
    "deadzone": 0.18,
    "invert_x": False,
    "invert_y": False,
    "acceleration_enabled": False,
    "acceleration_factor": 1.4,
    "smoothing": 0.35,
    "digital_mouse_step": 18.0,
}

CONTROLLER_PROFILE_DIR = CONFIG_DIR / "controller_profiles"

PROFILE_MOTOR = "motor_accessibility"
PROFILE_HEARING = "hearing_accessibility"
PROFILE_COMBINED = "combined"
PROFILE_CUSTOM = "custom"

PROFILE_TRANSLATION_KEYS = {
    PROFILE_MOTOR: "profile.motor_accessibility",
    PROFILE_HEARING: "profile.hearing_accessibility",
    PROFILE_COMBINED: "profile.combined",
    PROFILE_CUSTOM: "profile.custom",
}

PROFILE_PRESETS = {
    PROFILE_MOTOR: {
        "profile": PROFILE_MOTOR,
        "simulate_inputs": True,
        "gesture_recognition_enabled": True,
        "audio_accessibility_enabled": True,
        "audio_alerts_enabled": False,
        "audio_interval_seconds": DEFAULT_AUDIO_INTERVAL_SECONDS,
        "input_cooldown_seconds": 0.9,
        "gesture_mappings": DEFAULT_GESTURE_MAPPINGS,
    },
    PROFILE_HEARING: {
        "profile": PROFILE_HEARING,
        "simulate_inputs": True,
        "gesture_recognition_enabled": False,
        "audio_accessibility_enabled": True,
        "audio_alerts_enabled": True,
        "audio_interval_seconds": 3.0,
        "audio_detection_enabled": True,
        "audio_overlay_enabled": True,
        "input_cooldown_seconds": DEFAULT_INPUT_COOLDOWN_SECONDS,
        "gesture_mappings": DEFAULT_GESTURE_MAPPINGS,
    },
    PROFILE_COMBINED: {
        "profile": PROFILE_COMBINED,
        "simulate_inputs": True,
        "gesture_recognition_enabled": True,
        "audio_accessibility_enabled": True,
        "audio_alerts_enabled": True,
        "audio_interval_seconds": 3.0,
        "audio_detection_enabled": True,
        "audio_overlay_enabled": True,
        "input_cooldown_seconds": 0.9,
        "gesture_mappings": DEFAULT_GESTURE_MAPPINGS,
    },
    PROFILE_CUSTOM: {
        "profile": PROFILE_CUSTOM,
    },
}

DEFAULT_SETTINGS = {
    "profile": PROFILE_CUSTOM,
    "language": DEFAULT_LANGUAGE,
    "camera_index": DEFAULT_CAMERA_INDEX,
    "camera_zoom": DEFAULT_CAMERA_CALIBRATION_SETTINGS["zoom"],
    "camera_offset_x": DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_x"],
    "camera_offset_y": DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_y"],
    "camera_mirror": DEFAULT_CAMERA_CALIBRATION_SETTINGS["mirror"],
    "camera_invert_movement": DEFAULT_CAMERA_CALIBRATION_SETTINGS["invert_movement"],
    "camera_tracking_area": DEFAULT_CAMERA_CALIBRATION_SETTINGS["tracking_area"],
    "simulate_inputs": True,
    "gesture_recognition_enabled": True,
    "audio_alerts_enabled": True,
    "audio_accessibility_enabled": True,
    "audio_interval_seconds": DEFAULT_AUDIO_INTERVAL_SECONDS,
    "audio_detection_enabled": DEFAULT_AUDIO_DETECTION_SETTINGS["enabled"],
    "audio_overlay_enabled": DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_enabled"],
    "audio_detection_sensitivity": DEFAULT_AUDIO_DETECTION_SETTINGS["sensitivity"],
    "audio_minimum_volume": DEFAULT_AUDIO_DETECTION_SETTINGS["minimum_volume"],
    "audio_detection_interval": DEFAULT_AUDIO_DETECTION_SETTINGS["detection_interval"],
    "audio_overlay_opacity": DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_opacity"],
    "audio_overlay_duration": DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_duration"],
    "audio_overlay_size": DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_size"],
    "input_cooldown_seconds": DEFAULT_INPUT_COOLDOWN_SECONDS,
    "gesture_mappings": DEFAULT_GESTURE_MAPPINGS,
    "controller_enabled": True,
    "controller_button_mappings": DEFAULT_CONTROLLER_BUTTON_MAPPINGS,
    "controller_stick_settings": DEFAULT_CONTROLLER_STICK_SETTINGS,
    "controller_mouse_settings": DEFAULT_CONTROLLER_MOUSE_SETTINGS,
    "controller_mouse_enabled": True,
    "controller_trigger_clicks_enabled": True,
}


