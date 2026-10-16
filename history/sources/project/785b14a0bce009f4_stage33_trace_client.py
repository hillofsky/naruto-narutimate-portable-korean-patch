import base64
import csv
import hashlib
import json
import os
import secrets
import socket
import struct
import sys
import time
from pathlib import Path


HOST = "127.0.0.1"
PORT = 26222
MARKER = b"QZTRACE7F2C9DAB"

BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage33"

JSONL = OUT / "stage33_debugger_session.jsonl"
HITS_TSV = OUT / "stage33_trace_hits.tsv"
PCS_TSV = OUT / "stage33_unique_pcs.tsv"
DISASM_TXT = OUT / "stage33_disasm.txt"
SUMMARY = OUT / "stage33_trace_summary.txt"


class WSClosed(RuntimeError):
    pass


class SimpleWebSocket:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.fragments = bytearray()
        self.fragment_opcode = None

    def connect(self, timeout=60.0):
        deadline = time.time() + timeout
        last_error = None

        while time.time() < deadline:
            try:
                s = socket.create_connection(
                    (self.host, self.port),
                    timeout=2.0,
                )
                s.settimeout(1.0)

                key = base64.b64encode(
                    secrets.token_bytes(16)
                ).decode("ascii")

                req = (
                    "GET /debugger HTTP/1.1\r\n"
                    f"Host: {self.host}:{self.port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    "Sec-WebSocket-Protocol: debugger.ppsspp.org\r\n"
                    "\r\n"
                ).encode("ascii")

                s.sendall(req)

                data = bytearray()

                while b"\r\n\r\n" not in data:
                    chunk = s.recv(4096)

                    if not chunk:
                        raise RuntimeError(
                            "WebSocket HTTP handshake closed"
                        )

                    data.extend(chunk)

                    if len(data) > 65536:
                        raise RuntimeError(
                            "WebSocket handshake too large"
                        )

                header = bytes(
                    data.split(
                        b"\r\n\r\n",
                        1
                    )[0]
                ).decode(
                    "latin-1",
                    errors="replace"
                )

                if " 101 " not in header.splitlines()[0]:
                    raise RuntimeError(
                        "WebSocket upgrade failed: "
                        + header.splitlines()[0]
                    )

                if "debugger.ppsspp.org" not in header.lower():
                    # Some builds may omit echoing the subprotocol,
                    # but current builds should include it.
                    pass

                self.sock = s
                return

            except Exception as exc:
                last_error = exc

                try:
                    s.close()
                except Exception:
                    pass

                time.sleep(0.5)

        raise RuntimeError(
            f"PPSSPP debugger 연결 실패: {last_error}"
        )

    def _recv_exact(self, n):
        out = bytearray()

        while len(out) < n:
            chunk = self.sock.recv(
                n - len(out)
            )

            if not chunk:
                raise WSClosed(
                    "WebSocket closed"
                )

            out.extend(chunk)

        return bytes(out)

    def _send_frame(self, opcode, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        fin_opcode = (
            0x80
            | (opcode & 0x0F)
        )

        length = len(payload)
        mask_key = secrets.token_bytes(4)

        if length < 126:
            header = bytes([
                fin_opcode,
                0x80 | length,
            ])
        elif length <= 0xFFFF:
            header = bytes([
                fin_opcode,
                0x80 | 126,
            ]) + struct.pack(
                "!H",
                length
            )
        else:
            header = bytes([
                fin_opcode,
                0x80 | 127,
            ]) + struct.pack(
                "!Q",
                length
            )

        masked = bytes(
            b ^ mask_key[i & 3]
            for i, b in enumerate(payload)
        )

        self.sock.sendall(
            header
            + mask_key
            + masked
        )

    def send_text(self, text):
        self._send_frame(
            0x1,
            text
        )

    def recv_text(self, timeout=1.0):
        self.sock.settimeout(
            timeout
        )

        while True:
            try:
                h = self._recv_exact(2)
            except socket.timeout:
                return None

            b0 = h[0]
            b1 = h[1]

            fin = bool(
                b0 & 0x80
            )

            opcode = (
                b0 & 0x0F
            )

            masked = bool(
                b1 & 0x80
            )

            length = (
                b1 & 0x7F
            )

            if length == 126:
                length = struct.unpack(
                    "!H",
                    self._recv_exact(2)
                )[0]

            elif length == 127:
                length = struct.unpack(
                    "!Q",
                    self._recv_exact(8)
                )[0]

            mask = (
                self._recv_exact(4)
                if masked
                else None
            )

            payload = self._recv_exact(
                length
            )

            if mask is not None:
                payload = bytes(
                    b ^ mask[i & 3]
                    for i, b
                    in enumerate(payload)
                )

            if opcode == 0x8:
                raise WSClosed(
                    "Server closed WebSocket"
                )

            if opcode == 0x9:
                self._send_frame(
                    0xA,
                    payload
                )
                continue

            if opcode == 0xA:
                continue

            if opcode == 0x1:
                if fin:
                    return payload.decode(
                        "utf-8",
                        errors="replace"
                    )

                self.fragments = bytearray(
                    payload
                )
                self.fragment_opcode = opcode
                continue

            if opcode == 0x0:
                self.fragments.extend(
                    payload
                )

                if fin:
                    result = bytes(
                        self.fragments
                    )
                    self.fragments.clear()
                    self.fragment_opcode = None

                    return result.decode(
                        "utf-8",
                        errors="replace"
                    )

                continue

    def close(self):
        if self.sock is None:
            return

        try:
            self._send_frame(
                0x8,
                b""
            )
        except Exception:
            pass

        try:
            self.sock.close()
        except Exception:
            pass

        self.sock = None


class DebuggerClient:
    def __init__(self, ws):
        self.ws = ws
        self.ticket = 0
        self.pending = []
        self.jsonl = JSONL.open(
            "w",
            encoding="utf-8"
        )

    def log_msg(self, direction, obj):
        row = {
            "time": time.time(),
            "direction": direction,
            "message": obj,
        }

        self.jsonl.write(
            json.dumps(
                row,
                ensure_ascii=False
            )
            + "\n"
        )
        self.jsonl.flush()

    def send(self, event, **kwargs):
        self.ticket += 1

        obj = {
            "event": event,
            "ticket": self.ticket,
        }
        obj.update(kwargs)

        self.log_msg(
            "send",
            obj
        )

        self.ws.send_text(
            json.dumps(
                obj,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

        return self.ticket

    def recv_obj(self, timeout=1.0):
        if self.pending:
            return self.pending.pop(0)

        text = self.ws.recv_text(
            timeout
        )

        if text is None:
            return None

        try:
            obj = json.loads(
                text
            )
        except Exception:
            obj = {
                "event": "_invalid_json",
                "raw": text,
            }

        self.log_msg(
            "recv",
            obj
        )

        return obj

    def request(self, event, timeout=10.0, **kwargs):
        ticket = self.send(
            event,
            **kwargs
        )

        deadline = (
            time.time()
            + timeout
        )

        keep = []

        while time.time() < deadline:
            obj = self.recv_obj(
                timeout=min(
                    1.0,
                    max(
                        0.05,
                        deadline - time.time()
                    )
                )
            )

            if obj is None:
                continue

            if obj.get("ticket") == ticket:
                self.pending = (
                    keep
                    + self.pending
                )
                return obj

            keep.append(
                obj
            )

        self.pending = (
            keep
            + self.pending
        )

        raise TimeoutError(
            f"request timeout: {event}"
        )

    def close(self):
        try:
            self.jsonl.close()
        except Exception:
            pass


def search_marker(client):
    pattern = base64.b64encode(
        MARKER
    ).decode("ascii")

    # Standard PSP user RAM. The first range is preferred
    # because commercial games normally live there.
    ranges = [
        (
            0x08800000,
            0x01800000,
            "USER_24MB",
        ),
        (
            0x08000000,
            0x02000000,
            "RAM_32MB",
        ),
    ]

    for address, size, label in ranges:
        try:
            result = client.request(
                "memory.search",
                timeout=15.0,
                address=address,
                size=size,
                type="bytes",
                base64=pattern,
                align=1,
                maxResults=64,
            )
        except Exception:
            continue

        if result.get("event") == "error":
            continue

        matches = result.get(
            "matches",
            []
        )

        if matches:
            return (
                sorted(
                    set(
                        int(x)
                        for x in matches
                    )
                ),
                label,
            )

    return (
        [],
        None,
    )


def main():
    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 72)
    print("Naruto PSP Stage33 runtime tracer")
    print("=" * 72)
    print()
    print("PPSSPP WebSocket debugger 연결 대기...")
    print("PPSSPP에서는 평소처럼 게임을 조작하세요.")
    print("첫 이벤트의 QZTRACE7F2C9DAB 대사까지 진행하면 됩니다.")
    print()

    ws = SimpleWebSocket(
        HOST,
        PORT
    )

    ws.connect(
        timeout=90.0
    )

    client = DebuggerClient(
        ws
    )

    try:
        version = client.request(
            "version",
            timeout=10.0,
            name="naruto-stage33-tracer",
            version="1.0",
        )

        print(
            "Debugger connected:",
            version.get(
                "name",
                "PPSSPP"
            ),
            version.get(
                "version",
                ""
            )
        )

        print(
            "PID:",
            version.get(
                "pid"
            )
        )

        print(
            "Loaded path:",
            version.get(
                "path"
            )
        )

        # Reduce unrelated websocket traffic.
        try:
            client.request(
                "broadcast.config.set",
                timeout=5.0,
                disallowed={
                    "logger": True,
                    "game": False,
                    "stepping": False,
                    "input": True,
                    "breakpoint": False,
                },
            )
        except Exception:
            pass

        # --debugger starts the emulated CPU paused at the entry point.
        # Resume asynchronously so the user can navigate to the first event.
        client.send(
            "cpu.resume"
        )

        print(
            "CPU resumed - 게임 조작 가능"
        )

        # Poll until event000 is decompressed/loaded.
        search_start = time.time()
        last_notice = 0.0
        matches = []
        range_label = None

        # Drive the short path to event000 without relying on window focus:
        # enter the title menu, choose New Game/confirm, then skip movies.
        auto_inputs = [
            (8.0, "start", "타이틀 진입"),
            (16.0, "start", "메뉴 진입"),
            (24.0, "circle", "새 게임 선택"),
            (32.0, "circle", "새 게임 확인"),
            (45.0, "start", "영상 스킵"),
            (60.0, "start", "영상 스킵 재시도"),
            (75.0, "start", "영상 스킵 재시도"),
            (90.0, "start", "영상 스킵 재시도"),
            (105.0, "start", "영상 스킵 재시도"),
            (120.0, "start", "영상 스킵 재시도"),
        ]
        auto_input_index = 0

        while (
            time.time()
            - search_start
            < 600.0
        ):
            elapsed_f = (
                time.time()
                - search_start
            )

            while (
                auto_input_index
                < len(auto_inputs)
                and elapsed_f
                >= auto_inputs[auto_input_index][0]
            ):
                _, button, label = auto_inputs[auto_input_index]
                client.send(
                    "input.buttons.press",
                    button=button,
                    duration=2,
                )
                print(
                    f"AUTO INPUT: {button.upper()} - {label}"
                )
                auto_input_index += 1

            matches, range_label = search_marker(
                client
            )

            if matches:
                break

            now = time.time()

            if (
                now - last_notice
                > 10.0
            ):
                elapsed = int(
                    now - search_start
                )

                print(
                    f"[{elapsed:3d}s] marker 아직 없음 - "
                    "첫 이벤트까지 진행하세요..."
                )
                last_notice = now

            time.sleep(
                0.75
            )

        if not matches:
            raise RuntimeError(
                "10분 내 marker를 PSP RAM에서 찾지 못했습니다."
            )

        print()
        print(
            "MARKER FOUND:",
            ", ".join(
                f"0x{x:08X}"
                for x in matches
            )
        )
        print(
            "Search range:",
            range_label
        )
        print()
        print(
            "읽기 breakpoint 설정 중..."
        )

        armed = []

        for addr in matches:
            response = client.request(
                "memory.breakpoint.add",
                timeout=10.0,
                address=addr,
                size=len(MARKER),
                enabled=False,
                log=True,
                read=True,
                write=False,
                change=False,
            )

            if response.get(
                "event"
            ) == "error":
                print(
                    "Breakpoint add failed:",
                    hex(addr),
                    response.get(
                        "message"
                    )
                )
                continue

            armed.append(
                addr
            )

        if not armed:
            raise RuntimeError(
                "marker read breakpoint를 설정하지 못했습니다."
            )

        print(
            "ARMED:",
            ", ".join(
                f"0x{x:08X}"
                for x in armed
            )
        )
        print()
        print(
            "첫 대사를 화면에 띄운 채 잠시 기다리세요."
        )
        print(
            "첫 read hit부터 20초간 자동 수집합니다."
        )
        print()

        hits = []
        first_hit_time = None
        wait_deadline = (
            time.time()
            + 300.0
        )

        while (
            time.time()
            < wait_deadline
        ):
            obj = client.recv_obj(
                timeout=1.0
            )

            if obj is None:
                continue

            if obj.get(
                "event"
            ) != "cpu.breakpoint.hit":
                continue

            hit = obj.get(
                "hit",
                {}
            )

            if hit.get(
                "kind"
            ) != "memory":
                continue

            bp = hit.get(
                "breakpoint",
                {}
            )

            start = bp.get(
                "start"
            )

            if start not in armed:
                continue

            if hit.get(
                "access"
            ) != "read":
                continue

            now = time.time()

            if first_hit_time is None:
                first_hit_time = now
                print(
                    "FIRST READ HIT:",
                    f"PC=0x{int(hit.get('pc', 0)):08X}",
                    f"ADDR=0x{int(hit.get('address', 0)):08X}",
                    f"SOURCE={hit.get('source')}"
                )

            hits.append({
                "sequence":
                    obj.get(
                        "sequence",
                        ""
                    ),
                "time_since_first":
                    (
                        0.0
                        if first_hit_time is None
                        else now - first_hit_time
                    ),
                "pc":
                    int(
                        hit.get(
                            "pc",
                            0
                        )
                    ),
                "address":
                    int(
                        hit.get(
                            "address",
                            0
                        )
                    ),
                "size":
                    hit.get(
                        "size",
                        ""
                    ),
                "access":
                    hit.get(
                        "access",
                        ""
                    ),
                "source":
                    hit.get(
                        "source",
                        ""
                    ),
                "hits":
                    hit.get(
                        "hits",
                        ""
                    ),
                "breakpoint_start":
                    int(
                        start
                    ),
                "breakpoint_end":
                    int(
                        bp.get(
                            "end",
                            start
                        )
                    ),
                "symbol":
                    hit.get(
                        "symbol"
                    )
                    or "",
            })

            if (
                first_hit_time is not None
                and now - first_hit_time
                >= 20.0
            ):
                break

            if len(hits) >= 500:
                break

        # If first hit occurred, continue until 20-second capture actually elapsed,
        # even if traffic briefly stopped.
        if first_hit_time is not None:
            target_end = (
                first_hit_time
                + 20.0
            )

            while (
                time.time() < target_end
                and len(hits) < 500
            ):
                obj = client.recv_obj(
                    timeout=min(
                        1.0,
                        target_end
                        - time.time()
                    )
                )

                if obj is None:
                    continue

                if obj.get(
                    "event"
                ) != "cpu.breakpoint.hit":
                    continue

                hit = obj.get(
                    "hit",
                    {}
                )

                bp = hit.get(
                    "breakpoint",
                    {}
                )

                start = bp.get(
                    "start"
                )

                if (
                    hit.get("kind") == "memory"
                    and hit.get("access") == "read"
                    and start in armed
                ):
                    now = time.time()

                    hits.append({
                        "sequence":
                            obj.get(
                                "sequence",
                                ""
                            ),
                        "time_since_first":
                            now - first_hit_time,
                        "pc":
                            int(
                                hit.get(
                                    "pc",
                                    0
                                )
                            ),
                        "address":
                            int(
                                hit.get(
                                    "address",
                                    0
                                )
                            ),
                        "size":
                            hit.get(
                                "size",
                                ""
                            ),
                        "access":
                            hit.get(
                                "access",
                                ""
                            ),
                        "source":
                            hit.get(
                                "source",
                                ""
                            ),
                        "hits":
                            hit.get(
                                "hits",
                                ""
                            ),
                        "breakpoint_start":
                            int(
                                start
                            ),
                        "breakpoint_end":
                            int(
                                bp.get(
                                    "end",
                                    start
                                )
                            ),
                        "symbol":
                            hit.get(
                                "symbol"
                            )
                            or "",
                    })

        # Remove memchecks.
        for addr in armed:
            try:
                client.request(
                    "memory.breakpoint.remove",
                    timeout=5.0,
                    address=addr,
                    size=len(MARKER),
                )
            except Exception:
                pass

        if not hits:
            raise RuntimeError(
                "marker는 RAM에서 찾았지만 5분 내 read breakpoint가 한 번도 발생하지 않았습니다."
            )

        # ====================================================
        # Reports
        # ====================================================

        with HITS_TSV.open(
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as f:
            fields = [
                "sequence",
                "time_since_first",
                "pc_hex",
                "address_hex",
                "size",
                "access",
                "source",
                "hits",
                "breakpoint_start_hex",
                "breakpoint_end_hex",
                "symbol",
            ]

            w = csv.DictWriter(
                f,
                delimiter="\t",
                fieldnames=fields
            )
            w.writeheader()

            for h in hits:
                w.writerow({
                    "sequence":
                        h["sequence"],
                    "time_since_first":
                        f"{h['time_since_first']:.6f}",
                    "pc_hex":
                        f"0x{h['pc']:08X}",
                    "address_hex":
                        f"0x{h['address']:08X}",
                    "size":
                        h["size"],
                    "access":
                        h["access"],
                    "source":
                        h["source"],
                    "hits":
                        h["hits"],
                    "breakpoint_start_hex":
                        f"0x{h['breakpoint_start']:08X}",
                    "breakpoint_end_hex":
                        f"0x{h['breakpoint_end']:08X}",
                    "symbol":
                        h["symbol"],
                })

        pc_stats = {}

        for h in hits:
            pc = h["pc"]

            item = pc_stats.setdefault(
                pc,
                {
                    "pc": pc,
                    "count": 0,
                    "first_t":
                        h[
                            "time_since_first"
                        ],
                    "last_t":
                        h[
                            "time_since_first"
                        ],
                    "source":
                        h[
                            "source"
                        ],
                    "symbol":
                        h[
                            "symbol"
                        ],
                }
            )

            item["count"] += 1
            item["last_t"] = h[
                "time_since_first"
            ]

        unique = sorted(
            pc_stats.values(),
            key=lambda x: (
                x["first_t"],
                -x["count"],
                x["pc"],
            )
        )

        with PCS_TSV.open(
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as f:
            fields = [
                "rank",
                "pc_hex",
                "count",
                "first_t",
                "last_t",
                "source",
                "symbol",
            ]

            w = csv.DictWriter(
                f,
                delimiter="\t",
                fieldnames=fields
            )
            w.writeheader()

            for rank, item in enumerate(
                unique,
                1
            ):
                w.writerow({
                    "rank":
                        rank,
                    "pc_hex":
                        f"0x{item['pc']:08X}",
                    "count":
                        item["count"],
                    "first_t":
                        f"{item['first_t']:.6f}",
                    "last_t":
                        f"{item['last_t']:.6f}",
                    "source":
                        item["source"],
                    "symbol":
                        item["symbol"],
                })

        # Ask PPSSPP for compact disassembly around each unique read PC.
        disasm_blocks = []

        for item in unique[:32]:
            pc = item["pc"]
            start = (
                pc - 24
                if pc >= 24
                else pc
            )

            try:
                resp = client.request(
                    "memory.disasm",
                    timeout=10.0,
                    address=start,
                    count=16,
                    displaySymbols=True,
                    compact=True,
                )

                lines = resp.get(
                    "lines",
                    []
                )

                disasm_blocks.append(
                    (
                        pc,
                        item["count"],
                        item["first_t"],
                        lines,
                    )
                )

            except Exception as exc:
                disasm_blocks.append(
                    (
                        pc,
                        item["count"],
                        item["first_t"],
                        [
                            f"DISASM ERROR: {exc}"
                        ],
                    )
                )

        with DISASM_TXT.open(
            "w",
            encoding="utf-8"
        ) as f:
            for (
                pc,
                count,
                first_t,
                lines
            ) in disasm_blocks:

                f.write(
                    "=" * 72
                    + "\n"
                )
                f.write(
                    f"PC 0x{pc:08X} "
                    f"hits={count} "
                    f"first={first_t:.6f}s\n"
                )
                f.write(
                    "=" * 72
                    + "\n"
                )

                for line in lines:
                    f.write(
                        str(line)
                        + "\n"
                    )

                f.write("\n")

        SUMMARY.write_text(
            "\n".join([
                "Naruto PSP Stage 33",
                "=" * 72,
                "",
                f"Marker: {MARKER.decode('ascii')}",
                "Marker addresses:",
                *[
                    f"  0x{x:08X}"
                    for x in matches
                ],
                "",
                f"Search range: {range_label}",
                f"Read hits captured: {len(hits)}",
                f"Unique read PCs: {len(unique)}",
                "",
                "Unique PCs (first-seen order):",
                *[
                    (
                        f"  {rank:02d}. "
                        f"0x{item['pc']:08X} "
                        f"count={item['count']} "
                        f"first={item['first_t']:.6f}s "
                        f"source={item['source']} "
                        f"symbol={item['symbol']}"
                    )
                    for rank, item
                    in enumerate(
                        unique,
                        1
                    )
                ],
                "",
                "Use stage33_disasm.txt to identify",
                "the real event text parser/renderer path.",
            ]),
            encoding="utf-8"
        )

        print()
        print("=" * 72)
        print("STAGE33 TRACE COMPLETE")
        print("=" * 72)
        print("Read hits:", len(hits))
        print("Unique PCs:", len(unique))

        for rank, item in enumerate(
            unique[:16],
            1
        ):
            print(
                f"{rank:02d}. "
                f"0x{item['pc']:08X} "
                f"count={item['count']} "
                f"source={item['source']}"
            )

        print()
        print("Reports:")
        print(HITS_TSV)
        print(PCS_TSV)
        print(DISASM_TXT)
        print(SUMMARY)

    finally:
        client.close()
        ws.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("TRACE ERROR:", exc)
        raise
