from __future__ import annotations

import logging
import math
import random
import threading
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any, Callable


try:
    import numpy as np
except Exception:  # pragma: no cover - optional runtime dependency guard
    np = None


@dataclass(frozen=True)
class AudioEvent:
    """Directional audio event emitted by the live detector."""

    event_type: str
    label: str
    direction: str
    left_intensity: float
    right_intensity: float
    center_intensity: float
    timestamp: float


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    sample_rate: int
    channels: int


class DirectionAnalyzer:
    """Analyzes stereo intensity and resolves a directional accessibility event."""

    def __init__(self, sensitivity: float = 0.18, minimum_volume: float = 0.02) -> None:
        self.sensitivity = sensitivity
        self.minimum_volume = minimum_volume
        self.selected_pair: tuple[int, int] = (0, 1)

    def configure(self, sensitivity: float, minimum_volume: float) -> None:
        self.sensitivity = max(0.01, min(1.0, float(sensitivity)))
        self.minimum_volume = max(0.0, min(1.0, float(minimum_volume)))

    def analyze(self, samples: Any) -> AudioEvent | None:
        left, right = self._channel_intensity(samples)
        center = (left + right) / 2.0
        if max(left, right, center) < self.minimum_volume:
            return None

        difference = abs(left - right)
        comparison_floor = max(center, self.minimum_volume)
        direction_threshold = comparison_floor * (1.0 - self.sensitivity) * 0.8
        if difference <= direction_threshold:
            direction = "center"
            event_type = "nearby_action"
            label = "Center audio event"
        elif left > right:
            direction = "left"
            event_type = "left_danger"
            label = "Left audio event"
        else:
            direction = "right"
            event_type = "right_danger"
            label = "Right audio event"

        return AudioEvent(
            event_type=event_type,
            label=label,
            direction=direction,
            left_intensity=left,
            right_intensity=right,
            center_intensity=center,
            timestamp=monotonic(),
        )

    def _channel_intensity(self, samples: Any) -> tuple[float, float]:
        if np is not None:
            data = np.asarray(samples, dtype="float32")
            if data.size == 0:
                return 0.0, 0.0
            if data.ndim == 1:
                rms = float(np.sqrt(np.mean(np.square(data))))
                return rms, rms
            if data.shape[1] == 1:
                mono = data[:, 0]
                rms = float(np.sqrt(np.mean(np.square(mono))))
                return rms, rms
            intensities = np.sqrt(np.mean(np.square(data), axis=0))
            if data.shape[1] == 2:
                return float(intensities[0]), float(intensities[1])
            left_index, right_index = self._best_stereo_pair(intensities)
            self.selected_pair = (left_index, right_index)
            return float(intensities[left_index]), float(intensities[right_index])

        left_values: list[float] = []
        right_values: list[float] = []
        for frame in samples:
            if isinstance(frame, (list, tuple)) and len(frame) >= 2:
                left_values.append(float(frame[0]))
                right_values.append(float(frame[1]))
            else:
                value = float(frame)
                left_values.append(value)
                right_values.append(value)
        return self._rms(left_values), self._rms(right_values)

    def _best_stereo_pair(self, intensities: Any) -> tuple[int, int]:
        if np is None:
            return 0, 1

        channel_count = len(intensities)
        if channel_count < 2:
            return 0, 0

        preferred_pairs = [(0, 1), (2, 3), (4, 5), (6, 7)]
        best_pair = (0, 1)
        best_score = -1.0

        for left_index, right_index in preferred_pairs:
            if right_index >= channel_count:
                continue
            left = float(intensities[left_index])
            right = float(intensities[right_index])
            volume = max(left, right)
            if volume < self.minimum_volume:
                score = 0.0
            else:
                score = abs(left - right) + (volume * 0.05)
            if score > best_score:
                best_score = score
                best_pair = (left_index, right_index)

        if best_score <= 0.0:
            top = sorted(range(channel_count), key=lambda index: float(intensities[index]), reverse=True)[:2]
            if len(top) == 2:
                return min(top), max(top)

        return best_pair

    def _rms(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return math.sqrt(sum(value * value for value in values) / len(values))


class AudioDetector:
    """Captures Windows output audio through WASAPI loopback and emits direction events."""

    def __init__(
        self,
        callback: Callable[[AudioEvent], None],
        settings: dict[str, Any] | None = None,
        *,
        simulate_inputs: bool = False,
    ) -> None:
        self.callback = callback
        self.logger = logging.getLogger(__name__)
        self.settings = self._normalize_settings(settings or {})
        self.simulate_inputs = simulate_inputs
        self.analyzer = DirectionAnalyzer(
            sensitivity=float(self.settings["sensitivity"]),
            minimum_volume=float(self.settings["minimum_volume"]),
        )
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._settings_lock = threading.Lock()
        self._last_emit_at = 0.0
        self._last_direction = ""

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def configure(self, settings: dict[str, Any] | None = None, *, simulate_inputs: bool | None = None) -> None:
        with self._settings_lock:
            if settings:
                self.settings.update(self._normalize_settings(settings))
            if simulate_inputs is not None:
                self.simulate_inputs = bool(simulate_inputs)
            self.analyzer.configure(
                sensitivity=float(self.settings["sensitivity"]),
                minimum_volume=float(self.settings["minimum_volume"]),
            )

    def start(self) -> None:
        if self.running:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="AudioDetector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.2)
        self._thread = None
        self._last_emit_at = 0.0
        self._last_direction = ""

    def _run(self) -> None:
        if self.simulate_inputs:
            self._run_simulation()
            return

        try:
            self._run_wasapi_loopback()
        except Exception as exc:
            self.logger.exception("Live audio detector failed: %s", exc)
            if self.simulate_inputs and self.running:
                self._run_simulation()

    def _run_wasapi_loopback(self) -> None:
        if self._run_pyaudiowpatch_loopback():
            return

        self.logger.info("Default WASAPI loopback capture was unavailable; trying sounddevice fallback")
        try:
            import sounddevice as sd
        except Exception as exc:
            self.logger.warning("sounddevice is unavailable for audio loopback: %s", exc)
            return

        device = self._find_loopback_device(sd)
        if device is None:
            self.logger.warning("No WASAPI loopback audio device detected")
            return

        channels = max(1, min(2, device.channels))
        self.logger.info("Starting sounddevice WASAPI loopback audio capture from %s", device.name)
        while self.running:
            with self._settings_lock:
                interval = float(self.settings["detection_interval"])
            blocksize = max(128, int(device.sample_rate * interval))

            try:
                with sd.InputStream(
                    device=device.index,
                    channels=channels,
                    samplerate=device.sample_rate,
                    blocksize=blocksize,
                    dtype="float32",
                ) as stream:
                    while self.running:
                        samples, overflowed = stream.read(blocksize)
                        if overflowed:
                            self.logger.debug("Audio detector stream overflowed")
                        event = self.analyzer.analyze(samples)
                        if event is not None:
                            self._log_selected_audio_pair(channels, event)
                            self._emit_if_due(event)
            except Exception as exc:
                self.logger.warning("Audio stream interrupted: %s", exc)
                sleep(0.5)

    def _run_pyaudiowpatch_loopback(self) -> bool:
        if np is None:
            self.logger.warning("numpy is required for pyaudiowpatch loopback capture")
            return False
        try:
            import pyaudiowpatch as pyaudio
        except Exception as exc:
            self.logger.warning("pyaudiowpatch is unavailable for WASAPI loopback: %s", exc)
            return False

        audio = pyaudio.PyAudio()
        stream = None
        try:
            device = self._find_pyaudiowpatch_loopback_device(audio, pyaudio)
            if device is None:
                self.logger.warning("No pyaudiowpatch WASAPI loopback device detected")
                return False

            sample_rate = int(float(device.get("defaultSampleRate", 44100)))
            channels = self._resolve_pyaudiowpatch_channels(audio, pyaudio, device, sample_rate)
            self.logger.info(
                "Starting default Windows loopback audio capture from %s with %s channel(s)",
                device.get("name", "loopback"),
                channels,
            )
            while self.running:
                with self._settings_lock:
                    interval = float(self.settings["detection_interval"])
                blocksize = max(128, int(sample_rate * interval))
                stream = audio.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    frames_per_buffer=blocksize,
                    input=True,
                    input_device_index=int(device["index"]),
                )
                try:
                    while self.running:
                        raw = stream.read(blocksize, exception_on_overflow=False)
                        data = np.frombuffer(raw, dtype=np.float32)
                        if data.size == 0:
                            continue
                        usable = (data.size // channels) * channels
                        samples = data[:usable].reshape(-1, channels)
                        event = self.analyzer.analyze(samples)
                        if event is not None:
                            self._log_selected_audio_pair(channels, event)
                            self._emit_if_due(event)
                finally:
                    stream.stop_stream()
                    stream.close()
                    stream = None
            return True
        except Exception as exc:
            self.logger.exception("pyaudiowpatch loopback capture failed: %s", exc)
            return False
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            audio.terminate()

    def _resolve_pyaudiowpatch_channels(self, audio: Any, pyaudio: Any, device: dict[str, Any], sample_rate: int) -> int:
        reported = int(device.get("maxInputChannels") or device.get("maxOutputChannels") or 2)
        candidates = []
        for value in (reported, 2, 1, 8, 6, 4):
            if value > 0 and value not in candidates:
                candidates.append(value)

        for channels in candidates:
            try:
                probe = audio.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    frames_per_buffer=256,
                    input=True,
                    input_device_index=int(device["index"]),
                )
                probe.close()
                return channels
            except Exception as exc:
                self.logger.debug(
                    "Loopback channel probe failed for %s channel(s) on %s: %s",
                    channels,
                    device.get("name", "loopback"),
                    exc,
                )
        raise RuntimeError(f"No valid channel count found for loopback device {device.get('name', 'loopback')}")

    def _find_pyaudiowpatch_loopback_device(self, audio: Any, pyaudio: Any) -> dict[str, Any] | None:
        try:
            wasapi_info = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_output = audio.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            default_name = str(default_output.get("name", "Unknown"))
            self.logger.info("Windows default audio output: %s", default_name)

            if default_output.get("isLoopbackDevice"):
                self.logger.info("Using default loopback audio device: %s", default_name)
                return default_output

            for loopback in audio.get_loopback_device_info_generator():
                loopback_name = str(loopback.get("name", ""))
                if default_name and default_name in loopback_name:
                    self.logger.info("Using loopback device for default output: %s", loopback_name)
                    return loopback

            fallback = next(audio.get_loopback_device_info_generator(), None)
            if fallback is not None:
                self.logger.warning(
                    "Could not find an exact loopback match for default output %s; using %s",
                    default_name,
                    fallback.get("name", "loopback"),
                )
            return fallback
        except Exception as exc:
            self.logger.warning("Could not resolve pyaudiowpatch loopback device: %s", exc)
            return None

    def _find_loopback_device(self, sd: Any) -> AudioDevice | None:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        candidates: list[AudioDevice] = []
        fallback_candidates: list[AudioDevice] = []

        for index, device in enumerate(devices):
            hostapi_name = str(hostapis[int(device["hostapi"])]["name"]).lower()
            device_name = str(device["name"])
            lower_name = device_name.lower()
            channels = int(device.get("max_input_channels", 0))
            if channels <= 0:
                continue
            sample_rate = int(float(device.get("default_samplerate", 44100)))
            audio_device = AudioDevice(index=index, name=device_name, sample_rate=sample_rate, channels=channels)
            if "wasapi" in hostapi_name and "loopback" in lower_name:
                candidates.append(audio_device)
            elif "wasapi" in hostapi_name and any(token in lower_name for token in ("stereo mix", "speakers", "output")):
                fallback_candidates.append(audio_device)

        return (candidates or fallback_candidates or [None])[0]

    def _run_simulation(self) -> None:
        sequence = [
            ("left", "left_danger", "Simulated left audio event", 0.8, 0.25),
            ("right", "right_danger", "Simulated right audio event", 0.25, 0.8),
            ("center", "nearby_action", "Simulated center audio event", 0.55, 0.52),
        ]
        index = 0
        while self.running:
            with self._settings_lock:
                interval = max(0.25, float(self.settings["detection_interval"]))
                minimum = float(self.settings["minimum_volume"])
            direction, event_type, label, left, right = sequence[index % len(sequence)]
            index += 1
            jitter = random.uniform(-0.03, 0.03)
            event = AudioEvent(
                event_type=event_type,
                label=label,
                direction=direction,
                left_intensity=max(minimum, left + jitter),
                right_intensity=max(minimum, right - jitter),
                center_intensity=(left + right) / 2.0,
                timestamp=monotonic(),
            )
            self._emit_if_due(event, force=True)
            sleep(max(interval, 0.5))

    def _log_selected_audio_pair(self, channels: int, event: AudioEvent) -> None:
        if channels <= 2:
            return
        now = monotonic()
        if now - self._last_pair_log_at < 3.0:
            return
        self._last_pair_log_at = now
        self.logger.info(
            "Audio direction sample: pair=%s direction=%s left=%.4f right=%.4f",
            self.analyzer.selected_pair,
            event.direction,
            event.left_intensity,
            event.right_intensity,
        )

    def _emit_if_due(self, event: AudioEvent, *, force: bool = False) -> None:
        with self._settings_lock:
            interval = max(0.1, float(self.settings["detection_interval"]))
        now = monotonic()
        if not force and event.direction == self._last_direction and now - self._last_emit_at < interval:
            return
        self._last_emit_at = now
        self._last_direction = event.direction
        try:
            self.callback(event)
        except Exception as exc:
            self.logger.exception("Failed to dispatch audio event: %s", exc)

    def _normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "sensitivity": self._coerce_float(settings.get("sensitivity", 0.18), 0.01, 1.0),
            "minimum_volume": self._coerce_float(settings.get("minimum_volume", 0.02), 0.0, 1.0),
            "detection_interval": self._coerce_float(settings.get("detection_interval", 0.15), 0.05, 2.0),
        }

    def _coerce_float(self, value: Any, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = minimum
        return max(minimum, min(maximum, number))
