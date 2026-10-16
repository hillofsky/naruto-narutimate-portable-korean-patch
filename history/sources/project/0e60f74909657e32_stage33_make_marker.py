from pathlib import Path
import csv
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage33"
SRC = BASE / "analysis" / "stage14" / "test_patch" / "event000_original.tbl"
DST = OUT / "event000_stage33.tbl"

MARKER = b"QZTRACE7F2C9DAB"

def main():
    raw = SRC.read_bytes()
    lines = raw.splitlines(keepends=True)

    out = []
    done = False
    report = []

    for line_no, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        newline = line[len(body):]

        if not done and body.startswith(b"MSG ="):
            parts = body.split(b",", 2)

            if len(parts) == 3:
                original = parts[2]

                patched = (
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + MARKER
                    + newline
                )

                out.append(patched)

                report.append({
                    "line": line_no,
                    "msg_id": parts[1].decode("ascii", errors="replace"),
                    "original_hex": original.hex(" "),
                    "marker_ascii": MARKER.decode("ascii"),
                    "marker_hex": MARKER.hex(" "),
                })

                done = True
                continue

        out.append(line)

    if not done:
        raise RuntimeError("첫 MSG 행을 찾지 못했습니다.")

    DST.write_bytes(b"".join(out))

    with (OUT / "stage33_marker.tsv").open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=[
                "line",
                "msg_id",
                "original_hex",
                "marker_ascii",
                "marker_hex",
            ]
        )
        w.writeheader()
        w.writerows(report)

    print("MARKER:", MARKER.decode("ascii"))
    print("TBL:", DST)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
