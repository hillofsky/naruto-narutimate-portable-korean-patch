from pathlib import Path
import csv
import re
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage16"

SOURCE = (
    BASE
    / "analysis"
    / "stage14"
    / "test_patch"
    / "event000_original.tbl"
)

TARGET = OUT / "event000_stage16.tbl"
REPORT = OUT / "stage16_probe_map.tsv"


PROBES = [
    "NOSPACEABCDEFGHIJ",
    "ASCII SPACE TEST",
    "FULL　WIDTH　SPACE",
    "UPPERABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "lowerabcdefghijklmnopqrstuvwxyz",
    "NUM0123456789-+!?.,:/",
    "LINE1<br>LINE2",
]


def main():

    if not SOURCE.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: {SOURCE}"
        )

    raw = SOURCE.read_bytes()

    text = raw.decode(
        "cp932",
        errors="strict"
    )

    lines = text.splitlines(
        keepends=True
    )

    report = []
    probe_index = 0

    out_lines = []

    rx = re.compile(
        r"^(MSG =)([^,]*),([^,]*),(.*?)(\r?\n)?$"
    )

    for line in lines:

        m = rx.match(line)

        if (
            m is not None
            and probe_index < len(PROBES)
        ):

            prefix = m.group(1)
            speaker = m.group(2)
            msg_id = m.group(3)
            original = m.group(4)
            newline = m.group(5) or ""

            probe = PROBES[
                probe_index
            ]

            new_line = (
                prefix
                + speaker
                + ","
                + msg_id
                + ","
                + probe
                + newline
            )

            out_lines.append(
                new_line
            )

            report.append({
                "probe_no":
                    probe_index + 1,

                "speaker":
                    speaker,

                "msg_id":
                    msg_id,

                "original":
                    original,

                "probe":
                    probe,

                "probe_cp932_hex":
                    probe.encode(
                        "cp932"
                    ).hex(" "),
            })

            probe_index += 1

        else:

            out_lines.append(
                line
            )

    if probe_index != len(PROBES):
        raise RuntimeError(
            f"MSG 행 부족: "
            f"{probe_index}/"
            f"{len(PROBES)}"
        )

    encoded = "".join(
        out_lines
    ).encode(
        "cp932",
        errors="strict"
    )

    # 다시 decode해서 round-trip 검증
    encoded.decode(
        "cp932",
        errors="strict"
    )

    TARGET.write_bytes(
        encoded
    )

    with REPORT.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=[
                "probe_no",
                "speaker",
                "msg_id",
                "original",
                "probe",
                "probe_cp932_hex",
            ]
        )

        w.writeheader()
        w.writerows(report)

    print("=" * 72)
    print("STAGE 16 PROBE TBL CREATED")
    print("=" * 72)

    for r in report:
        print(
            f"{r['probe_no']}: "
            f"{r['msg_id']} -> "
            f"{r['probe']}"
        )

    print()
    print("Output:", TARGET)


if __name__ == "__main__":

    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
