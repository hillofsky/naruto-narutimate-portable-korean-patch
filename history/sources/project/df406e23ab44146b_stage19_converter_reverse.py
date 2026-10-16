from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage19"

OUT.mkdir(
    parents=True,
    exist_ok=True
)

S17 = (
    BASE
    / "analysis"
    / "stage17"
    / "stage17_font_engine.py"
)

KR_BOOT = (
    BASE
    / "kr_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)

US_BOOT = (
    BASE
    / "us_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)

CONVERTER = 0x002ACCF4

# Deliberately much larger than the Stage18 dump.
SCAN_SIZE = 0x1800


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


def u32(data, off):
    return struct.unpack_from(
        "<I",
        data,
        off
    )[0]


def s16(v):
    return (
        v - 0x10000
        if v & 0x8000
        else v
    )


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
    if not S17.exists():
        raise RuntimeError(
            f"Stage17 script 없음: {S17}"
        )

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


# ============================================================
# Better MIPS decoder
# Includes branch-likely opcodes missing in Stage17.
# ============================================================

def decode(ins, pc):
    op = (
        ins >> 26
    ) & 0x3F

    rs = (
        ins >> 21
    ) & 31

    rt = (
        ins >> 16
    ) & 31

    rd = (
        ins >> 11
    ) & 31

    sa = (
        ins >> 6
    ) & 31

    fn = ins & 0x3F

    imm = ins & 0xFFFF
    simm = s16(imm)

    branch_target = (
        pc
        + 4
        + (simm << 2)
    )

    if ins == 0:
        return "nop"

    # SPECIAL
    if op == 0:
        if fn == 0x00:
            return (
                f"sll {REG[rd]},"
                f"{REG[rt]},{sa}"
            )

        if fn == 0x02:
            return (
                f"srl {REG[rd]},"
                f"{REG[rt]},{sa}"
            )

        if fn == 0x03:
            return (
                f"sra {REG[rd]},"
                f"{REG[rt]},{sa}"
            )

        if fn == 0x04:
            return (
                f"sllv {REG[rd]},"
                f"{REG[rt]},"
                f"{REG[rs]}"
            )

        if fn == 0x06:
            return (
                f"srlv {REG[rd]},"
                f"{REG[rt]},"
                f"{REG[rs]}"
            )

        if fn == 0x07:
            return (
                f"srav {REG[rd]},"
                f"{REG[rt]},"
                f"{REG[rs]}"
            )

        if fn == 0x08:
            return (
                f"jr {REG[rs]}"
            )

        if fn == 0x09:
            return (
                f"jalr {REG[rd]},"
                f"{REG[rs]}"
            )

        if fn == 0x10:
            return (
                f"mfhi {REG[rd]}"
            )

        if fn == 0x12:
            return (
                f"mflo {REG[rd]}"
            )

        if fn == 0x18:
            return (
                f"mult {REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x19:
            return (
                f"multu {REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x1A:
            return (
                f"div {REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x1B:
            return (
                f"divu {REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x20:
            return (
                f"add {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x21:
            return (
                f"addu {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x22:
            return (
                f"sub {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x23:
            return (
                f"subu {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x24:
            return (
                f"and {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x25:
            return (
                f"or {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x26:
            return (
                f"xor {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x27:
            return (
                f"nor {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x2A:
            return (
                f"slt {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

        if fn == 0x2B:
            return (
                f"sltu {REG[rd]},"
                f"{REG[rs]},"
                f"{REG[rt]}"
            )

    # REGIMM
    if op == 1:
        names = {
            0x00: "bltz",
            0x01: "bgez",
            0x02: "bltzl",
            0x03: "bgezl",
            0x10: "bltzal",
            0x11: "bgezal",
            0x12: "bltzall",
            0x13: "bgezall",
        }

        if rt in names:
            return (
                f"{names[rt]} "
                f"{REG[rs]},"
                f"0x{branch_target:08X}"
            )

    if op in (2, 3):
        target = (
            ((pc + 4)
             & 0xF0000000)
            |
            (
                (ins
                 & 0x03FFFFFF)
                << 2
            )
        )

        opname = (
            "j"
            if op == 2
            else "jal"
        )

        return (
            f"{opname} "
            f"0x{target:08X}"
        )

    branch_names = {
        0x04: "beq",
        0x05: "bne",
        0x14: "beql",
        0x15: "bnel",
    }

    if op in branch_names:
        return (
            f"{branch_names[op]} "
            f"{REG[rs]},"
            f"{REG[rt]},"
            f"0x{branch_target:08X}"
        )

    one_reg_branches = {
        0x06: "blez",
        0x07: "bgtz",
        0x16: "blezl",
        0x17: "bgtzl",
    }

    if op in one_reg_branches:
        return (
            f"{one_reg_branches[op]} "
            f"{REG[rs]},"
            f"0x{branch_target:08X}"
        )

    imm_names = {
        0x08: "addi",
        0x09: "addiu",
        0x0A: "slti",
        0x0B: "sltiu",
    }

    if op in imm_names:
        return (
            f"{imm_names[op]} "
            f"{REG[rt]},"
            f"{REG[rs]},"
            f"{simm}"
        )

    if op == 0x0C:
        return (
            f"andi {REG[rt]},"
            f"{REG[rs]},"
            f"0x{imm:04X}"
        )

    if op == 0x0D:
        return (
            f"ori {REG[rt]},"
            f"{REG[rs]},"
            f"0x{imm:04X}"
        )

    if op == 0x0E:
        return (
            f"xori {REG[rt]},"
            f"{REG[rs]},"
            f"0x{imm:04X}"
        )

    if op == 0x0F:
        return (
            f"lui {REG[rt]},"
            f"0x{imm:04X}"
        )

    mem = {
        0x20: "lb",
        0x21: "lh",
        0x22: "lwl",
        0x23: "lw",
        0x24: "lbu",
        0x25: "lhu",
        0x26: "lwr",

        0x28: "sb",
        0x29: "sh",
        0x2A: "swl",
        0x2B: "sw",
        0x2E: "swr",
    }

    if op in mem:
        return (
            f"{mem[op]} "
            f"{REG[rt]},"
            f"{simm}({REG[rs]})"
        )

    return (
        f".word 0x{ins:08X}"
    )


# ============================================================
# Dump utilities
# ============================================================

def va_dump(
    elf,
    start_va,
    size,
    title
):
    off = elf.va_to_offset(
        start_va
    )

    if off is None:
        raise RuntimeError(
            f"VA 변환 실패: "
            f"0x{start_va:08X}"
        )

    max_size = min(
        size,
        len(elf.data) - off
    )

    lines = [
        "=" * 84,
        (
            f"{title} "
            f"VA=0x{start_va:08X} "
            f"FILE=0x{off:X} "
            f"SIZE=0x{max_size:X}"
        ),
        "=" * 84,
    ]

    p = off
    end = off + max_size

    while p + 4 <= end:
        pc = (
            start_va
            + p - off
        )

        ins = u32(
            elf.data,
            p
        )

        lines.append(
            f"0x{pc:08X}: "
            f"{ins:08X}  "
            f"{decode(ins, pc)}"
        )

        p += 4

    return (
        "\n".join(lines),
        off,
        max_size
    )


def direct_jals(
    elf,
    start_va,
    size
):
    off = elf.va_to_offset(
        start_va
    )

    if off is None:
        return []

    rows = []

    end = min(
        len(elf.data),
        off + size
    )

    p = off

    while p + 4 <= end:
        ins = u32(
            elf.data,
            p
        )

        op = (
            ins >> 26
        ) & 0x3F

        if op == 3:
            pc = (
                start_va
                + p - off
            )

            target = (
                ((pc + 4)
                 & 0xF0000000)
                |
                (
                    (ins
                     & 0x03FFFFFF)
                    << 2
                )
            )

            rows.append({
                "call_va":
                    pc,

                "call_va_hex":
                    f"0x{pc:08X}",

                "file_offset":
                    p,

                "file_offset_hex":
                    f"0x{p:X}",

                "target_va":
                    target,

                "target_va_hex":
                    f"0x{target:08X}",
            })

        p += 4

    return rows


def prologue_candidates(
    elf,
    start_va,
    size
):
    off = elf.va_to_offset(
        start_va
    )

    if off is None:
        return []

    rows = []

    end = min(
        len(elf.data),
        off + size
    )

    p = off

    while p + 4 <= end:
        ins = u32(
            elf.data,
            p
        )

        op = (
            ins >> 26
        ) & 0x3F

        rs = (
            ins >> 21
        ) & 31

        rt = (
            ins >> 16
        ) & 31

        imm = s16(
            ins & 0xFFFF
        )

        if (
            op == 9
            and rs == 29
            and rt == 29
            and imm < 0
        ):
            va = (
                start_va
                + p - off
            )

            rows.append({
                "va":
                    va,

                "va_hex":
                    f"0x{va:08X}",

                "file_offset":
                    p,

                "file_offset_hex":
                    f"0x{p:X}",

                "stack_size":
                    -imm,
            })

        p += 4

    return rows


def returns(
    elf,
    start_va,
    size
):
    off = elf.va_to_offset(
        start_va
    )

    if off is None:
        return []

    rows = []

    end = min(
        len(elf.data),
        off + size
    )

    p = off

    while p + 4 <= end:
        ins = u32(
            elf.data,
            p
        )

        # jr ra
        if ins == 0x03E00008:
            va = (
                start_va
                + p - off
            )

            rows.append({
                "va":
                    va,

                "va_hex":
                    f"0x{va:08X}",

                "file_offset":
                    p,

                "file_offset_hex":
                    f"0x{p:X}",
            })

        p += 4

    return rows


# ============================================================
# Search equivalent US function
# ============================================================

def find_us_matches(
    kr,
    us
):
    kr_off = kr.va_to_offset(
        CONVERTER
    )

    if kr_off is None:
        return []

    # First instructions before the first call are relocation
    # independent enough to be a useful signature.
    sig = kr.data[
        kr_off:
        kr_off + 0x50
    ]

    matches = []

    pos = 0

    while True:
        pos = us.data.find(
            sig,
            pos
        )

        if pos < 0:
            break

        va = None

        for s in us.sections:
            if (
                s["offset"]
                <= pos
                < s["offset"]
                + s["size"]
            ):
                va = (
                    s["addr"]
                    + pos
                    - s["offset"]
                )
                break

        matches.append({
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
        })

        pos += 1

    return matches


# ============================================================
# ELF layout
# ============================================================

def layout_rows(
    region,
    elf
):
    rows = []

    for p in elf.programs:
        rows.append({
            "region":
                region,

            "kind":
                "PROGRAM",

            "index":
                p["index"],

            "name":
                "",

            "type":
                p["type"],

            "flags":
                p["flags"],

            "va":
                f"0x{p['vaddr']:08X}",

            "file_offset":
                f"0x{p['offset']:X}",

            "file_size":
                p["filesz"],

            "mem_size":
                p["memsz"],

            "align":
                p["align"],
        })

    for s in elf.sections:
        rows.append({
            "region":
                region,

            "kind":
                "SECTION",

            "index":
                s["index"],

            "name":
                s["name"],

            "type":
                s["type"],

            "flags":
                s["flags"],

            "va":
                f"0x{s['addr']:08X}",

            "file_offset":
                f"0x{s['offset']:X}",

            "file_size":
                s["size"],

            "mem_size":
                s["size"],

            "align":
                s["align"],
        })

    return rows


# ============================================================
# main
# ============================================================

def main():
    print("=" * 72)
    print("Naruto PSP Stage 19")
    print("Full CP932 -> Unicode converter reverse")
    print("=" * 72)

    s17 = load_stage17()

    kr = s17.ELF32(
        KR_BOOT
    )

    us = s17.ELF32(
        US_BOOT
    )

    print(
        "KR BOOT SHA256:",
        sha256_file(KR_BOOT)
    )

    print(
        "US BOOT SHA256:",
        sha256_file(US_BOOT)
    )

    # --------------------------------------------------------
    # Full region
    # --------------------------------------------------------

    full_text, kr_off, raw_size = (
        va_dump(
            kr,
            CONVERTER,
            SCAN_SIZE,
            "KR CONVERTER REGION"
        )
    )

    (
        OUT
        / "kr_converter_full_disasm.txt"
    ).write_text(
        full_text,
        encoding="utf-8"
    )

    raw = kr.data[
        kr_off:
        kr_off + raw_size
    ]

    (
        OUT
        / "kr_converter_region.bin"
    ).write_bytes(raw)

    # --------------------------------------------------------
    # Calls
    # --------------------------------------------------------

    calls = direct_jals(
        kr,
        CONVERTER,
        SCAN_SIZE
    )

    write_tsv(
        OUT
        / "converter_calls.tsv",
        calls,
        [
            "call_va",
            "call_va_hex",
            "file_offset",
            "file_offset_hex",
            "target_va",
            "target_va_hex",
        ]
    )

    # Dump unique targets.
    target_text = []

    targets = sorted({
        r["target_va"]
        for r in calls
    })

    for target in targets:
        try:
            txt, _, _ = va_dump(
                kr,
                target,
                0x500,
                (
                    "CALL TARGET "
                    f"0x{target:08X}"
                )
            )

            target_text.append(txt)

        except Exception as ex:
            target_text.append(
                (
                    "=" * 80
                    + "\n"
                    + f"TARGET "
                    f"0x{target:08X}: "
                    f"{ex}"
                )
            )

    (
        OUT
        / "converter_call_targets.txt"
    ).write_text(
        "\n\n".join(
            target_text
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Function boundary clues
    # --------------------------------------------------------

    prologues = (
        prologue_candidates(
            kr,
            CONVERTER,
            SCAN_SIZE
        )
    )

    ret_rows = returns(
        kr,
        CONVERTER,
        SCAN_SIZE
    )

    write_tsv(
        OUT
        / "converter_prologues.tsv",
        prologues,
        [
            "va",
            "va_hex",
            "file_offset",
            "file_offset_hex",
            "stack_size",
        ]
    )

    write_tsv(
        OUT
        / "converter_returns.tsv",
        ret_rows,
        [
            "va",
            "va_hex",
            "file_offset",
            "file_offset_hex",
        ]
    )

    # --------------------------------------------------------
    # US equivalent search
    # --------------------------------------------------------

    us_matches = find_us_matches(
        kr,
        us
    )

    write_tsv(
        OUT
        / "us_converter_matches.tsv",
        us_matches,
        [
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
        ]
    )

    us_texts = []

    for m in us_matches[:10]:
        if not isinstance(
            m["va"],
            int
        ):
            continue

        txt, _, _ = va_dump(
            us,
            m["va"],
            SCAN_SIZE,
            (
                "US CONVERTER MATCH "
                f"{m['va_hex']}"
            )
        )

        us_texts.append(txt)

    (
        OUT
        / "us_converter_disasm.txt"
    ).write_text(
        "\n\n".join(
            us_texts
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    layout = (
        layout_rows("KR", kr)
        + layout_rows("US", us)
    )

    write_tsv(
        OUT
        / "elf_layout.tsv",
        layout,
        [
            "region",
            "kind",
            "index",
            "name",
            "type",
            "flags",
            "va",
            "file_offset",
            "file_size",
            "mem_size",
            "align",
        ]
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    next_prologues = [
        r
        for r in prologues
        if r["va"] > CONVERTER
    ]

    summary = (
        OUT
        / "stage19_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "Naruto PSP Stage 19\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"KR converter start: "
            f"0x{CONVERTER:08X}\n"
        )

        f.write(
            f"Dumped bytes: "
            f"0x{raw_size:X}\n"
        )

        f.write(
            f"Direct JALs in region: "
            f"{len(calls)}\n"
        )

        f.write(
            f"Unique JAL targets: "
            f"{len(targets)}\n"
        )

        f.write(
            f"JR RA occurrences: "
            f"{len(ret_rows)}\n"
        )

        f.write(
            f"Stack prologue candidates: "
            f"{len(prologues)}\n"
        )

        if next_prologues:
            f.write(
                f"First prologue after converter: "
                f"{next_prologues[0]['va_hex']}\n"
            )

        f.write(
            f"Exact US signature matches: "
            f"{len(us_matches)}\n\n"
        )

        f.write(
            "Confirmed from Stage18 runtime tesLOCAL_PATH"
        )

        f.write(
            "  CP949 bytes are decoded as CP932.\n"
        )

        f.write(
            "  UTF-8 bytes are decoded as CP932.\n"
        )

        f.write(
            "  Raw UTF-16BE is decoded as CP932/single-byte data.\n"
        )

        f.write(
            "  Normal CP932 Japanese works.\n"
        )

        f.write(
            "  Korean font selector already supports "
            "U+3130..U+318F and U+AC00..U+D7FF.\n"
        )

    print()
    print("=" * 72)
    print("STAGE 19 COMPLETE")
    print("=" * 72)

    print(
        "Direct calls:",
        len(calls)
    )

    print(
        "Unique targets:",
        len(targets)
    )

    print(
        "Prologues:",
        len(prologues)
    )

    print(
        "Returns:",
        len(ret_rows)
    )

    print(
        "US matches:",
        len(us_matches)
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
