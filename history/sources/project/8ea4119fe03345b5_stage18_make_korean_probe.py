from pathlib import Path
import csv
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage18"

SOURCE = (
    BASE
    / "analysis"
    / "stage14"
    / "test_patch"
    / "event000_original.tbl"
)

TARGET = OUT / "event000_stage18.tbl"
REPORT = OUT / "stage18_probe_map.tsv"


PROBES = [
    (
        "K1_CP949_COMMON",
        b"K1:" + "한글테스트".encode("cp949")
    ),
    (
        "K2_CP949_FULLWIDTH_SPACE",
        b"K2:" + "한글　테스트".encode("cp949")
    ),
    (
        "K3_CP949_EXTENSION",
        b"K3:" + "똠방각하".encode("cp949")
    ),
    (
        "U1_UTF8_COMMON",
        b"U1:" + "한글테스트".encode("utf-8")
    ),
    (
        "U2_UTF8_FULLWIDTH_SPACE",
        b"U2:" + "한글　테스트".encode("utf-8")
    ),
    (
        "B1_UTF16BE_RAW",
        b"B1:" + "한국".encode("utf-16-be")
    ),
    (
        "JP_CP932_CONTROL",
        b"JP:" + "日本語確認".encode("cp932")
    ),
]


def main():

    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    if not SOURCE.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: {SOURCE}"
        )

    raw = SOURCE.read_bytes()

    # Preserve the original file byte-for-byte except the
    # message payloads.  Do NOT decode the whole file because
    # this test intentionally inserts non-CP932 byte streams.
    lines = raw.splitlines(
        keepends=True
    )

    out = []
    report = []

    probe_index = 0

    for line_no, line in enumerate(
        lines,
        1
    ):

        body = line.rstrip(
            b"\r\n"
        )

        newline = line[
            len(body):
        ]

        if (
            probe_index < len(PROBES)
            and body.startswith(
                b"MSG ="
            )
        ):
            parts = body.split(
                b",",
                2
            )

            if len(parts) == 3:

                name, payload = (
                    PROBES[
                        probe_index
                    ]
                )

                old_payload = (
                    parts[2]
                )

                new_line = (
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + payload
                    + newline
                )

                out.append(
                    new_line
                )

                report.append({
                    "probe_no":
                        probe_index + 1,

                    "probe_name":
                        name,

                    "line":
                        line_no,

                    "speaker_bytes":
                        parts[0].hex(" "),

                    "msg_id":
                        parts[1].decode(
                            "ascii",
                            errors="replace"
                        ),

                    "original_hex":
                        old_payload.hex(" "),

                    "probe_hex":
                        payload.hex(" "),

                    "probe_length":
                        len(payload),
                })

                probe_index += 1
                continue

        out.append(line)

    if probe_index != len(PROBES):
        raise RuntimeError(
            f"MSG 행 부족: "
            f"{probe_index}/"
            f"{len(PROBES)}"
        )

    patched = b"".join(out)

    TARGET.write_bytes(
        patched
    )

    with REPORT.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        fields = [
            "probe_no",
            "probe_name",
            "line",
            "speaker_bytes",
            "msg_id",
            "original_hex",
            "probe_hex",
            "probe_length",
        ]

        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields
        )

        w.writeheader()
        w.writerows(report)

    print("=" * 72)
    print("STAGE 18 KOREAN ENCODING PROBE")
    print("=" * 72)

    for row in report:
        print(
            f"{row['probe_no']} "
            f"{row['probe_name']} "
            f"id={row['msg_id']} "
            f"bytes={row['probe_hex']}"
        )

    print()
    print(
        "Output:",
        TARGET
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
