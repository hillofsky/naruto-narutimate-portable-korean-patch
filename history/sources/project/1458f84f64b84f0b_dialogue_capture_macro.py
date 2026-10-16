import argparse
import base64
from io import BytesIO
import importlib.util
import json
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path


BASE = Path(r"PROJECT_ROOT")
PPSSPP = BASE / "tools" / "ppsspp-stage33-2314" / "PPSSPPWindows64.exe"
MEMSTICK = Path(
    r"LOCAL_PATH"
    r"\work\ppsspp\memstick"
)
TRACER = BASE / "analysis" / "stage33" / "stage33_trace_client.py"


def choose_debugger_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_debugger_module(log_path):
    spec = importlib.util.spec_from_file_location("stage33_trace_client", TRACER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.JSONL = log_path
    return module


def press(client, button, wait=0.8):
    response = client.request(
        "input.buttons.press",
        timeout=10.0,
        button=button,
        duration=2,
    )
    if response.get("event") == "error":
        raise RuntimeError(f"Could not press {button}: {response.get('message')}")
    time.sleep(wait)


def wait_for_game_start(client, timeout=60.0):
    status = client.request("game.status", timeout=15.0)
    if status.get("event") == "error":
        raise RuntimeError(f"Could not read PPSSPP game status: {status.get('message')}")
    game = status.get("game")
    if game:
        print("Game already booted.")
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = client.recv_obj(timeout=min(1.0, deadline - time.monotonic()))
        if not event:
            continue
        if event.get("event") == "game.start":
            print("Game booted.")
            return
        if event.get("event") == "error":
            raise RuntimeError(f"PPSSPP debugger error: {event.get('message')}")
    raise TimeoutError("PPSSPP did not report game.start within 60 seconds")


def capture_frame(client):
    client.send("cpu.stepping")
    deadline = time.time() + 10.0
    while time.time() < deadline:
        event = client.recv_obj(timeout=1.0)
        if event and event.get("event") == "cpu.stepping":
            break
    else:
        raise RuntimeError("CPU pause timeout while taking screenshot")

    try:
        response = client.request(
            "gpu.buffer.screenshot",
            timeout=30.0,
            type="uri",
        )
        uri = response.get("uri", "")
        prefix = "data:image/png;base64,"
        if not uri.startswith(prefix):
            raise RuntimeError(f"Screenshot failed: {response}")
        return base64.b64decode(uri[len(prefix):])
    finally:
        client.send("cpu.resume")


def wait_for_dialogue_complete(client, timeout=30.0, minimum_wait=3.0, stable_for=1.2):
    try:
        from PIL import Image
    except ImportError:
        print("Pillow unavailable; waiting for dialogue output to finish...")
        time.sleep(5.0)
        return capture_frame(client)

    started = time.monotonic()
    previous = None
    last_change = started
    last_frame = None

    while time.monotonic() - started < timeout:
        last_frame = capture_frame(client)
        image = Image.open(BytesIO(last_frame)).convert("RGB")
        width, height = image.size
        text_panel = image.crop((
            int(width * 0.14),
            int(height * 0.70),
            int(width * 0.85),
            int(height * 0.94),
        ))
        current = text_panel.tobytes()
        now = time.monotonic()

        if previous is not None and current != previous:
            last_change = now

        if now - started >= minimum_wait and now - last_change >= stable_for:
            return last_frame

        previous = current
        time.sleep(0.35)

    raise TimeoutError(
        f"Dialogue text did not stabilize within {timeout:.0f} seconds; "
        "no screenshot was saved for this line."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("iso", type=Path)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    iso = args.iso.resolve()
    if not iso.is_file() or iso.suffix.lower() not in (".iso", ".cso", ".chd"):
        raise SystemExit(f"ISO/CSO/CHD file not found: {iso}")
    if not PPSSPP.is_file():
        raise SystemExit(f"PPSSPP not found: {PPSSPP}")
    if not TRACER.is_file():
        raise SystemExit(f"Debugger helper not found: {TRACER}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BASE / "dialogue_screenshots" / f"{iso.stem}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)

    module = load_debugger_module(output_dir / "debugger_session.jsonl")
    port = choose_debugger_port()
    process = subprocess.Popen(
        [
            str(PPSSPP),
            "-i",
            f"--debugger={port}",
            f"--memstick={MEMSTICK}",
            str(iso),
        ],
        cwd=str(PPSSPP.parent),
    )

    ws = module.SimpleWebSocket("127.0.0.1", port)
    client = None
    try:
        print("Waiting for PPSSPP debugger...")
        ws.connect(timeout=30.0)
        client = module.DebuggerClient(ws)
        version = client.request(
            "version",
            timeout=15.0,
            name="dialogue-capture-macro",
            version="1.0",
        )
        connected_pid = version.get("pid")
        if connected_pid is not None and int(connected_pid) != process.pid:
            raise RuntimeError(
                f"Connected to the wrong PPSSPP process (PID {connected_pid}; "
                f"this run started PID {process.pid}). Close other PPSSPP windows and retry."
            )
        connected_path = version.get("path")
        if connected_path and Path(connected_path).resolve() != iso:
            raise RuntimeError(
                f"Debugger attached to a different game: {connected_path}"
            )
        print(f"Connected to PPSSPP PID {connected_pid or process.pid}")

        print("Waiting for the ISO to finish booting...")
        wait_for_game_start(client)

        speed = client.request("game.speed.set", timeout=10.0, percent=200)
        if speed.get("event") == "error":
            raise RuntimeError(f"Could not set 2x speed: {speed.get('message')}")
        if speed.get("percent") != 200:
            raise RuntimeError(f"PPSSPP did not confirm 2x speed: {speed}")
        print("2x speed is on and will stay on through the captures.")
        time.sleep(0.2)

        print("Pressing UP once, then CIRCLE to start a new game...")
        press(client, "up", 0.5)
        press(client, "circle", 1.5)

        print("Pressing CIRCLE to start the opening movie, then waiting for it to begin...")
        press(client, "circle", 5.0)

        print("Skipping the opening movie...")
        press(client, "start", 3.0)

        print(f"Capturing {args.count} completed dialogue screens...")
        files = []
        for index in range(1, args.count + 1):
            print(f"Waiting for dialogue {index} to finish printing...")
            frame = wait_for_dialogue_complete(client)
            output = output_dir / f"dialogue_{index:02d}.png"
            output.write_bytes(frame)
            files.append(output.name)
            print(f"  [{index}/{args.count}] {output}")

            # Advance only after this screenshot; long waits start after this O press.
            if index < args.count:
                press(client, "circle", 0.0)
                if index in (9, 12):
                    print(f"  Dialogue {index} complete; O pressed. Waiting 5 seconds...")
                    time.sleep(5.0)
                else:
                    time.sleep(1.0)

        report = {
            "iso": str(iso),
            "ppsspp": str(PPSSPP),
            "created": datetime.now().isoformat(timespec="seconds"),
            "screenshots": files,
        }
        (output_dir / "capture_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"Done: {output_dir}")
        subprocess.Popen(["explorer.exe", str(output_dir)])
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        try:
            ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
