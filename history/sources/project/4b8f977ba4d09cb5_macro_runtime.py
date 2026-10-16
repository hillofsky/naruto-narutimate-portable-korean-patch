import base64
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import time


BASE = Path(r"PROJECT_ROOT")
PPSSPP = BASE / "tools" / "ppsspp-stage33-2314" / "PPSSPPWindows64.exe"
MEMSTICK = Path(
    r"LOCAL_PATH"
    r"\work\ppsspp\memstick"
)
TRACER = BASE / "analysis" / "stage33" / "stage33_trace_client.py"


def save_screenshot(connection, directory, index):
    connection.send_oneway("cpu.stepping")
    try:
        deadline = time.monotonic() + 15.0
        keep = []
        while time.monotonic() < deadline:
            event = connection.receive(timeout=0.5)
            if event and event.get("event") == "cpu.stepping":
                break
            if event:
                keep.append(event)
        else:
            raise TimeoutError("Screenshot pause timed out")
        connection.pending = keep + connection.pending
        response = connection.request("gpu.buffer.screenshot", timeout=30.0, type="uri")
    finally:
        connection.send_oneway("cpu.resume")
    uri = response.get("uri", "")
    prefix = "data:image/png;base64,"
    if not uri.startswith(prefix):
        raise RuntimeError("PPSSPP did not return a PNG screenshot")
    png = base64.b64decode(uri[len(prefix):], validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Invalid screenshot PNG")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{index:04d}.png"
    path.write_bytes(png)
    print(f"Screenshot: {path}")
    return path


class DebuggerConnection:
    def __init__(self, ws):
        self.ws = ws
        self.ticket = 0
        self.pending = []

    def send(self, event, **params):
        self.ticket += 1
        message = {"event": event, "ticket": self.ticket}
        message.update(params)
        self.ws.send_text(json.dumps(message, separators=(",", ":")))
        return self.ticket

    def send_oneway(self, event, **params):
        message = {"event": event}
        message.update(params)
        self.ws.send_text(json.dumps(message, separators=(",", ":")))

    def receive(self, timeout=1.0):
        if self.pending:
            return self.pending.pop(0)
        raw = self.ws.recv_text(timeout=timeout)
        return json.loads(raw) if raw else None

    def request(self, event, timeout=15.0, **params):
        ticket = self.send(event, **params)
        deadline = time.monotonic() + timeout
        keep = []
        while time.monotonic() < deadline:
            message = self.receive(min(1.0, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("ticket") == ticket:
                self.pending = keep + self.pending
                if message.get("event") == "error":
                    raise RuntimeError(message.get("message", f"PPSSPP rejected {event}"))
                return message
            keep.append(message)
        self.pending = keep + self.pending
        raise TimeoutError(f"PPSSPP request timed out: {event}")


def load_websocket_class():
    spec = importlib.util.spec_from_file_location("stage33_trace_client", TRACER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SimpleWebSocket


def choose_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_game(iso, reset_after_connect=True):
    iso = Path(iso).resolve()
    if not iso.is_file() or iso.suffix.lower() not in (".iso", ".cso", ".chd"):
        raise FileNotFoundError(f"ISO/CSO/CHD file not found: {iso}")
    if not PPSSPP.is_file():
        raise FileNotFoundError(f"PPSSPP not found: {PPSSPP}")
    if not TRACER.is_file():
        raise FileNotFoundError(f"Debugger helper not found: {TRACER}")

    port = choose_port()
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
    ws = load_websocket_class()("127.0.0.1", port)
    try:
        ws.connect(timeout=30.0)
        connection = DebuggerConnection(ws)
        version = connection.request(
            "version",
            name="ppsspp-controller-macro",
            version="1.0",
        )
        pid = version.get("pid")
        if pid is not None and int(pid) != process.pid:
            raise RuntimeError(
                f"Debugger attached to PPSSPP PID {pid}, but this run started PID {process.pid}"
            )
        actual_path = version.get("path")
        if actual_path and Path(actual_path).resolve() != iso:
            raise RuntimeError(f"Debugger attached to another game: {actual_path}")

        connection.request(
            "broadcast.config.set",
            disallowed={"logger": True, "game": False, "stepping": False, "input": False},
        )
        print("Waiting for PPSSPP game boot...")
        wait_for_game(connection)
        if reset_after_connect:
            print("Sending Ctrl+B-equivalent reset to synchronize the game...")
            connection.pending = [
                event for event in connection.pending
                if event.get("event") not in ("game.start", "game.quit")
            ]
            connection.request("game.reset", timeout=15.0)
            wait_for_reset(connection)
            print("Game reset synchronized.")
        speed = connection.request("game.speed.set", percent=200)
        if speed.get("percent") != 200:
            raise RuntimeError(f"PPSSPP did not confirm 2x speed: {speed}")
        return process, ws, connection, iso
    except Exception:
        ws.close()
        if process.poll() is None:
            process.terminate()
        raise


def wait_for_game(connection, timeout=60.0):
    status = connection.request("game.status", timeout=15.0)
    if status.get("game"):
        return

    deadline = time.monotonic() + timeout
    next_status = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        event = connection.receive(timeout=0.5)
        if event and event.get("event") == "game.start":
            return
        if time.monotonic() >= next_status:
            status = connection.request("game.status", timeout=10.0)
            if status.get("game"):
                return
            next_status = time.monotonic() + 2.0
    raise TimeoutError("PPSSPP did not report a booted game within 60 seconds")


def wait_for_reset(connection, timeout=45.0):
    deadline = time.monotonic() + timeout
    next_status = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        event = connection.receive(timeout=0.5)
        if event and event.get("event") == "game.start":
            return
        if time.monotonic() >= next_status:
            status = connection.request("game.status", timeout=10.0)
            if status.get("game"):
                return
            next_status = time.monotonic() + 2.0
    raise TimeoutError("PPSSPP game reset did not finish within 45 seconds")
