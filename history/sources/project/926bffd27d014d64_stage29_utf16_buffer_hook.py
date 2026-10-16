from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage29"
OUT.mkdir(parents=True, exist_ok=True)

STAGE26 = (
    BASE / "analysis" / "stage26"
    / "stage26_final_unicode_hook.py"
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

PATCHED_BOOT = OUT / "BOOT_stage29_utf16_buffer_hook.BIN"
PATCHED_TBL = OUT / "event000_stage29.tbl"


# Proven file-backed .data cave from Stage25.
CAVE_VA = 0x0043D57C
CAVE_OFF = 0x43D5D0
CAVE_AVAILABLE = 224

# Renderer 0x002AC2A4:
#   0x002AC2E4 a0 = sp+0xD0 output UTF16 buffer
#   0x002AC2E8 a1 = 0x100
#   0x002AC2EC jal 0x002ACCF4
# Therefore hook the whole UTF8->UTF16 conversion call and patch
# the resulting UTF16 buffer, instead of changing decoder return values.
CALL_SITE = 0x002AC2EC
ORIGINAL_CONVERTER = 0x002ACCF4


# Normal CP932 Greek placeholders.
PLACEHOLDERS = [
    ("α", b"\x83\xBF"),
    ("β", b"\x83\xC0"),
    ("γ", b"\x83\xC1"),
    ("δ", b"\x83\xC2"),
    ("ε", b"\x83\xC3"),
    ("ζ", b"\x83\xC4"),
    ("η", b"\x83\xC5"),
    ("θ", b"\x83\xC6"),
    ("ι", b"\x83\xC7"),
    ("κ", b"\x83\xC8"),
]


def load_stage26():
    spec = importlib.util.spec_from_file_location(
        "stage26hook",
        STAGE26
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


def build_wrapper(mod, cave_va):
    h = mod.load_stage24()

    ZERO = 0
    V0 = 2
    T0 = 8
    T1 = 9
    T2 = 10
    T3 = 11
    T9 = 25
    SP = 29
    RA = 31

    # bgezal is instruction 3, so RA becomes instruction 5.
    self_ref = cave_va + 5 * 4

    converter_delta = (
        ORIGINAL_CONVERTER
        - self_ref
    ) & 0xFFFFFFFF

    c_hi, c_lo = h.split_u32(
        converter_delta
    )

    words = []

    # 0..2: private stack, save caller RA and UTF16 output pointer.
    words.append(
        h.I(
            0x09,
            SP,
            SP,
            -32
        )
    )
    words.append(
        h.I(
            0x2B,
            SP,
            RA,
            28
        )
    )
    words.append(
        h.I(
            0x2B,
            SP,
            4,      # a0
            16
        )
    )

    # 3..4: get runtime self PC.
    words.append(
        h.I(
            0x01,
            ZERO,
            0x11,
            1
        )
    )
    words.append(0)

    # 5..9: call original UTF8 -> UTF16 converter.
    words.append(
        h.I(
            0x0F,
            ZERO,
            T9,
            c_hi
        )
    )
    words.append(
        h.I(
            0x0D,
            T9,
            T9,
            c_lo
        )
    )
    words.append(
        h.R(
            T9,
            RA,
            T9,
            0,
            0x21
        )
    )
    words.append(
        h.R(
            T9,
            ZERO,
            RA,
            0,
            0x09
        )
    )
    words.append(0)

    # Preserve converter return value.
    words.append(
        h.I(
            0x2B,
            SP,
            V0,
            12
        )
    )

    # t0 = UTF16 output buffer.
    words.append(
        h.I(
            0x23,
            SP,
            T0,
            16
        )
    )

    # loop = instruction 12
    loop_idx = len(words)

    # t1 = *t0
    words.append(
        h.I(
            0x25,   # lhu
            T0,
            T1,
            0
        )
    )

    # if zero -> done
    done_branch_idx = len(words)
    words.append(0)
    words.append(0)

    # t2 = codepoint - U+03B1
    words.append(
        h.I(
            0x09,
            T1,
            T2,
            -0x03B1
        )
    )

    # t3 = index < 10
    words.append(
        h.I(
            0x0B,
            T2,
            T3,
            10
        )
    )

    # if not custom -> next
    next_branch_idx = len(words)
    words.append(0)
    words.append(0)

    # first five?
    words.append(
        h.I(
            0x0B,
            T2,
            T3,
            5
        )
    )

    korean_branch_idx = len(words)
    words.append(0)
    words.append(0)

    # Japanese diagnostic: U+3041 + index.
    words.append(
        h.I(
            0x09,
            T2,
            T1,
            0x3041
        )
    )

    store_branch_idx = len(words)
    words.append(0)
    words.append(0)

    # Korean diagnostic: all five become U+AC00 "가".
    korean_idx = len(words)
    words.append(
        h.I(
            0x0D,   # ori
            ZERO,
            T1,
            0xAC00
        )
    )

    # store:
    store_idx = len(words)
    words.append(
        h.I(
            0x29,   # sh
            T0,
            T1,
            0
        )
    )

    # next:
    next_idx = len(words)
    words.append(
        h.I(
            0x09,
            T0,
            T0,
            2
        )
    )

    # unconditional branch to loop
    loop_branch_idx = len(words)
    words.append(0)
    words.append(0)

    # done:
    done_idx = len(words)

    words.append(
        h.I(
            0x23,
            SP,
            V0,
            12
        )
    )
    words.append(
        h.I(
            0x23,
            SP,
            RA,
            28
        )
    )
    words.append(
        h.I(
            0x09,
            SP,
            SP,
            32
        )
    )
    words.append(
        h.R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )
    words.append(0)

    # Fill branches now that labels are known.
    def va(index):
        return cave_va + index * 4

    words[done_branch_idx] = h.branch(
        0x04,
        T1,
        ZERO,
        va(done_branch_idx),
        va(done_idx)
    )

    words[next_branch_idx] = h.branch(
        0x04,
        T3,
        ZERO,
        va(next_branch_idx),
        va(next_idx)
    )

    words[korean_branch_idx] = h.branch(
        0x04,
        T3,
        ZERO,
        va(korean_branch_idx),
        va(korean_idx)
    )

    words[store_branch_idx] = h.branch(
        0x04,
        ZERO,
        ZERO,
        va(store_branch_idx),
        va(store_idx)
    )

    words[loop_branch_idx] = h.branch(
        0x04,
        ZERO,
        ZERO,
        va(loop_branch_idx),
        va(loop_idx)
    )

    blob = b"".join(
        struct.pack(
            "<I",
            word
        )
        for word in words
    )

    if len(blob) > CAVE_AVAILABLE:
        raise RuntimeError(
            f"Hook too large: "
            f"{len(blob)} > {CAVE_AVAILABLE}"
        )

    return blob, words


def make_probe_tbl():
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: "
            f"{SOURCE_TBL}"
        )

    P = [x[1] for x in PLACEHOLDERS]

    probes = [
        (
            "POST_UTF16_JAPANESE",
            "JMAP:ぁあぃいぅ",
            b"JMAP:" + b"".join(P[0:5]),
        ),
        (
            "POST_UTF16_KOREAN",
            "KMAP:가가가가가",
            b"KMAP:" + b"".join(P[5:10]),
        ),
        (
            "POST_UTF16_MIX",
            "MIX:ぁ가あ가",
            b"MIX:"
            + P[0] + P[5]
            + P[1] + P[6],
        ),
        (
            "JP_CONTROL",
            "JP:日本語確認",
            b"JP:"
            + "日本語確認".encode(
                "cp932"
            ),
        ),
        (
            "ASCII_CONTROL",
            "ASCII:OK",
            b"ASCII:OK",
        ),
    ]

    raw = SOURCE_TBL.read_bytes()
    lines = raw.splitlines(
        keepends=True
    )

    out = []
    report = []
    index = 0

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
            index < len(probes)
            and body.startswith(
                b"MSG =")
        ):
            parts = body.split(
                b",",
                2
            )

            if len(parts) == 3:
                name, expected, payload = (
                    probes[index]
                )

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
                        index + 1,
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

                index += 1
                continue

        out.append(line)

    if index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: "
            f"{index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT / "stage29_probe_map.tsv",
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
    print("Naruto PSP Stage 29")
    print("Post-conversion UTF16 buffer hook")
    print("=" * 72)

    mod = load_stage26()
    h = mod.load_stage24()
    s17 = h.load_stage17()
    elf = s17.ELF32(
        BOOT
    )

    original = bytearray(
        elf.data
    )

    actual_cave_off = elf.va_to_offset(
        CAVE_VA
    )

    if actual_cave_off != CAVE_OFF:
        raise RuntimeError(
            f"Cave VA/file mismatch: "
            f"{actual_cave_off} != "
            f"{CAVE_OFF}"
        )

    if any(
        original[
            CAVE_OFF:
            CAVE_OFF + CAVE_AVAILABLE
        ]
    ):
        raise RuntimeError(
            "Stage29 cave is not zero "
            "in original BOOT"
        )

    call_off = elf.va_to_offset(
        CALL_SITE
    )

    if call_off is None:
        raise RuntimeError(
            "Renderer converter callsite "
            "VA 변환 실패"
        )

    old_word = h.u32(
        original,
        call_off
    )

    expected_word = h.JAL(
        ORIGINAL_CONVERTER
    )

    if old_word != expected_word:
        raise RuntimeError(
            f"Callsite mismatch: "
            f"0x{old_word:08X} != "
            f"0x{expected_word:08X}"
        )

    relocs = h.relocation_sites(
        elf
    )

    if 4 not in relocs.get(
        CALL_SITE,
        []
    ):
        raise RuntimeError(
            "Renderer converter callsite에 "
            "R_MIPS_26 relocation 없음"
        )

    blob, words = build_wrapper(
        mod,
        CAVE_VA
    )

    patched = bytearray(
        original
    )

    patched[
        CAVE_OFF:
        CAVE_OFF + len(blob)
    ] = blob

    new_word = h.JAL(
        CAVE_VA
    )

    h.p32(
        patched,
        call_off,
        new_word
    )

    PATCHED_BOOT.write_bytes(
        patched
    )

    make_probe_tbl()

    hook_rows = []

    for i, word in enumerate(
        words
    ):
        hook_rows.append({
            "index": i,
            "va":
                f"0x{CAVE_VA + i*4:08X}",
            "word":
                f"0x{word:08X}",
        })

    write_tsv(
        OUT / "stage29_hook_words.tsv",
        hook_rows,
        [
            "index",
            "va",
            "word",
        ],
    )

    write_tsv(
        OUT / "stage29_hook_patch.tsv",
        [
            {
                "kind":
                    "JAL_WRAPPER",
                "va":
                    f"0x{CALL_SITE:08X}",
                "file_offset":
                    f"0x{call_off:X}",
                "old":
                    f"0x{old_word:08X}",
                "new":
                    f"0x{new_word:08X}",
            },
            {
                "kind":
                    "DATA_CAVE",
                "va":
                    f"0x{CAVE_VA:08X}",
                "file_offset":
                    f"0x{CAVE_OFF:X}",
                "old":
                    f"{len(blob)} zero bytes",
                "new":
                    f"{len(blob)} byte wrapper",
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

    (OUT / "stage29_summary.txt").write_text(
        "\n".join([
            "Naruto PSP Stage 29",
            "=" * 72,
            "",
            "Patch point:",
            "  renderer call 0x002AC2EC",
            "  original UTF8->UTF16 0x002ACCF4",
            "",
            "Strategy:",
            "  1. call original converter unchanged",
            "  2. scan its actual UTF16 output buffer",
            "  3. replace U+03B1..U+03B5 -> U+3041..U+3045",
            "  4. replace U+03B6..U+03BA -> U+AC00",
            "",
            f"Code cave: 0x{CAVE_VA:08X}",
            f"Hook size: {len(blob)} bytes",
            f"Original BOOT SHA256: {sha256(original)}",
            f"Patched BOOT SHA256:  {sha256(patched)}",
            "",
            "Expected:",
            "  JMAP:ぁあぃいぅ",
            "  KMAP:가가가가가",
            "  MIX:ぁ가あ가",
        ]),
        encoding="utf-8"
    )

    print()
    print("Renderer callsite:",
          f"0x{CALL_SITE:08X}")
    print("Original converter:",
          f"0x{ORIGINAL_CONVERTER:08X}")
    print("Code cave:",
          f"0x{CAVE_VA:08X}")
    print("Hook bytes:",
          len(blob))
    print(PATCHED_BOOT)
    print(PATCHED_TBL)

    print()
    print("=" * 72)
    print("STAGE29 HOOK READY")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
