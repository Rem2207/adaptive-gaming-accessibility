from __future__ import annotations

import ctypes
import json
import queue
import sys
import threading
import tkinter as tk
from time import monotonic
from typing import Any


TRANSPARENT_COLOR = "#010203"


class OverlayWindow:
    """Tk overlay window that runs in its own Python process."""

    def __init__(self) -> None:
        self.settings = self._normalize_settings({})
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()
        self.root = tk.Tk()
        self.canvas: tk.Canvas | None = None
        self.items: dict[str, tuple[int, int]] = {}
        self.active_direction = ""
        self.active_since = 0.0

    def run(self) -> None:
        self._build_window()
        threading.Thread(target=self._read_stdin, daemon=True).start()
        self.root.after(33, self._poll)
        self.root.mainloop()

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                self.commands.put(payload)

    def _build_window(self) -> None:
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except tk.TclError:
            pass
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")
        self.canvas = tk.Canvas(self.root, width=width, height=height, highlightthickness=0, bg=TRANSPARENT_COLOR)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._build_indicators(width, height)
        self.root.update_idletasks()
        self._make_click_through()

    def _build_indicators(self, width: int, height: int) -> None:
        if self.canvas is None:
            return
        self.canvas.delete("all")
        self.items.clear()
        size = int(self.settings["size"])
        y = max(60, int(height * 0.12))
        positions = {
            "left": (60, y),
            "center": ((width - size) // 2, y),
            "right": (width - size - 60, y),
        }
        colors = {"left": "#DC2626", "center": "#F59E0B", "right": "#DC2626"}
        labels = self.settings["labels"]
        for direction, (x, top) in positions.items():
            height_px = max(70, size // 2)
            rect = self.canvas.create_rectangle(x, top, x + size, top + height_px, fill=colors[direction], outline="", state=tk.HIDDEN)
            text = self.canvas.create_text(
                x + size // 2,
                top + height_px // 2,
                text=labels.get(direction, direction.upper()),
                fill="#FFFFFF",
                font=("Segoe UI", max(13, size // 12), "bold"),
                state=tk.HIDDEN,
                width=max(90, size - 20),
            )
            self.items[direction] = (rect, text)

    def _poll(self) -> None:
        try:
            while True:
                command = self.commands.get_nowait()
                kind = command.get("type")
                if kind == "stop":
                    self.root.destroy()
                    return
                if kind == "configure":
                    settings = command.get("settings")
                    if isinstance(settings, dict):
                        self.settings.update(self._normalize_settings(settings))
                        width = self.root.winfo_screenwidth()
                        height = self.root.winfo_screenheight()
                        self._build_indicators(width, height)
                elif kind == "event":
                    self._activate(str(command.get("direction", "center")))
        except queue.Empty:
            pass
        self._animate()
        self.root.after(33, self._poll)

    def _activate(self, direction: str) -> None:
        direction = direction if direction in {"left", "right", "center"} else "center"
        self.active_direction = direction
        self.active_since = monotonic()
        self.root.deiconify()
        self.root.lift()
        self._set_visible(direction)

    def _animate(self) -> None:
        if not self.active_direction:
            return
        elapsed = monotonic() - self.active_since
        duration = float(self.settings["duration"])
        max_opacity = float(self.settings["opacity"])
        fade_in = 0.18
        fade_out = 0.45
        if elapsed < fade_in:
            alpha = max_opacity * (elapsed / fade_in)
        elif elapsed <= duration:
            alpha = max_opacity
        elif elapsed <= duration + fade_out:
            alpha = max_opacity * (1.0 - ((elapsed - duration) / fade_out))
        else:
            self.active_direction = ""
            self._hide_all()
            self.root.withdraw()
            return
        try:
            self.root.attributes("-alpha", max(0.02, min(max_opacity, alpha)))
        except tk.TclError:
            pass

    def _set_visible(self, active_direction: str) -> None:
        if self.canvas is None:
            return
        for direction, items in self.items.items():
            state = tk.NORMAL if direction == active_direction else tk.HIDDEN
            for item in items:
                self.canvas.itemconfigure(item, state=state)

    def _hide_all(self) -> None:
        if self.canvas is None:
            return
        for items in self.items.values():
            for item in items:
                self.canvas.itemconfigure(item, state=tk.HIDDEN)

    def _make_click_through(self) -> None:
        if self.root.tk.call("tk", "windowingsystem") != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            style |= 0x00080000
            style |= 0x00000020
            style |= 0x00000080
            style |= 0x00000008
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
        except Exception:
            pass

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


def main() -> None:
    OverlayWindow().run()


if __name__ == "__main__":
    main()
