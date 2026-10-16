from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage20"

OUT.mkdir(parents=True, exist_ok=True)


BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

SOURCE_TBL = (
    BASE / "analysis"
    / "stage14"
    / "test_patch"
    / "event000_original.tbl"
)

S17 = (
    BASE / "analysis"
    / "stage17"
    / "stage17_font_engine.py"
)

PATCHED_BOOT = (
    OUT / "BOOT_stage20_patched.BIN"
)

PATCHED_TBL = (
    OUT / "event000_stage20.tbl"
)


KNOWN_FORWARD = {
    0x2121: 0x3000,  # ideographic space
    0x2122: 0x3001,  # 、
    0x2123: 0x3002,  # 。
    0x2421: 0x3041,  # ぁ
    0x2422: 0x3042,  # あ
    0x2521: 0x30A1,  # ァ
    0x2522: 0x30A2,  # ア
}


PROBES = [
    "KMAP:한글테스트",
    "KMAP:가나다라마바사",
    "KMAP:아자차카타파하",
    "KMAP:한국어　출력성공",
    "KMAP:똠방각하",
    "JP:日本語確認",
]


TARGET_CALLS = {
    0x002ACCF4: "UTF8_TO_UTF16",
    0x002ACED4: "SJIS_TO_UTF8",
    0x002AD284: "SET_CONVERSION_TABLES",
}


def u16(data, off):
    return struct.unpack_from(
        "<H", data, off
    )[0]


def u32(data, off):
    return struct.unpack_from(
        "<I", data, off
    )[0]


def p16(data, off, value):
    struct.pack_into(
        "<H",
        data,
        off,
        value
    )


def sha256(data):
    return hashlib.sha256(
        data
    ).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            b = f.read(
                1024 * 1024
            )

            if not b:
                break

            h.update(b)

    return h.hexdigest()


def write_tsv(
    path,
    rows,
    fields
):
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


def load_stage17():
    spec = (
        importlib.util
        .spec_from_file_location(
            "stage17",
            S17
        )
    )

    mod = (
        importlib.util
        .module_from_spec(spec)
    )

    spec.loader.exec_module(mod)

    return mod


def file_to_va(elf, off):
    for sec in elf.sections:
        if (
            sec["size"]
            and sec["offset"]
            <= off
            < sec["offset"] + sec["size"]
        ):
            return (
                sec["addr"]
                + off
                - sec["offset"]
            )

    return None


def find_all(data, needle):
    p = 0

    while True:
        p = data.find(
            needle,
            p
        )

        if p < 0:
            break

        yield p
        p += 1


# ============================================================
# Find 65536-entry JIS -> Unicode table.
# ============================================================

def find_forward_tables(
    elf
):
    data = elf.data
    sec = elf.section(".data")

    if sec is None:
        raise RuntimeError(
            ".data section 없음"
        )

    sec_start = sec["offset"]
    sec_end = (
        sec["offset"]
        + sec["size"]
    )

    marker_index = 0x2422
    marker_value = 0x3042

    marker = struct.pack(
        "<H",
        marker_value
    )

    results = []

    for hit in find_all(
        data[
            sec_start:sec_end
        ],
        marker
    ):
        hit += sec_start

        base = (
            hit
            - marker_index * 2
        )

        if base < sec_start:
            continue

        if (
            base + 0x20000
            > sec_end
        ):
            continue

        good = True

        for idx, uni in (
            KNOWN_FORWARD.items()
        ):
            if (
                u16(
                    data,
                    base + idx * 2
                )
                != uni
            ):
                good = False
                break

        if good:
            va = file_to_va(
                elf,
                base
            )

            results.append({
                "file_offset":
                    base,

                "file_offset_hex":
                    f"0x{base:X}",

                "va":
                    va,

                "va_hex":
                    (
                        f"0x{va:08X}"
                        if va is not None
                        else ""
                    ),
            })

    return results


# ============================================================
# Reverse Unicode -> JIS table.
# ============================================================

def find_reverse_tables(
    elf
):
    data = elf.data
    sec = elf.section(".data")

    sec_start = sec["offset"]
    sec_end = (
        sec["offset"]
        + sec["size"]
    )

    marker_unicode = 0x3042
    marker_jis = 0x2422

    marker = struct.pack(
        "<H",
        marker_jis
    )

    results = []

    for hit in find_all(
        data[
            sec_start:sec_end
        ],
        marker
    ):
        hit += sec_start

        base = (
            hit
            - marker_unicode * 2
        )

        if base < sec_start:
            continue

        if (
            base + 0x20000
            > sec_end
        ):
            continue

        good = True

        for jis, uni in (
            KNOWN_FORWARD.items()
        ):
            if (
                u16(
                    data,
                    base + uni * 2
                )
                != jis
            ):
                good = False
                break

        if good:
            va = file_to_va(
                elf,
                base
            )

            results.append({
                "file_offset":
                    base,

                "file_offset_hex":
                    f"0x{base:X}",

                "va":
                    va,

                "va_hex":
                    (
                        f"0x{va:08X}"
                        if va is not None
                        else ""
                    ),
            })

    return results


# ============================================================
# Standard Shift-JIS <-> JIS X 0208 conversion.
# Only plane-1 style pairs are used for custom Hangul.
# ============================================================

def sjis_to_jis(
    lead,
    trail
):
    if 0x81 <= lead <= 0x9F:
        row = (
            (lead - 0x81) * 2
            + 0x21
        )

    elif 0xE0 <= lead <= 0xEF:
        row = (
            (lead - 0xE0) * 2
            + 0x5F
        )

    else:
        return None

    if 0x40 <= trail <= 0x7E:
        pass

    elif 0x80 <= trail <= 0xFC:
        pass

    else:
        return None

    if trail >= 0x9F:
        row += 1
        cell = (
            trail - 0x7E
        )

    else:
        t = trail

        if t >= 0x80:
            t -= 1

        cell = (
            t - 0x1F
        )

    if not (
        0x21 <= row <= 0x7E
        and
        0x21 <= cell <= 0x7E
    ):
        return None

    return (
        (row << 8)
        | cell
    )


def enumerate_free_slots(
    table
):
    rows = []

    leads = (
        list(
            range(0x81, 0xA0)
        )
        +
        list(
            range(0xE0, 0xF0)
        )
    )

    trails = (
        list(
            range(0x40, 0x7F)
        )
        +
        list(
            range(0x80, 0xFD)
        )
    )

    for lead in leads:
        for trail in trails:
            jis = sjis_to_jis(
                lead,
                trail
            )

            if jis is None:
                continue

            value = u16(
                table,
                jis * 2
            )

            if value != 0:
                continue

            pair = bytes(
                [lead, trail]
            )

            # Prefer codes that Windows CP932 itself
            # regards as unassigned.
            try:
                pair.decode(
                    "cp932",
                    errors="strict"
                )

                continue

            except UnicodeDecodeError:
                pass

            rows.append({
                "lead":
                    lead,

                "trail":
                    trail,

                "sjis_hex":
                    pair.hex(" "),

                "jis":
                    jis,

                "jis_hex":
                    f"0x{jis:04X}",
            })

    return rows


# ============================================================
# Direct JAL callsite report.
# ============================================================

def scan_target_calls(
    elf
):
    rows = []
    contexts = []

    for sec in elf.sections:
        if not (
            sec["flags"] & 0x4
        ):
            continue

        start = sec["offset"]
        end = (
            sec["offset"]
            + sec["size"]
        )

        p = start

        while p + 4 <= end:
            ins = u32(
                elf.data,
                p
            )

            if (
                (ins >> 26)
                & 0x3F
            ) == 3:
                pc = (
                    sec["addr"]
                    + p
                    - sec["offset"]
                )

                target = (
                    ((pc + 4)
                     & 0xF0000000)
                    |
                    (
                        (ins & 0x03FFFFFF)
                        << 2
                    )
                )

                if target in TARGET_CALLS:
                    rows.append({
                        "function":
                            TARGET_CALLS[
                                target
                            ],

                        "target":
                            f"0x{target:08X}",

                        "call_va":
                            f"0x{pc:08X}",

                        "file_offset":
                            f"0x{p:X}",
                    })

                    cstart = max(
                        start,
                        p - 24 * 4
                    )

                    cend = min(
                        end,
                        p + 14 * 4
                    )

                    lines = [
                        "=" * 80,
                        (
                            f"{TARGET_CALLS[target]} "
                            f"call at 0x{pc:08X}"
                        ),
                        "=" * 80,
                    ]

                    q = cstart

                    while q + 4 <= cend:
                        qpc = (
                            sec["addr"]
                            + q
                            - sec["offset"]
                        )

                        qins = u32(
                            elf.data,
                            q
                        )

                        mark = (
                            ">>>"
                            if q == p
                            else "   "
                        )

                        lines.append(
                            f"{mark} "
                            f"0x{qpc:08X}: "
                            f"{qins:08X}  "
                            f"{TARGET_CALLS.get(0,'')}"
                        )

                        q += 4

                    contexts.append(
                        "\n".join(lines)
                    )

            p += 4

    return rows, contexts


# ============================================================
# Custom text encoder.
# ============================================================

def unique_hangul(
    texts
):
    out = []

    for text in texts:
        for ch in text:
            n = ord(ch)

            if (
                0xAC00
                <= n
                <= 0xD7A3
                and ch not in out
            ):
                out.append(ch)

    return out


def encode_probe(
    text,
    mapping
):
    out = bytearray()

    for ch in text:
        if ch in mapping:
            out.extend(
                mapping[ch]["bytes"]
            )

        elif ch == "\u3000":
            # Original CP932 full-width space.
            out.extend(
                b"\x81\x40"
            )

        elif ord(ch) < 0x80:
            if ch == " ":
                # ASCII 0x20 terminates dialogue in this game.
                out.extend(
                    b"\x81\x40"
                )
            else:
                out.append(
                    ord(ch)
                )

        else:
            out.extend(
                ch.encode(
                    "cp932"
                )
            )

    return bytes(out)


def patch_first_messages(
    source,
    probes,
    mapping
):
    lines = source.splitlines(
        keepends=True
    )

    result = []
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
                b"MSG ="
            )
        ):
            parts = body.split(
                b",",
                2
            )

            if len(parts) == 3:
                encoded = encode_probe(
                    probes[index],
                    mapping
                )

                result.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + encoded
                    + newline
                )

                report.append({
                    "probe":
                        index + 1,

                    "line":
                        line_no,

                    "msg_id":
                        parts[1].decode(
                            "ascii",
                            errors="replace"
                        ),

                    "text":
                        probes[index],

                    "encoded_hex":
                        encoded.hex(" "),
                })

                index += 1
                continue

        result.append(line)

    if index != len(probes):
        raise RuntimeError(
            f"MSG 행 부족: "
            f"{index}/{len(probes)}"
        )

    return (
        b"".join(result),
        report
    )


# ============================================================
# main
# ============================================================

def main():
    print("=" * 72)
    print("Naruto PSP Stage 20")
    print("Static JIS <-> Unicode table test")
    print("=" * 72)

    s17 = load_stage17()
    elf = s17.ELF32(BOOT)

    print(
        "BOOT SHA256:",
        sha256_file(BOOT)
    )

    forward = find_forward_tables(
        elf
    )

    reverse = find_reverse_tables(
        elf
    )

    print(
        "Forward table candidates:",
        len(forward)
    )

    print(
        "Reverse table candidates:",
        len(reverse)
    )

    table_report = []

    for x in forward:
        table_report.append({
            "direction":
                "JIS_TO_UNICODE",

            **x,
        })

    for x in reverse:
        table_report.append({
            "direction":
                "UNICODE_TO_JIS",

            **x,
        })

    write_tsv(
        OUT / "conversion_table_candidates.tsv",
        table_report,
        [
            "direction",
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
        ]
    )

    calls, contexts = (
        scan_target_calls(
            elf
        )
    )

    write_tsv(
        OUT / "converter_global_callsites.tsv",
        calls,
        [
            "function",
            "target",
            "call_va",
            "file_offset",
        ]
    )

    (
        OUT / "converter_global_contexts.txt"
    ).write_text(
        "\n\n".join(contexts),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # If no unique static table, stop as analysis-only.
    # --------------------------------------------------------

    if len(forward) != 1:
        (
            OUT / "stage20_status.txt"
        ).write_text(
            "ANALYSIS_ONLY\n",
            encoding="ascii"
        )

        (
            OUT / "stage20_summary.txt"
        ).write_text(
            "\n".join([
                "Naruto PSP Stage 20",
                "=" * 72,
                "",
                (
                    "Unique static JIS->Unicode "
                    f"table not found: {len(forward)} candidates"
                ),
                (
                    f"Reverse candidates: "
                    f"{len(reverse)}"
                ),
                "",
                "No executable or TBL patch generated.",
                "Use converter_global_contexts.txt for next analysis.",
            ]),
            encoding="utf-8"
        )

        print()
        print(
            "Static forward table not uniquely found."
        )

        print(
            "Stage20 finished in ANALYSIS_ONLY mode."
        )

        return

    # --------------------------------------------------------
    # Analyze free slots.
    # --------------------------------------------------------

    fwd_off = forward[0][
        "file_offset"
    ]

    fwd_table = elf.data[
        fwd_off:
        fwd_off + 0x20000
    ]

    free = enumerate_free_slots(
        fwd_table
    )

    print(
        "Unused CP932/JIS slots:",
        len(free)
    )

    write_tsv(
        OUT / "unused_sjis_slots.tsv",
        free,
        [
            "lead",
            "trail",
            "sjis_hex",
            "jis",
            "jis_hex",
        ]
    )

    chars = unique_hangul(
        PROBES
    )

    if len(free) < len(chars):
        raise RuntimeError(
            f"미사용 슬롯 부족: "
            f"{len(free)} < "
            f"{len(chars)}"
        )

    patched = bytearray(
        elf.data
    )

    mapping = {}
    mapping_rows = []

    reverse_off = (
        reverse[0]["file_offset"]
        if len(reverse) == 1
        else None
    )

    for ch, slot in zip(
        chars,
        free
    ):
        cp = ord(ch)
        jis = slot["jis"]

        foff = (
            fwd_off
            + jis * 2
        )

        old = u16(
            patched,
            foff
        )

        if old != 0:
            raise RuntimeError(
                "Selected forward slot "
                "was not empty"
            )

        p16(
            patched,
            foff,
            cp
        )

        reverse_old = ""

        if reverse_off is not None:
            roff = (
                reverse_off
                + cp * 2
            )

            reverse_old = u16(
                patched,
                roff
            )

            if reverse_old == 0:
                p16(
                    patched,
                    roff,
                    jis
                )

        pair = bytes([
            slot["lead"],
            slot["trail"],
        ])

        mapping[ch] = {
            "bytes":
                pair,

            "jis":
                jis,
        }

        mapping_rows.append({
            "char":
                ch,

            "unicode":
                f"U+{cp:04X}",

            "sjis_hex":
                pair.hex(" "),

            "jis_hex":
                f"0x{jis:04X}",

            "forward_file_offset":
                f"0x{foff:X}",

            "forward_old":
                f"0x{old:04X}",

            "forward_new":
                f"0x{cp:04X}",

            "reverse_old":
                (
                    f"0x{reverse_old:04X}"
                    if reverse_old != ""
                    else ""
                ),

            "reverse_patched":
                (
                    reverse_off is not None
                    and reverse_old == 0
                ),
        })

    PATCHED_BOOT.write_bytes(
        patched
    )

    write_tsv(
        OUT / "hangul_custom_mapping.tsv",
        mapping_rows,
        [
            "char",
            "unicode",
            "sjis_hex",
            "jis_hex",
            "forward_file_offset",
            "forward_old",
            "forward_new",
            "reverse_old",
            "reverse_patched",
        ]
    )

    # --------------------------------------------------------
    # Verify executable diff only occurs at expected table bytes.
    # --------------------------------------------------------

    source_boot = elf.data

    diff_positions = [
        i
        for i, (a, b) in enumerate(
            zip(
                source_boot,
                patched
            )
        )
        if a != b
    ]

    (
        OUT / "boot_diff_summary.txt"
    ).write_text(
        "\n".join([
            f"Original SHA256: {sha256(source_boot)}",
            f"Patched  SHA256: {sha256(patched)}",
            f"Changed byte positions: {len(diff_positions)}",
            (
                "First changes: "
                + ", ".join(
                    f"0x{x:X}"
                    for x in diff_positions[:100]
                )
            ),
        ]),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Build probe TBL.
    # --------------------------------------------------------

    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 TBL 없음: "
            f"{SOURCE_TBL}"
        )

    tbl, probe_report = (
        patch_first_messages(
            SOURCE_TBL.read_bytes(),
            PROBES,
            mapping
        )
    )

    PATCHED_TBL.write_bytes(
        tbl
    )

    write_tsv(
        OUT / "stage20_probe_map.tsv",
        probe_report,
        [
            "probe",
            "line",
            "msg_id",
            "text",
            "encoded_hex",
        ]
    )

    # --------------------------------------------------------
    # Self-simulate custom mappings.
    # --------------------------------------------------------

    sim = []

    for row in mapping_rows:
        jis = int(
            row["jis_hex"],
            16
        )

        got = u16(
            patched,
            fwd_off
            + jis * 2
        )

        expected = int(
            row["unicode"][2:],
            16
        )

        sim.append({
            "char":
                row["char"],

            "jis_hex":
                row["jis_hex"],

            "expected_unicode":
                row["unicode"],

            "actual_unicode":
                f"U+{got:04X}",

            "ok":
                got == expected,
        })

        if got != expected:
            raise RuntimeError(
                "Mapping verification failed"
            )

    write_tsv(
        OUT / "mapping_validation.tsv",
        sim,
        [
            "char",
            "jis_hex",
            "expected_unicode",
            "actual_unicode",
            "ok",
        ]
    )

    (
        OUT / "stage20_status.txt"
    ).write_text(
        "PATCHABLE\n",
        encoding="ascii"
    )

    summary = (
        OUT / "stage20_summary.txt"
    )

    summary.write_text(
        "\n".join([
            "Naruto PSP Stage 20",
            "=" * 72,
            "",
            "Static JIS->Unicode table: FOUND",
            (
                f"  file={forward[0]['file_offset_hex']} "
                f"VA={forward[0]['va_hex']}"
            ),
            (
                "Static Unicode->JIS table: "
                + (
                    "FOUND"
                    if len(reverse) == 1
                    else f"{len(reverse)} candidates"
                )
            ),
            "",
            (
                f"Unused CP932/JIS slots: "
                f"{len(free)}"
            ),
            (
                f"Hangul test mappings: "
                f"{len(mapping_rows)}"
            ),
            "",
            f"Patched BOOT: {PATCHED_BOOT}",
            f"Patched TBL: {PATCHED_TBL}",
            "",
            "STATUS: PATCHABLE",
        ]),
        encoding="utf-8"
    )

    print()
    print("=" * 72)
    print("STAGE 20 TABLE PATCH READY")
    print("=" * 72)

    print(
        "Forward table:",
        forward[0][
            "file_offset_hex"
        ],
        forward[0][
            "va_hex"
        ]
    )

    print(
        "Free slots:",
        len(free)
    )

    print(
        "Mapped Hangul:",
        len(mapping_rows)
    )

    print(
        "Patched BOOT:",
        PATCHED_BOOT
    )

    print(
        "Patched TBL:",
        PATCHED_TBL
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
