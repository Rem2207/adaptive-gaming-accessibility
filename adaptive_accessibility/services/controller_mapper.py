from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from time import monotonic
from typing import Any

from adaptive_accessibility.core.constants import (
    CONTROLLER_PROFILE_DIR,
    DEFAULT_CONTROLLER_BUTTON_MAPPINGS,
    DEFAULT_CONTROLLER_MOUSE_SETTINGS,
    DEFAULT_CONTROLLER_STICK_SETTINGS,
)


@dataclass(frozen=True)
class ControllerStatus:
    available: bool
    name: str
    details: str


@dataclass(frozen=True)
class ControllerMappingResult:
    source: str
    command: str
    executed: bool
    message: str


class ControllerMapper:
    """Fully configurable mapper for gamepads, arcade sticks, hitboxes, and adaptive controllers."""

    BUTTON_INDEX_NAMES = {
        0: "A",
        1: "B",
        2: "X",
        3: "Y",
        4: "LB",
        5: "RB",
        6: "Select",
        7: "Start",
        8: "L3",
        9: "R3",
    }
    TRIGGER_AXES = {"LT": 4, "RT": 5}
    STICK_AXES = {
        "left_stick": (0, 1),
        "right_stick": (2, 3),
    }
    STICK_LABELS = {
        "left_stick": "Left Stick",
        "right_stick": "Right Stick",
    }
    MODES = {"disabled", "mouse", "digital", "custom"}
    ACTIVATION_MODES = {"tap", "hold", "turbo"}
    DEFAULT_REPEAT_RATE = 10
    MIN_REPEAT_RATE = 1
    MAX_REPEAT_RATE = 30
    DIRECTIONS = ("up", "down", "left", "right")

    def __init__(
        self,
        simulate_inputs: bool = True,
        button_mappings: dict[str, Any] | None = None,
        stick_settings: dict[str, Any] | None = None,
        mouse_settings: dict[str, Any] | None = None,
        profile_dir: Path = CONTROLLER_PROFILE_DIR,
        click_threshold: float = 0.55,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.simulate_inputs = simulate_inputs
        self.button_mappings = self._normalize_button_mappings(button_mappings)
        self.stick_settings = self._merge_stick_settings(stick_settings)
        self.mouse_settings = self._merge_mouse_settings(mouse_settings)
        self.profile_dir = profile_dir
        self.click_threshold = click_threshold

        self._pygame = None
        self._joystick = None
        self._keyboard = None
        self._mouse = None
        self._key_lookup = {}
        self._mouse_button_lookup = {}
        self._button_states: dict[str, bool] = {}
        self._trigger_states = {"LT": False, "RT": False}
        self._hat_states = {name: False for name in self._dpad_names().values()}
        self._stick_direction_states: dict[str, bool] = {}
        self._held_outputs: dict[str, str] = {}
        self._turbo_last_sent_at: dict[str, float] = {}
        self._last_mouse_status_at = 0.0
        self._last_digital_mouse_status_at = 0.0
        self._smoothed_delta = {
            "left_stick": (0.0, 0.0),
            "right_stick": (0.0, 0.0),
        }

        self._load_backends()

    @property
    def backend_available(self) -> bool:
        return self._keyboard is not None and self._mouse is not None

    @property
    def controller_name(self) -> str:
        if self._joystick is None:
            return ""
        try:
            return str(self._joystick.get_name())
        except Exception:
            return ""

    @property
    def x_sensitivity(self) -> float:
        return float(self.mouse_settings.get("x_sensitivity", 18.0))

    @property
    def y_sensitivity(self) -> float:
        return float(self.mouse_settings.get("y_sensitivity", 18.0))

    @property
    def deadzone(self) -> float:
        return float(self.mouse_settings.get("deadzone", 0.18))

    @property
    def acceleration_enabled(self) -> bool:
        return bool(self.mouse_settings.get("acceleration_enabled", False))

    @property
    def acceleration_factor(self) -> float:
        return float(self.mouse_settings.get("acceleration_factor", 1.4))

    @property
    def smoothing(self) -> float:
        return max(0.0, min(0.95, float(self.mouse_settings.get("smoothing", 0.35))))

    @property
    def digital_mouse_step(self) -> float:
        return float(self.mouse_settings.get("digital_mouse_step", 18.0))

    def set_simulation(self, enabled: bool) -> None:
        self.simulate_inputs = enabled

    def detect_controller(self) -> ControllerStatus:
        if self._pygame is None:
            return ControllerStatus(False, "", "pygame is not installed")

        try:
            self._pygame.joystick.init()
            count = self._pygame.joystick.get_count()
            if count <= 0:
                self._joystick = None
                return ControllerStatus(False, "", "No controller detected")

            if self._joystick is None:
                self._joystick = self._pygame.joystick.Joystick(0)
                self._joystick.init()

            return ControllerStatus(True, self.controller_name or "Controller", f"{count} controller(s) detected")
        except Exception as exc:
            self.logger.exception("Controller detection failed: %s", exc)
            self._joystick = None
            return ControllerStatus(False, "", f"Controller detection failed: {exc}")

    def update(self) -> list[ControllerMappingResult]:
        status = self.detect_controller()
        if not status.available or self._joystick is None or self._pygame is None:
            return []

        results: list[ControllerMappingResult] = []
        try:
            self._pygame.event.pump()
            results.extend(self._update_buttons())
            results.extend(self._update_triggers())
            results.extend(self._update_dpad())
            results.extend(self._update_sticks())
        except Exception as exc:
            self.logger.exception("Controller update failed: %s", exc)
            results.append(ControllerMappingResult("Controller", "update", False, f"Controller update failed: {exc}"))

        return results

    def map_button(self, button_name: str, pressed: bool) -> list[ControllerMappingResult]:
        previous = self._button_states.get(button_name, False)
        self._button_states[button_name] = pressed
        return self._process_mapping_state(button_name, self.button_mappings.get(button_name, ""), pressed, previous)

    def map_axis(self) -> ControllerMappingResult | None:
        if self._joystick is None:
            return None
        results = self._update_sticks() + self._update_triggers()
        return results[-1] if results else None

    def move_mouse(self, x_axis: float, y_axis: float, *, stick_name: str = "left_stick") -> ControllerMappingResult | None:
        x_axis, y_axis = self._apply_axis_options(x_axis, y_axis)
        if abs(x_axis) < self.deadzone and abs(y_axis) < self.deadzone:
            self._smoothed_delta[stick_name] = (0.0, 0.0)
            return None

        dx = x_axis * self.x_sensitivity
        dy = y_axis * self.y_sensitivity
        if self.acceleration_enabled:
            magnitude = min(1.0, max(abs(x_axis), abs(y_axis)))
            factor = 1.0 + (magnitude * max(0.0, self.acceleration_factor - 1.0))
            dx *= factor
            dy *= factor

        dx, dy = self._smooth_delta(stick_name, dx, dy)
        int_dx = int(dx)
        int_dy = int(dy)
        if int_dx == 0 and int_dy == 0:
            return None

        if self.simulate_inputs:
            now = monotonic()
            if now - self._last_mouse_status_at >= 0.5:
                self._last_mouse_status_at = now
                return ControllerMappingResult(self.STICK_LABELS.get(stick_name, stick_name), "mouse_move", False, "Simulated mouse movement")
            return None

        if self._mouse is None:
            return ControllerMappingResult(self.STICK_LABELS.get(stick_name, stick_name), "mouse_move", False, "pynput unavailable; mouse movement logged only")

        try:
            self._mouse.move(int_dx, int_dy)
        except Exception as exc:
            self.logger.exception("Failed to move mouse from controller: %s", exc)
            return ControllerMappingResult(self.STICK_LABELS.get(stick_name, stick_name), "mouse_move", False, "Failed to move mouse from controller")
        return None

    def click_mouse(self, button_name: str) -> ControllerMappingResult:
        return self._execute_mouse_action(button_name.upper(), f"mouse:{button_name}_click")

    def load_profile(self, profile: dict[str, Any]) -> None:
        self._release_all_held_outputs()
        mappings = profile.get("button_mappings")
        if isinstance(mappings, dict):
            self.button_mappings.update(self._normalize_button_mappings(mappings, include_defaults=False))

        stick_settings = profile.get("stick_settings")
        if isinstance(stick_settings, dict):
            self.stick_settings = self._merge_stick_settings(stick_settings)

        mouse_settings = profile.get("mouse_settings")
        if isinstance(mouse_settings, dict):
            self.mouse_settings = self._merge_mouse_settings(mouse_settings)

        self.simulate_inputs = bool(profile.get("simulate_inputs", self.simulate_inputs))

    def to_profile(self, name: str = "Custom") -> dict[str, Any]:
        return {
            "name": name,
            "simulate_inputs": self.simulate_inputs,
            "button_mappings": dict(self.button_mappings),
            "stick_settings": deepcopy(self.stick_settings),
            "mouse_settings": deepcopy(self.mouse_settings),
        }

    def export_profile(self, path: str | Path, name: str = "Custom") -> None:
        profile_path = Path(path)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with profile_path.open("w", encoding="utf-8") as file:
            json.dump(self.to_profile(name), file, indent=2, sort_keys=True)

    def import_profile(self, path: str | Path) -> dict[str, Any]:
        profile_path = Path(path)
        with profile_path.open("r", encoding="utf-8") as file:
            profile = json.load(file)
        if not isinstance(profile, dict):
            raise ValueError("Controller profile must be a JSON object")
        self.load_profile(profile)
        return profile

    def save_named_profile(self, name: str) -> Path:
        safe_name = "".join(char for char in name if char.isalnum() or char in {"-", "_", " "}).strip() or "Custom"
        path = self.profile_dir / f"{safe_name.replace(' ', '_')}.json"
        self.export_profile(path, safe_name)
        return path

    def load_named_profile(self, name: str) -> dict[str, Any]:
        path = self.profile_dir / f"{name.replace(' ', '_')}.json"
        return self.import_profile(path)

    def stop(self) -> None:
        self._release_all_held_outputs()
        self._turbo_last_sent_at.clear()
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception as exc:
                self.logger.debug("Could not quit joystick: %s", exc)
        self._joystick = None

    def _update_buttons(self) -> list[ControllerMappingResult]:
        if self._joystick is None:
            return []
        results = []
        for index, button_name in self.BUTTON_INDEX_NAMES.items():
            if index < self._joystick.get_numbuttons():
                results.extend(self.map_button(button_name, bool(self._joystick.get_button(index))))
        return results

    def _update_triggers(self) -> list[ControllerMappingResult]:
        if self._joystick is None:
            return []
        results = []
        for trigger_name, axis_index in self.TRIGGER_AXES.items():
            if self._joystick.get_numaxes() <= axis_index:
                continue
            pressed = self._joystick.get_axis(axis_index) > self.click_threshold
            previous = self._trigger_states.get(trigger_name, False)
            self._trigger_states[trigger_name] = pressed
            results.extend(self._process_mapping_state(trigger_name, self.button_mappings.get(trigger_name, ""), pressed, previous))
        return results

    def _update_dpad(self) -> list[ControllerMappingResult]:
        if self._joystick is None or self._joystick.get_numhats() <= 0:
            return []
        x_hat, y_hat = self._joystick.get_hat(0)
        states = {
            "DPad Up": y_hat > 0,
            "DPad Down": y_hat < 0,
            "DPad Left": x_hat < 0,
            "DPad Right": x_hat > 0,
        }
        results = []
        for dpad_name, pressed in states.items():
            previous = self._hat_states.get(dpad_name, False)
            self._hat_states[dpad_name] = pressed
            results.extend(self._process_mapping_state(dpad_name, self.button_mappings.get(dpad_name, ""), pressed, previous))
        return results

    def _update_sticks(self) -> list[ControllerMappingResult]:
        if self._joystick is None:
            return []
        results = []
        for stick_name, (x_axis_index, y_axis_index) in self.STICK_AXES.items():
            if self._joystick.get_numaxes() <= max(x_axis_index, y_axis_index):
                continue
            settings = self.stick_settings.get(stick_name, {})
            mode = str(settings.get("mode", "disabled")).lower()
            if mode not in self.MODES or mode == "disabled":
                continue
            x_axis = self._joystick.get_axis(x_axis_index)
            y_axis = self._joystick.get_axis(y_axis_index)
            if mode == "mouse":
                result = self.move_mouse(x_axis, y_axis, stick_name=stick_name)
                if result is not None:
                    results.append(result)
            else:
                results.extend(self._map_stick_directions(stick_name, x_axis, y_axis, settings))
        return results

    def _map_stick_directions(self, stick_name: str, x_axis: float, y_axis: float, settings: dict[str, Any]) -> list[ControllerMappingResult]:
        states = {
            "left": x_axis < -self.deadzone,
            "right": x_axis > self.deadzone,
            "up": y_axis < -self.deadzone,
            "down": y_axis > self.deadzone,
        }
        results = []
        for direction, active in states.items():
            state_key = f"{stick_name}:{direction}"
            previous = self._stick_direction_states.get(state_key, False)
            self._stick_direction_states[state_key] = active
            source = f"{self.STICK_LABELS.get(stick_name, stick_name)} {direction.title()}"
            results.extend(self._process_mapping_state(source, settings.get(direction, ""), active, previous, state_key=state_key))
        return results

    def _process_mapping_state(
        self,
        source: str,
        mapping: Any,
        pressed: bool,
        previous: bool,
        *,
        state_key: str | None = None,
    ) -> list[ControllerMappingResult]:
        config = self._normalize_mapping_config(mapping)
        command = str(config["key"])
        mode = str(config["mode"])
        repeat_rate = int(config["repeat_rate"])
        key = state_key or source
        results: list[ControllerMappingResult] = []

        if not command or command == "disabled":
            return results

        if mode == "hold":
            if self._is_mouse_movement(command):
                if pressed:
                    result = self._execute_mapping(source, command)
                    if result is not None:
                        results.append(result)
                return results
            if pressed and not previous:
                result = self._press_mapping(source, command)
                if result is not None:
                    self._held_outputs[key] = command
                    results.append(result)
            elif not pressed and previous:
                command_to_release = self._held_outputs.pop(key, command)
                result = self._release_mapping(source, command_to_release)
                if result is not None:
                    results.append(result)
            return results

        if mode == "turbo":
            if not pressed:
                if previous:
                    self._turbo_last_sent_at.pop(key, None)
                return results
            now = monotonic()
            interval = 1.0 / max(self.MIN_REPEAT_RATE, repeat_rate)
            last_sent = self._turbo_last_sent_at.get(key)
            if last_sent is None or now - last_sent >= interval:
                self._turbo_last_sent_at[key] = now
                result = self._execute_mapping(source, command)
                if result is not None:
                    results.append(result)
            return results

        if pressed and not previous:
            result = self._execute_mapping(source, command)
            if result is not None:
                results.append(result)
        return results

    def _execute_mapping(self, source: str, command: str) -> ControllerMappingResult | None:
        command = str(command).strip().lower()
        if not command or command == "disabled":
            return None
        if command.startswith("mouse:"):
            return self._execute_mouse_action(source, command)
        return self._execute_key_action(source, command)

    def _press_mapping(self, source: str, command: str) -> ControllerMappingResult | None:
        command = str(command).strip().lower()
        if not command or command == "disabled":
            return None
        if command.startswith("mouse:"):
            return self._press_mouse_action(source, command)
        return self._press_key_action(source, command)

    def _release_mapping(self, source: str, command: str) -> ControllerMappingResult | None:
        command = str(command).strip().lower()
        if not command or command == "disabled":
            return None
        if command.startswith("mouse:"):
            return self._release_mouse_action(source, command)
        return self._release_key_action(source, command)

    def _execute_key_action(self, source: str, command: str) -> ControllerMappingResult:
        if self.simulate_inputs:
            return ControllerMappingResult(source, command, False, f"Simulated controller command: {source} -> {command.upper()}")
        if self._keyboard is None:
            return ControllerMappingResult(source, command, False, "pynput unavailable; controller command logged only")
        key = self._key_lookup.get(command, command)
        try:
            self._keyboard.press(key)
            self._keyboard.release(key)
        except Exception as exc:
            self.logger.exception("Failed to send controller command for %s: %s", source, exc)
            return ControllerMappingResult(source, command, False, f"Failed controller command: {source} -> {command.upper()}")
        return ControllerMappingResult(source, command, True, f"Sent controller command: {source} -> {command.upper()}")

    def _press_key_action(self, source: str, command: str) -> ControllerMappingResult:
        if self.simulate_inputs:
            return ControllerMappingResult(source, command, False, f"Simulated hold start: {source} -> {command.upper()}")
        if self._keyboard is None:
            return ControllerMappingResult(source, command, False, "pynput unavailable; controller command logged only")
        try:
            self._keyboard.press(self._key_lookup.get(command, command))
        except Exception as exc:
            self.logger.exception("Failed to hold controller command for %s: %s", source, exc)
            return ControllerMappingResult(source, command, False, f"Failed hold start: {source} -> {command.upper()}")
        return ControllerMappingResult(source, command, True, f"Held controller command: {source} -> {command.upper()}")

    def _release_key_action(self, source: str, command: str) -> ControllerMappingResult:
        if self.simulate_inputs:
            return ControllerMappingResult(source, command, False, f"Simulated hold release: {source} -> {command.upper()}")
        if self._keyboard is None:
            return ControllerMappingResult(source, command, False, "pynput unavailable; controller command logged only")
        try:
            self._keyboard.release(self._key_lookup.get(command, command))
        except Exception as exc:
            self.logger.exception("Failed to release controller command for %s: %s", source, exc)
            return ControllerMappingResult(source, command, False, f"Failed hold release: {source} -> {command.upper()}")
        return ControllerMappingResult(source, command, True, f"Released controller command: {source} -> {command.upper()}")

    def _execute_mouse_action(self, source: str, command: str) -> ControllerMappingResult:
        action = command.removeprefix("mouse:")
        if action in {"left", "right", "up", "down"}:
            return self._execute_digital_mouse_move(source, action)
        if action in {"left_click", "right_click", "middle_click"}:
            return self._execute_mouse_click(source, action)
        return ControllerMappingResult(source, command, False, f"Unsupported mouse action: {action}")

    def _execute_mouse_click(self, source: str, action: str) -> ControllerMappingResult:
        button_name = action.removesuffix("_click")
        if self.simulate_inputs:
            return ControllerMappingResult(source, f"mouse:{action}", False, f"Simulated mouse {button_name} click")
        if self._mouse is None:
            return ControllerMappingResult(source, f"mouse:{action}", False, "pynput unavailable; mouse click logged only")
        try:
            self._mouse.click(self._mouse_button_lookup[button_name])
        except Exception as exc:
            self.logger.exception("Failed to send mouse click from controller: %s", exc)
            return ControllerMappingResult(source, f"mouse:{action}", False, f"Failed mouse {button_name} click")
        return ControllerMappingResult(source, f"mouse:{action}", True, f"Sent mouse {button_name} click")

    def _press_mouse_action(self, source: str, command: str) -> ControllerMappingResult:
        action = command.removeprefix("mouse:")
        if action in {"left", "right", "up", "down"}:
            return self._execute_digital_mouse_move(source, action)
        if action not in {"left_click", "right_click", "middle_click"}:
            return ControllerMappingResult(source, command, False, f"Unsupported mouse action: {action}")
        button_name = action.removesuffix("_click")
        if self.simulate_inputs:
            return ControllerMappingResult(source, command, False, f"Simulated mouse {button_name} hold start")
        if self._mouse is None:
            return ControllerMappingResult(source, command, False, "pynput unavailable; mouse click logged only")
        try:
            self._mouse.press(self._mouse_button_lookup[button_name])
        except Exception as exc:
            self.logger.exception("Failed to hold mouse button from controller: %s", exc)
            return ControllerMappingResult(source, command, False, f"Failed mouse {button_name} hold start")
        return ControllerMappingResult(source, command, True, f"Held mouse {button_name} button")

    def _release_mouse_action(self, source: str, command: str) -> ControllerMappingResult:
        action = command.removeprefix("mouse:")
        if action in {"left", "right", "up", "down"}:
            return ControllerMappingResult(source, command, True, f"Stopped mouse {action}")
        if action not in {"left_click", "right_click", "middle_click"}:
            return ControllerMappingResult(source, command, False, f"Unsupported mouse action: {action}")
        button_name = action.removesuffix("_click")
        if self.simulate_inputs:
            return ControllerMappingResult(source, command, False, f"Simulated mouse {button_name} hold release")
        if self._mouse is None:
            return ControllerMappingResult(source, command, False, "pynput unavailable; mouse click logged only")
        try:
            self._mouse.release(self._mouse_button_lookup[button_name])
        except Exception as exc:
            self.logger.exception("Failed to release mouse button from controller: %s", exc)
            return ControllerMappingResult(source, command, False, f"Failed mouse {button_name} hold release")
        return ControllerMappingResult(source, command, True, f"Released mouse {button_name} button")

    def _execute_digital_mouse_move(self, source: str, action: str) -> ControllerMappingResult:
        deltas = {
            "left": (-self.digital_mouse_step, 0),
            "right": (self.digital_mouse_step, 0),
            "up": (0, -self.digital_mouse_step),
            "down": (0, self.digital_mouse_step),
        }
        dx, dy = deltas[action]
        if self.simulate_inputs:
            return ControllerMappingResult(source, f"mouse:{action}", False, f"Simulated mouse {action}")
        if self._mouse is None:
            return ControllerMappingResult(source, f"mouse:{action}", False, "pynput unavailable; mouse movement logged only")
        try:
            self._mouse.move(int(dx), int(dy))
        except Exception as exc:
            self.logger.exception("Failed to move mouse from digital controller input: %s", exc)
            return ControllerMappingResult(source, f"mouse:{action}", False, f"Failed mouse {action}")
        return ControllerMappingResult(source, f"mouse:{action}", True, f"Sent mouse {action}")

    def _apply_axis_options(self, x_axis: float, y_axis: float) -> tuple[float, float]:
        if bool(self.mouse_settings.get("invert_x", False)):
            x_axis *= -1
        if bool(self.mouse_settings.get("invert_y", False)):
            y_axis *= -1
        return x_axis, y_axis

    def _smooth_delta(self, stick_name: str, dx: float, dy: float) -> tuple[float, float]:
        smoothing = self.smoothing
        previous_x, previous_y = self._smoothed_delta.get(stick_name, (0.0, 0.0))
        smoothed_x = (previous_x * smoothing) + (dx * (1.0 - smoothing))
        smoothed_y = (previous_y * smoothing) + (dy * (1.0 - smoothing))
        self._smoothed_delta[stick_name] = (smoothed_x, smoothed_y)
        return smoothed_x, smoothed_y

    def _merge_stick_settings(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        settings = deepcopy(DEFAULT_CONTROLLER_STICK_SETTINGS)
        if isinstance(overrides, dict):
            for stick_name, stick_overrides in overrides.items():
                if stick_name in settings and isinstance(stick_overrides, dict):
                    settings[stick_name].update(stick_overrides)
        for stick in settings.values():
            mode = str(stick.get("mode", "disabled")).lower()
            stick["mode"] = mode if mode in self.MODES else "disabled"
            for direction in self.DIRECTIONS:
                stick[direction] = self._normalize_mapping_config(stick.get(direction, ""))
        return settings

    def _normalize_button_mappings(self, mappings: dict[str, Any] | None, *, include_defaults: bool = True) -> dict[str, dict[str, Any]]:
        merged = deepcopy(DEFAULT_CONTROLLER_BUTTON_MAPPINGS) if include_defaults else {}
        if isinstance(mappings, dict):
            merged.update(mappings)
        return {str(button): self._normalize_mapping_config(mapping) for button, mapping in merged.items()}

    def _normalize_mapping_config(self, mapping: Any) -> dict[str, Any]:
        if isinstance(mapping, dict):
            command = str(mapping.get("key", mapping.get("action", mapping.get("command", "")))).strip().lower()
            default_mode = "hold" if self._is_mouse_movement(command) else "tap"
            mode = str(mapping.get("mode", default_mode)).strip().lower()
            repeat_rate = mapping.get("repeat_rate", self.DEFAULT_REPEAT_RATE)
        else:
            command = str(mapping).strip().lower()
            default_mode = "hold" if self._is_mouse_movement(command) else "tap"
            mode = default_mode
            repeat_rate = self.DEFAULT_REPEAT_RATE
        if mode not in self.ACTIVATION_MODES:
            mode = default_mode
        return {
            "key": command,
            "mode": mode,
            "repeat_rate": self._coerce_repeat_rate(repeat_rate),
        }

    def _coerce_repeat_rate(self, value: Any) -> int:
        try:
            rate = int(round(float(value)))
        except (TypeError, ValueError):
            rate = self.DEFAULT_REPEAT_RATE
        return max(self.MIN_REPEAT_RATE, min(self.MAX_REPEAT_RATE, rate))

    def _is_mouse_movement(self, command: str) -> bool:
        return str(command).strip().lower() in {"mouse:up", "mouse:down", "mouse:left", "mouse:right"}

    def _release_all_held_outputs(self) -> None:
        for source, command in list(self._held_outputs.items()):
            self._release_mapping(source, command)
        self._held_outputs.clear()

    def _merge_mouse_settings(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        settings = deepcopy(DEFAULT_CONTROLLER_MOUSE_SETTINGS)
        if isinstance(overrides, dict):
            settings.update(overrides)
        return settings

    def _dpad_names(self) -> dict[str, str]:
        return {
            "up": "DPad Up",
            "down": "DPad Down",
            "left": "DPad Left",
            "right": "DPad Right",
        }

    def _load_backends(self) -> None:
        if find_spec("pygame") is not None:
            try:
                import pygame

                pygame.init()
                pygame.joystick.init()
                self._pygame = pygame
            except Exception as exc:
                self.logger.warning("pygame controller backend unavailable: %s", exc)

        if find_spec("pynput") is None:
            return

        try:
            from pynput.keyboard import Controller as KeyboardController
            from pynput.keyboard import Key
            from pynput.mouse import Button, Controller as MouseController
        except Exception as exc:
            self.logger.warning("pynput controller backend unavailable: %s", exc)
            return

        self._keyboard = KeyboardController()
        self._mouse = MouseController()
        self._key_lookup = {
            "space": Key.space,
            "enter": Key.enter,
            "escape": Key.esc,
            "esc": Key.esc,
            "tab": Key.tab,
            "shift": Key.shift,
            "ctrl": Key.ctrl,
            "control": Key.ctrl,
            "alt": Key.alt,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
        }
        self._mouse_button_lookup = {
            "left": Button.left,
            "right": Button.right,
            "middle": Button.middle,
        }

