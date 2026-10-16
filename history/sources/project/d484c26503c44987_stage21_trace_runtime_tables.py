from pathlib import Path
import csv
import hashlib
import importlib.util
import mmap
import os
import shutil
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage21"
CAND = OUT / "candidates"

OUT.mkdir(parents=True, exist_ok=True)

if CAND.exists():
    shutil.rmtree(CAND)

CAND.mkdir(parents=True)


S17 = (
    BASE / "analysis"
    / "stage17"
    / "stage17_font_engine.py"
)

KR_BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)

KR_EBOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "EBOOT.BIN"
)


SETTER = 0x002AD284

GLOBALS = {
    0x004BD5E0: "DEFAULT_CHAR",
    0x004BD5E4: "UTF8_FALLBACK",
    0x004BD5E8: "UTF16_FALLBACK",
    0x004BD5EC: "JIS_TO_UNICODE_PTR",
    0x004BD5F0: "UNICODE_TO_JIS_PTR",
}


# Confirmed using the game's own 0x002AC9E4 decoder.
KNOWN_FORWARD = {
    0x2121: 0x3000,  # 　
    0x2122: 0x3001,  # 、
    0x2123: 0x3002,  # 。
    0x2421: 0x3041,  # ぁ
    0x2422: 0x3042,  # あ
    0x2521: 0x30A1,  # ァ
    0x2522: 0x30A2,  # ア
    0x334E: 0x78BA,  # 確
    0x386C: 0x8A9E,  # 語
    0x467C: 0x65E5,  # 日
    0x4727: 0x8A8D,  # 認
    0x4B5C: 0x672C,  # 本
}


SKIP_SUFFIX = {
    ".iso",
    ".zip",
    ".7z",
    ".rar",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".mp4",
    ".log",
    ".tsv",
    ".csv",
    ".txt",
    ".json",
    ".py",
    ".ps1",
}


REG = [
    "zero","at","v0","v1",
    "a0","a1","a2","a3",
    "t0","t1","t2","t3",
    "t4","t5","t6","t7",
    "s0","s1","s2","s3",
    "s4","s5","s6","s7",
    "t8","t9","k0","k1",
    "gp","sp","fp","ra"
]


def u16(data, off):
    return struct.unpack_from(
        "<H",
        data,
        off
    )[0]


def u32(data, off):
    return struct.unpack_from(
        "<I",
        data,
        off
    )[0]


def sign16(v):
    return (
        v - 0x10000
        if v & 0x8000
        else v
    )


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


def load_stage17():

    if not S17.exists():
        raise RuntimeError(
            f"Stage17 script 없음: {S17}"
        )

    spec = importlib.util.spec_from_file_location(
        "stage17",
        S17
    )

    mod = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(mod)

    return mod


def section_for_offset(
    elf,
    off
):
    for sec in elf.sections:
        if (
            sec["size"]
            and sec["offset"] <= off
            < sec["offset"] + sec["size"]
        ):
            return sec

    return None


def offset_to_va(
    elf,
    off
):
    sec = section_for_offset(
        elf,
        off
    )

    if sec is None:
        return None

    if sec["addr"] == 0:
        return None

    return (
        sec["addr"]
        + off
        - sec["offset"]
    )


# ============================================================
# Raw pointer references to 0x002AD284
# ============================================================

def find_pointer_words(
    elf
):
    needle = struct.pack(
        "<I",
        SETTER
    )

    rows = []
    contexts = []

    data = elf.data
    pos = 0

    while True:
        pos = data.find(
            needle,
            pos
        )

        if pos < 0:
            break

        sec = section_for_offset(
            elf,
            pos
        )

        va = offset_to_va(
            elf,
            pos
        )

        rows.append({
            "file_offset":
                pos,

            "file_offset_hex":
                f"0x{pos:X}",

            "va":
                (
                    va
                    if va is not None
                    else ""
                ),

            "va_hex":
                (
                    f"0x{va:08X}"
                    if va is not None
                    else ""
                ),

            "section":
                (
                    sec["name"]
                    if sec
                    else ""
                ),
        })

        start = max(
            0,
            pos - 0x80
        )

        end = min(
            len(data),
            pos + 0x84
        )

        block = data[
            start:end
        ]

        lines = [
            "=" * 78,
            (
                f"SETTER POINTER occurrence "
                f"file=0x{pos:X} "
                f"VA="
                + (
                    f"0x{va:08X}"
                    if va is not None
                    else "?"
                )
            ),
            (
                f"section="
                f"{sec['name'] if sec else '?'}"
            ),
            "=" * 78,
        ]

        for i in range(
            0,
            len(block),
            16
        ):
            chunk = block[
                i:i+16
            ]

            lines.append(
                f"0x{start+i:08X}: "
                + chunk.hex(" ")
            )

        contexts.append(
            "\n".join(lines)
        )

        pos += 1

    return rows, contexts


# ============================================================
# Scan executable for absolute-address construction/access.
# ============================================================

MEM_OPS = {
    0x20: "lb",
    0x21: "lh",
    0x23: "lw",
    0x24: "lbu",
    0x25: "lhu",
    0x28: "sb",
    0x29: "sh",
    0x2B: "sw",
}


def executable_instructions(
    elf
):
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

            pc = (
                sec["addr"]
                + p
                - sec["offset"]
            )

            yield (
                sec,
                p,
                pc,
                u32(
                    elf.data,
                    p
                )
            )

            p += 4


def scan_global_accesses(
    elf
):
    ins = list(
        executable_instructions(
            elf
        )
    )

    rows = []

    for i, (
        sec,
        off,
        pc,
        word
    ) in enumerate(ins):

        op = (
            word >> 26
        ) & 0x3F

        rt = (
            word >> 16
        ) & 31

        imm = (
            word & 0xFFFF
        )

        if op != 0x0F:
            continue

        high = (
            imm << 16
        )

        # Follow the register for a short straight-line window.
        for j in range(
            i + 1,
            min(
                i + 9,
                len(ins)
            )
        ):
            sec2, off2, pc2, w2 = (
                ins[j]
            )

            if sec2["index"] != sec["index"]:
                break

            op2 = (
                w2 >> 26
            ) & 0x3F

            rs2 = (
                w2 >> 21
            ) & 31

            rt2 = (
                w2 >> 16
            ) & 31

            imm2 = (
                w2 & 0xFFFF
            )

            # Register overwritten by another LUI.
            if (
                op2 == 0x0F
                and rt2 == rt
            ):
                break

            # lui r,H ; load/store X,lo(r)
            if (
                op2 in MEM_OPS
                and rs2 == rt
            ):
                addr = (
                    high
                    + sign16(
                        imm2
                    )
                ) & 0xFFFFFFFF

                if addr in GLOBALS:

                    rows.append({
                        "global":
                            GLOBALS[addr],

                        "address":
                            f"0x{addr:08X}",

                        "operation":
                            MEM_OPS[op2],

                        "lui_va":
                            f"0x{pc:08X}",

                        "access_va":
                            f"0x{pc2:08X}",

                        "access_file_offset":
                            f"0x{off2:X}",

                        "base_register":
                            REG[rt],

                        "value_register":
                            REG[rt2],

                        "section":
                            sec["name"],
                    })

    return rows


# ============================================================
# Generic references to addresses of pointer-table occurrences.
# ============================================================

def find_address_uses(
    elf,
    targets
):
    if not targets:
        return []

    target_set = set(
        targets
    )

    rows = []

    instructions = list(
        executable_instructions(
            elf
        )
    )

    for i, (
        sec,
        off,
        pc,
        word
    ) in enumerate(
        instructions
    ):
        op = (
            word >> 26
        ) & 0x3F

        rt = (
            word >> 16
        ) & 31

        if op != 0x0F:
            continue

        high = (
            (word & 0xFFFF)
            << 16
        )

        for j in range(
            i + 1,
            min(
                i + 9,
                len(instructions)
            )
        ):
            (
                sec2,
                off2,
                pc2,
                w2
            ) = instructions[j]

            if sec2["index"] != sec["index"]:
                break

            op2 = (
                w2 >> 26
            ) & 0x3F

            rs2 = (
                w2 >> 21
            ) & 31

            rt2 = (
                w2 >> 16
            ) & 31

            imm2 = (
                w2 & 0xFFFF
            )

            if (
                op2 == 0x0F
                and rt2 == rt
            ):
                break

            # addiu same register
            if (
                op2 == 0x09
                and rs2 == rt
                and rt2 == rt
            ):
                addr = (
                    high
                    + sign16(
                        imm2
                    )
                ) & 0xFFFFFFFF

                if addr in target_set:
                    rows.append({
                        "target":
                            f"0x{addr:08X}",

                        "kind":
                            "lui+addiu",

                        "start_va":
                            f"0x{pc:08X}",

                        "use_va":
                            f"0x{pc2:08X}",

                        "use_file_offset":
                            f"0x{off2:X}",

                        "register":
                            REG[rt],
                    })

            # ori same register
            if (
                op2 == 0x0D
                and rs2 == rt
                and rt2 == rt
            ):
                addr = (
                    high
                    | imm2
                )

                if addr in target_set:
                    rows.append({
                        "target":
                            f"0x{addr:08X}",

                        "kind":
                            "lui+ori",

                        "start_va":
                            f"0x{pc:08X}",

                        "use_va":
                            f"0x{pc2:08X}",

                        "use_file_offset":
                            f"0x{off2:X}",

                        "register":
                            REG[rt],
                    })

            # memory reference through high/low pair
            if (
                op2 in MEM_OPS
                and rs2 == rt
            ):
                addr = (
                    high
                    + sign16(
                        imm2
                    )
                ) & 0xFFFFFFFF

                if addr in target_set:
                    rows.append({
                        "target":
                            f"0x{addr:08X}",

                        "kind":
                            (
                                "memory:"
                                + MEM_OPS[op2]
                            ),

                        "start_va":
                            f"0x{pc:08X}",

                        "use_va":
                            f"0x{pc2:08X}",

                        "use_file_offset":
                            f"0x{off2:X}",

                        "register":
                            REG[rt],
                    })

    return rows


# ============================================================
# JALR contexts
# ============================================================

def scan_jalr(
    elf
):
    rows = []
    contexts = []

    instructions = list(
        executable_instructions(
            elf
        )
    )

    by_off = {
        x[1]: n
        for n, x in enumerate(
            instructions
        )
    }

    for n, (
        sec,
        off,
        pc,
        word
    ) in enumerate(
        instructions
    ):
        if (
            (word >> 26)
            != 0
        ):
            continue

        fn = word & 0x3F

        if fn != 0x09:
            continue

        rs = (
            word >> 21
        ) & 31

        rd = (
            word >> 11
        ) & 31

        rows.append({
            "va":
                f"0x{pc:08X}",

            "file_offset":
                f"0x{off:X}",

            "source_register":
                REG[rs],

            "link_register":
                REG[rd],

            "section":
                sec["name"],
        })

        start_n = max(
            0,
            n - 20
        )

        end_n = min(
            len(instructions),
            n + 10
        )

        lines = [
            "=" * 78,
            (
                f"JALR at 0x{pc:08X} "
                f"via {REG[rs]}"
            ),
            "=" * 78,
        ]

        for k in range(
            start_n,
            end_n
        ):
            (
                s,
                o,
                v,
                w
            ) = instructions[k]

            if s["index"] != sec["index"]:
                continue

            mark = (
                ">>>"
                if k == n
                else "   "
            )

            lines.append(
                f"{mark} "
                f"0x{v:08X}: "
                f"{w:08X}"
            )

        contexts.append(
            "\n".join(lines)
        )

    return rows, contexts


# ============================================================
# Sparse conversion-table verification
# ============================================================

def verify_forward(
    data,
    base
):
    if base < 0:
        return False

    max_index = max(
        KNOWN_FORWARD
    )

    if (
        base
        + max_index * 2
        + 2
        > len(data)
    ):
        return False

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
            return False

    return True


def verify_reverse(
    data,
    base
):
    if base < 0:
        return False

    max_uni = max(
        KNOWN_FORWARD.values()
    )

    if (
        base
        + max_uni * 2
        + 2
        > len(data)
    ):
        return False

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
            return False

    return True


def scan_mapping_file(
    path
):
    results = []

    size = path.stat().st_size

    if size < 0x20000:
        return results

    try:
        with path.open("rb") as f:
            mm = mmap.mmap(
                f.fileno(),
                0,
                access=mmap.ACCESS_READ
            )

            # Forward anchor:
            # table[0x2121] = U+3000
            needle = b"\x00\x30"

            pos = 0
            hits = 0

            while True:
                pos = mm.find(
                    needle,
                    pos
                )

                if pos < 0:
                    break

                hits += 1

                if hits > 200000:
                    break

                base = (
                    pos
                    - 0x2121 * 2
                )

                if verify_forward(
                    mm,
                    base
                ):
                    results.append({
                        "direction":
                            "JIS_TO_UNICODE",

                        "file":
                            str(path),

                        "file_size":
                            size,

                        "table_offset":
                            base,

                        "table_offset_hex":
                            f"0x{base:X}",
                    })

                pos += 2

            # Reverse anchor:
            # table[U+3000] = 0x2121
            needle = struct.pack(
                "<H",
                0x2121
            )

            pos = 0
            hits = 0

            while True:
                pos = mm.find(
                    needle,
                    pos
                )

                if pos < 0:
                    break

                hits += 1

                if hits > 200000:
                    break

                base = (
                    pos
                    - 0x3000 * 2
                )

                if verify_reverse(
                    mm,
                    base
                ):
                    results.append({
                        "direction":
                            "UNICODE_TO_JIS",

                        "file":
                            str(path),

                        "file_size":
                            size,

                        "table_offset":
                            base,

                        "table_offset_hex":
                            f"0x{base:X}",
                    })

                pos += 2

            mm.close()

    except Exception:
        return results

    # de-dupe
    seen = set()
    unique = []

    for r in results:
        key = (
            r["direction"],
            r["table_offset"]
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(r)

    return unique


def collect_scan_files():

    roots = [
        BASE / "kr_extracted",
        BASE / "analysis" / "stage9",
        BASE / "analysis" / "stage10",
        BASE / "analysis" / "stage11",
    ]

    paths = []
    seen = set()

    for root in roots:

        if not root.exists():
            continue

        for path in root.rglob("*"):

            if not path.is_file():
                continue

            try:
                rp = str(
                    path.resolve()
                ).lower()
            except Exception:
                rp = str(path).lower()

            if rp in seen:
                continue

            seen.add(rp)

            if (
                path.suffix.lower()
                in SKIP_SUFFIX
            ):
                continue

            try:
                size = path.stat().st_size
            except OSError:
                continue

            if size < 0x20000:
                continue

            # Ordinary resources only. DAT is handled separately.
            if (
                size
                > 96 * 1024 * 1024
                and path.name.lower()
                != "naruto.dat"
            ):
                continue

            paths.append(path)

    # Explicitly include BOOT/EBOOT.
    for path in (
        KR_BOOT,
        KR_EBOOT
    ):
        if path.exists():
            rp = str(
                path.resolve()
            ).lower()

            if rp not in seen:
                paths.append(path)
                seen.add(rp)

    return paths


# ============================================================
# Candidate extraction
# ============================================================

def extract_candidates(
    candidates
):
    rows = []

    for n, r in enumerate(
        candidates,
        1
    ):
        path = Path(
            r["file"]
        )

        base = r[
            "table_offset"
        ]

        try:
            with path.open("rb") as f:
                f.seek(base)

                block = f.read(
                    0x20000
                )

            if len(block) < 0x20000:
                continue

            out = (
                CAND
                / (
                    f"{n:03d}__"
                    f"{r['direction']}__"
                    f"{path.name}.bin"
                )
            )

            out.write_bytes(block)

            rows.append({
                **r,

                "extracted":
                    str(out),

                "sha256":
                    hashlib.sha256(
                        block
                    ).hexdigest(),
            })

        except Exception:
            continue

    return rows


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 72)
    print("Naruto PSP Stage 21")
    print("Runtime conversion-table source trace")
    print("=" * 72)

    s17 = load_stage17()

    elf = s17.ELF32(
        KR_BOOT
    )

    print(
        "KR BOOT SHA256:",
        sha256_file(
            KR_BOOT
        )
    )

    # --------------------------------------------------------
    # BSS/global facts
    # --------------------------------------------------------

    program_end = max(
        (
            p["vaddr"]
            + p["memsz"]
        )
        for p in elf.programs
        if p["type"] == 1
    )

    data_end = max(
        (
            p["vaddr"]
            + p["filesz"]
        )
        for p in elf.programs
        if p["type"] == 1
    )

    print(
        f"PT_LOAD file end : "
        f"0x{data_end:08X}"
    )

    print(
        f"PT_LOAD memory end: "
        f"0x{program_end:08X}"
    )

    print(
        f"Forward global: "
        f"0x004BD5EC"
    )

    print(
        f"Reverse global: "
        f"0x004BD5F0"
    )

    # --------------------------------------------------------
    # Setter as raw function pointer
    # --------------------------------------------------------

    pointer_refs, ptr_contexts = (
        find_pointer_words(
            elf
        )
    )

    write_tsv(
        OUT
        / "setter_pointer_refs.tsv",
        pointer_refs,
        [
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
            "section",
        ]
    )

    (
        OUT
        / "setter_pointer_contexts.txt"
    ).write_text(
        "\n\n".join(
            ptr_contexts
        ),
        encoding="utf-8"
    )

    print(
        "Raw setter pointer refs:",
        len(pointer_refs)
    )

    # --------------------------------------------------------
    # All BSS accesses
    # --------------------------------------------------------

    global_accesses = (
        scan_global_accesses(
            elf
        )
    )

    write_tsv(
        OUT
        / "conversion_global_accesses.tsv",
        global_accesses,
        [
            "global",
            "address",
            "operation",
            "lui_va",
            "access_va",
            "access_file_offset",
            "base_register",
            "value_register",
            "section",
        ]
    )

    print(
        "Conversion-global accesses:",
        len(global_accesses)
    )

    # --------------------------------------------------------
    # Xrefs to data cells containing setter pointer.
    # --------------------------------------------------------

    ptr_vas = [
        x["va"]
        for x in pointer_refs
        if isinstance(
            x["va"],
            int
        )
    ]

    setter_xrefs = (
        find_address_uses(
            elf,
            ptr_vas
        )
    )

    write_tsv(
        OUT
        / "setter_data_xrefs.tsv",
        setter_xrefs,
        [
            "target",
            "kind",
            "start_va",
            "use_va",
            "use_file_offset",
            "register",
        ]
    )

    print(
        "Setter data xrefs:",
        len(setter_xrefs)
    )

    # --------------------------------------------------------
    # All indirect calls.
    # --------------------------------------------------------

    jalr_rows, jalr_contexts = (
        scan_jalr(
            elf
        )
    )

    write_tsv(
        OUT
        / "jalr_calls.tsv",
        jalr_rows,
        [
            "va",
            "file_offset",
            "source_register",
            "link_register",
            "section",
        ]
    )

    (
        OUT
        / "jalr_contexts.txt"
    ).write_text(
        "\n\n".join(
            jalr_contexts
        ),
        encoding="utf-8"
    )

    print(
        "JALR callsites:",
        len(jalr_rows)
    )

    # --------------------------------------------------------
    # Search extracted resources.
    # --------------------------------------------------------

    paths = collect_scan_files()

    print()
    print(
        "Binary/resource files to scan:",
        len(paths)
    )

    table_candidates = []

    scan_rows = []

    total = len(paths)

    for i, path in enumerate(
        paths,
        1
    ):
        try:
            size = (
                path.stat().st_size
            )

            hits = scan_mapping_file(
                path
            )

            table_candidates.extend(
                hits
            )

            scan_rows.append({
                "file":
                    str(path),

                "size":
                    size,

                "candidates":
                    len(hits),
            })

        except Exception as ex:

            scan_rows.append({
                "file":
                    str(path),

                "size":
                    "",

                "candidates":
                    0,

                "error":
                    str(ex),
            })

        if (
            i % 100 == 0
            or i == total
        ):
            print(
                f"[table scan] "
                f"{i}/{total} "
                f"candidates="
                f"{len(table_candidates)}"
            )

    write_tsv(
        OUT
        / "resource_scan.tsv",
        scan_rows,
        [
            "file",
            "size",
            "candidates",
            "error",
        ]
    )

    write_tsv(
        OUT
        / "table_source_candidates.tsv",
        table_candidates,
        [
            "direction",
            "file",
            "file_size",
            "table_offset",
            "table_offset_hex",
        ]
    )

    extracted = extract_candidates(
        table_candidates
    )

    write_tsv(
        OUT
        / "extracted_table_candidates.tsv",
        extracted,
        [
            "direction",
            "file",
            "file_size",
            "table_offset",
            "table_offset_hex",
            "extracted",
            "sha256",
        ]
    )

    print()
    print(
        "Table source candidates:",
        len(table_candidates)
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    fwd = [
        x
        for x in table_candidates
        if x["direction"]
        == "JIS_TO_UNICODE"
    ]

    rev = [
        x
        for x in table_candidates
        if x["direction"]
        == "UNICODE_TO_JIS"
    ]

    summary = (
        OUT
        / "stage21_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 21\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            "Confirmed runtime globalLOCAL_PATH"
        )

        f.write(
            "  0x004BD5EC "
            "JIS/internal-code -> Unicode pointer\n"
        )

        f.write(
            "  0x004BD5F0 "
            "Unicode -> JIS/internal-code pointer\n\n"
        )

        f.write(
            f"PT_LOAD file-backed end: "
            f"0x{data_end:08X}\n"
        )

        f.write(
            f"PT_LOAD memory end: "
            f"0x{program_end:08X}\n"
        )

        f.write(
            "Therefore 0x004BD5EC/F0 are "
            "runtime/BSS values.\n\n"
        )

        f.write(
            f"Raw 0x002AD284 function-pointer "
            f"references: {len(pointer_refs)}\n"
        )

        f.write(
            f"Xrefs to setter-pointer cells: "
            f"{len(setter_xrefs)}\n"
        )

        f.write(
            f"Conversion-global code accesses: "
            f"{len(global_accesses)}\n"
        )

        f.write(
            f"Indirect JALR callsites: "
            f"{len(jalr_rows)}\n\n"
        )

        f.write(
            f"Files scanned for conversion table: "
            f"{len(paths)}\n"
        )

        f.write(
            f"Forward table candidates: "
            f"{len(fwd)}\n"
        )

        f.write(
            f"Reverse table candidates: "
            f"{len(rev)}\n"
        )

        for row in table_candidates:
            f.write(
                f"  {row['direction']} "
                f"{row['file']} "
                f"@ {row['table_offset_hex']}\n"
            )

    print()
    print("=" * 72)
    print("STAGE 21 COMPLETE")
    print("=" * 72)

    print(
        "Setter pointer refs:",
        len(pointer_refs)
    )

    print(
        "Setter data xrefs:",
        len(setter_xrefs)
    )

    print(
        "Global accesses:",
        len(global_accesses)
    )

    print(
        "JALR calls:",
        len(jalr_rows)
    )

    print(
        "Forward table candidates:",
        len(fwd)
    )

    print(
        "Reverse table candidates:",
        len(rev)
    )

    print(
        "Output:",
        OUT
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
