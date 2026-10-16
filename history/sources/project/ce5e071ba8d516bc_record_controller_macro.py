import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import queue
import threading
import time

from macro_runtime import BASE, launch_game, save_screenshot


OUTPUT_DIR = BASE / "generated_macros"
PLAYER = BASE / "tools" / "play_controller_macro.py"


def safe_macro_name(value):
    value = value.strip()
    characters = [char if char.isalnum() or char in "-_ " else "_" for char in value]
    name = re.sub(r"\s+", "_", "".join(characters)).strip("_.-")
    return name or "controller_macro"


def unique_stem(name):
    stem = safe_macro_name(name)
    candidate = stem
    suffix = 2
    while (OUTPUT_DIR / f"{candidate}.bat").exists() or (OUTPUT_DIR / f"{candidate}.json").exists():
        candidate = f"{stem}_{suffix}"
        suffix += 1
    return candidate


def make_player_bat(stem):
    return f"""@echo off
setlocal
chcp 65001 >nul

if \"%~1\"==\"\" (
    echo Drag an ISO, CSO, or CHD file onto this BAT file.
    pause
    exit /b 1
)

if not exist \"%~f1\" (
    echo File not found: %~f1
    pause
    exit /b 1
)

set \"PLAYER={PLAYER}\"
set \"MACRO=%~dpn0.json\"
if not exist \"%MACRO%\" (
    echo Macro data not found: %MACRO%
    pause
    exit /b 1
)

python \"%PLAYER%\" \"%~f1\" \"%MACRO%\"
set \"RESULT=%ERRORLEVEL%\"
echo.
if not \"%RESULT%\"==\"0\" echo Macro playback failed. Error code: %RESULT%
if not \"%RESULT%\"==\"0\" pause
exit /b %RESULT%
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("iso", type=Path)
    parser.add_argument("macro_name")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    process, ws, connection, iso = launch_game(args.iso)
    events = []
    pressed_buttons = set()
    analog_positions = {}
    started = time.monotonic()
    stop_requested = threading.Event()
    commands = queue.Queue()
    screenshot_dir = BASE / "macro_screenshots" / (
        "record_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    screenshot_count = 0

    def wait_for_enter():
        try:
            while True:
                command = input().strip().lower()
                if not command:
                    break
                if command == "s":
                    commands.put(time.monotonic())
                else:
                    print("Type s + Enter to capture, or Enter alone to finish.")
        except EOFError:
            pass
        stop_requested.set()

    try:
        print(f"RECORDER READY. PPSSPP PID {process.pid}; 2x speed active.")
        print("Use the controller in-game. Type s + Enter to capture; Enter alone finishes recording.")
        threading.Thread(target=wait_for_enter, daemon=True).start()

        while not stop_requested.is_set() or not commands.empty():
            try:
                capture_time = commands.get_nowait()
            except queue.Empty:
                capture_time = None
            if capture_time is not None:
                screenshot_count += 1
                capture_ms = round((capture_time - started) * 1000)
                capture_started = time.monotonic()
                save_screenshot(connection, screenshot_dir, screenshot_count)
                started += time.monotonic() - capture_started
                events.append({"t_ms": capture_ms, "type": "screenshot"})
                continue
            event = connection.receive(timeout=0.25)
            if not event:
                continue
            now_ms = round((time.monotonic() - started) * 1000)
            if event.get("event") == "input.buttons":
                changed = event.get("changed") or {}
                if not changed:
                    continue
                for button, down in changed.items():
                    if down:
                        pressed_buttons.add(button)
                    else:
                        pressed_buttons.discard(button)
                events.append({"t_ms": now_ms, "type": "buttons", "buttons": changed})
            elif event.get("event") == "input.analog":
                stick = event.get("stick")
                x = float(event.get("x", 0.0))
                y = float(event.get("y", 0.0))
                analog_positions[stick] = (x, y)
                events.append({"t_ms": now_ms, "type": "analog", "stick": stick, "x": x, "y": y})
    except KeyboardInterrupt:
        stop_requested.set()
    finally:
        now_ms = round((time.monotonic() - started) * 1000)
        if pressed_buttons:
            events.append(
                {
                    "t_ms": now_ms,
                    "type": "buttons",
                    "buttons": {button: False for button in sorted(pressed_buttons)},
                }
            )
        for stick, (x, y) in analog_positions.items():
            if x != 0.0 or y != 0.0:
                events.append({"t_ms": now_ms, "type": "analog", "stick": stick, "x": 0.0, "y": 0.0})
        ws.close()

    if not events:
        raise SystemExit("No controller inputs were received; no macro files were created.")

    stem = unique_stem(args.macro_name)
    events.sort(key=lambda event: event["t_ms"])
    macro_path = OUTPUT_DIR / f"{stem}.json"
    batch_path = OUTPUT_DIR / f"{stem}.bat"
    macro = {
        "format": "ppsspp-controller-macro",
        "version": 1,
        "timing_origin": "recorder_ready_after_reset",
        "recorded_iso": str(iso),
        "speed_percent": 200,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event_count": len(events),
        "events": events,
    }
    macro_path.write_text(json.dumps(macro, ensure_ascii=False, indent=2), encoding="utf-8")
    with batch_path.open("w", encoding="ascii", newline="\r\n") as output:
        output.write(make_player_bat(stem))
    print(f"Recorded {len(events)} controller changes.")
    print(f"Playback BAT: {batch_path}")
    print(f"Macro data: {macro_path}")
    print("Close the recording PPSSPP window before running the generated BAT.")


if __name__ == "__main__":
    main()
