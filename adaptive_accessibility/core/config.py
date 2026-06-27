from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from .constants import DEFAULT_SETTINGS, PROFILE_CUSTOM, PROFILE_PRESETS, SETTINGS_FILE


class SettingsManager:
    """Loads and persists user settings for the desktop prototype."""

    def __init__(self, settings_path=SETTINGS_FILE) -> None:
        self.settings_path = settings_path
        self.logger = logging.getLogger(__name__)
        self.settings: dict[str, Any] = self.load()

    def load(self) -> dict[str, Any]:
        defaults = deepcopy(DEFAULT_SETTINGS)
        if not self.settings_path.exists():
            self.save(defaults)
            return defaults

        try:
            with self.settings_path.open("r", encoding="utf-8") as file:
                stored = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.exception("Failed to load settings; using defaults: %s", exc)
            self.save(defaults)
            return defaults

        if not isinstance(stored, dict):
            self.logger.warning("Settings file did not contain a JSON object; using defaults.")
            self.save(defaults)
            return defaults

        return self._merge_defaults(defaults, stored)

    def save(self, settings: dict[str, Any] | None = None) -> None:
        data = deepcopy(settings if settings is not None else self.settings)
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, sort_keys=True)
        except OSError as exc:
            self.logger.exception("Failed to save settings: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any, *, persist: bool = True) -> None:
        self.settings[key] = value
        if persist:
            self.save()

    def update(self, values: dict[str, Any], *, persist: bool = True) -> None:
        self.settings.update(values)
        if persist:
            self.save()

    def apply_profile(self, profile_key: str) -> dict[str, Any]:
        preset = deepcopy(PROFILE_PRESETS.get(profile_key, PROFILE_PRESETS[PROFILE_CUSTOM]))
        if profile_key == PROFILE_CUSTOM:
            self.settings["profile"] = PROFILE_CUSTOM
        else:
            self.settings.update(preset)
        self.save()
        return self.settings

    def _merge_defaults(self, defaults: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(defaults)
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged
