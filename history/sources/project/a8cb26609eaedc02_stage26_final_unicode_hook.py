from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage26"
OUT.mkdir(parents=True, exist_ok=True)

STAGE24 = (
    BASE / "analysis" / "stage24"
    / "stage24_hangul_hook.py"
)

BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = OUT / "BOOT_stage26_unicode_hook.BIN"
PATCHED_TBL = OUT / "event000_stage26.tbl"

# Stage25 proved this is a file-backed .data zero cave.
CAVE_VA = 0x0043D57C
CAVE_OFF = 0x43D5D0
CAVE_AVAILABLE = 224

# Final renderer calls UTF8->UTF16, whose loop decodes one UTF-8
# code point here:
CALL_SITE = 0x002ACD50
ORIGINAL_UTF8_DECODER = 0x002AC8AC

# Valid CP932 Greek placeholders.
# They survive the earlier SJIS->UTF8 stage unchanged as Unicode
# U+03B1..U+03BA, then this hook replaces them immediately before
# the final UTF16 buffer is produced.
PLACEHOLDERS = [
    ("α", b"\x83\xBF", 0x03B1, "한", 0xD55C),
    ("β", b"\x83\xC0", 0x03B2, "글", 0xAE00),
    ("γ", b"\x83\xC1", 0x03B3, "테", 0xD14C),
    ("δ", b"\x83\xC2", 0x03B4, "스", 0xC2A4),
    ("ε", b"\x83\xC3", 0x03B5, "트", 0xD2B8),
    ("ζ", b"\x83\xC4", 0x03B6, "가", 0xAC00),
    ("η", b"\x83\xC5", 0x03B7, "나", 0xB098),
    ("θ", b"\x83\xC6", 0x03B8, "다", 0xB2E4),
    ("ι", b"\x83\xC7", 0x03B9, "라", 0xB77C),
    ("κ", b"\x83\xC8", 0x03BA, "마", 0xB9C8),
]


def load_stage24():
    spec = importlib.util.spec_from_file_location(
        "stage24hook",
        STAGE24
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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_hook(mod, cave_va):
    # Runtime self-reference created by bgezal at instruction 2.
    self_ref = cave_va + 0x10

    # 25 instructions = 100 bytes.
    table_va = cave_va + 0x64

    parser_delta = (
        ORIGINAL_UTF8_DECODER
        - self_ref
    ) & 0xFFFFFFFF

    table_delta = (
        table_va
        - self_ref
    ) & 0xFFFFFFFF

    p_hi, p_lo = mod.split_u32(parser_delta)
    t_hi, t_lo = mod.split_u32(table_delta)

    ZERO = 0
    V0 = 2
    T0 = 8
    T1 = 9
    T8 = 24
    T9 = 25
    SP = 29
    RA = 31

    words = []

    # Save caller RA.
    words.append(mod.I(0x09, SP, SP, -16))
    words.append(mod.I(0x2B, SP, RA, 12))

    # Get runtime PC into RA. RA becomes cave+0x10.
    words.append(mod.I(0x01, ZERO, 0x11, 1))
    words.append(0)
    words.append(mod.I(0x2B, SP, RA, 8))

    # Call original UTF-8 decoder using PC-relative address.
    words.append(mod.I(0x0F, ZERO, T9, p_hi))
    words.append(mod.I(0x0D, T9, T9, p_lo))
    words.append(mod.R(T9, RA, T9, 0, 0x21))
    words.append(mod.R(T9, ZERO, RA, 0, 0x09))
    words.append(0)

    # Recover runtime self-reference.
    words.append(mod.I(0x23, SP, T8, 8))

    # index = decoded Unicode - U+03B1
    words.append(mod.I(0x09, V0, T0, -0x03B1))

    # Only remap α..κ (10 contiguous characters).
    words.append(mod.I(0x0B, T0, T1, len(PLACEHOLDERS)))

    # Branch to done if index >= 10.
    branch_pc = cave_va + 13 * 4
    done_va = cave_va + 21 * 4
    words.append(
        mod.branch(
            0x04,
            T1,
            ZERO,
            branch_pc,
            done_va
        )
    )
    words.append(0)

    # Load replacement Hangul directly into v0.
    words.append(mod.R(ZERO, T0, T0, 1, 0))
    words.append(mod.I(0x0F, ZERO, T1, t_hi))
    words.append(mod.I(0x0D, T1, T1, t_lo))
    words.append(mod.R(T1, T8, T1, 0, 0x21))
    words.append(mod.R(T1, T0, T1, 0, 0x21))
    words.append(mod.I(0x25, T1, V0, 0))

    # done
    words.append(mod.I(0x23, SP, RA, 12))
    words.append(mod.I(0x09, SP, SP, 16))
    words.append(mod.R(RA, ZERO, ZERO, 0, 0x08))
    words.append(0)

    if len(words) != 25:
        raise RuntimeError(
            f"Unexpected hook instruction count: {len(words)}"
        )

    code = b"".join(
        struct.pack("<I", w)
        for w in words
    )

    table = b"".join(
        struct.pack("<H", hangul)
        for _, _, _, _, hangul in PLACEHOLDERS
    )

    blob = code + table

    if len(blob) != 120:
        raise RuntimeError(
            f"Unexpected Stage26 hook size: {len(blob)}"
        )

    return blob, words, table_va


def make_probe_tbl():
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: {SOURCE_TBL}"
        )

    P = [x[1] for x in PLACEHOLDERS]

    probes = [
        (
            "FINAL_HANGUL_TEST",
            "KMAP:한글테스트",
            b"KMAP:" + b"".join(P[0:5]),
        ),
        (
            "FINAL_GANADARAMA",
            "KMAP:가나다라마",
            b"KMAP:" + b"".join(P[5:10]),
        ),
        (
            "FINAL_BR",
            "KMAP:한글<br>테스트",
            b"KMAP:" + P[0] + P[1]
            + b"<br>"
            + P[2] + P[3] + P[4],
        ),
        (
            "FINAL_FULLWIDTH_SPACE",
            "KMAP:한글　테스트",
            b"KMAP:" + P[0] + P[1]
            + b"\x81\x40"
            + P[2] + P[3] + P[4],
        ),
        (
            "FINAL_MIX",
            "MIX:日本:한글",
            b"MIX:"
            + "日本".encode("cp932")
            + b":"
            + P[0] + P[1],
        ),
        (
            "JP_CONTROL",
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
    probe_index = 0

    for line_no, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        newline = line[len(body):]

        if (
            probe_index < len(probes)
            and body.startswith(b"MSG =")
        ):
            parts = body.split(b",", 2)

            if len(parts) == 3:
                name, expected, payload = probes[
                    probe_index
                ]

                out.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + payload
                    + newline
                )

                report.append({
                    "probe":
                        probe_index + 1,
                    "probe_name":
                        name,
                    "line":
                        line_no,
                    "msg_id":
                        parts[1].decode(
                            "ascii",
                            errors="replace"
                        ),
                    "expected":
                        expected,
                    "encoded_hex":
                        payload.hex(" "),
                })

                probe_index += 1
                continue

        out.append(line)

    if probe_index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: "
            f"{probe_index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT / "stage26_probe_map.tsv",
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
    print("Naruto PSP Stage 26")
    print("Final Unicode remap probe")
    print("=" * 72)

    mod = load_stage24()
    s17 = mod.load_stage17()
    elf = s17.ELF32(BOOT)

    original = bytearray(elf.data)

    actual_cave_off = elf.va_to_offset(
        CAVE_VA
    )

    if actual_cave_off != CAVE_OFF:
        raise RuntimeError(
            f"Stage25 cave VA/file mismatch: "
            f"{actual_cave_off} != {CAVE_OFF}"
        )

    if any(
        original[
            CAVE_OFF:
            CAVE_OFF + CAVE_AVAILABLE
        ]
    ):
        raise RuntimeError(
            "Stage25 .data cave is no longer zero "
            "in the original BOOT."
        )

    call_off = elf.va_to_offset(
        CALL_SITE
    )

    if call_off is None:
        raise RuntimeError(
            "UTF8 decoder callsite VA 변환 실패"
        )

    old_word = mod.u32(
        original,
        call_off
    )

    expected_word = mod.JAL(
        ORIGINAL_UTF8_DECODER
    )

    if old_word != expected_word:
        raise RuntimeError(
            f"Callsite mismatch: "
            f"0x{old_word:08X} != "
            f"0x{expected_word:08X}"
        )

    relocs = mod.relocation_sites(
        elf
    )

    if 4 not in relocs.get(
        CALL_SITE,
        []
    ):
        raise RuntimeError(
            "UTF8 decoder callsite에 "
            "R_MIPS_26 relocation이 없습니다."
        )

    blob, words, table_va = build_hook(
        mod,
        CAVE_VA
    )

    if len(blob) > CAVE_AVAILABLE:
        raise RuntimeError(
            "Stage26 hook이 cave보다 큽니다."
        )

    patched = bytearray(
        original
    )

    patched[
        CAVE_OFF:
        CAVE_OFF + len(blob)
    ] = blob

    new_word = mod.JAL(
        CAVE_VA
    )

    mod.p32(
        patched,
        call_off,
        new_word
    )

    PATCHED_BOOT.write_bytes(
        patched
    )

    mapping_rows = []

    for greek, sjis, greek_cp, hangul, hangul_cp in PLACEHOLDERS:
        mapping_rows.append({
            "source_sjis":
                sjis.hex(" "),
            "placeholder":
                greek,
            "placeholder_unicode":
                f"U+{greek_cp:04X}",
            "replacement":
                hangul,
            "replacement_unicode":
                f"U+{hangul_cp:04X}",
        })

    write_tsv(
        OUT / "stage26_mapping.tsv",
        mapping_rows,
        [
            "source_sjis",
            "placeholder",
            "placeholder_unicode",
            "replacement",
            "replacement_unicode",
        ],
    )

    hook_rows = []

    for i, word in enumerate(words):
        hook_rows.append({
            "index": i,
            "va": f"0x{CAVE_VA + i*4:08X}",
            "word": f"0x{word:08X}",
        })

    write_tsv(
        OUT / "stage26_hook_words.tsv",
        hook_rows,
        ["index", "va", "word"],
    )

    write_tsv(
        OUT / "stage26_hook_patch.tsv",
        [
            {
                "kind": "JAL_HOOK",
                "va": f"0x{CALL_SITE:08X}",
                "file_offset": f"0x{call_off:X}",
                "old": f"0x{old_word:08X}",
                "new": f"0x{new_word:08X}",
            },
            {
                "kind": "DATA_CAVE",
                "va": f"0x{CAVE_VA:08X}",
                "file_offset": f"0x{CAVE_OFF:X}",
                "old": f"{len(blob)} zero bytes",
                "new": f"{len(blob)} byte hook",
            },
        ],
        [
            "kind",
            "va",
            "file_offset",
            "old",
            "new",
        ],
    )

    make_probe_tbl()

    changed = sum(
        1
        for a, b in zip(
            original,
            patched
        )
        if a != b
    )

    summary = OUT / "stage26_summary.txt"

    summary.write_text(
        "\n".join([
            "Naruto PSP Stage 26",
            "=" * 72,
            "",
            "Purpose:",
            "  Bypass custom SJIS/JIS table mutation.",
            "  Use valid CP932 Greek placeholders.",
            "  Remap their Unicode codepoints directly after",
            "  UTF-8 decode and before UTF-16 rendering.",
            "",
            f"Original BOOT SHA256: {sha256(original)}",
            f"Patched BOOT SHA256:  {sha256(patched)}",
            f"Changed BOOT bytes: {changed}",
            "",
            f"UTF8 decoder callsite: 0x{CALL_SITE:08X}",
            f"Original decoder:      0x{ORIGINAL_UTF8_DECODER:08X}",
            f"Code cave VA:          0x{CAVE_VA:08X}",
            f"Code cave file:        0x{CAVE_OFF:X}",
            f"Hook size:             {len(blob)}",
            f"Replacement table VA:  0x{table_va:08X}",
            "",
            "If the first line displays KMAP:한글테스트,",
            "the final UTF8->UTF16 + Korean font path is solved.",
        ]),
        encoding="utf-8"
    )

    print()
    print("Callsite:",
          f"0x{CALL_SITE:08X}")
    print("Data cave:",
          f"0x{CAVE_VA:08X}",
          f"file=0x{CAVE_OFF:X}")
    print("Hook bytes:", len(blob))
    print("Patched BOOT:", PATCHED_BOOT)
    print("Probe TBL:", PATCHED_TBL)

    print()
    print("=" * 72)
    print("STAGE26 HOOK READY")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
