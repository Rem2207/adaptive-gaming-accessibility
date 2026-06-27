# Adaptive Gaming Accessibility System

Desktop accessibility middleware for PC gaming, developed as an academic
research prototype for inclusive interaction, adaptive input, and cyberculture
studies.

The application sits between the player and a PC game. It detects available
devices, maps adaptive inputs to keyboard and mouse actions, recognizes webcam
hand gestures, supports controller remapping, and provides visual alerts for
audio events.

## Features

- Device detection for keyboard, mouse, webcam, gamepads, and simulated
  adaptive controllers.
- Webcam gesture recognition with MediaPipe and OpenCV fallback.
- Finger-count gesture mapping for one or two hands.
- Xbox and generic controller mapping with keyboard and mouse simulation.
- Button activation modes: tap, hold, and turbo.
- Analog stick mouse control and configurable digital/custom stick modes.
- Live visual audio alerts with loopback audio detection when available.
- English and Spanish interface.
- Persistent JSON settings and accessibility profiles.
- Modular Python architecture for future adaptive device support.

## Technologies

- Python
- Tkinter / ttk
- OpenCV
- MediaPipe
- Pygame
- pynput
- sounddevice / pyaudiowpatch

## Project Structure

```text
adaptive_accessibility/
  config/
  core/
  models/
  services/
  ui/
  utils/
main.py
requirements.txt
run_app.ps1
setup_venv.ps1
```

## Setup

Python 3.11 is recommended on Windows. Python 3.14 is not currently supported
by every dependency used in this prototype, especially `pygame` and
`mediapipe`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python main.py
```

You can also use the included helper scripts:

```powershell
.\setup_venv.ps1
.\run_app.ps1
```

If PowerShell shows a path such as `C:\Python314\...`, the virtual environment
is not active. Activate `.venv` again before installing dependencies or running
the app.

## Notes

This is a research MVP, not a commercial release. For safe testing, keep input
simulation enabled until you are ready to send real keyboard or mouse commands
to another application.

## Espanol

Sistema de accesibilidad para videojuegos desarrollado como prototipo academico.
La aplicacion funciona como una capa intermedia entre el jugador y el juego,
permitiendo controles adaptativos, reconocimiento gestual, mapeo de controles y
alertas visuales para eventos de audio.

Proyecto academico desarrollado para la carrera de Ingenieria en Informatica de
la Universidad de Palermo.

Author: Ricardo Morales
