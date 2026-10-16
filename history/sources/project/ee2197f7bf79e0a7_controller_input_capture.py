import argparse
from datetime import datetime
import importlib.util
import json
import os
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


def choose_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_websocket_class():
    spec = importlib.util.spec_from_file_location("stage33_trace_client", TRACER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SimpleWebSocket


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
                return message
            keep.append(message)
        self.pending = keep + self.pending
        raise TimeoutError(f"PPSSPP request timed out: {event}")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("iso", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("stop_file", type=Path)
    args = parser.parse_args()

    iso = args.iso.resolve()
    if not iso.is_file() or iso.suffix.lower() not in (".iso", ".cso", ".chd"):
        raise SystemExit(f"ISO/CSO/CHD file not found: {iso}")
    if not PPSSPP.is_file():
        raise SystemExit(f"PPSSPP not found: {PPSSPP}")
    if not TRACER.is_file():
        raise SystemExit(f"Debugger helper not found: {TRACER}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    input_log = args.output_dir / "controller_inputs.jsonl"
    status_path = args.output_dir / "session.json"
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
    connection = None
    count = 0
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        ws.connect(timeout=30.0)
        connection = DebuggerConnection(ws)
        version = connection.request(
            "version",
            name="controller-input-capture",
            version="1.0",
        )
        if version.get("event") == "error":
            raise RuntimeError(version.get("message", "PPSSPP debugger handshake failed"))
        if version.get("pid") is not None and int(version["pid"]) != process.pid:
            raise RuntimeError(
                f"Connected to PPSSPP PID {version['pid']}, not this run's PID {process.pid}"
            )

        connection.send(
            "broadcast.config.set",
            disallowed={
                "logger": True,
                "game": True,
                "stepping": True,
                "breakpoint": True,
            },
        )
        write_json(
            status_path,
            {
                "status": "waiting_for_game",
                "iso": str(iso),
                "ppsspp_pid": process.pid,
                "recorder_pid": os.getpid(),
                "debugger_port": port,
                "started": started,
                "input_log": str(input_log),
                "stop_file": str(args.stop_file),
            },
        )

        deadline = time.monotonic() + 60.0
        booted = False
        while time.monotonic() < deadline and not args.stop_file.exists():
            event = connection.receive(timeout=1.0)
            if event and event.get("event") == "game.start":
                booted = True
                break
        if args.stop_file.exists():
            return
        if not booted:
            status = connection.request("game.status", timeout=10.0)
            booted = bool(status.get("game"))
        if not booted:
            raise TimeoutError("PPSSPP did not report a booted game within 60 seconds")

        speed = connection.request("game.speed.set", timeout=10.0, percent=200)
        if speed.get("event") == "error" or speed.get("percent") != 200:
            raise RuntimeError(f"Could not set 2x speed: {speed}")

        started_monotonic = time.monotonic()
        write_json(
            status_path,
            {
                "status": "recording",
                "iso": str(iso),
                "ppsspp_pid": process.pid,
                "recorder_pid": os.getpid(),
                "debugger_port": port,
                "started": started,
                "recording_started": datetime.now().astimezone().isoformat(timespec="seconds"),
                "speed_percent": 200,
                "input_log": str(input_log),
                "stop_file": str(args.stop_file),
            },
        )
        with input_log.open("a", encoding="utf-8") as output:
            while not args.stop_file.exists():
                event = connection.receive(timeout=0.5)
                if not event or event.get("event") not in ("input.buttons", "input.analog"):
                    continue
                record = {
                    "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                    "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
                    "event": event["event"],
                }
                for key in ("buttons", "changed", "stick", "x", "y"):
                    if key in event:
                        record[key] = event[key]
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                count += 1
                if count % 25 == 0:
                    current = json.loads(status_path.read_text(encoding="utf-8"))
                    current["input_events"] = count
                    write_json(status_path, current)
        final_status = json.loads(status_path.read_text(encoding="utf-8"))
        final_status.update(
            {
                "status": "stopped",
                "ended": datetime.now().astimezone().isoformat(timespec="seconds"),
                "input_events": count,
            }
        )
        write_json(status_path, final_status)
    finally:
        if connection is not None:
            try:
                connection.request("broadcast.config.set", disallowed={})
            except Exception:
                pass
        ws.close()


if __name__ == "__main__":
    main()
