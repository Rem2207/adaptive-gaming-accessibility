from __future__ import annotations

import logging
import queue
import re
import threading
import tkinter as tk
from io import BytesIO
from time import monotonic, sleep
from tkinter import filedialog, ttk
from typing import Any

from PIL import Image, ImageTk

from adaptive_accessibility.core.config import SettingsManager
from adaptive_accessibility.core.constants import (
    APP_NAME,
    DEFAULT_AUDIO_DETECTION_SETTINGS,
    DEFAULT_AUDIO_INTERVAL_SECONDS,
    DEFAULT_CAMERA_CALIBRATION_SETTINGS,
    DEFAULT_CONTROLLER_BUTTON_MAPPINGS,
    DEFAULT_CONTROLLER_MOUSE_SETTINGS,
    DEFAULT_CONTROLLER_STICK_SETTINGS,
    DEFAULT_CAMERA_INDEX,
    DEFAULT_GESTURE_MAPPINGS,
    DEFAULT_INPUT_COOLDOWN_SECONDS,
    DEFAULT_WINDOW_SIZE,
    GESTURE_MAPPING_ORDER,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    PROFILE_COMBINED,
    PROFILE_CUSTOM,
    PROFILE_HEARING,
    PROFILE_MOTOR,
    PROFILE_TRANSLATION_KEYS,
)
from adaptive_accessibility.core.i18n import SUPPORTED_LANGUAGES, Translator
from adaptive_accessibility.services.audio_assistance import AudioAssist, SoundEvent
from adaptive_accessibility.services.audio_detector import AudioDetector, AudioEvent
from adaptive_accessibility.services.camera_calibration import CameraCalibrationSettings
from adaptive_accessibility.services.controller_mapper import ControllerMapper, ControllerMappingResult
from adaptive_accessibility.services.device_manager import DeviceInfo, DeviceManager
from adaptive_accessibility.services.input_mapper import InputMapper, MappingResult
from adaptive_accessibility.ui.overlay_manager import OverlayManager
from adaptive_accessibility.ui.theme import Fonts, Palette


class MainUI:
    """Modern Tkinter dashboard for the adaptive gaming accessibility system."""

    PAGE_KEYS = (
        "dashboard",
        "devices",
        "gestures",
        "camera",
        "accessibility",
        "settings",
        "statistics",
        "about",
    )

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.settings
        self.translator = Translator(str(self.settings.get("language", "en")))

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry(DEFAULT_WINDOW_SIZE)
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.root.configure(bg=Palette.background)

        camera_index = int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX))
        gesture_enabled = bool(self.settings.get("gesture_recognition_enabled", True))
        self.device_manager = DeviceManager(camera_index=camera_index, webcam_detection_enabled=gesture_enabled)
        self.input_mapper = InputMapper(
            simulate_inputs=bool(self.settings.get("simulate_inputs", True)),
            cooldown_seconds=float(self.settings.get("input_cooldown_seconds", DEFAULT_INPUT_COOLDOWN_SECONDS)),
            mappings=dict(self.settings.get("gesture_mappings", {})),
        )
        self.controller_mapper = ControllerMapper(
            simulate_inputs=bool(self.settings.get("simulate_inputs", True)),
            button_mappings=dict(self.settings.get("controller_button_mappings", DEFAULT_CONTROLLER_BUTTON_MAPPINGS)),
            stick_settings=dict(self.settings.get("controller_stick_settings", DEFAULT_CONTROLLER_STICK_SETTINGS)),
            mouse_settings=dict(self.settings.get("controller_mouse_settings", DEFAULT_CONTROLLER_MOUSE_SETTINGS)),
        )
        self.gesture_recognizer: Any | None = None
        self.audio_assist = AudioAssist(
            callback=self._enqueue_sound_event,
            interval_seconds=float(self.settings.get("audio_interval_seconds", DEFAULT_AUDIO_INTERVAL_SECONDS)),
        )
        self.audio_detector = AudioDetector(
            callback=self._enqueue_sound_event,
            settings=self._audio_detection_settings_from_store(),
            simulate_inputs=bool(self.settings.get("simulate_inputs", True)),
        )
        self.overlay_manager = OverlayManager(settings=self._audio_overlay_settings_from_store())

        self.running = False
        self.shutting_down = False
        self.gesture_thread: threading.Thread | None = None
        self.controller_thread: threading.Thread | None = None
        self.device_thread: threading.Thread | None = None
        self.device_scan_in_progress = False
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.event_after_id: str | None = None
        self.session_after_id: str | None = None
        self.photo_image: tk.PhotoImage | None = None
        self.camera_photo_images: list[ImageTk.PhotoImage] = []
        self.camera_calibration_after_id: str | None = None
        self.current_page = "dashboard"
        self.last_preview_at = 0.0
        self.preview_interval_seconds = 0.18
        self.last_controller_status_at = 0.0

        self.profile_labels = self._localized_profile_labels()
        self.profile_keys_by_label = {label: key for key, label in self.profile_labels.items()}
        self.language_names = SUPPORTED_LANGUAGES
        self.language_keys_by_label = {label: key for key, label in self.language_names.items()}

        self.simulate_inputs = tk.BooleanVar(value=bool(self.settings.get("simulate_inputs", True)))
        self.gesture_recognition_enabled = tk.BooleanVar(value=bool(self.settings.get("gesture_recognition_enabled", True)))
        self.audio_accessibility_enabled = tk.BooleanVar(value=bool(self.settings.get("audio_accessibility_enabled", True)))
        self.audio_enabled = tk.BooleanVar(value=bool(self.settings.get("audio_alerts_enabled", True)))
        self.hearing_assist_enabled = tk.BooleanVar(value=bool(self.settings.get("hearing_assistance", self.audio_enabled.get())))
        self.audio_detection_enabled = tk.BooleanVar(value=bool(self.settings.get("audio_detection_enabled", DEFAULT_AUDIO_DETECTION_SETTINGS["enabled"])))
        self.audio_overlay_enabled = tk.BooleanVar(value=bool(self.settings.get("audio_overlay_enabled", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_enabled"])))
        self.audio_detection_sensitivity = tk.DoubleVar(value=float(self.settings.get("audio_detection_sensitivity", DEFAULT_AUDIO_DETECTION_SETTINGS["sensitivity"])))
        self.audio_minimum_volume = tk.DoubleVar(value=float(self.settings.get("audio_minimum_volume", DEFAULT_AUDIO_DETECTION_SETTINGS["minimum_volume"])))
        self.audio_detection_interval = tk.DoubleVar(value=float(self.settings.get("audio_detection_interval", DEFAULT_AUDIO_DETECTION_SETTINGS["detection_interval"])))
        self.audio_overlay_opacity = tk.DoubleVar(value=float(self.settings.get("audio_overlay_opacity", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_opacity"])))
        self.audio_overlay_duration = tk.DoubleVar(value=float(self.settings.get("audio_overlay_duration", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_duration"])))
        self.audio_overlay_size = tk.DoubleVar(value=float(self.settings.get("audio_overlay_size", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_size"])))
        self.high_contrast_enabled = tk.BooleanVar(value=bool(self.settings.get("high_contrast", False)))
        self.large_text_enabled = tk.BooleanVar(value=bool(self.settings.get("large_text", False)))
        self.reduced_motion_enabled = tk.BooleanVar(value=bool(self.settings.get("reduced_motion", False)))
        self.simplified_ui_enabled = tk.BooleanVar(value=bool(self.settings.get("simplified_ui", False)))
        self.controller_enabled = tk.BooleanVar(value=bool(self.settings.get("controller_enabled", True)))
        self.controller_mouse_enabled = tk.BooleanVar(value=bool(self.settings.get("controller_mouse_enabled", True)))
        self.controller_trigger_clicks_enabled = tk.BooleanVar(value=bool(self.settings.get("controller_trigger_clicks_enabled", True)))
        self.camera_sensitivity = tk.DoubleVar(value=float(self.settings.get("camera_sensitivity", 0.55)))
        self.gesture_cooldown = tk.DoubleVar(value=float(self.settings.get("input_cooldown_seconds", DEFAULT_INPUT_COOLDOWN_SECONDS)))
        self.gesture_cooldown.trace_add("write", self._on_gesture_cooldown_changed)
        self.camera_zoom = tk.DoubleVar(value=float(self.settings.get("camera_zoom", DEFAULT_CAMERA_CALIBRATION_SETTINGS["zoom"])))
        self.camera_offset_x = tk.DoubleVar(value=float(self.settings.get("camera_offset_x", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_x"])))
        self.camera_offset_y = tk.DoubleVar(value=float(self.settings.get("camera_offset_y", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_y"])))
        self.camera_mirror = tk.BooleanVar(value=bool(self.settings.get("camera_mirror", DEFAULT_CAMERA_CALIBRATION_SETTINGS["mirror"])))
        self.camera_invert_movement = tk.BooleanVar(value=bool(self.settings.get("camera_invert_movement", DEFAULT_CAMERA_CALIBRATION_SETTINGS["invert_movement"])))
        for camera_var in (self.camera_zoom, self.camera_offset_x, self.camera_offset_y):
            camera_var.trace_add("write", self._on_camera_calibration_changed)

        selected_profile = str(self.settings.get("profile", PROFILE_CUSTOM))
        selected_language = str(self.settings.get("language", "en"))
        selected_theme = str(self.settings.get("theme", "light"))
        self.profile_text = tk.StringVar(value=self.profile_labels.get(selected_profile, self.profile_labels[PROFILE_CUSTOM]))
        self.language_text = tk.StringVar(value=self.language_names.get(selected_language, self.language_names["en"]))
        self.theme_text = tk.StringVar(value=self._theme_label(selected_theme))
        self.camera_choice_text = tk.StringVar(value=self._camera_label(camera_index))
        self.camera_tracking_area_text = tk.StringVar(value=self._tracking_area_label(str(self.settings.get("camera_tracking_area", DEFAULT_CAMERA_CALIBRATION_SETTINGS["tracking_area"]))))
        gesture_settings = {**DEFAULT_GESTURE_MAPPINGS, **dict(self.settings.get("gesture_mappings", {}))}
        self.gesture_mapping_vars: dict[str, tk.StringVar] = {
            gesture: tk.StringVar(value=str(gesture_settings.get(gesture, "")).upper())
            for gesture in GESTURE_MAPPING_ORDER
        }
        button_settings = dict(self.settings.get("controller_button_mappings", DEFAULT_CONTROLLER_BUTTON_MAPPINGS))
        self.controller_mapping_vars: dict[str, tk.StringVar] = {
            button: tk.StringVar(value=self._controller_mapping_action(button_settings.get(button, DEFAULT_CONTROLLER_BUTTON_MAPPINGS[button])).upper())
            for button in DEFAULT_CONTROLLER_BUTTON_MAPPINGS
        }
        self.controller_mapping_mode_vars: dict[str, tk.StringVar] = {
            button: tk.StringVar(value=self._controller_mapping_mode(button_settings.get(button, DEFAULT_CONTROLLER_BUTTON_MAPPINGS[button])))
            for button in DEFAULT_CONTROLLER_BUTTON_MAPPINGS
        }
        self.controller_mapping_repeat_vars: dict[str, tk.DoubleVar] = {
            button: tk.DoubleVar(value=self._controller_mapping_repeat(button_settings.get(button, DEFAULT_CONTROLLER_BUTTON_MAPPINGS[button])))
            for button in DEFAULT_CONTROLLER_BUTTON_MAPPINGS
        }
        stick_settings = dict(self.settings.get("controller_stick_settings", DEFAULT_CONTROLLER_STICK_SETTINGS))
        mouse_settings = dict(self.settings.get("controller_mouse_settings", DEFAULT_CONTROLLER_MOUSE_SETTINGS))
        self.controller_stick_mode_vars = {
            stick: tk.StringVar(value=str(stick_settings.get(stick, {}).get("mode", DEFAULT_CONTROLLER_STICK_SETTINGS[stick]["mode"])))
            for stick in ("left_stick", "right_stick")
        }
        self.controller_stick_mapping_vars = {
            stick: {
                direction: tk.StringVar(value=self._controller_mapping_action(stick_settings.get(stick, {}).get(direction, DEFAULT_CONTROLLER_STICK_SETTINGS[stick][direction])).upper())
                for direction in ("up", "down", "left", "right")
            }
            for stick in ("left_stick", "right_stick")
        }
        self.controller_stick_mapping_mode_vars = {
            stick: {
                direction: tk.StringVar(value=self._controller_mapping_mode(stick_settings.get(stick, {}).get(direction, DEFAULT_CONTROLLER_STICK_SETTINGS[stick][direction])))
                for direction in ("up", "down", "left", "right")
            }
            for stick in ("left_stick", "right_stick")
        }
        self.controller_stick_mapping_repeat_vars = {
            stick: {
                direction: tk.DoubleVar(value=self._controller_mapping_repeat(stick_settings.get(stick, {}).get(direction, DEFAULT_CONTROLLER_STICK_SETTINGS[stick][direction])))
                for direction in ("up", "down", "left", "right")
            }
            for stick in ("left_stick", "right_stick")
        }
        self.controller_mouse_x_sensitivity = tk.DoubleVar(value=float(mouse_settings.get("x_sensitivity", 18.0)))
        self.controller_mouse_y_sensitivity = tk.DoubleVar(value=float(mouse_settings.get("y_sensitivity", 18.0)))
        self.controller_deadzone = tk.DoubleVar(value=float(mouse_settings.get("deadzone", 0.18)))
        self.controller_invert_x = tk.BooleanVar(value=bool(mouse_settings.get("invert_x", False)))
        self.controller_invert_y = tk.BooleanVar(value=bool(mouse_settings.get("invert_y", False)))
        self.controller_acceleration_enabled = tk.BooleanVar(value=bool(mouse_settings.get("acceleration_enabled", False)))
        self.controller_acceleration_factor = tk.DoubleVar(value=float(mouse_settings.get("acceleration_factor", 1.4)))
        self.controller_smoothing = tk.DoubleVar(value=float(mouse_settings.get("smoothing", 0.35)))
        self.controller_digital_mouse_step = tk.DoubleVar(value=float(mouse_settings.get("digital_mouse_step", 18.0)))
        self.controller_profile_name = tk.StringVar(value="Custom")

        self.status_text = tk.StringVar(value=self._t("status.system_stopped"))
        self.footer_text = tk.StringVar(value=self._t("footer.ready"))
        self.header_language_text = tk.StringVar(value=self.language_text.get())
        self.header_profile_text = tk.StringVar(value=self._short_profile_label(selected_profile))
        self.last_gesture_text = tk.StringVar(value=self._t("activity.none"))
        self.last_command_text = tk.StringVar(value=self._t("activity.none"))
        self.last_alert_text = tk.StringVar(value=self._t("activity.none"))
        self.devices_connected_text = tk.StringVar(value="0")
        self.camera_status_text = tk.StringVar(value=self._t("card.unavailable"))
        self.alerts_enabled_text = tk.StringVar(value=self._enabled_text(self.audio_enabled.get()))
        self.inputs_enabled_text = tk.StringVar(value=self._enabled_text(self.simulate_inputs.get()))
        self.current_gesture_text = tk.StringVar(value=self._t("activity.none"))
        self.current_command_text = tk.StringVar(value=self._t("activity.none"))
        self.confidence_text = tk.StringVar(value=self._t("statistics.not_available"))
        self.gestures_count_text = tk.StringVar(value="0")
        self.commands_count_text = tk.StringVar(value="0")
        self.alerts_count_text = tk.StringVar(value="0")
        self.session_time_text = tk.StringVar(value="00:00")
        self.average_response_text = tk.StringVar(value=self._t("statistics.not_available"))
        self.controller_status_text = tk.StringVar(value=self._t("controller.not_detected"))
        self.controller_activity_text = tk.StringVar(value=self._t("controller.ready"))
        self.controller_module_status_text = tk.StringVar(value=self._enabled_text(self.controller_enabled.get()))
        self.gesture_module_status_text = tk.StringVar(value=self._enabled_text(self.gesture_recognition_enabled.get()))
        self.audio_module_status_text = tk.StringVar(value=self._enabled_text(self.audio_accessibility_enabled.get()))
        self.camera_hand_position_text = tk.StringVar(value=self._t("camera.no_position"))
        self.camera_detection_status_text = tk.StringVar(value=self._t("status.no_gesture"))
        self.camera_distance_quality_text = tk.StringVar(value=self._t("camera.quality.unknown"))

        self.stats = {
            "gestures_detected": 0,
            "commands_sent": 0,
            "alerts_triggered": 0,
        }
        self.session_started_at: float | None = None
        self.last_devices: list[DeviceInfo] = []

        self.pages: dict[str, ttk.Frame] = {}
        self.sidebar_buttons: dict[str, ttk.Button] = {}
        self.sidebar_button_keys: dict[str, str] = {}
        self.sidebar_icons = {
            "dashboard": "[D]",
            "devices": "[I]",
            "gestures": "[G]",
            "camera": "[C]",
            "accessibility": "[A]",
            "settings": "[S]",
            "statistics": "[%]",
            "about": "[?]",
        }
        self.translatable_widgets: list[tuple[ttk.Label | ttk.Button | ttk.Checkbutton, str]] = []
        self.camera_preview_labels: list[ttk.Label] = []
        self.camera_preview_labels_by_page: dict[str, ttk.Label] = {}
        self.device_rows: list[tuple[ttk.Label, ttk.Label, ttk.Label, ttk.Label]] = []
        self.alert_labels: dict[str, ttk.Label] = {}
        self.mapping_labels: dict[str, ttk.Label] = {}
        self.settings_notebook: ttk.Notebook | None = None
        self.controller_settings_notebook: ttk.Notebook | None = None
        self.camera_selectors: list[ttk.Combobox] = []
        self.camera_tracking_area_selectors: list[ttk.Combobox] = []
        self.focus_sink: ttk.Frame | None = None
        self.toast_label: ttk.Label | None = None
        self.toast_after_id: str | None = None

        self._configure_style()
        self._build_layout()
        self._show_page("dashboard")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.event_after_id = self.root.after(80, self._process_events)
        self.session_after_id = self.root.after(1000, self._update_session_time)
        self.root.after(120, self.refresh_devices_async)

    def run(self) -> None:
        try:
            self.logger.info("Opening main application window")
            self.root.mainloop()
        finally:
            self._safe_shutdown(closing=True)

    def _t(self, key: str, **kwargs: object) -> str:
        return self.translator.text(key, **kwargs)

    def _track_text(self, widget: ttk.Label | ttk.Button | ttk.Checkbutton, translation_key: str) -> None:
        self.translatable_widgets.append((widget, translation_key))

    def _localized_profile_labels(self) -> dict[str, str]:
        return {profile: self._t(key) for profile, key in PROFILE_TRANSLATION_KEYS.items()}

    def _short_profile_label(self, profile: str) -> str:
        keys = {
            PROFILE_MOTOR: "profile.short.motor_accessibility",
            PROFILE_HEARING: "profile.short.hearing_accessibility",
            PROFILE_COMBINED: "profile.short.combined",
            PROFILE_CUSTOM: "profile.short.custom",
        }
        return self._t(keys.get(profile, "profile.short.custom"))

    def _theme_label(self, theme: str) -> str:
        return self._t("settings.theme_dark") if theme == "dark" else self._t("settings.theme_light")

    def _enabled_text(self, enabled: bool) -> str:
        return self._t("card.enabled") if enabled else self._t("card.disabled")

    def _sidebar_text(self, page_key: str, text_key: str) -> str:
        icon = self.sidebar_icons.get(page_key, "[ ]")
        return f"{icon} {self._t(text_key)}"

    def _set_status_badge(self, running: bool) -> None:
        if hasattr(self, "status_badge"):
            self.status_badge.configure(style="StatusRunning.TLabel" if running else "StatusStopped.TLabel")

    def _camera_label(self, index: int) -> str:
        return self._t("settings.camera_option", index=index)

    def _camera_options(self) -> list[str]:
        return [self._camera_label(index) for index in range(3)]

    def _tracking_area_options(self) -> list[str]:
        return [
            self._t("camera.full_frame"),
            self._t("camera.left_side"),
            self._t("camera.right_side"),
            self._t("camera.custom_area"),
        ]

    def _tracking_area_label(self, value: str) -> str:
        keys = {
            "full": "camera.full_frame",
            "left": "camera.left_side",
            "right": "camera.right_side",
            "custom": "camera.custom_area",
        }
        return self._t(keys.get(value, "camera.full_frame"))

    def _tracking_area_value(self) -> str:
        labels = {
            self._t("camera.full_frame"): "full",
            self._t("camera.left_side"): "left",
            self._t("camera.right_side"): "right",
            self._t("camera.custom_area"): "custom",
        }
        return labels.get(self.camera_tracking_area_text.get(), "full")

    def _distance_quality_text(self, quality: str) -> str:
        return self._t(
            {
                "good": "camera.quality.good",
                "far": "camera.quality.far",
                "too_close": "camera.quality.too_close",
                "unknown": "camera.quality.unknown",
            }.get(quality, "camera.quality.unknown")
        )

    def _gesture_label_key(self, gesture: str) -> str:
        if gesture.startswith("finger_count_"):
            return f"gesture.{gesture}"
        return {
            "left_movement": "gesture.move_left",
            "right_movement": "gesture.move_right",
            "open_hand": "gesture.open_hand",
            "closed_fist": "gesture.closed_fist",
        }.get(gesture, gesture)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=Palette.background)
        style.configure("Header.TFrame", background=Palette.surface)
        style.configure("Sidebar.TFrame", background=Palette.sidebar)
        style.configure("Main.TFrame", background=Palette.background)
        style.configure("Footer.TFrame", background=Palette.surface)
        style.configure("Card.TFrame", background=Palette.surface, relief="solid", borderwidth=1)
        style.configure("SubtleCard.TFrame", background=Palette.surface_alt, relief="flat", borderwidth=0)
        style.configure("DarkCard.TFrame", background=Palette.camera, relief="solid", borderwidth=1)

        style.configure("TLabel", background=Palette.background, foreground=Palette.text, font=(Fonts.family, 10))
        style.configure("HeaderTitle.TLabel", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 18, "bold"))
        style.configure("HeaderMeta.TLabel", background=Palette.surface, foreground=Palette.text_muted, font=(Fonts.family, 9))
        style.configure("HeaderValue.TLabel", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 10, "bold"))
        style.configure("StatusRunning.TLabel", background="#DCFCE7", foreground="#166534", font=(Fonts.family, 10, "bold"))
        style.configure("StatusStopped.TLabel", background="#FEE2E2", foreground="#991B1B", font=(Fonts.family, 10, "bold"))
        style.configure("SidebarTitle.TLabel", background=Palette.sidebar, foreground="#F9FAFB", font=(Fonts.family, 11, "bold"))
        style.configure("SidebarHint.TLabel", background=Palette.sidebar, foreground="#9CA3AF", font=(Fonts.family, 9))
        style.configure("CardTitle.TLabel", background=Palette.surface, foreground=Palette.text_muted, font=(Fonts.family, 9, "bold"))
        style.configure("CardValue.TLabel", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 20, "bold"))
        style.configure("SectionTitle.TLabel", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 13, "bold"))
        style.configure("Panel.TLabel", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 10))
        style.configure("Muted.TLabel", background=Palette.surface, foreground=Palette.text_muted, font=(Fonts.family, 9))
        style.configure("SubStatus.TLabel", background=Palette.surface, foreground="#374151", font=(Fonts.family, 10))
        style.configure("Available.TLabel", background=Palette.surface, foreground=Palette.success, font=(Fonts.family, 10, "bold"))
        style.configure("Missing.TLabel", background=Palette.surface, foreground=Palette.danger, font=(Fonts.family, 10, "bold"))
        style.configure("Code.TLabel", background="#EFF6FF", foreground=Palette.primary_dark, font=(Fonts.mono, 10, "bold"))
        style.configure("Camera.TLabel", background=Palette.camera, foreground="#D1D5DB", font=(Fonts.family, 11))
        style.configure("Alert.TLabel", background="#F8FAFC", foreground="#334155", font=(Fonts.family, 12, "bold"))
        style.configure("ActiveAlert.TLabel", background=Palette.danger, foreground="#FFFFFF", font=(Fonts.family, 12, "bold"))
        style.configure("ActionAlert.TLabel", background=Palette.primary, foreground="#FFFFFF", font=(Fonts.family, 12, "bold"))
        style.configure("Footer.TLabel", background=Palette.surface, foreground=Palette.text_muted, font=(Fonts.family, 9))
        style.configure("Toast.TLabel", background=Palette.text, foreground="#FFFFFF", font=(Fonts.family, 10, "bold"))

        style.configure("TButton", font=(Fonts.family, 10), padding=(12, 8), background="#F8FAFC", foreground=Palette.text)
        style.map("TButton", background=[("active", "#E5E7EB")], foreground=[("disabled", "#9CA3AF")])
        style.configure("Primary.TButton", font=(Fonts.family, 10, "bold"), padding=(16, 10), background=Palette.primary, foreground="#FFFFFF")
        style.map("Primary.TButton", background=[("active", Palette.primary_dark)], foreground=[("active", "#FFFFFF")])
        style.configure("Sidebar.TButton", font=(Fonts.family, 10, "bold"), padding=(16, 12), anchor="w", background=Palette.sidebar, foreground="#D1D5DB", borderwidth=0)
        style.configure("SidebarActive.TButton", font=(Fonts.family, 10, "bold"), padding=(16, 12), anchor="w", background=Palette.primary, foreground="#FFFFFF", borderwidth=0)
        style.map("Sidebar.TButton", background=[("active", Palette.sidebar_active)], foreground=[("active", "#FFFFFF")])
        style.map("SidebarActive.TButton", background=[("active", Palette.primary_dark)], foreground=[("active", "#FFFFFF")])
        style.configure("TCheckbutton", background=Palette.surface, foreground=Palette.text, font=(Fonts.family, 10))
        style.map("TCheckbutton", background=[("active", Palette.surface)])
        style.configure("TCombobox", font=(Fonts.family, 10), padding=(8, 5))
        style.configure("Horizontal.TScale", background=Palette.surface)

    def _build_layout(self) -> None:
        root = ttk.Frame(self.root, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=0)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)
        self.focus_sink = ttk.Frame(root, style="App.TFrame", width=1, height=1, takefocus=True)
        self.focus_sink.place(x=-100, y=-100)

        self._build_header(root)
        self._build_sidebar(root)
        self._build_main_area(root)
        self._build_footer(root)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Header.TFrame", padding=(20, 14))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text=APP_NAME, style="HeaderTitle.TLabel")
        title.grid(row=0, column=0, rowspan=2, sticky="w")

        meta = ttk.Frame(header, style="Header.TFrame")
        meta.grid(row=0, column=1, sticky="e", padx=(20, 16))
        for col in range(3):
            meta.columnconfigure(col, weight=0)

        self.status_badge = self._build_header_metric(meta, 0, "header.system_status", self.status_text)
        self.status_badge.configure(style="StatusStopped.TLabel", padding=(10, 4))
        self._build_header_metric(meta, 1, "header.language", self.header_language_text)
        self._build_header_metric(meta, 2, "header.profile", self.header_profile_text)

        self.start_button = ttk.Button(header, text=self._t("button.start"), style="Primary.TButton", command=self.toggle_system)
        self.start_button.grid(row=0, column=2, rowspan=2, sticky="e")
        self._disable_keyboard_activation(self.start_button)

    def _build_header_metric(self, parent: ttk.Frame, column: int, label_key: str, value: tk.StringVar) -> ttk.Label:
        label = ttk.Label(parent, text=self._t(label_key), style="HeaderMeta.TLabel")
        label.grid(row=0, column=column, sticky="w", padx=(0, 18))
        self._track_text(label, label_key)
        value_label = ttk.Label(parent, textvariable=value, style="HeaderValue.TLabel")
        value_label.grid(row=1, column=column, sticky="w", padx=(0, 18))
        return value_label

    def _disable_keyboard_activation(self, button: ttk.Button) -> None:
        button.configure(takefocus=False)
        button.bind("<space>", lambda _event: "break")
        button.bind("<Return>", lambda _event: "break")
        button.bind("<KP_Enter>", lambda _event: "break")

    def _release_control_focus(self) -> None:
        try:
            if self.focus_sink is not None:
                self.focus_sink.focus_set()
            else:
                self.root.focus_set()
        except Exception as exc:
            self.logger.debug("Could not move focus away from command control: %s", exc)

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        sidebar = ttk.Frame(parent, style="Sidebar.TFrame", padding=(14, 18))
        sidebar.grid(row=1, column=0, sticky="ns")
        sidebar.columnconfigure(0, weight=1)

        label = ttk.Label(sidebar, text=APP_NAME, style="SidebarTitle.TLabel", wraplength=170)
        label.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        subtitle = ttk.Label(sidebar, text=self._t("app.subtitle"), style="SidebarHint.TLabel", wraplength=170)
        subtitle.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self._track_text(subtitle, "app.subtitle")

        pages = [
            ("dashboard", "nav.dashboard"),
            ("devices", "nav.devices"),
            ("gestures", "nav.gestures"),
            ("camera", "nav.camera"),
            ("accessibility", "nav.accessibility"),
            ("settings", "nav.settings"),
            ("statistics", "nav.statistics"),
            ("about", "nav.about"),
        ]
        for row, (page_key, text_key) in enumerate(pages, start=2):
            button = ttk.Button(
                sidebar,
                text=self._sidebar_text(page_key, text_key),
                style="Sidebar.TButton",
                command=lambda key=page_key: self._show_page(key),
            )
            button.grid(row=row, column=0, sticky="ew", pady=4)
            self.sidebar_buttons[page_key] = button
            self.sidebar_button_keys[page_key] = text_key

    def _build_main_area(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent, style="Main.TFrame", padding=18)
        container.grid(row=1, column=1, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        for page_key in self.PAGE_KEYS:
            frame = ttk.Frame(container, style="Main.TFrame")
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[page_key] = frame

        self._build_dashboard_page(self.pages["dashboard"])
        self._build_devices_page(self.pages["devices"])
        self._build_gestures_page(self.pages["gestures"])
        self._build_camera_page(self.pages["camera"])
        self._build_accessibility_page(self.pages["accessibility"])
        self._build_settings_page(self.pages["settings"])
        self._build_statistics_page(self.pages["statistics"])
        self._build_about_page(self.pages["about"])

    def _build_footer(self, parent: ttk.Frame) -> None:
        footer = ttk.Frame(parent, style="Footer.TFrame", padding=(18, 8))
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.footer_text, style="Footer.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, text=APP_NAME, style="Footer.TLabel").grid(row=0, column=1, sticky="e")

    def _build_dashboard_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure((0, 1, 2, 3), weight=1)
        parent.columnconfigure(4, weight=2)
        parent.rowconfigure(1, weight=1)

        self._build_metric_card(parent, 0, 0, "card.devices_connected", self.devices_connected_text)
        self._build_metric_card(parent, 0, 1, "card.camera_status", self.camera_status_text)
        self._build_metric_card(parent, 0, 2, "card.alerts_enabled", self.alerts_enabled_text)
        self._build_metric_card(parent, 0, 3, "card.inputs_enabled", self.inputs_enabled_text)

        activity = self._panel(parent, "section.recent_activity")
        activity.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=(16, 0))
        activity.columnconfigure(0, weight=1)
        self._build_activity_row(activity, 1, "activity.last_gesture", self.last_gesture_text)
        self._build_activity_row(activity, 2, "activity.last_command", self.last_command_text)
        self._build_activity_row(activity, 3, "activity.last_alert", self.last_alert_text)
        self._build_activity_row(activity, 4, "header.system_status", self.status_text)

        modules = self._panel(parent, "settings.modules")
        modules.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(16, 0))
        modules.columnconfigure((0, 1, 2), weight=1)
        self._build_module_status_card(modules, 1, 0, "module.controller_input", self.controller_module_status_text)
        self._build_module_status_card(modules, 1, 1, "module.gesture_recognition", self.gesture_module_status_text)
        self._build_module_status_card(modules, 1, 2, "module.audio_accessibility", self.audio_module_status_text)

    def _build_devices_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        actions = ttk.Frame(parent, style="Main.TFrame")
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        actions.columnconfigure(0, weight=1)
        title = ttk.Label(actions, text=self._t("panel.devices"), style="SectionTitle.TLabel")
        title.grid(row=0, column=0, sticky="w")
        self._track_text(title, "panel.devices")
        refresh = ttk.Button(actions, text=self._t("button.refresh"), command=self.refresh_devices_async)
        refresh.grid(row=0, column=1, sticky="e")
        self._track_text(refresh, "button.refresh")

        table = ttk.Frame(parent, style="Card.TFrame", padding=16)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.columnconfigure(1, weight=1)
        table.columnconfigure(2, weight=1)
        table.columnconfigure(3, weight=3)
        headers = ("label.device", "label.status", "devices.table_type", "label.details")
        for col, key in enumerate(headers):
            label = ttk.Label(table, text=self._t(key), style="CardTitle.TLabel")
            label.grid(row=0, column=col, sticky="w", padx=(0, 12), pady=(0, 12))
            self._track_text(label, key)

        for row in range(5):
            widgets = (
                ttk.Label(table, text="", style="Panel.TLabel"),
                ttk.Label(table, text="", style="Panel.TLabel"),
                ttk.Label(table, text="", style="Muted.TLabel"),
                ttk.Label(table, text="", style="Muted.TLabel", wraplength=540),
            )
            for col, widget in enumerate(widgets):
                widget.grid(row=row + 1, column=col, sticky="w", padx=(0, 12), pady=8)
            self.device_rows.append(widgets)

    def _build_gestures_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1, minsize=620)
        parent.columnconfigure(1, weight=0, minsize=340)
        parent.rowconfigure(0, weight=1)

        preview = self._panel(parent, "panel.camera")
        preview.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        preview.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)
        camera_shell = ttk.Frame(preview, style="DarkCard.TFrame", padding=12)
        camera_shell.grid(row=1, column=0, sticky="nsew", pady=(12, 12))
        camera_shell.columnconfigure(0, weight=1)
        camera_shell.rowconfigure(0, weight=1)
        self.camera_label = ttk.Label(camera_shell, text=self._t("camera.placeholder"), anchor=tk.CENTER, style="Camera.TLabel")
        self.camera_label.grid(row=0, column=0, sticky="nsew")
        self.camera_preview_labels.append(self.camera_label)
        self.camera_preview_labels_by_page["gestures"] = self.camera_label

        current = ttk.Frame(preview, style="Card.TFrame")
        current.grid(row=2, column=0, sticky="ew")
        current.columnconfigure((0, 1), weight=1)
        self._build_activity_row(current, 0, "gestures.current_gesture", self.current_gesture_text)
        self._build_activity_row(current, 1, "gestures.current_command", self.current_command_text)
        self._build_activity_row(current, 2, "gestures.confidence", self.confidence_text)

        side = self._panel(parent, "gestures.mappings")
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(1, weight=1)
        headers = (("label.gesture", 0), ("label.command", 1))
        for key, column in headers:
            label = ttk.Label(side, text=self._t(key), style="Muted.TLabel")
            label.grid(row=1, column=column, sticky="w", pady=(12, 6), padx=(0, 8))
            self._track_text(label, key)

        for row, gesture_name in enumerate(GESTURE_MAPPING_ORDER, start=2):
            gesture_key = self._gesture_label_key(gesture_name)
            gesture = ttk.Label(side, text=self._t(gesture_key), style="Panel.TLabel")
            gesture.grid(row=row, column=0, sticky="w", pady=5, padx=(0, 8))
            self._track_text(gesture, gesture_key)
            ttk.Entry(side, textvariable=self.gesture_mapping_vars[gesture_name], width=12).grid(row=row, column=1, sticky="ew", pady=5)

        cooldown_row = len(GESTURE_MAPPING_ORDER) + 2
        self._build_slider_row(side, cooldown_row, "settings.gesture_cooldown", self.gesture_cooldown, 0.1, 5.0)

        apply_button = ttk.Button(side, text=self._t("settings.save"), command=self._save_settings)
        apply_button.grid(row=cooldown_row + 1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._track_text(apply_button, "settings.save")

    def _build_camera_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1, minsize=620)
        parent.columnconfigure(1, weight=0, minsize=340)
        parent.rowconfigure(0, weight=1)

        preview = self._panel(parent, "camera.settings")
        preview.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        preview.rowconfigure(1, weight=1)
        preview.columnconfigure(0, weight=1)

        shell = ttk.Frame(preview, style="DarkCard.TFrame", padding=12)
        shell.grid(row=1, column=0, sticky="nsew", pady=(12, 12))
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        camera_label = ttk.Label(shell, text=self._t("camera.placeholder"), anchor=tk.CENTER, style="Camera.TLabel")
        camera_label.grid(row=0, column=0, sticky="nsew")
        self.camera_preview_labels.append(camera_label)
        self.camera_preview_labels_by_page["camera"] = camera_label

        feedback = ttk.Frame(preview, style="Card.TFrame")
        feedback.grid(row=2, column=0, sticky="ew")
        feedback.columnconfigure(1, weight=1)
        self._build_activity_row(feedback, 0, "camera.hand_position", self.camera_hand_position_text)
        self._build_activity_row(feedback, 1, "camera.detection_status", self.camera_detection_status_text)
        self._build_activity_row(feedback, 2, "camera.distance_quality", self.camera_distance_quality_text)

        controls = self._panel(parent, "camera.settings")
        controls.grid(row=0, column=1, sticky="nsew")
        controls.grid_propagate(False)
        controls.columnconfigure(1, weight=1)
        self._build_combobox_row(controls, 1, "settings.camera", self.camera_choice_text, self._camera_options(), self._on_camera_source_changed)
        self._build_slider_row(controls, 2, "camera.zoom", self.camera_zoom, 1.0, 2.0)
        self._build_slider_row(controls, 3, "camera.offset_x", self.camera_offset_x, -1.0, 1.0)
        self._build_slider_row(controls, 4, "camera.offset_y", self.camera_offset_y, -1.0, 1.0)
        self._build_combobox_row(controls, 5, "camera.tracking_area", self.camera_tracking_area_text, self._tracking_area_options(), self._on_camera_calibration_selected)
        mirror = ttk.Checkbutton(controls, text=self._t("camera.mirror"), variable=self.camera_mirror, command=self._sync_accessibility_options)
        mirror.grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_text(mirror, "camera.mirror")
        invert = ttk.Checkbutton(controls, text=self._t("camera.invert_movement"), variable=self.camera_invert_movement, command=self._sync_accessibility_options)
        invert.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._track_text(invert, "camera.invert_movement")
        calibrate = ttk.Button(controls, text=self._t("camera.calibrate"), style="Primary.TButton", command=self._calibrate_camera)
        calibrate.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self._track_text(calibrate, "camera.calibrate")
        save = ttk.Button(controls, text=self._t("settings.save"), command=self._save_settings)
        save.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._track_text(save, "settings.save")

    def _build_accessibility_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        options = ttk.Frame(parent, style="Main.TFrame")
        options.grid(row=0, column=0, sticky="ew")
        options.columnconfigure((0, 1, 2), weight=1)
        self._build_toggle_card(options, 0, 0, "accessibility.visual_sound_alerts", self.audio_enabled)
        self._build_toggle_card(options, 0, 1, "accessibility.hearing_assistance", self.hearing_assist_enabled)
        self._build_toggle_card(options, 0, 2, "accessibility.high_contrast", self.high_contrast_enabled)
        self._build_toggle_card(options, 1, 0, "accessibility.large_text", self.large_text_enabled)
        self._build_toggle_card(options, 1, 1, "accessibility.reduced_motion", self.reduced_motion_enabled)
        self._build_toggle_card(options, 1, 2, "accessibility.simplified_ui", self.simplified_ui_enabled)

        alerts_panel = self._panel(parent, "accessibility.live_alerts")
        alerts_panel.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        alerts_panel.columnconfigure((0, 1, 2), weight=1)
        alerts = [
            ("left_danger", "alert.left_danger"),
            ("nearby_action", "alert.nearby_action"),
            ("right_danger", "alert.right_danger"),
        ]
        for col, (key, text_key) in enumerate(alerts):
            widget = ttk.Label(alerts_panel, text=self._t(text_key), style="Alert.TLabel", anchor=tk.CENTER, padding=(12, 26))
            widget.grid(row=1, column=col, sticky="ew", padx=6, pady=(12, 0))
            self.alert_labels[key] = widget
            self._track_text(widget, text_key)

    def _build_settings_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        settings = self._panel(parent, "panel.options")
        settings.grid(row=0, column=0, sticky="new")
        settings.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(settings)
        notebook.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.settings_notebook = notebook

        general_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        audio_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        controller_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        general_tab.columnconfigure(1, weight=1)
        audio_tab.columnconfigure(1, weight=1)
        controller_tab.columnconfigure(1, weight=1)
        notebook.add(general_tab, text=self._t("settings.general_tab"))
        notebook.add(audio_tab, text=self._t("settings.audio_tab"))
        notebook.add(controller_tab, text=self._t("settings.controller_tab"))

        self._build_combobox_row(general_tab, 1, "label.language", self.language_text, list(self.language_names.values()), self._on_language_selected)
        self._build_combobox_row(general_tab, 2, "label.user_profile", self.profile_text, list(self.profile_labels.values()), self._on_profile_selected)
        self._build_slider_row(general_tab, 3, "settings.camera_sensitivity", self.camera_sensitivity, 0.1, 1.0)
        self._build_slider_row(general_tab, 4, "settings.gesture_cooldown", self.gesture_cooldown, 0.1, 5.0)
        self._build_combobox_row(general_tab, 5, "settings.camera", self.camera_choice_text, self._camera_options(), None)
        self._build_combobox_row(
            general_tab,
            6,
            "settings.theme",
            self.theme_text,
            [self._t("settings.theme_light"), self._t("settings.theme_dark")],
            None,
        )
        self._build_modules_section(general_tab, 7)
        simulation = ttk.Checkbutton(general_tab, text=self._t("settings.input_simulation"), variable=self.simulate_inputs, command=self._sync_accessibility_options)
        simulation.grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._track_text(simulation, "settings.input_simulation")
        save = ttk.Button(general_tab, text=self._t("settings.save"), style="Primary.TButton", command=self._save_settings)
        save.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self._track_text(save, "settings.save")

        self._build_audio_accessibility_tab(audio_tab)
        self._build_controller_settings_tab(controller_tab)

    def _build_audio_accessibility_tab(self, parent: ttk.Frame) -> None:
        detector = ttk.Checkbutton(parent, text=self._t("audio.enable_detection"), variable=self.audio_detection_enabled, command=self._sync_accessibility_options)
        detector.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._track_text(detector, "audio.enable_detection")
        overlay = ttk.Checkbutton(parent, text=self._t("audio.enable_overlay"), variable=self.audio_overlay_enabled, command=self._sync_accessibility_options)
        overlay.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._track_text(overlay, "audio.enable_overlay")
        self._build_slider_row(parent, 2, "audio.sensitivity", self.audio_detection_sensitivity, 0.01, 1.0)
        self._build_slider_row(parent, 3, "audio.minimum_volume", self.audio_minimum_volume, 0.0, 1.0)
        self._build_slider_row(parent, 4, "audio.detection_interval", self.audio_detection_interval, 0.05, 1.0)
        self._build_slider_row(parent, 5, "audio.overlay_opacity", self.audio_overlay_opacity, 0.1, 1.0)
        self._build_slider_row(parent, 6, "audio.overlay_duration", self.audio_overlay_duration, 0.3, 5.0)
        self._build_slider_row(parent, 7, "audio.overlay_size", self.audio_overlay_size, 80.0, 360.0)
        save = ttk.Button(parent, text=self._t("settings.save"), style="Primary.TButton", command=self._save_settings)
        save.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self._track_text(save, "settings.save")

    def _build_controller_settings_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, sticky="ew")
        self.controller_settings_notebook = notebook

        status_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        sticks_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        mouse_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        buttons_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        profiles_tab = ttk.Frame(notebook, style="Card.TFrame", padding=10)
        for tab in (status_tab, sticks_tab, mouse_tab, buttons_tab, profiles_tab):
            tab.columnconfigure(1, weight=1)

        notebook.add(status_tab, text=self._t("controller.tab.status"))
        notebook.add(sticks_tab, text=self._t("controller.tab.sticks"))
        notebook.add(mouse_tab, text=self._t("controller.tab.mouse"))
        notebook.add(buttons_tab, text=self._t("controller.tab.buttons"))
        notebook.add(profiles_tab, text=self._t("controller.tab.profiles"))

        self._build_controller_status_tab(status_tab)
        self._build_controller_sticks_tab(sticks_tab)
        self._build_controller_mouse_tab(mouse_tab)
        self._build_controller_buttons_tab(buttons_tab)
        self._build_controller_profiles_tab(profiles_tab)

    def _build_controller_status_tab(self, parent: ttk.Frame) -> None:
        enabled = ttk.Checkbutton(parent, text=self._t("settings.controller_enabled"), variable=self.controller_enabled, command=self._sync_accessibility_options)
        enabled.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._track_text(enabled, "settings.controller_enabled")
        status_label = ttk.Label(parent, text=self._t("controller.connected"), style="CardTitle.TLabel")
        status_label.grid(row=1, column=0, sticky="w", pady=4)
        self._track_text(status_label, "controller.connected")
        ttk.Label(parent, textvariable=self.controller_status_text, style="Panel.TLabel").grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(parent, textvariable=self.controller_activity_text, style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_controller_sticks_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        mode_values = ["disabled", "mouse", "digital", "custom"]
        activation_values = ["tap", "hold", "turbo"]
        row = 0
        for stick, title_key in (("left_stick", "controller.left_stick"), ("right_stick", "controller.right_stick")):
            title = ttk.Label(parent, text=self._t(title_key), style="CardTitle.TLabel")
            title.grid(row=row, column=0, columnspan=4, sticky="w", pady=(8, 4))
            self._track_text(title, title_key)
            row += 1
            mode_label = ttk.Label(parent, text=self._t("controller.stick_mode"), style="Panel.TLabel")
            mode_label.grid(row=row, column=0, sticky="w", pady=3)
            self._track_text(mode_label, "controller.stick_mode")
            ttk.Combobox(parent, textvariable=self.controller_stick_mode_vars[stick], values=mode_values, state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
            row += 1
            for column, key in enumerate(("controller.mapping_action", "controller.mapping_mode", "controller.repeat_rate"), start=1):
                label = ttk.Label(parent, text=self._t(key), style="Muted.TLabel")
                label.grid(row=row, column=column, sticky="w", padx=(0, 8), pady=(4, 2))
                self._track_text(label, key)
            row += 1
            for direction in ("up", "down", "left", "right"):
                label = ttk.Label(parent, text=self._t(f"controller.direction.{direction}"), style="Panel.TLabel")
                label.grid(row=row, column=0, sticky="w", pady=3)
                self._track_text(label, f"controller.direction.{direction}")
                ttk.Entry(parent, textvariable=self.controller_stick_mapping_vars[stick][direction], width=18).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
                ttk.Combobox(parent, textvariable=self.controller_stick_mapping_mode_vars[stick][direction], values=activation_values, state="readonly", width=10).grid(row=row, column=2, sticky="ew", padx=(0, 8), pady=3)
                ttk.Scale(parent, variable=self.controller_stick_mapping_repeat_vars[stick][direction], from_=1, to=30, orient="horizontal").grid(row=row, column=3, sticky="ew", pady=3)
                row += 1

    def _build_controller_mouse_tab(self, parent: ttk.Frame) -> None:
        self._build_slider_row(parent, 0, "controller.mouse_x_sensitivity", self.controller_mouse_x_sensitivity, 1.0, 50.0)
        self._build_slider_row(parent, 1, "controller.mouse_y_sensitivity", self.controller_mouse_y_sensitivity, 1.0, 50.0)
        self._build_slider_row(parent, 2, "controller.deadzone", self.controller_deadzone, 0.0, 0.8)
        self._build_slider_row(parent, 3, "controller.acceleration_factor", self.controller_acceleration_factor, 1.0, 4.0)
        self._build_slider_row(parent, 4, "controller.smoothing", self.controller_smoothing, 0.0, 0.95)
        self._build_slider_row(parent, 5, "controller.digital_mouse_step", self.controller_digital_mouse_step, 1.0, 60.0)
        invert_x = ttk.Checkbutton(parent, text=self._t("controller.invert_x"), variable=self.controller_invert_x, command=self._sync_accessibility_options)
        invert_x.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self._track_text(invert_x, "controller.invert_x")
        invert_y = ttk.Checkbutton(parent, text=self._t("controller.invert_y"), variable=self.controller_invert_y, command=self._sync_accessibility_options)
        invert_y.grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
        self._track_text(invert_y, "controller.invert_y")
        acceleration = ttk.Checkbutton(parent, text=self._t("controller.acceleration_enabled"), variable=self.controller_acceleration_enabled, command=self._sync_accessibility_options)
        acceleration.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        self._track_text(acceleration, "controller.acceleration_enabled")

    def _build_controller_buttons_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        buttons = list(DEFAULT_CONTROLLER_BUTTON_MAPPINGS.keys())
        activation_values = ["tap", "hold", "turbo"]
        for column, key in enumerate(("controller.mapping_action", "controller.mapping_mode", "controller.repeat_rate"), start=1):
            label = ttk.Label(parent, text=self._t(key), style="Muted.TLabel")
            label.grid(row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 4))
            self._track_text(label, key)
        for index, button in enumerate(buttons, start=1):
            ttk.Label(parent, text=button, style="Panel.TLabel").grid(row=index, column=0, sticky="w", pady=3)
            ttk.Entry(parent, textvariable=self.controller_mapping_vars[button], width=22).grid(row=index, column=1, sticky="ew", padx=(0, 8), pady=3)
            ttk.Combobox(parent, textvariable=self.controller_mapping_mode_vars[button], values=activation_values, state="readonly", width=10).grid(row=index, column=2, sticky="ew", padx=(0, 8), pady=3)
            ttk.Scale(parent, variable=self.controller_mapping_repeat_vars[button], from_=1, to=30, orient="horizontal").grid(row=index, column=3, sticky="ew", pady=3)
        apply_button = ttk.Button(parent, text=self._t("settings.apply_controller"), command=self._apply_controller_profile)
        apply_button.grid(row=len(buttons) + 1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self._track_text(apply_button, "settings.apply_controller")
        reset_button = ttk.Button(parent, text=self._t("controller.reset_defaults"), command=self._reset_controller_defaults)
        reset_button.grid(row=len(buttons) + 2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self._track_text(reset_button, "controller.reset_defaults")

    def _build_controller_profiles_tab(self, parent: ttk.Frame) -> None:
        name_label = ttk.Label(parent, text=self._t("controller.profile_name"), style="Panel.TLabel")
        name_label.grid(row=0, column=0, sticky="w", pady=4)
        self._track_text(name_label, "controller.profile_name")
        ttk.Entry(parent, textvariable=self.controller_profile_name, width=24).grid(row=0, column=1, sticky="ew", pady=4)
        export_button = ttk.Button(parent, text=self._t("controller.export_profile"), command=self._export_controller_profile)
        export_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._track_text(export_button, "controller.export_profile")
        import_button = ttk.Button(parent, text=self._t("controller.import_profile"), command=self._import_controller_profile)
        import_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._track_text(import_button, "controller.import_profile")
    def _build_statistics_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure((0, 1, 2), weight=1)
        self._build_metric_card(parent, 0, 0, "statistics.gestures_today", self.gestures_count_text)
        self._build_metric_card(parent, 0, 1, "statistics.commands_sent", self.commands_count_text)
        self._build_metric_card(parent, 0, 2, "statistics.alerts_triggered", self.alerts_count_text)
        self._build_metric_card(parent, 1, 0, "statistics.session_time", self.session_time_text)
        self._build_metric_card(parent, 1, 1, "statistics.avg_response", self.average_response_text)

    def _build_about_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        about = self._panel(parent, "nav.about")
        about.grid(row=0, column=0, sticky="nsew")
        desc_title = ttk.Label(about, text=self._t("about.description_title"), style="CardTitle.TLabel")
        desc_title.grid(row=1, column=0, sticky="w", pady=(12, 4))
        self._track_text(desc_title, "about.description_title")
        desc = ttk.Label(about, text=self._t("about.description"), style="Panel.TLabel")
        desc.grid(row=2, column=0, sticky="w")
        self._track_text(desc, "about.description")
        tech_title = ttk.Label(about, text=self._t("about.technologies"), style="CardTitle.TLabel")
        tech_title.grid(row=3, column=0, sticky="w", pady=(20, 8))
        self._track_text(tech_title, "about.technologies")
        ttk.Label(about, text="Python\nTkinter\nOpenCV\nMediaPipe", style="Panel.TLabel").grid(row=4, column=0, sticky="w")

    def _panel(self, parent: ttk.Frame, title_key: str) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Card.TFrame", padding=16)
        panel.columnconfigure(0, weight=1)
        title = ttk.Label(panel, text=self._t(title_key), style="SectionTitle.TLabel")
        title.grid(row=0, column=0, sticky="w", columnspan=4)
        self._track_text(title, title_key)
        return panel

    def _build_metric_card(self, parent: ttk.Frame, row: int, column: int, title_key: str, value: tk.StringVar) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        label = ttk.Label(card, text=self._t(title_key), style="CardTitle.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._track_text(label, title_key)
        ttk.Label(card, textvariable=value, style="CardValue.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _build_activity_row(self, parent: ttk.Frame, row: int, label_key: str, value: tk.StringVar) -> None:
        label = ttk.Label(parent, text=self._t(label_key), style="CardTitle.TLabel")
        label.grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
        self._track_text(label, label_key)
        ttk.Label(parent, textvariable=value, style="Panel.TLabel").grid(row=row, column=1, sticky="w", pady=8)

    def _build_toggle_card(self, parent: ttk.Frame, row: int, column: int, label_key: str, variable: tk.BooleanVar) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.grid(row=row, column=column, sticky="ew", padx=6, pady=6)
        card.columnconfigure(0, weight=1)
        check = ttk.Checkbutton(card, text=self._t(label_key), variable=variable, command=self._sync_accessibility_options)
        check.grid(row=0, column=0, sticky="w")
        self._track_text(check, label_key)

    def _build_module_status_card(self, parent: ttk.Frame, row: int, column: int, label_key: str, value: tk.StringVar) -> None:
        card = ttk.Frame(parent, style="SubtleCard.TFrame", padding=12)
        card.grid(row=row, column=column, sticky="ew", padx=6, pady=(12, 0))
        card.columnconfigure(0, weight=1)
        label = ttk.Label(card, text=self._t(label_key), style="CardTitle.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._track_text(label, label_key)
        ttk.Label(card, textvariable=value, style="SubStatus.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_modules_section(self, parent: ttk.Frame, row: int) -> None:
        modules = self._panel(parent, "settings.modules")
        modules.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        modules.columnconfigure(1, weight=1)
        options = [
            ("settings.controller_enabled", self.controller_enabled, self.controller_module_status_text),
            ("settings.gesture_enabled", self.gesture_recognition_enabled, self.gesture_module_status_text),
            ("settings.audio_accessibility_enabled", self.audio_accessibility_enabled, self.audio_module_status_text),
        ]
        for index, (label_key, variable, status_var) in enumerate(options, start=1):
            check = ttk.Checkbutton(modules, text=self._t(label_key), variable=variable, command=self._sync_accessibility_options)
            check.grid(row=index, column=0, sticky="w", pady=5)
            self._track_text(check, label_key)
            ttk.Label(modules, textvariable=status_var, style="SubStatus.TLabel").grid(row=index, column=1, sticky="e", pady=5)

    def _build_combobox_row(
        self,
        parent: ttk.Frame,
        row: int,
        label_key: str,
        variable: tk.StringVar,
        values: list[str],
        callback: Any,
    ) -> ttk.Combobox:
        label = ttk.Label(parent, text=self._t(label_key), style="CardTitle.TLabel")
        label.grid(row=row, column=0, sticky="w", pady=10, padx=(0, 14))
        self._track_text(label, label_key)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=10)
        if callback:
            combo.bind("<<ComboboxSelected>>", callback)
        if label_key == "label.language":
            self.language_selector = combo
        elif label_key == "label.user_profile":
            self.profile_selector = combo
        elif label_key == "settings.theme":
            self.theme_selector = combo
        elif label_key == "settings.camera":
            self.camera_selectors.append(combo)
            self.camera_selector = combo
        elif label_key == "camera.tracking_area":
            self.camera_tracking_area_selectors.append(combo)
            self.camera_tracking_area_selector = combo
        return combo

    def _build_slider_row(
        self,
        parent: ttk.Frame,
        row: int,
        label_key: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
    ) -> None:
        label = ttk.Label(parent, text=self._t(label_key), style="CardTitle.TLabel")
        label.grid(row=row, column=0, sticky="w", pady=10, padx=(0, 14))
        self._track_text(label, label_key)
        ttk.Scale(parent, from_=minimum, to=maximum, variable=variable, orient=tk.HORIZONTAL).grid(row=row, column=1, sticky="ew", pady=10)

    def _show_page(self, page_key: str) -> None:
        page = self.pages.get(page_key)
        if page is None:
            return
        self.current_page = page_key
        page.tkraise()
        for key, button in self.sidebar_buttons.items():
            button.configure(style="SidebarActive.TButton" if key == page_key else "Sidebar.TButton")

    def refresh_devices_async(self) -> None:
        if self.device_scan_in_progress:
            return

        self.device_manager.webcam_detection_enabled = self.gesture_recognition_enabled.get()
        self.device_scan_in_progress = True
        self.footer_text.set(self._t("footer.ready"))
        self.device_thread = threading.Thread(target=self._scan_devices_worker, daemon=True)
        self.device_thread.start()

    def _scan_devices_worker(self) -> None:
        try:
            devices = self.device_manager.detect_devices()
            self.event_queue.put(("devices_detected", devices))
        except Exception as exc:
            self.logger.exception("Device scan failed: %s", exc)
            self.event_queue.put(("device_scan_failed", None))

    def _handle_devices_detected(self, devices: list[DeviceInfo]) -> None:
        self.device_scan_in_progress = False
        self.last_devices = devices
        connected = sum(1 for device in devices if device.available)
        self.devices_connected_text.set(str(connected))
        if not self.gesture_recognition_enabled.get():
            self.camera_status_text.set(self._t("card.disabled"))
        else:
            self.camera_status_text.set(
                self._t("card.ready")
                if any(device.name == "Webcam" and device.available for device in devices)
                else self._t("card.unavailable")
            )
        for row, device in zip(self.device_rows, devices):
            self._set_device_row(row, device)
        self._append_log(self._t("log.device_scan_complete"))

    def _handle_device_scan_failed(self) -> None:
        self.device_scan_in_progress = False
        self._append_log(self._t("log.device_scan_failed"))

    def toggle_system(self) -> None:
        if self.running:
            self.stop_system()
        else:
            self.start_system()

    def start_system(self) -> None:
        if self.running:
            return

        self.shutting_down = False
        self._sync_options(mark_custom=False)
        camera_started = False
        camera_index = int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX))

        if self.gesture_recognition_enabled.get():
            try:
                self.gesture_recognizer = self._create_gesture_recognizer(camera_index)
                camera_started = self.gesture_recognizer.start()
            except Exception as exc:
                self.logger.exception("Gesture recognizer startup failed: %s", exc)
                camera_started = False
        else:
            self.gesture_recognizer = None
            self.status_text.set(self._t("status.gesture_disabled"))
            self.camera_status_text.set(self._t("card.disabled"))
            self.current_gesture_text.set(self._t("status.gesture_disabled"))
            self._append_log(self._t("log.gesture_disabled"))

        if self.gesture_recognition_enabled.get() and not camera_started:
            self.status_text.set(self._t("status.camera_unavailable"))
            self.camera_status_text.set(self._t("card.unavailable"))
            self._append_log(self._t("log.camera_start_failed"))
        elif camera_started:
            backend = "MediaPipe" if self.gesture_recognizer and self.gesture_recognizer.mediapipe_enabled else "OpenCV fallback"
            self.camera_status_text.set(self._t("card.ready"))
            self._append_log(self._t("log.gesture_started", backend=backend))

        self.running = True
        self.session_started_at = monotonic()
        self.status_text.set(self._t("status.system_running"))
        self._set_status_badge(True)
        self.footer_text.set(self._t("footer.running"))
        self.start_button.configure(text=self._t("button.stop"))
        self._release_control_focus()

        self._apply_audio_runtime_settings()
        try:
            if not self.audio_accessibility_enabled.get():
                self.audio_detector.stop()
                self.audio_assist.stop()
                self.overlay_manager.stop()
            elif self.audio_detection_enabled.get():
                self.audio_detector.start()
                self._append_log(self._t("log.audio_detector_started"))
            else:
                self.audio_assist.start()
        except Exception as exc:
            self.logger.exception("Audio assistance startup failed: %s", exc)
            self._append_log(self._t("log.audio_start_failed"))

        if camera_started:
            self.gesture_thread = threading.Thread(target=self._gesture_loop, daemon=True)
            self.gesture_thread.start()

        if self.controller_enabled.get():
            self._apply_controller_profile(log_result=False)
            self.controller_thread = threading.Thread(target=self._controller_loop, daemon=True)
            self.controller_thread.start()
            self._append_log(self._t("log.controller_started"))

        self.logger.info("System started")

    def _create_gesture_recognizer(self, camera_index: int) -> Any:
        from adaptive_accessibility.services.gesture_recognizer import GestureRecognizer

        return GestureRecognizer(camera_index=camera_index, calibration_settings=self._camera_calibration_settings())

    def stop_system(self) -> None:
        self._safe_shutdown()
        self.start_button.configure(text=self._t("button.start"))
        self.status_text.set(self._t("status.system_stopped"))
        self._set_status_badge(False)
        self.footer_text.set(self._t("footer.stopped"))
        self.current_gesture_text.set(self._t("activity.none"))
        self.current_command_text.set(self._t("activity.none"))
        self.controller_activity_text.set(self._t("controller.stopped"))
        self._release_control_focus()
        self._append_log(self._t("log.system_stopped"))

    def _gesture_loop(self) -> None:
        recognizer = self.gesture_recognizer
        while self.running and not self.shutting_down:
            if recognizer is None or recognizer.capture is None:
                return

            try:
                result = recognizer.read()
            except Exception as exc:
                self.logger.exception("Gesture loop failed: %s", exc)
                if not self.shutting_down:
                    self.event_queue.put(("gesture_status", self._t("status.gesture_error")))
                return

            if self.shutting_down or not self.running:
                return

            self.event_queue.put(("gesture_status", result.status))
            self.event_queue.put(
                (
                    "camera_feedback",
                    {
                        "status": result.status,
                        "hand_position": result.hand_position,
                        "distance_quality": result.distance_quality,
                    },
                )
            )

            if result.frame is not None:
                now = monotonic()
                if now - self.last_preview_at >= self.preview_interval_seconds:
                    self.last_preview_at = now
                    image_bytes = recognizer.encode_frame(result.frame)
                    if image_bytes is not None and not self.shutting_down and self.running:
                        self.event_queue.put(("camera_frame", image_bytes))

            if result.gesture:
                self.event_queue.put(("gesture_detected", result.gesture))
                mapping = self.input_mapper.map_gesture(result.gesture)
                if mapping and not self.shutting_down and self.running:
                    self.event_queue.put(("mapping", mapping))

    def _controller_loop(self) -> None:
        while self.running and not self.shutting_down and self.controller_enabled.get():
            status = self.controller_mapper.detect_controller()
            now = monotonic()
            if now - self.last_controller_status_at >= 0.5:
                self.last_controller_status_at = now
                self.event_queue.put(("controller_status", status.details))

            if status.available:
                for result in self.controller_mapper.update():
                    if not self.shutting_down and self.running:
                        self.event_queue.put(("controller_mapping", result))
                sleep(0.025)
            else:
                sleep(0.2)

    def _process_events(self) -> None:
        self.event_after_id = None
        if self.shutting_down:
            return

        processed = 0
        max_events_per_tick = 30
        while processed < max_events_per_tick:
            try:
                event_type, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1

            if event_type == "gesture_status":
                if not self.gesture_recognition_enabled.get():
                    continue
                self.current_gesture_text.set(self._translate_gesture_status(payload))
            elif event_type == "camera_feedback":
                if not self.gesture_recognition_enabled.get():
                    continue
                self._update_camera_feedback(payload)
            elif event_type == "gesture_detected":
                if not self.gesture_recognition_enabled.get():
                    continue
                self._handle_gesture_detected(payload)
            elif event_type == "camera_frame":
                if not self.gesture_recognition_enabled.get():
                    continue
                self._update_camera(payload)
            elif event_type == "mapping":
                if not self.gesture_recognition_enabled.get():
                    continue
                self._handle_mapping(payload)
            elif event_type == "controller_status":
                self.controller_status_text.set(self._translate_controller_status(payload))
            elif event_type == "controller_mapping":
                self._handle_controller_mapping(payload)
            elif event_type == "sound_event":
                self._show_sound_event(payload)
            elif event_type == "devices_detected":
                self._handle_devices_detected(payload)
            elif event_type == "device_scan_failed":
                self._handle_device_scan_failed()

        if not self.shutting_down:
            self.event_after_id = self.root.after(80, self._process_events)

    def _update_camera(self, image_bytes: bytes) -> None:
        label = self._active_camera_preview_label()
        if label is None:
            return

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        resized = self._resize_camera_image_for_label(image, label)
        photo = ImageTk.PhotoImage(resized)
        self.camera_photo_images = [photo]
        label.configure(image=photo, text="")
        label.image = photo

    def _active_camera_preview_label(self) -> ttk.Label | None:
        if self.current_page not in {"camera", "gestures"}:
            return None
        return self.camera_preview_labels_by_page.get(self.current_page)

    def _resize_camera_image_for_label(self, image: Image.Image, label: ttk.Label) -> Image.Image:
        container = label.master
        available_width = max(label.winfo_width(), container.winfo_width() if container is not None else 0)
        available_height = max(label.winfo_height(), container.winfo_height() if container is not None else 0)

        if available_width < 120:
            available_width = 760
        if available_height < 120:
            available_height = 430

        available_width = max(320, min(int(available_width) - 24, 980))
        available_height = max(180, min(int(available_height) - 24, 560))

        source_width, source_height = image.size
        ratio = min(available_width / source_width, available_height / source_height)
        target_size = (
            max(1, int(source_width * ratio)),
            max(1, int(source_height * ratio)),
        )
        return image.resize(target_size, Image.Resampling.LANCZOS)

    def _update_camera_feedback(self, payload: dict[str, object]) -> None:
        hand_position = payload.get("hand_position")
        if isinstance(hand_position, tuple):
            self.camera_hand_position_text.set(f"{hand_position[0]:.2f}, {hand_position[1]:.2f}")
        else:
            self.camera_hand_position_text.set(self._t("camera.no_position"))
        status = str(payload.get("status", ""))
        self.camera_detection_status_text.set(self._translate_gesture_status(status))
        self.camera_distance_quality_text.set(self._distance_quality_text(str(payload.get("distance_quality", "unknown"))))

    def _handle_gesture_detected(self, gesture: str) -> None:
        translated = self._translate_runtime_gesture(gesture.replace("_", " "))
        self.stats["gestures_detected"] += 1
        self.gestures_count_text.set(str(self.stats["gestures_detected"]))
        self.last_gesture_text.set(translated)
        self.current_gesture_text.set(translated)

    def _handle_mapping(self, mapping: MappingResult) -> None:
        message = self._translate_mapping_result(mapping)
        self.stats["commands_sent"] += 1
        self.commands_count_text.set(str(self.stats["commands_sent"]))
        self.last_command_text.set(message)
        self.current_command_text.set(mapping.command.upper())
        self._append_log(message)

    def _handle_controller_mapping(self, mapping: ControllerMappingResult) -> None:
        message = self._translate_controller_result(mapping)
        if mapping.command != "mouse_move":
            self.stats["commands_sent"] += 1
            self.commands_count_text.set(str(self.stats["commands_sent"]))
            self.last_command_text.set(message)
        self.controller_activity_text.set(message)
        self.current_command_text.set(mapping.command.upper())
        self._append_log(message)

    def _show_sound_event(self, event: SoundEvent | AudioEvent) -> None:
        if not self.audio_accessibility_enabled.get():
            return
        if not self.audio_enabled.get() and not self.audio_overlay_enabled.get():
            return

        event_label = self._t(f"sound.{event.event_type}")
        if self.audio_overlay_enabled.get():
            self.overlay_manager.configure(self._audio_overlay_settings())
            self.overlay_manager.show_event(event)

        self.stats["alerts_triggered"] += 1
        self.alerts_count_text.set(str(self.stats["alerts_triggered"]))
        self.last_alert_text.set(event_label)
        self._append_log(self._t("log.visual_cue", event=event_label))

        if not self.audio_enabled.get():
            return

        style = "ActionAlert.TLabel" if event.event_type == "nearby_action" else "ActiveAlert.TLabel"
        label = self.alert_labels.get(event.event_type)
        if label is None:
            return
        label.configure(style=style)
        self.root.after(1400, lambda: self._reset_alert_style(label))

    def _enqueue_sound_event(self, event: SoundEvent | AudioEvent) -> None:
        if not self.shutting_down:
            self.event_queue.put(("sound_event", event))

    def _reset_alert_style(self, label: ttk.Label) -> None:
        if not self.shutting_down:
            label.configure(style="Alert.TLabel")

    def _sync_options(self, *, mark_custom: bool = False) -> None:
        profile = PROFILE_CUSTOM if mark_custom else str(self.settings.get("profile", PROFILE_CUSTOM))
        if mark_custom and hasattr(self, "profile_text"):
            self.profile_text.set(self.profile_labels[PROFILE_CUSTOM])
            self.header_profile_text.set(self._short_profile_label(PROFILE_CUSTOM))
        self.input_mapper.set_simulation(self.simulate_inputs.get())
        self.input_mapper.set_mappings(self._gesture_mappings_from_ui())
        self._apply_controller_profile(log_result=False)
        self._apply_audio_runtime_settings()
        self._apply_module_runtime_settings()
        self._apply_camera_runtime_settings()
        self.alerts_enabled_text.set(self._enabled_text(self.audio_enabled.get() or self.audio_overlay_enabled.get()))
        self.inputs_enabled_text.set(self._enabled_text(self.simulate_inputs.get()))
        self._update_module_status_texts()
        self.settings_manager.update(
            {
                "profile": profile,
                "simulate_inputs": self.simulate_inputs.get(),
                "gesture_recognition_enabled": self.gesture_recognition_enabled.get(),
                "audio_accessibility_enabled": self.audio_accessibility_enabled.get(),
                "camera_index": self._selected_camera_index(),
                "camera_zoom": self._camera_zoom_value(),
                "camera_offset_x": round(float(self.camera_offset_x.get()), 2),
                "camera_offset_y": round(float(self.camera_offset_y.get()), 2),
                "camera_mirror": self.camera_mirror.get(),
                "camera_invert_movement": self.camera_invert_movement.get(),
                "camera_tracking_area": self._tracking_area_value(),
                "audio_alerts_enabled": self.audio_enabled.get(),
                "hearing_assistance": self.hearing_assist_enabled.get(),
                "high_contrast": self.high_contrast_enabled.get(),
                "large_text": self.large_text_enabled.get(),
                "reduced_motion": self.reduced_motion_enabled.get(),
                "simplified_ui": self.simplified_ui_enabled.get(),
                "audio_detection_enabled": self.audio_detection_enabled.get(),
                "audio_overlay_enabled": self.audio_overlay_enabled.get(),
                "audio_detection_sensitivity": round(float(self.audio_detection_sensitivity.get()), 2),
                "audio_minimum_volume": round(float(self.audio_minimum_volume.get()), 3),
                "audio_detection_interval": round(float(self.audio_detection_interval.get()), 2),
                "audio_overlay_opacity": round(float(self.audio_overlay_opacity.get()), 2),
                "audio_overlay_duration": round(float(self.audio_overlay_duration.get()), 2),
                "audio_overlay_size": round(float(self.audio_overlay_size.get()), 0),
                "gesture_mappings": self._gesture_mappings_from_ui(),
                "controller_enabled": self.controller_enabled.get(),
                "controller_button_mappings": self._controller_button_mappings(),
                "controller_stick_settings": self._controller_stick_settings(),
                "controller_mouse_settings": self._controller_mouse_settings(),
            }
        )
        self.settings = self.settings_manager.settings

    def _sync_accessibility_options(self) -> None:
        self._sync_options(mark_custom=True)

    def _on_profile_selected(self, _event: object | None = None) -> None:
        profile_key = self.profile_keys_by_label.get(self.profile_text.get(), PROFILE_CUSTOM)
        self.settings = self.settings_manager.apply_profile(profile_key)
        self._apply_current_settings_to_runtime()
        label = self.profile_labels.get(profile_key, self.profile_labels[PROFILE_CUSTOM])
        self.profile_text.set(label)
        self.header_profile_text.set(self._short_profile_label(profile_key))
        self._append_log(self._t("log.profile_loaded", profile=label))

    def _on_language_selected(self, _event: object | None = None) -> None:
        language = self.language_keys_by_label.get(self.language_text.get(), "en")
        self.translator.set_language(language)
        self.settings_manager.set("language", language)
        self.settings = self.settings_manager.settings
        self.header_language_text.set(self.language_names[language])
        self._refresh_language()
        self._append_log(self._t("log.language_changed", language=self.language_names[language]))

    def _apply_current_settings_to_runtime(self) -> None:
        self.simulate_inputs.set(bool(self.settings.get("simulate_inputs", True)))
        self.audio_enabled.set(bool(self.settings.get("audio_alerts_enabled", True)))
        self.gesture_recognition_enabled.set(bool(self.settings.get("gesture_recognition_enabled", True)))
        self.audio_accessibility_enabled.set(bool(self.settings.get("audio_accessibility_enabled", True)))
        self.hearing_assist_enabled.set(bool(self.settings.get("hearing_assistance", self.audio_enabled.get())))
        self.high_contrast_enabled.set(bool(self.settings.get("high_contrast", False)))
        self.large_text_enabled.set(bool(self.settings.get("large_text", False)))
        self.reduced_motion_enabled.set(bool(self.settings.get("reduced_motion", False)))
        self.simplified_ui_enabled.set(bool(self.settings.get("simplified_ui", False)))
        self.controller_enabled.set(bool(self.settings.get("controller_enabled", True)))
        self.audio_detection_enabled.set(bool(self.settings.get("audio_detection_enabled", DEFAULT_AUDIO_DETECTION_SETTINGS["enabled"])))
        self.audio_overlay_enabled.set(bool(self.settings.get("audio_overlay_enabled", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_enabled"])))
        self.audio_detection_sensitivity.set(float(self.settings.get("audio_detection_sensitivity", DEFAULT_AUDIO_DETECTION_SETTINGS["sensitivity"])))
        self.audio_minimum_volume.set(float(self.settings.get("audio_minimum_volume", DEFAULT_AUDIO_DETECTION_SETTINGS["minimum_volume"])))
        self.audio_detection_interval.set(float(self.settings.get("audio_detection_interval", DEFAULT_AUDIO_DETECTION_SETTINGS["detection_interval"])))
        self.audio_overlay_opacity.set(float(self.settings.get("audio_overlay_opacity", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_opacity"])))
        self.audio_overlay_duration.set(float(self.settings.get("audio_overlay_duration", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_duration"])))
        self.audio_overlay_size.set(float(self.settings.get("audio_overlay_size", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_size"])))
        for button, mapping in dict(self.settings.get("controller_button_mappings", DEFAULT_CONTROLLER_BUTTON_MAPPINGS)).items():
            if button in self.controller_mapping_vars:
                self.controller_mapping_vars[button].set(self._controller_mapping_action(mapping).upper())
                self.controller_mapping_mode_vars[button].set(self._controller_mapping_mode(mapping))
                self.controller_mapping_repeat_vars[button].set(self._controller_mapping_repeat(mapping))
        stick_settings = dict(self.settings.get("controller_stick_settings", DEFAULT_CONTROLLER_STICK_SETTINGS))
        for stick, settings in stick_settings.items():
            if stick in self.controller_stick_mode_vars and isinstance(settings, dict):
                self.controller_stick_mode_vars[stick].set(str(settings.get("mode", DEFAULT_CONTROLLER_STICK_SETTINGS[stick]["mode"])))
            if stick in self.controller_stick_mapping_vars and isinstance(settings, dict):
                for direction in ("up", "down", "left", "right"):
                    mapping = settings.get(direction, DEFAULT_CONTROLLER_STICK_SETTINGS[stick][direction])
                    self.controller_stick_mapping_vars[stick][direction].set(self._controller_mapping_action(mapping).upper())
                    self.controller_stick_mapping_mode_vars[stick][direction].set(self._controller_mapping_mode(mapping))
                    self.controller_stick_mapping_repeat_vars[stick][direction].set(self._controller_mapping_repeat(mapping))
        mouse_settings = dict(self.settings.get("controller_mouse_settings", DEFAULT_CONTROLLER_MOUSE_SETTINGS))
        self.controller_mouse_x_sensitivity.set(float(mouse_settings.get("x_sensitivity", 18.0)))
        self.controller_mouse_y_sensitivity.set(float(mouse_settings.get("y_sensitivity", 18.0)))
        self.controller_deadzone.set(float(mouse_settings.get("deadzone", 0.18)))
        self.controller_invert_x.set(bool(mouse_settings.get("invert_x", False)))
        self.controller_invert_y.set(bool(mouse_settings.get("invert_y", False)))
        self.controller_acceleration_enabled.set(bool(mouse_settings.get("acceleration_enabled", False)))
        self.controller_acceleration_factor.set(float(mouse_settings.get("acceleration_factor", 1.4)))
        self.controller_smoothing.set(float(mouse_settings.get("smoothing", 0.35)))
        self.controller_digital_mouse_step.set(float(mouse_settings.get("digital_mouse_step", 18.0)))
        self.camera_sensitivity.set(float(self.settings.get("camera_sensitivity", 0.55)))
        self.gesture_cooldown.set(float(self.settings.get("input_cooldown_seconds", DEFAULT_INPUT_COOLDOWN_SECONDS)))
        self.camera_choice_text.set(self._camera_label(int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX))))
        self.camera_zoom.set(float(self.settings.get("camera_zoom", DEFAULT_CAMERA_CALIBRATION_SETTINGS["zoom"])))
        self.camera_offset_x.set(float(self.settings.get("camera_offset_x", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_x"])))
        self.camera_offset_y.set(float(self.settings.get("camera_offset_y", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_y"])))
        self.camera_mirror.set(bool(self.settings.get("camera_mirror", DEFAULT_CAMERA_CALIBRATION_SETTINGS["mirror"])))
        self.camera_invert_movement.set(bool(self.settings.get("camera_invert_movement", DEFAULT_CAMERA_CALIBRATION_SETTINGS["invert_movement"])))
        self.camera_tracking_area_text.set(self._tracking_area_label(str(self.settings.get("camera_tracking_area", DEFAULT_CAMERA_CALIBRATION_SETTINGS["tracking_area"]))))
        gesture_settings = {**DEFAULT_GESTURE_MAPPINGS, **dict(self.settings.get("gesture_mappings", {}))}
        for gesture, variable in self.gesture_mapping_vars.items():
            variable.set(str(gesture_settings.get(gesture, "")).upper())
        self.input_mapper.set_simulation(self.simulate_inputs.get())
        self.input_mapper.cooldown_seconds = float(self.settings.get("input_cooldown_seconds", DEFAULT_INPUT_COOLDOWN_SECONDS))
        self.input_mapper.set_mappings(self._gesture_mappings_from_ui())
        self._apply_controller_profile(log_result=False)
        self._apply_audio_runtime_settings()
        self.audio_assist.interval_seconds = float(self.settings.get("audio_interval_seconds", DEFAULT_AUDIO_INTERVAL_SECONDS))
        self._apply_camera_runtime_settings()
        self.alerts_enabled_text.set(self._enabled_text(self.audio_enabled.get() or self.audio_overlay_enabled.get()))
        self.inputs_enabled_text.set(self._enabled_text(self.simulate_inputs.get()))
        self._update_module_status_texts()

    def _audio_detection_settings_from_store(self) -> dict[str, float]:
        return {
            "sensitivity": float(self.settings.get("audio_detection_sensitivity", DEFAULT_AUDIO_DETECTION_SETTINGS["sensitivity"])),
            "minimum_volume": float(self.settings.get("audio_minimum_volume", DEFAULT_AUDIO_DETECTION_SETTINGS["minimum_volume"])),
            "detection_interval": float(self.settings.get("audio_detection_interval", DEFAULT_AUDIO_DETECTION_SETTINGS["detection_interval"])),
        }

    def _audio_overlay_settings_from_store(self) -> dict[str, object]:
        return {
            "opacity": float(self.settings.get("audio_overlay_opacity", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_opacity"])),
            "duration": float(self.settings.get("audio_overlay_duration", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_duration"])),
            "size": float(self.settings.get("audio_overlay_size", DEFAULT_AUDIO_DETECTION_SETTINGS["overlay_size"])),
            "labels": self._audio_overlay_labels(),
        }

    def _audio_detection_settings(self) -> dict[str, float]:
        return {
            "sensitivity": round(float(self.audio_detection_sensitivity.get()), 2),
            "minimum_volume": round(float(self.audio_minimum_volume.get()), 3),
            "detection_interval": round(float(self.audio_detection_interval.get()), 2),
        }

    def _audio_overlay_settings(self) -> dict[str, object]:
        return {
            "opacity": round(float(self.audio_overlay_opacity.get()), 2),
            "duration": round(float(self.audio_overlay_duration.get()), 2),
            "size": round(float(self.audio_overlay_size.get()), 0),
            "labels": self._audio_overlay_labels(),
        }

    def _audio_overlay_labels(self) -> dict[str, str]:
        return {
            "left": self._t("alert.left_danger"),
            "center": self._t("alert.nearby_action"),
            "right": self._t("alert.right_danger"),
        }

    def _camera_zoom_value(self) -> float:
        raw = float(self.camera_zoom.get())
        return min((1.0, 1.25, 1.5, 2.0), key=lambda value: abs(value - raw))

    def _camera_calibration_settings(self) -> CameraCalibrationSettings:
        return CameraCalibrationSettings(
            camera_index=self._selected_camera_index(),
            zoom=self._camera_zoom_value(),
            offset_x=max(-1.0, min(1.0, round(float(self.camera_offset_x.get()), 2))),
            offset_y=max(-1.0, min(1.0, round(float(self.camera_offset_y.get()), 2))),
            mirror=self.camera_mirror.get(),
            invert_movement=self.camera_invert_movement.get(),
            tracking_area=self._tracking_area_value(),
        )

    def _camera_calibration_settings_from_store(self) -> CameraCalibrationSettings:
        return CameraCalibrationSettings(
            camera_index=int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX)),
            zoom=float(self.settings.get("camera_zoom", DEFAULT_CAMERA_CALIBRATION_SETTINGS["zoom"])),
            offset_x=float(self.settings.get("camera_offset_x", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_x"])),
            offset_y=float(self.settings.get("camera_offset_y", DEFAULT_CAMERA_CALIBRATION_SETTINGS["offset_y"])),
            mirror=bool(self.settings.get("camera_mirror", DEFAULT_CAMERA_CALIBRATION_SETTINGS["mirror"])),
            invert_movement=bool(self.settings.get("camera_invert_movement", DEFAULT_CAMERA_CALIBRATION_SETTINGS["invert_movement"])),
            tracking_area=str(self.settings.get("camera_tracking_area", DEFAULT_CAMERA_CALIBRATION_SETTINGS["tracking_area"])),
        )

    def _apply_camera_runtime_settings(self) -> None:
        if self.gesture_recognizer is not None:
            self.gesture_recognizer.configure_calibration(self._camera_calibration_settings())

    def _on_camera_calibration_changed(self, *_args: object) -> None:
        if self.camera_calibration_after_id is not None:
            try:
                self.root.after_cancel(self.camera_calibration_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel camera calibration callback: %s", exc)
        self.camera_calibration_after_id = self.root.after(180, self._apply_debounced_camera_calibration)

    def _on_gesture_cooldown_changed(self, *_args: object) -> None:
        try:
            self.input_mapper.cooldown_seconds = float(self.gesture_cooldown.get())
        except (tk.TclError, ValueError):
            return

    def _apply_debounced_camera_calibration(self) -> None:
        self.camera_calibration_after_id = None
        self._apply_camera_runtime_settings()

    def _on_camera_calibration_selected(self, _event: object | None = None) -> None:
        self._apply_camera_runtime_settings()

    def _on_camera_source_changed(self, _event: object | None = None) -> None:
        self.device_manager.camera_index = self._selected_camera_index()
        if self.running and self.gesture_recognition_enabled.get():
            self._stop_gesture_module()
            self._apply_module_runtime_settings()

    def _calibrate_camera(self) -> None:
        recognizer = self.gesture_recognizer
        if recognizer is None:
            message = self._t("camera.calibration_no_hand")
            self._append_log(message)
            self._show_toast(message)
            return

        result = recognizer.calibrator.calibrate(recognizer.last_hand_position, recognizer.last_distance_quality)
        if result.status != "calibration.ready":
            message = self._t("camera.calibration_no_hand")
            self._append_log(message)
            self._show_toast(message)
            return

        offset_x = max(-1.0, min(1.0, float(self.camera_offset_x.get()) + ((result.center_x - 0.5) * 1.4)))
        offset_y = max(-1.0, min(1.0, float(self.camera_offset_y.get()) + ((result.center_y - 0.5) * 1.4)))
        self.camera_offset_x.set(round(offset_x, 2))
        self.camera_offset_y.set(round(offset_y, 2))
        self.camera_zoom.set(result.suggested_zoom)
        self._apply_camera_runtime_settings()
        self._save_settings()
        message = self._t("camera.calibration_ready", zoom=int(result.suggested_zoom * 100))
        self._append_log(self._t("log.camera_calibrated"))
        self._show_toast(message)

    def _apply_audio_runtime_settings(self) -> None:
        if not self.audio_accessibility_enabled.get():
            self.audio_assist.set_enabled(False)
            self.audio_detector.stop()
            self.audio_assist.stop()
            self.overlay_manager.stop()
            return

        detector_was_running = self.audio_detector.running
        simulation_changed = bool(self.audio_detector.simulate_inputs) != bool(self.simulate_inputs.get())
        if detector_was_running and simulation_changed:
            self.audio_detector.stop()

        self.audio_assist.set_enabled((self.audio_enabled.get() or self.hearing_assist_enabled.get()) and not self.audio_detection_enabled.get())
        self.audio_detector.configure(self._audio_detection_settings(), simulate_inputs=self.simulate_inputs.get())
        self.overlay_manager.configure(self._audio_overlay_settings())
        if not self.audio_overlay_enabled.get():
            self.overlay_manager.stop()
        if not self.running:
            return
        if self.audio_detection_enabled.get():
            self.audio_assist.stop()
            self.audio_detector.start()
        else:
            self.audio_detector.stop()
            if self.audio_enabled.get() or self.hearing_assist_enabled.get():
                self.audio_assist.start()

    def _gesture_mappings_from_ui(self) -> dict[str, str]:
        mappings: dict[str, str] = {}
        for gesture, variable in self.gesture_mapping_vars.items():
            command = variable.get().strip().lower()
            if command:
                mappings[gesture] = command
        return mappings

    def _apply_module_runtime_settings(self) -> None:
        self.device_manager.webcam_detection_enabled = self.gesture_recognition_enabled.get()
        if not self.gesture_recognition_enabled.get():
            self._stop_gesture_module()
            self.camera_status_text.set(self._t("card.disabled"))
            self.current_gesture_text.set(self._t("status.gesture_disabled"))
            return

        if self.running and self.gesture_recognizer is None and self.gesture_thread is None:
            camera_index = self._selected_camera_index()
            try:
                self.gesture_recognizer = self._create_gesture_recognizer(camera_index)
                camera_started = self.gesture_recognizer.start()
            except Exception as exc:
                self.logger.exception("Gesture recognizer startup failed: %s", exc)
                camera_started = False

            if not camera_started:
                self.gesture_recognizer = None
                self.camera_status_text.set(self._t("card.unavailable"))
                self.current_gesture_text.set(self._t("status.camera_unavailable"))
                self._append_log(self._t("log.camera_start_failed"))
                return

            backend = "MediaPipe" if self.gesture_recognizer and self.gesture_recognizer.mediapipe_enabled else "OpenCV fallback"
            self.camera_status_text.set(self._t("card.ready"))
            self._append_log(self._t("log.gesture_started", backend=backend))
            self.gesture_thread = threading.Thread(target=self._gesture_loop, daemon=True)
            self.gesture_thread.start()

    def _stop_gesture_module(self) -> None:
        recognizer = self.gesture_recognizer
        self.gesture_recognizer = None
        if recognizer is not None:
            try:
                recognizer.stop()
            except Exception as exc:
                self.logger.exception("Gesture recognizer shutdown failed: %s", exc)
        if self.gesture_thread and self.gesture_thread.is_alive():
            self.gesture_thread.join(timeout=1.0)
        self.gesture_thread = None
        for label in getattr(self, "camera_preview_labels", []):
            label.configure(image="", text=self._t("camera.placeholder"))
        self.photo_image = None
        self.camera_photo_images = []

    def _update_module_status_texts(self) -> None:
        self.controller_module_status_text.set(self._enabled_text(self.controller_enabled.get()))
        self.gesture_module_status_text.set(self._enabled_text(self.gesture_recognition_enabled.get()))
        self.audio_module_status_text.set(self._enabled_text(self.audio_accessibility_enabled.get()))

    def _controller_button_mappings(self) -> dict[str, dict[str, object]]:
        return {
            button: self._controller_mapping_config(
                self.controller_mapping_vars[button],
                self.controller_mapping_mode_vars[button],
                self.controller_mapping_repeat_vars[button],
            )
            for button in self.controller_mapping_vars
            if self.controller_mapping_vars[button].get().strip()
        }

    def _controller_stick_settings(self) -> dict[str, dict[str, object]]:
        return {
            stick: {
                "mode": self.controller_stick_mode_vars[stick].get().strip().lower(),
                "up": self._controller_mapping_config(self.controller_stick_mapping_vars[stick]["up"], self.controller_stick_mapping_mode_vars[stick]["up"], self.controller_stick_mapping_repeat_vars[stick]["up"]),
                "down": self._controller_mapping_config(self.controller_stick_mapping_vars[stick]["down"], self.controller_stick_mapping_mode_vars[stick]["down"], self.controller_stick_mapping_repeat_vars[stick]["down"]),
                "left": self._controller_mapping_config(self.controller_stick_mapping_vars[stick]["left"], self.controller_stick_mapping_mode_vars[stick]["left"], self.controller_stick_mapping_repeat_vars[stick]["left"]),
                "right": self._controller_mapping_config(self.controller_stick_mapping_vars[stick]["right"], self.controller_stick_mapping_mode_vars[stick]["right"], self.controller_stick_mapping_repeat_vars[stick]["right"]),
            }
            for stick in ("left_stick", "right_stick")
        }

    def _controller_mapping_config(self, action_var: tk.StringVar, mode_var: tk.StringVar, repeat_var: tk.DoubleVar) -> dict[str, object]:
        mode = mode_var.get().strip().lower()
        if mode not in {"tap", "hold", "turbo"}:
            mode = "tap"
        return {
            "key": action_var.get().strip().lower(),
            "mode": mode,
            "repeat_rate": self._controller_repeat_rate_value(repeat_var.get()),
        }

    def _controller_mapping_action(self, mapping: object) -> str:
        if isinstance(mapping, dict):
            return str(mapping.get("key", mapping.get("action", mapping.get("command", "")))).strip()
        return str(mapping).strip()

    def _controller_mapping_mode(self, mapping: object) -> str:
        action = self._controller_mapping_action(mapping).lower()
        default_mode = "hold" if action in {"mouse:up", "mouse:down", "mouse:left", "mouse:right"} else "tap"
        if isinstance(mapping, dict):
            mode = str(mapping.get("mode", default_mode)).strip().lower()
            return mode if mode in {"tap", "hold", "turbo"} else default_mode
        return default_mode

    def _controller_mapping_repeat(self, mapping: object) -> int:
        if isinstance(mapping, dict):
            return self._controller_repeat_rate_value(mapping.get("repeat_rate", 10))
        return 10

    def _controller_repeat_rate_value(self, value: object) -> int:
        try:
            rate = int(round(float(value)))
        except (TypeError, ValueError):
            rate = 10
        return max(1, min(30, rate))

    def _controller_mouse_settings(self) -> dict[str, float | bool]:
        return {
            "x_sensitivity": round(float(self.controller_mouse_x_sensitivity.get()), 2),
            "y_sensitivity": round(float(self.controller_mouse_y_sensitivity.get()), 2),
            "deadzone": round(float(self.controller_deadzone.get()), 2),
            "invert_x": self.controller_invert_x.get(),
            "invert_y": self.controller_invert_y.get(),
            "acceleration_enabled": self.controller_acceleration_enabled.get(),
            "acceleration_factor": round(float(self.controller_acceleration_factor.get()), 2),
            "smoothing": round(float(self.controller_smoothing.get()), 2),
            "digital_mouse_step": round(float(self.controller_digital_mouse_step.get()), 2),
        }

    def _controller_profile(self) -> dict[str, object]:
        return {
            "simulate_inputs": self.simulate_inputs.get(),
            "button_mappings": self._controller_button_mappings(),
            "stick_settings": self._controller_stick_settings(),
            "mouse_settings": self._controller_mouse_settings(),
        }

    def _apply_controller_profile(self, *, log_result: bool = True) -> None:
        self.controller_mapper.load_profile(self._controller_profile())
        if log_result:
            self._append_log(self._t("log.controller_mappings_applied"))

    def _reset_controller_defaults(self) -> None:
        for button, mapping in DEFAULT_CONTROLLER_BUTTON_MAPPINGS.items():
            self.controller_mapping_vars[button].set(self._controller_mapping_action(mapping).upper())
            self.controller_mapping_mode_vars[button].set(self._controller_mapping_mode(mapping))
            self.controller_mapping_repeat_vars[button].set(self._controller_mapping_repeat(mapping))
        for stick, settings in DEFAULT_CONTROLLER_STICK_SETTINGS.items():
            self.controller_stick_mode_vars[stick].set(settings["mode"])
            for direction in ("up", "down", "left", "right"):
                mapping = settings[direction]
                self.controller_stick_mapping_vars[stick][direction].set(self._controller_mapping_action(mapping).upper())
                self.controller_stick_mapping_mode_vars[stick][direction].set(self._controller_mapping_mode(mapping))
                self.controller_stick_mapping_repeat_vars[stick][direction].set(self._controller_mapping_repeat(mapping))
        self.controller_mouse_x_sensitivity.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["x_sensitivity"]))
        self.controller_mouse_y_sensitivity.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["y_sensitivity"]))
        self.controller_deadzone.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["deadzone"]))
        self.controller_invert_x.set(bool(DEFAULT_CONTROLLER_MOUSE_SETTINGS["invert_x"]))
        self.controller_invert_y.set(bool(DEFAULT_CONTROLLER_MOUSE_SETTINGS["invert_y"]))
        self.controller_acceleration_enabled.set(bool(DEFAULT_CONTROLLER_MOUSE_SETTINGS["acceleration_enabled"]))
        self.controller_acceleration_factor.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["acceleration_factor"]))
        self.controller_smoothing.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["smoothing"]))
        self.controller_digital_mouse_step.set(float(DEFAULT_CONTROLLER_MOUSE_SETTINGS["digital_mouse_step"]))
        self._apply_controller_profile()

    def _export_controller_profile(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{self.controller_profile_name.get().strip() or 'Custom'}.json",
        )
        if not path:
            return
        self.controller_mapper.load_profile(self._controller_profile())
        self.controller_mapper.export_profile(path, self.controller_profile_name.get().strip() or "Custom")
        self._append_log(self._t("controller.profile_exported"))

    def _import_controller_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        profile = self.controller_mapper.import_profile(path)
        self._load_controller_profile_to_ui(profile)
        self._append_log(self._t("controller.profile_imported"))

    def _load_controller_profile_to_ui(self, profile: dict[str, object]) -> None:
        button_mappings = profile.get("button_mappings", {})
        if isinstance(button_mappings, dict):
            for button, mapping in button_mappings.items():
                if button in self.controller_mapping_vars:
                    self.controller_mapping_vars[button].set(self._controller_mapping_action(mapping).upper())
                    self.controller_mapping_mode_vars[button].set(self._controller_mapping_mode(mapping))
                    self.controller_mapping_repeat_vars[button].set(self._controller_mapping_repeat(mapping))
        stick_settings = profile.get("stick_settings", {})
        if isinstance(stick_settings, dict):
            for stick, settings in stick_settings.items():
                if stick in self.controller_stick_mapping_vars and isinstance(settings, dict):
                    self.controller_stick_mode_vars[stick].set(str(settings.get("mode", "disabled")))
                    for direction in ("up", "down", "left", "right"):
                        mapping = settings.get(direction, "")
                        self.controller_stick_mapping_vars[stick][direction].set(self._controller_mapping_action(mapping).upper())
                        self.controller_stick_mapping_mode_vars[stick][direction].set(self._controller_mapping_mode(mapping))
                        self.controller_stick_mapping_repeat_vars[stick][direction].set(self._controller_mapping_repeat(mapping))
        mouse_settings = profile.get("mouse_settings", {})
        if isinstance(mouse_settings, dict):
            self.controller_mouse_x_sensitivity.set(float(mouse_settings.get("x_sensitivity", self.controller_mouse_x_sensitivity.get())))
            self.controller_mouse_y_sensitivity.set(float(mouse_settings.get("y_sensitivity", self.controller_mouse_y_sensitivity.get())))
            self.controller_deadzone.set(float(mouse_settings.get("deadzone", self.controller_deadzone.get())))
            self.controller_invert_x.set(bool(mouse_settings.get("invert_x", self.controller_invert_x.get())))
            self.controller_invert_y.set(bool(mouse_settings.get("invert_y", self.controller_invert_y.get())))
            self.controller_acceleration_enabled.set(bool(mouse_settings.get("acceleration_enabled", self.controller_acceleration_enabled.get())))
            self.controller_acceleration_factor.set(float(mouse_settings.get("acceleration_factor", self.controller_acceleration_factor.get())))
            self.controller_smoothing.set(float(mouse_settings.get("smoothing", self.controller_smoothing.get())))
            self.controller_digital_mouse_step.set(float(mouse_settings.get("digital_mouse_step", self.controller_digital_mouse_step.get())))
    def _selected_camera_index(self) -> int:
        match = re.search(r"(\d+)", self.camera_choice_text.get())
        return int(match.group(1)) if match else DEFAULT_CAMERA_INDEX

    def _save_settings(self) -> None:
        theme = "dark" if self.theme_text.get() == self._t("settings.theme_dark") else "light"
        self.input_mapper.cooldown_seconds = float(self.gesture_cooldown.get())
        self.settings_manager.update(
            {
                "language": self.language_keys_by_label.get(self.language_text.get(), "en"),
                "camera_index": self._selected_camera_index(),
                "simulate_inputs": self.simulate_inputs.get(),
                "gesture_recognition_enabled": self.gesture_recognition_enabled.get(),
                "audio_accessibility_enabled": self.audio_accessibility_enabled.get(),
                "camera_sensitivity": round(float(self.camera_sensitivity.get()), 2),
                "camera_zoom": self._camera_zoom_value(),
                "camera_offset_x": round(float(self.camera_offset_x.get()), 2),
                "camera_offset_y": round(float(self.camera_offset_y.get()), 2),
                "camera_mirror": self.camera_mirror.get(),
                "camera_invert_movement": self.camera_invert_movement.get(),
                "camera_tracking_area": self._tracking_area_value(),
                "input_cooldown_seconds": round(float(self.gesture_cooldown.get()), 2),
                "theme": theme,
                "high_contrast": self.high_contrast_enabled.get(),
                "large_text": self.large_text_enabled.get(),
                "reduced_motion": self.reduced_motion_enabled.get(),
                "simplified_ui": self.simplified_ui_enabled.get(),
                "audio_detection_enabled": self.audio_detection_enabled.get(),
                "audio_overlay_enabled": self.audio_overlay_enabled.get(),
                "audio_detection_sensitivity": round(float(self.audio_detection_sensitivity.get()), 2),
                "audio_minimum_volume": round(float(self.audio_minimum_volume.get()), 3),
                "audio_detection_interval": round(float(self.audio_detection_interval.get()), 2),
                "audio_overlay_opacity": round(float(self.audio_overlay_opacity.get()), 2),
                "audio_overlay_duration": round(float(self.audio_overlay_duration.get()), 2),
                "audio_overlay_size": round(float(self.audio_overlay_size.get()), 0),
                "gesture_mappings": self._gesture_mappings_from_ui(),
                "controller_enabled": self.controller_enabled.get(),
                "controller_button_mappings": self._controller_button_mappings(),
                "controller_stick_settings": self._controller_stick_settings(),
                "controller_mouse_settings": self._controller_mouse_settings(),
            }
        )
        self.settings = self.settings_manager.settings
        self.device_manager.camera_index = int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX))
        self.device_manager.webcam_detection_enabled = self.gesture_recognition_enabled.get()
        self.input_mapper.set_mappings(self._gesture_mappings_from_ui())
        self._apply_module_runtime_settings()
        self._apply_camera_runtime_settings()
        self._apply_audio_runtime_settings()
        self._update_module_status_texts()
        self._append_log(self._t("settings.saved"))
        self._show_toast(self._t("toast.saved"))

    def _set_device_row(self, row: tuple[ttk.Label, ttk.Label, ttk.Label, ttk.Label], device: DeviceInfo) -> None:
        name, status, category, details = row
        name.configure(text=self._translate_device_name(device.name))
        status.configure(
            text=self._t("status.available") if device.available else self._t("status.missing"),
            style="Available.TLabel" if device.available else "Missing.TLabel",
        )
        category.configure(text=device.category)
        details.configure(text=self._translate_device_detail(device.details))

    def _translate_device_name(self, name: str) -> str:
        device_keys = {
            "Keyboard": "device.keyboard",
            "Mouse": "device.mouse",
            "Webcam": "device.webcam",
            "Gamepad": "device.gamepad",
            "Controller mapper": "device.controller_mapper",
            "Adaptive controller": "device.adaptive_controller",
        }
        key = device_keys.get(name)
        return self._t(key) if key else name

    def _translate_device_detail(self, detail: str) -> str:
        exact_matches = {
            "System keyboard assumed available": "device.detail.keyboard",
            "System pointing device assumed available": "device.detail.mouse",
            "OpenCV is not installed": "device.detail.opencv_missing",
            "pygame is not installed": "device.detail.pygame_missing",
            "No controller detected": "device.detail.controller_missing",
            "Simulated adaptive controller enabled for research demo": "device.detail.adaptive_simulated",
            "Webcam scan disabled because gesture recognition is disabled": "device.detail.webcam_scan_disabled",
        }
        key = exact_matches.get(detail)
        if key:
            return self._t(key)

        camera_ready = re.fullmatch(r"Camera index (\d+) ready", detail)
        if camera_ready:
            return self._t("device.detail.camera_ready", index=camera_ready.group(1))

        camera_missing = re.fullmatch(r"No camera found at index (\d+)", detail)
        if camera_missing:
            return self._t("device.detail.camera_missing", index=camera_missing.group(1))

        gamepad_count = re.fullmatch(r"(\d+) joystick/gamepad device\(s\) detected", detail)
        if gamepad_count:
            return self._t("device.detail.gamepad_count", count=gamepad_count.group(1))

        controller_ready = re.fullmatch(r"Controller ready: (.+)", detail)
        if controller_ready:
            return self._t("device.detail.controller_ready", name=controller_ready.group(1))

        controller_count = re.fullmatch(r"(\d+) controller\(s\) detected", detail)
        if controller_count:
            return self._t("device.detail.controller_count", count=controller_count.group(1))

        return detail

    def _translate_controller_status(self, status: str) -> str:
        return self._translate_device_detail(status)

    def _translate_gesture_status(self, status: str) -> str:
        exact_matches = {
            "Camera is not running": "gesture.status.camera_stopped",
            "Unable to read webcam frame": "gesture.status.frame_error",
            "Waiting for hand gesture": "gesture.status.waiting",
            "Hand tracked": "gesture.status.tracked",
            "OpenCV fallback active; calibrating motion": "gesture.status.fallback_calibrating",
            "OpenCV fallback active; no motion": "gesture.status.fallback_no_motion",
            "OpenCV fallback active; low motion": "gesture.status.fallback_low_motion",
            "OpenCV fallback active; move hand left or right": "gesture.status.fallback_move",
        }
        key = exact_matches.get(status)
        if key:
            return self._t(key)

        if status.startswith("Detected "):
            gesture = status.removeprefix("Detected ")
            return self._t("gesture.status.detected", gesture=self._translate_runtime_gesture(gesture))

        return status

    def _translate_runtime_gesture(self, gesture: str) -> str:
        gesture_keys = {
            "left movement": "gesture.left_movement",
            "right movement": "gesture.right_movement",
            "open hand": "gesture.open_hand_value",
            "closed fist": "gesture.closed_fist_value",
            "hand raise": "gesture.hand_raise_value",
        }
        if gesture.startswith("finger count "):
            count = gesture.removeprefix("finger count ")
            return self._t(f"gesture.finger_count_{count}_value")
        key = gesture_keys.get(gesture)
        return self._t(key) if key else gesture

    def _translate_mapping_result(self, mapping: MappingResult) -> str:
        gesture = self._translate_runtime_gesture(mapping.gesture.replace("_", " "))
        command = mapping.command.upper()
        if mapping.message.startswith("Simulated"):
            return self._t("mapping.simulated", gesture=gesture, command=command)
        if mapping.message.startswith("Failed"):
            return self._t("mapping.failed", gesture=gesture, command=command)
        if "pynput unavailable" in mapping.message:
            return self._t("mapping.unavailable")
        if mapping.executed:
            return self._t("mapping.sent", gesture=gesture, command=command)
        return mapping.message

    def _translate_controller_result(self, mapping: ControllerMappingResult) -> str:
        command = mapping.command.upper()
        if "pynput unavailable" in mapping.message:
            return self._t("controller.unavailable")
        if mapping.message.startswith("Simulated mouse") or mapping.message.startswith("Simulated mouse movement"):
            return self._t("controller.mouse_simulated", action=mapping.message.removeprefix("Simulated "))
        if mapping.message.startswith("Sent mouse"):
            return self._t("controller.mouse_sent", action=mapping.message.removeprefix("Sent "))
        if mapping.message.startswith("Failed"):
            return self._t("controller.failed", source=mapping.source, command=command)
        if mapping.message.startswith("Simulated"):
            return self._t("controller.simulated", source=mapping.source, command=command)
        if mapping.executed:
            return self._t("controller.sent", source=mapping.source, command=command)
        return mapping.message
    def _refresh_language(self) -> None:
        self.profile_labels = self._localized_profile_labels()
        self.profile_keys_by_label = {label: key for key, label in self.profile_labels.items()}
        selected_profile = str(self.settings.get("profile", PROFILE_CUSTOM))
        self.profile_text.set(self.profile_labels.get(selected_profile, self.profile_labels[PROFILE_CUSTOM]))
        self.header_profile_text.set(self._short_profile_label(selected_profile))
        self.header_language_text.set(self.language_text.get())
        self.theme_text.set(self._theme_label(str(self.settings.get("theme", "light"))))

        if hasattr(self, "profile_selector"):
            self.profile_selector.configure(values=list(self.profile_labels.values()))
        if hasattr(self, "language_selector"):
            self.language_selector.configure(values=list(self.language_names.values()))
        if hasattr(self, "theme_selector"):
            self.theme_selector.configure(values=[self._t("settings.theme_light"), self._t("settings.theme_dark")])
        if self.settings_notebook is not None:
            self.settings_notebook.tab(0, text=self._t("settings.general_tab"))
            self.settings_notebook.tab(1, text=self._t("settings.audio_tab"))
            self.settings_notebook.tab(2, text=self._t("settings.controller_tab"))
        if self.controller_settings_notebook is not None:
            self.controller_settings_notebook.tab(0, text=self._t("controller.tab.status"))
            self.controller_settings_notebook.tab(1, text=self._t("controller.tab.sticks"))
            self.controller_settings_notebook.tab(2, text=self._t("controller.tab.mouse"))
            self.controller_settings_notebook.tab(3, text=self._t("controller.tab.buttons"))
            self.controller_settings_notebook.tab(4, text=self._t("controller.tab.profiles"))
        if self.camera_selectors:
            camera_index = int(self.settings.get("camera_index", DEFAULT_CAMERA_INDEX))
            for selector in self.camera_selectors:
                selector.configure(values=self._camera_options())
            self.camera_choice_text.set(self._camera_label(camera_index))
        if self.camera_tracking_area_selectors:
            tracking_area = str(self.settings.get("camera_tracking_area", DEFAULT_CAMERA_CALIBRATION_SETTINGS["tracking_area"]))
            for selector in self.camera_tracking_area_selectors:
                selector.configure(values=self._tracking_area_options())
            self.camera_tracking_area_text.set(self._tracking_area_label(tracking_area))

        for widget, translation_key in self.translatable_widgets:
            widget.configure(text=self._t(translation_key))
        for page_key, button in self.sidebar_buttons.items():
            text_key = self.sidebar_button_keys.get(page_key)
            if text_key:
                button.configure(text=self._sidebar_text(page_key, text_key))

        if not self.running:
            self.start_button.configure(text=self._t("button.start"))
            self.status_text.set(self._t("status.system_stopped"))
            self._set_status_badge(False)
            self.footer_text.set(self._t("footer.stopped"))
        else:
            self.start_button.configure(text=self._t("button.stop"))
            self.status_text.set(self._t("status.system_running"))
            self._set_status_badge(True)
            self.footer_text.set(self._t("footer.running"))

        self.alerts_enabled_text.set(self._enabled_text(self.audio_enabled.get() or self.audio_overlay_enabled.get()))
        self.inputs_enabled_text.set(self._enabled_text(self.simulate_inputs.get()))
        self._update_module_status_texts()
        if not self.gesture_recognition_enabled.get():
            self.current_gesture_text.set(self._t("status.gesture_disabled"))
            self.camera_status_text.set(self._t("card.disabled"))
        if self.controller_activity_text.get() in {"Controller mapper ready", "Mapeador de controlador listo"}:
            self.controller_activity_text.set(self._t("controller.ready"))
        if self.controller_status_text.get() in {"Controller not detected", "Controlador no detectado"}:
            self.controller_status_text.set(self._t("controller.not_detected"))
        self.average_response_text.set(self._t("statistics.not_available"))
        if self.confidence_text.get() in {"N/A", "N/D", self._t("statistics.not_available")}:
            self.confidence_text.set(self._t("statistics.not_available"))
        for label in self.camera_preview_labels:
            if label.cget("image") == "":
                label.configure(text=self._t("camera.placeholder"))

        for row, device in zip(self.device_rows, self.last_devices):
            self._set_device_row(row, device)

    def _update_session_time(self) -> None:
        if self.session_started_at is not None and self.running:
            elapsed = int(monotonic() - self.session_started_at)
            minutes, seconds = divmod(elapsed, 60)
            self.session_time_text.set(f"{minutes:02d}:{seconds:02d}")
        if not self.shutting_down:
            self.session_after_id = self.root.after(1000, self._update_session_time)

    def _append_log(self, message: str) -> None:
        self.footer_text.set(message)
        self.logger.info(message)

    def _show_toast(self, message: str) -> None:
        if self.shutting_down:
            return
        if self.toast_after_id is not None:
            try:
                self.root.after_cancel(self.toast_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel toast callback: %s", exc)
            self.toast_after_id = None
        if self.toast_label is None:
            self.toast_label = ttk.Label(self.root, style="Toast.TLabel", padding=(14, 9))
        self.toast_label.configure(text=message)
        self.toast_label.place(relx=0.985, rely=0.94, anchor="se")
        self.toast_after_id = self.root.after(2200, self._hide_toast)

    def _hide_toast(self) -> None:
        self.toast_after_id = None
        if self.toast_label is not None:
            self.toast_label.place_forget()

    def _on_close(self) -> None:
        self._safe_shutdown(closing=True)
        self.root.destroy()

    def _safe_shutdown(self, *, closing: bool = False) -> None:
        if self.shutting_down and not self.running and self.gesture_recognizer is None:
            return

        self.shutting_down = True
        self.running = False

        if closing and self.event_after_id is not None:
            try:
                self.root.after_cancel(self.event_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel event polling callback: %s", exc)
            self.event_after_id = None

        if closing and self.session_after_id is not None:
            try:
                self.root.after_cancel(self.session_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel session callback: %s", exc)
            self.session_after_id = None

        if closing and self.toast_after_id is not None:
            try:
                self.root.after_cancel(self.toast_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel toast callback: %s", exc)
            self.toast_after_id = None

        if self.camera_calibration_after_id is not None:
            try:
                self.root.after_cancel(self.camera_calibration_after_id)
            except Exception as exc:
                self.logger.debug("Could not cancel camera calibration callback: %s", exc)
            self.camera_calibration_after_id = None

        try:
            self.audio_detector.stop()
            self.overlay_manager.stop()
            self.audio_assist.stop()
        except Exception as exc:
            self.logger.exception("Audio assistance shutdown failed: %s", exc)

        recognizer = self.gesture_recognizer
        if recognizer is not None:
            try:
                recognizer.stop()
            except Exception as exc:
                self.logger.exception("Gesture recognizer shutdown failed: %s", exc)

        if self.gesture_thread and self.gesture_thread.is_alive():
            self.gesture_thread.join(timeout=1.0)
        self.gesture_thread = None
        if self.controller_thread and self.controller_thread.is_alive():
            self.controller_thread.join(timeout=1.0)
        self.controller_thread = None
        try:
            self.controller_mapper.stop()
        except Exception as exc:
            self.logger.exception("Controller mapper shutdown failed: %s", exc)
        if self.device_thread and self.device_thread.is_alive():
            self.device_thread.join(timeout=0.2)
        self.device_thread = None
        self.device_scan_in_progress = False
        self.gesture_recognizer = None
        self._clear_event_queue()
        self.settings_manager.save()
        self.logger.info("System stopped")

        if not closing:
            self.shutting_down = False
            if self.event_after_id is None:
                self.event_after_id = self.root.after(80, self._process_events)

    def _clear_event_queue(self) -> None:
        while True:
            try:
                self.event_queue.get_nowait()
            except queue.Empty:
                return







