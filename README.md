# Adaptive Gaming Accessibility MVP

Experimental desktop prototype for a university research project on cyberculture,
accessibility, and adaptive interaction in video games.

The app acts as a middleware layer between a player and a PC game. It detects
available input devices, recognizes simple webcam gestures, maps gestures to
keyboard commands, and shows simulated visual alerts for deaf or hard-of-hearing
players.

## Features

- Device detection for keyboard, mouse, webcam, gamepad, and simulated adaptive
  controllers.
- Webcam gesture recognition using MediaPipe when available, with an OpenCV
  motion fallback.
- Gesture-to-command mapping:
  - left movement -> `A`
  - right movement -> `D`
  - open hand -> `Space`
  - closed fist -> `Enter`
- Simulated audio accessibility events:
  - left danger indicator
  - right danger indicator
  - nearby action alert
- Tkinter desktop UI with status monitor and live visual cues.
- Modular object-oriented architecture.

## Project Structure

```text
adaptive_accessibility/
  __init__.py
  audio_assist.py
  devices.py
  gestures.py
  input_mapper.py
  ui.py
main.py
requirements.txt
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

If PowerShell shows a path such as `C:\Python314\...`, the virtual environment
is not active. Activate `.venv` again before installing dependencies or running
the app.

You can also use the included helper scripts:

```powershell
.\setup_venv.ps1
.\run_app.ps1
```

`tkinter` is included with most Python distributions. If MediaPipe is not
available on your Python version, the app still runs with the OpenCV fallback,
but hand-shape gestures are more limited.

## Research Prototype Notes

The prototype defaults to simulation-friendly behavior. Real keyboard injection
requires `pynput`; when unavailable, commands are logged in the UI instead. For
safe testing, keep input simulation enabled until you are ready to send commands
to another application.
