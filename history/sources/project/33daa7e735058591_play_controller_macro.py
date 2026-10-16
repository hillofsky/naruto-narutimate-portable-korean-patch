import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time

from macro_runtime import BASE, launch_game, save_screenshot


def wait_until(deadline):
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("iso", type=Path)
    parser.add_argument("macro", type=Path)
    args = parser.parse_args()

    if not args.macro.is_file():
        raise SystemExit(f"Macro data not found: {args.macro}")
    data = json.loads(args.macro.read_text(encoding="utf-8"))
    if data.get("format") != "ppsspp-controller-macro" or data.get("version") != 1:
        raise SystemExit("Unsupported or invalid macro file")
    if data.get("timing_origin") != "recorder_ready_after_reset":
        raise SystemExit(
            "This old recording lost the wait before the first input. "
            "Record it again with create_controller_macro.bat. Original files are unchanged."
        )
    events = data.get("events")
    if not isinstance(events, list) or not events:
        raise SystemExit("Macro contains no controller events")
    if any("t_ms" not in event or event.get("type") not in ("buttons", "analog", "screenshot") for event in events):
        raise SystemExit("Macro contains an invalid controller event")

    process, ws, connection, iso = launch_game(args.iso)
    held_buttons = set()
    analog_positions = {}
    screenshot_count = 0
    screenshot_dir = BASE / "macro_screenshots" / (
        args.macro.stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    start = time.monotonic()
    try:
        print(f"PPSSPP ready (PID {process.pid}); synchronized reset complete, 2x speed active.")
        print(f"Replaying {len(events)} recorded controller changes for {iso.name}.")
        for event in events:
            wait_until(start + max(0, int(event["t_ms"])) / 1000.0)
            if event["type"] == "screenshot":
                screenshot_count += 1
                capture_started = time.monotonic()
                save_screenshot(connection, screenshot_dir, screenshot_count)
                start += time.monotonic() - capture_started
            elif event["type"] == "buttons":
                buttons = event.get("buttons") or {}
                if not buttons:
                    continue
                connection.send_oneway("input.buttons.send", buttons=buttons)
                for button, down in buttons.items():
                    if down:
                        held_buttons.add(button)
                    else:
                        held_buttons.discard(button)
            else:
                stick = event.get("stick")
                if stick not in ("left", "right"):
                    continue
                x = min(1.0, max(-1.0, float(event.get("x", 0.0))))
                y = min(1.0, max(-1.0, float(event.get("y", 0.0))))
                connection.send_oneway("input.analog.send", stick=stick, x=x, y=y)
                analog_positions[stick] = (x, y)

        if held_buttons:
            connection.send_oneway(
                "input.buttons.send",
                buttons={button: False for button in sorted(held_buttons)},
            )
        for stick, (x, y) in analog_positions.items():
            if x != 0.0 or y != 0.0:
                connection.send_oneway("input.analog.send", stick=stick, x=0.0, y=0.0)
        print("Macro finished. PPSSPP remains open.")
        if screenshot_count:
            os.startfile(str(screenshot_dir))
    finally:
        ws.close()


if __name__ == "__main__":
    main()
