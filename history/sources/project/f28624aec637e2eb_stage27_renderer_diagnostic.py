from pathlib import Path
import csv
import importlib.util
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage27"
OUT.mkdir(parents=True, exist_ok=True)

SOURCE = (
    BASE / "analysis" / "stage26"
    / "stage26_final_unicode_hook.py"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = OUT / "BOOT_stage27_renderer_diag.BIN"
PATCHED_TBL = OUT / "event000_stage27.tbl"


# First 5: Japanese control.
# Last 5: Korean test.
DIAG_MAP = [
    ("α", b"\x83\xBF", 0x03B1, "あ", 0x3042),
    ("β", b"\x83\xC0", 0x03B2, "い", 0x3044),
    ("γ", b"\x83\xC1", 0x03B3, "う", 0x3046),
    ("δ", b"\x83\xC2", 0x03B4, "え", 0x3048),
    ("ε", b"\x83\xC3", 0x03B5, "お", 0x304A),

    ("ζ", b"\x83\xC4", 0x03B6, "가", 0xAC00),
    ("η", b"\x83\xC5", 0x03B7, "나", 0xB098),
    ("θ", b"\x83\xC6", 0x03B8, "다", 0xB2E4),
    ("ι", b"\x83\xC7", 0x03B9, "라", 0xB77C),
    ("κ", b"\x83\xC8", 0x03BA, "마", 0xB9C8),
]


def load_source():
    spec = importlib.util.spec_from_file_location(
        "stage26hook",
        SOURCE
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_tsv(path, rows, fields):
    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields
        )
        w.writeheader()
        for row in rows:
            w.writerow({
                k: row.get(k, "")
                for k in fields
            })


def make_probe_tbl(mod):
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: {SOURCE_TBL}"
        )

    P = [x[1] for x in DIAG_MAP]

    probes = [
        (
            "JAPANESE_RENDER_CONTROL",
            "JMAP:あいうえお",
            b"JMAP:" + b"".join(P[0:5]),
        ),
        (
            "KOREAN_RENDER_TEST",
            "KMAP:가나다라마",
            b"KMAP:" + b"".join(P[5:10]),
        ),
        (
            "MIX_RENDER_TEST",
            "MIX:あ가いな",
            b"MIX:"
            + P[0] + P[5]
            + P[1] + P[6],
        ),
        (
            "JAPANESE_ORIGINAL_CONTROL",
            "JP:日本語確認",
            b"JP:" + "日本語確認".encode("cp932"),
        ),
        (
            "ASCII_CONTROL",
            "ASCII:OK",
            b"ASCII:OK",
        ),
    ]

    raw = SOURCE_TBL.read_bytes()
    lines = raw.splitlines(keepends=True)

    out = []
    report = []
    index = 0

    for line_no, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        newline = line[len(body):]

        if (
            index < len(probes)
            and body.startswith(b"MSG =")
        ):
            parts = body.split(b",", 2)

            if len(parts) == 3:
                name, expected, payload = probes[index]

                out.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + payload
                    + newline
                )

                report.append({
                    "probe": index + 1,
                    "probe_name": name,
                    "line": line_no,
                    "msg_id": parts[1].decode(
                        "ascii",
                        errors="replace"
                    ),
                    "expected": expected,
                    "encoded_hex": payload.hex(" "),
                })

                index += 1
                continue

        out.append(line)

    if index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: {index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT / "stage27_probe_map.tsv",
        report,
        [
            "probe",
            "probe_name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ],
    )


def main():
    print("=" * 72)
    print("Naruto PSP Stage 27")
    print("Japanese-vs-Korean renderer diagnostic")
    print("=" * 72)

    mod = load_source()

    # Keep the proven Stage26 hook implementation, only replace
    # its Unicode output table and output paths.
    mod.OUT = OUT
    mod.PATCHED_BOOT = PATCHED_BOOT
    mod.PATCHED_TBL = PATCHED_TBL
    mod.PLACEHOLDERS = DIAG_MAP

    def custom_probe():
        make_probe_tbl(mod)

    mod.make_probe_tbl = custom_probe

    mod.main()

    # Stage26 main writes report names with "stage26_".
    for p in list(OUT.glob("stage26_*")):
        dest = p.with_name(
            p.name.replace(
                "stage26_",
                "stage27_",
                1
            )
        )
        if dest.exists():
            dest.unlink()
        p.rename(dest)

    # Write a diagnostic-specific mapping report.
    rows = []
    for greek, sjis, greek_cp, target, target_cp in DIAG_MAP:
        rows.append({
            "source_sjis": sjis.hex(" "),
            "placeholder": greek,
            "placeholder_unicode": f"U+{greek_cp:04X}",
            "target": target,
            "target_unicode": f"U+{target_cp:04X}",
            "font_expected":
                "Japanese"
                if target_cp < 0xAC00
                else "Korean",
        })

    write_tsv(
        OUT / "stage27_diagnostic_mapping.tsv",
        rows,
        [
            "source_sjis",
            "placeholder",
            "placeholder_unicode",
            "target",
            "target_unicode",
            "font_expected",
        ],
    )

    (OUT / "stage27_diagnostic_guide.txt").write_text(
        "\n".join([
            "Naruto PSP Stage27 renderer diagnostic",
            "=" * 72,
            "",
            "Expected runtime:",
            "  1. JMAP:あいうえお",
            "  2. KMAP:가나다라마",
            "  3. MIX:あ가い나",
            "  4. JP:日本語確認",
            "  5. ASCII:OK",
            "",
            "Interpretation:",
            "  Japanese clean + Korean corrupt:",
            "    Unicode hook works; Korean sceFont/kr0 rendering path is the fault.",
            "",
            "  Japanese and Korean both corrupt:",
            "    Stage26 Unicode hook/output table is still wrong.",
            "",
            "  Both clean:",
            "    Korean renderer works and the previous target set/path needs re-check.",
        ]),
        encoding="utf-8"
    )

    print()
    print("Expected:")
    print("  JMAP:あいうえお")
    print("  KMAP:가나다라마")
    print("  MIX:あ가い나")
    print()
    print(PATCHED_BOOT)
    print(PATCHED_TBL)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
