from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"D:\narutimate portable")
OUT  = BASE / "analysis" / "stage24"

OUT.mkdir(parents=True, exist_ok=True)


BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

CPTBL = BASE / "cptbl.dat"

SOURCE_TBL = (
    BASE
    / "analysis"
    / "stage14"
    / "test_patch"
    / "event000_original.tbl"
)

S17 = (
    BASE
    / "analysis"
    / "stage17"
    / "stage17_font_engine.py"
)


PATCHED_BOOT = (
    OUT / "BOOT_stage24_hangul_hook.BIN"
)

PATCHED_TBL = (
    OUT / "event000_stage24.tbl"
)


# Two calls to the same Shift-JIS decoder.
#
# Existing JAL relocation records are deliberately retained.
CALL_SITES = [
    0x002ACF18,   # Shift-JIS -> UTF-8
    0x002AD00C,   # Shift-JIS -> UTF-16
]

ORIGINAL_DECODER = 0x002AC9E4

# JIS/internal -> Unicode pointer variable.
JIS_TO_UNICODE_PTR = 0x004BD5EC


MAPPING = [
    (b"\x81\xAD", 0x222F, "한", 0xD55C),
    (b"\x81\xAE", 0x2230, "글", 0xAE00),
    (b"\x81\xAF", 0x2231, "테", 0xD14C),
    (b"\x81\xB0", 0x2232, "스", 0xC2A4),
    (b"\x81\xB1", 0x2233, "트", 0xD2B8),

    (b"\x81\xB2", 0x2234, "가", 0xAC00),
    (b"\x81\xB3", 0x2235, "나", 0xB098),
    (b"\x81\xB4", 0x2236, "다", 0xB2E4),
    (b"\x81\xB5", 0x2237, "라", 0xB77C),
    (b"\x81\xB6", 0x2238, "마", 0xB9C8),
]

# ============================================================
# Generic helpers
# ============================================================

def u16(data, off):
    return struct.unpack_from(
        "<H", data, off
    )[0]


def u32(data, off):
    return struct.unpack_from(
        "<I", data, off
    )[0]


def p32(data, off, value):
    struct.pack_into(
        "<I",
        data,
        off,
        value & 0xFFFFFFFF
    )


def sha256_bytes(data):
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


# ============================================================
# MIPS encoder
# ============================================================

def R(
    rs,
    rt,
    rd,
    shamt,
    funct
):
    return (
        ((rs & 31) << 21)
        |
        ((rt & 31) << 16)
        |
        ((rd & 31) << 11)
        |
        ((shamt & 31) << 6)
        |
        (funct & 0x3F)
    )


def I(
    op,
    rs,
    rt,
    imm
):
    return (
        ((op & 0x3F) << 26)
        |
        ((rs & 31) << 21)
        |
        ((rt & 31) << 16)
        |
        (imm & 0xFFFF)
    )


def J(
    target
):
    return (
        0x08000000
        |
        ((target >> 2)
         & 0x03FFFFFF)
    )


def JAL(
    target
):
    return (
        0x0C000000
        |
        ((target >> 2)
         & 0x03FFFFFF)
    )


def branch(
    op,
    rs,
    rt,
    pc,
    target
):
    delta = (
        target
        - (pc + 4)
    )

    if delta % 4:
        raise RuntimeError(
            "Unaligned branch target"
        )

    words = (
        delta // 4
    )

    if not (
        -32768
        <= words
        <= 32767
    ):
        raise RuntimeError(
            "Branch target out of range"
        )

    return I(
        op,
        rs,
        rt,
        words
    )


def split_u32(value):
    value &= 0xFFFFFFFF

    return (
        (value >> 16) & 0xFFFF,
        value & 0xFFFF,
    )


# registers
ZERO = 0
V0   = 2

T0   = 8
T1   = 9
T2   = 10
T3   = 11
T8   = 24
T9   = 25

SP   = 29
RA   = 31


# ============================================================
# Sony cptbl verification
# ============================================================

def sjis_dense_index(
    lead,
    trail
):

    if 0x81 <= lead <= 0x9F:
        lead_index = (
            lead - 0x81
        )

    elif 0xE0 <= lead <= 0xFC:
        lead_index = (
            31
            + lead - 0xE0
        )

    else:
        return None


    if 0x40 <= trail <= 0x7E:
        trail_index = (
            trail - 0x40
        )

    elif 0x80 <= trail <= 0xFC:
        trail_index = (
            63
            + trail - 0x80
        )

    else:
        return None


    return (
        188
        + lead_index * 188
        + trail_index
    )


def game_internal_code(
    lead,
    trail
):

    if trail <= 0x7E:
        adjust = -0x1F

    elif trail >= 0x9F:
        adjust = 0x82

    else:
        adjust = -0x20


    return (
        0x0200 * lead
        - 0xE100
        - (
            0x8000
            if lead >= 0xE0
            else 0
        )
        + trail
        + adjust
    ) & 0xFFFF


def verify_cptbl():

    if not CPTBL.exists():
        raise RuntimeError(
            f"cptbl.dat 없음: {CPTBL}"
        )

    raw = CPTBL.read_bytes()

    if len(raw) != 182356:
        print(
            "[warning] cptbl size differs:",
            len(raw)
        )

    cp932 = None

    for off in range(
        0,
        min(
            len(raw),
            0x2C0
        ),
        44
    ):

        if off + 44 > len(raw):
            break

        vals = struct.unpack_from(
            "<11I",
            raw,
            off
        )

        if vals[0] == 0:
            break

        if vals[0] == 0x0D:
            cp932 = {
                "descriptor_offset":
                    off,

                "flags":
                    vals[1],

                "table_offset":
                    vals[2],

                "table_size":
                    vals[3],

                "table_unpacked":
                    vals[4],
            }

            break


    if cp932 is None:
        raise RuntimeError(
            "cptbl에서 CP932 descriptor를 찾지 못했습니다."
        )


    start = cp932[
        "table_offset"
    ]

    size = cp932[
        "table_size"
    ]

    table = raw[
        start:
        start + size
    ]


    if len(table) < 0x5E00:
        raise RuntimeError(
            "CP932 table size가 예상보다 작습니다."
        )


    known = [
        (0x81, 0x40, 0x3000),
        (0x82, 0xA0, 0x3042),
        (0x93, 0xFA, 0x65E5),
    ]


    for lead, trail, expected in known:

        index = sjis_dense_index(
            lead,
            trail
        )

        got = u16(
            table,
            index * 2
        )

        if got != expected:
            raise RuntimeError(
                f"CP932 validation 실패: "
                f"{lead:02X}{trail:02X} "
                f"expected U+{expected:04X}, "
                f"actual U+{got:04X}"
            )


    free = 0
    nonzero = []

    trails = (
        list(
            range(0x40, 0x7F)
        )
        +
        list(
            range(0x80, 0xFD)
        )
    )


    for lead in range(
        0xF0,
        0xFA
    ):

        for trail in trails:

            index = sjis_dense_index(
                lead,
                trail
            )

            value = u16(
                table,
                index * 2
            )

            if value == 0:
                free += 1

            else:
                nonzero.append(
                    (
                        lead,
                        trail,
                        value,
                    )
                )


    if free != 1880:
        raise RuntimeError(
            f"F0-F9 free-slot count mismatch: "
            f"{free}/1880"
        )

    if nonzero:
        raise RuntimeError(
            "F0-F9 영역에 기존 CP932 문자가 존재합니다."
        )


    mapping_rows = []

    for pair, internal, char, uni in MAPPING:

        lead = pair[0]
        trail = pair[1]

        calculated = game_internal_code(
            lead,
            trail
        )

        if calculated != internal:
            raise RuntimeError(
                f"Internal-code mismatch "
                f"{pair.hex(' ')}: "
                f"{calculated:04X} != "
                f"{internal:04X}"
            )

        index = sjis_dense_index(
            lead,
            trail
        )

        stock = u16(
            table,
            index * 2
        )

        if stock != 0:
            raise RuntimeError(
                f"Custom SJIS slot not empty: "
                f"{pair.hex(' ')}"
            )

        mapping_rows.append({
            "sjis":
                pair.hex(" "),

            "internal_code":
                f"0x{internal:04X}",

            "character":
                char,

            "unicode":
                f"U+{uni:04X}",

            "stock_cp932":
                f"U+{stock:04X}",
        })


    write_tsv(
        OUT
        / "stage24_cptbl_validation.tsv",
        mapping_rows,
        [
            "sjis",
            "internal_code",
            "character",
            "unicode",
            "stock_cp932",
        ]
    )


    return {
        "sha256":
            sha256_bytes(raw),

        "cp932_offset":
            start,

        "cp932_size":
            size,

        "f0_f9_free":
            free,
    }


# ============================================================
# ELF code cave search
# ============================================================

def collect_branch_targets(
    elf,
    text
):

    targets = set()

    start = text["offset"]
    end = (
        text["offset"]
        + text["size"]
    )

    p = start

    while p + 4 <= end:

        ins = u32(
            elf.data,
            p
        )

        pc = (
            text["addr"]
            + p
            - text["offset"]
        )

        op = (
            ins >> 26
        ) & 0x3F


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

            targets.add(
                target
            )


        elif op in (
            1,
            4,
            5,
            6,
            7,
            0x14,
            0x15,
            0x16,
            0x17,
        ):

            imm = (
                ins & 0xFFFF
            )

            if imm & 0x8000:
                imm -= 0x10000

            target = (
                pc
                + 4
                + imm * 4
            )

            targets.add(
                target
            )


        p += 4


    return targets


def relocation_sites(
    elf
):

    rel = elf.section(
        ".rel.text"
    )

    if rel is None:
        raise RuntimeError(
            ".rel.text 없음"
        )

    rows = {}
    p = rel["offset"]
    end = (
        rel["offset"]
        + rel["size"]
    )


    while p + 8 <= end:

        r_offset = u32(
            elf.data,
            p
        )

        r_info = u32(
            elf.data,
            p + 4
        )

        rows.setdefault(
            r_offset,
            []
        ).append(
            r_info
        )

        p += 8


    return rows


def data_pointer_values(
    elf
):

    sec = elf.section(
        ".data"
    )

    values = set()

    if sec is None:
        return values

    start = sec["offset"]
    end = (
        sec["offset"]
        + sec["size"]
    )

    p = start

    while p + 4 <= end:

        value = u32(
            elf.data,
            p
        )

        if value:
            values.add(
                value
            )

        p += 4


    return values


def preceding_control(
    data,
    run_start,
    text_start
):

    for back in (
        4,
        8,
        12,
        16,
    ):

        p = run_start - back

        if p < text_start:
            continue

        ins = u32(
            data,
            p
        )

        op = (
            ins >> 26
        ) & 0x3F

        funct = (
            ins & 0x3F
        )

        rs = (
            ins >> 21
        ) & 31


        # jr ra / jr register
        if (
            op == 0
            and funct == 8
        ):
            return True


        # unconditional J
        if op == 2:
            return True


    return False


def find_code_cave(
    elf,
    minimum=0xA0
):

    text = elf.section(
        ".text"
    )

    if text is None:
        raise RuntimeError(
            ".text section 없음"
        )

    targets = collect_branch_targets(
        elf,
        text
    )

    relocs = relocation_sites(
        elf
    )

    ptrs = data_pointer_values(
        elf
    )


    start = text["offset"]
    end = (
        text["offset"]
        + text["size"]
    )

    data = elf.data

    candidates = []

    p = start

    while p < end:

        if data[p] != 0:
            p += 1
            continue

        run_start = p

        while (
            p < end
            and data[p] == 0
        ):
            p += 1

        run_end = p


        aligned_start = (
            run_start + 3
        ) & ~3

        aligned_end = (
            run_end
            & ~3
        )

        length = (
            aligned_end
            - aligned_start
        )


        if length < minimum:
            continue


        va = (
            text["addr"]
            + aligned_start
            - text["offset"]
        )

        va_end = (
            va + minimum
        )


        branch_hits = sum(
            1
            for x in targets
            if va <= x < va_end
        )

        reloc_hits = sum(
            1
            for x in relocs
            if va <= x < va_end
        )

        pointer_hits = sum(
            1
            for x in ptrs
            if va <= x < va_end
        )


        safe = (
            branch_hits == 0
            and reloc_hits == 0
            and pointer_hits == 0
        )


        candidates.append({
            "file_offset":
                aligned_start,

            "file_offset_hex":
                f"0x{aligned_start:X}",

            "va":
                va,

            "va_hex":
                f"0x{va:08X}",

            "available":
                length,

            "branch_targets":
                branch_hits,

            "relocations":
                reloc_hits,

            "data_pointers":
                pointer_hits,

            "preceded_by_control":
                preceding_control(
                    data,
                    aligned_start,
                    start
                ),

            "safe":
                safe,
        })


    write_tsv(
        OUT
        / "stage24_code_caves.tsv",
        candidates,
        [
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
            "available",
            "branch_targets",
            "relocations",
            "data_pointers",
            "preceded_by_control",
            "safe",
        ]
    )


    safe = [
        x
        for x in candidates
        if x["safe"]
    ]


    if not safe:
        raise RuntimeError(
            "안전한 0xA0-byte executable code cave를 찾지 못했습니다."
        )


    # Prefer padding following an explicit control-transfer,
    # then prefer a cave near the converter.
    safe.sort(
        key=lambda x: (
            not x[
                "preceded_by_control"
            ],
            abs(
                x["va"]
                - CALL_SITES[0]
            ),
            -x["available"],
        )
    )


    return safe[0]


# ============================================================
# Deterministic loader-gap injection
# ============================================================

def find_loader_gap_cave(
    elf,
    minimum=0xA0
):
    candidates = []

    for p in elf.programs:

        # PT_LOAD
        if p["type"] != 1:
            continue

        # Must be executable.
        # ELF PF_X == 1.
        if not (
            p["flags"] & 0x1
        ):
            continue

        file_end = (
            p["offset"]
            + p["filesz"]
        )

        mem_end = (
            p["offset"]
            + p["memsz"]
        )

        memory_slack = (
            p["memsz"]
            - p["filesz"]
        )

        if memory_slack < minimum:
            continue

        # Find the next real file-backed ELF section.
        #
        # SHT_NOBITS (.bss) occupies memory but has no bytes
        # in the file, so it does not block this injection.
        next_file_offset = len(
            elf.data
        )

        blocking = []

        for s in elf.sections:

            # SHT_NOBITS
            if s["type"] == 8:
                continue

            if s["size"] <= 0:
                continue

            soff = s["offset"]

            if soff >= file_end:

                next_file_offset = min(
                    next_file_offset,
                    soff
                )

        file_gap = (
            next_file_offset
            - file_end
        )

        if file_gap < minimum:
            continue

        cave_off = (
            file_end + 3
        ) & ~3

        alignment_loss = (
            cave_off
            - file_end
        )

        available = min(
            file_gap - alignment_loss,
            memory_slack - alignment_loss
        )

        if available < minimum:
            continue

        cave_va = (
            p["vaddr"]
            + (
                cave_off
                - p["offset"]
            )
        )

        cave_end = (
            cave_off
            + minimum
        )

        # Make absolutely sure this range does not overlap
        # any existing file-backed section.
        overlap = False

        for s in elf.sections:

            if s["type"] == 8:
                continue

            if s["size"] <= 0:
                continue

            s0 = s["offset"]
            s1 = (
                s["offset"]
                + s["size"]
            )

            if (
                cave_off < s1
                and cave_end > s0
            ):
                overlap = True
                blocking.append(
                    s["name"]
                )

        if overlap:
            continue

        old_filesz = p[
            "filesz"
        ]

        new_filesz = (
            cave_end
            - p["offset"]
        )

        if new_filesz > p["memsz"]:
            continue

        phdr_offset = (
            elf.e_phoff
            + p["index"]
            * elf.e_phentsize
        )

        row = {
            "file_offset":
                cave_off,

            "file_offset_hex":
                f"0x{cave_off:X}",

            "va":
                cave_va,

            "va_hex":
                f"0x{cave_va:08X}",

            "available":
                available,

            "branch_targets":
                0,

            "relocations":
                0,

            "data_pointers":
                0,

            "preceded_by_control":
                False,

            "safe":
                True,

            "requires_zero":
                False,

            "extend_load":
                True,

            "program_index":
                p["index"],

            "phdr_offset":
                phdr_offset,

            "old_filesz":
                old_filesz,

            "new_filesz":
                new_filesz,

            "old_memsz":
                p["memsz"],

            "file_gap":
                file_gap,

            "memory_slack":
                memory_slack,

            "next_file_offset":
                next_file_offset,
        }

        candidates.append(
            row
        )

    if not candidates:
        raise RuntimeError(
            "PT_LOAD 끝과 다음 ELF section 사이에 "
            "0xA0-byte 삽입 공간을 찾지 못했습니다."
        )

    # Prefer the smallest sufficient file gap.
    candidates.sort(
        key=lambda x: (
            x["available"],
            x["file_offset"]
        )
    )

    chosen = candidates[0]

    # Keep Stage24's existing required report name.
    write_tsv(
        OUT
        / "stage24_code_caves.tsv",
        candidates,
        [
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
            "available",
            "branch_targets",
            "relocations",
            "data_pointers",
            "preceded_by_control",
            "safe",
            "program_index",
            "phdr_offset",
            "old_filesz",
            "new_filesz",
            "old_memsz",
            "file_gap",
            "memory_slack",
            "next_file_offset",
        ]
    )

    return chosen



# ============================================================
# Hook
# ============================================================

def make_hook(
    cave_va
):

    # "bal" below makes RA point here.
    self_ref = (
        cave_va + 0x10
    )

    table_va = (
        cave_va + 0x80
    )


    parser_delta = (
        ORIGINAL_DECODER
        - self_ref
    ) & 0xFFFFFFFF

    table_delta = (
        table_va
        - self_ref
    ) & 0xFFFFFFFF

    global_delta = (
        JIS_TO_UNICODE_PTR
        - self_ref
    ) & 0xFFFFFFFF


    p_hi, p_lo = split_u32(
        parser_delta
    )

    t_hi, t_lo = split_u32(
        table_delta
    )

    g_hi, g_lo = split_u32(
        global_delta
    )


    words = []


    # 0
    words.append(
        I(
            0x09,
            SP,
            SP,
            -16
        )
    )

    # 1 - caller's RA
    words.append(
        I(
            0x2B,
            SP,
            RA,
            12
        )
    )

    # 2 - bgezal zero,+1
    # RA becomes runtime address of cave+0x10.
    words.append(
        I(
            0x01,
            ZERO,
            0x11,
            1
        )
    )

    # 3
    words.append(0)

    # 4 - save self-reference
    words.append(
        I(
            0x2B,
            SP,
            RA,
            8
        )
    )

    # 5/6 - parser delta
    words.append(
        I(
            0x0F,
            ZERO,
            T9,
            p_hi
        )
    )

    words.append(
        I(
            0x0D,
            T9,
            T9,
            p_lo
        )
    )

    # 7
    words.append(
        R(
            T9,
            RA,
            T9,
            0,
            0x21
        )
    )

    # 8 - jalr ra,t9
    words.append(
        R(
            T9,
            ZERO,
            RA,
            0,
            0x09
        )
    )

    # 9
    words.append(0)

    # 10 - restore runtime self-reference
    words.append(
        I(
            0x23,
            SP,
            T8,
            8
        )
    )

    # 11
    words.append(
        I(
            0x09,
            V0,
            T0,
            -MAPPING[0][1]
        )
    )

    # 12
    words.append(
        I(
            0x0B,
            T0,
            T1,
            len(MAPPING)
        )
    )

    # done label = instruction 28.
    branch_pc = (
        cave_va
        + 13 * 4
    )

    done_va = (
        cave_va
        + 28 * 4
    )

    # 13
    words.append(
        branch(
            0x04,
            T1,
            ZERO,
            branch_pc,
            done_va
        )
    )

    # 14
    words.append(0)

    # 15 - index * 2
    words.append(
        R(
            ZERO,
            T0,
            T0,
            1,
            0
        )
    )

    # 16/17 - custom Unicode table relative to self-ref
    words.append(
        I(
            0x0F,
            ZERO,
            T1,
            t_hi
        )
    )

    words.append(
        I(
            0x0D,
            T1,
            T1,
            t_lo
        )
    )

    # 18
    words.append(
        R(
            T1,
            T8,
            T1,
            0,
            0x21
        )
    )

    # 19
    words.append(
        R(
            T1,
            T0,
            T1,
            0,
            0x21
        )
    )

    # 20
    words.append(
        I(
            0x25,
            T1,
            T1,
            0
        )
    )

    # 21/22 - address of 0x004BD5EC relative to self-ref
    words.append(
        I(
            0x0F,
            ZERO,
            T2,
            g_hi
        )
    )

    words.append(
        I(
            0x0D,
            T2,
            T2,
            g_lo
        )
    )

    # 23
    words.append(
        R(
            T2,
            T8,
            T2,
            0,
            0x21
        )
    )

    # 24 - runtime JIS->Unicode table pointer
    words.append(
        I(
            0x23,
            T2,
            T2,
            0
        )
    )

    # 25 - v0 * 2
    words.append(
        R(
            ZERO,
            V0,
            T3,
            1,
            0
        )
    )

    # 26
    words.append(
        R(
            T2,
            T3,
            T2,
            0,
            0x21
        )
    )

    # 27 - patch table entry
    words.append(
        I(
            0x29,
            T2,
            T1,
            0
        )
    )

    # 28 - restore caller RA
    words.append(
        I(
            0x23,
            SP,
            RA,
            12
        )
    )

    # 29
    words.append(
        I(
            0x09,
            SP,
            SP,
            16
        )
    )

    # 30 - jr ra
    words.append(
        R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )

    # 31
    words.append(0)


    if len(words) != 32:
        raise RuntimeError(
            "Unexpected hook instruction count"
        )


    code = b"".join(
        struct.pack(
            "<I",
            word
        )
        for word in words
    )


    table = b"".join(
        struct.pack(
            "<H",
            uni
        )
        for (
            pair,
            internal,
            char,
            uni
        ) in MAPPING
    )


    blob = (
        code
        + table
    )


    if len(blob) != 148:
        raise RuntimeError(
            f"Unexpected hook size: "
            f"{len(blob)}"
        )


    return (
        blob,
        table_va,
        words,
    )


# ============================================================
# Probe TBL
# ============================================================

def make_probe_tbl():

    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"Original event000.tbl 없음: "
            f"{SOURCE_TBL}"
        )


    P = [
        x[0]
        for x in MAPPING
    ]


    probes = [
        (
            "KMAP_HANGUL_TEST",
            "KMAP:한글테스트",
            (
                b"KMAP:"
                + P[0]
                + P[1]
                + P[2]
                + P[3]
                + P[4]
            )
        ),

        (
            "KMAP_GANADARAMA",
            "KMAP:가나다라마",
            (
                b"KMAP:"
                + P[5]
                + P[6]
                + P[7]
                + P[8]
                + P[9]
            )
        ),

        (
            "KMAP_BR",
            "KMAP:한글<br>테스트",
            (
                b"KMAP:"
                + P[0]
                + P[1]
                + b"<br>"
                + P[2]
                + P[3]
                + P[4]
            )
        ),

        (
            "KMAP_FULLWIDTH_SPACE",
            "KMAP:한글　테스트",
            (
                b"KMAP:"
                + P[0]
                + P[1]
                + b"\x81\x40"
                + P[2]
                + P[3]
                + P[4]
            )
        ),

        (
            "MIX_JP_KR",
            "MIX:日本:한글",
            (
                b"MIX:"
                + "日本".encode(
                    "cp932"
                )
                + b":"
                + P[0]
                + P[1]
            )
        ),

        (
            "JP_CONTROL",
            "JP:日本語確認",
            (
                b"JP:"
                + "日本語確認".encode(
                    "cp932"
                )
            )
        ),

        (
            "ASCII_CONTROL",
            "ASCII:OK",
            b"ASCII:OK"
        ),
    ]


    source = (
        SOURCE_TBL.read_bytes()
    )

    lines = source.splitlines(
        keepends=True
    )

    out = []
    report = []

    probe_no = 0


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
            probe_no < len(probes)
            and body.startswith(
                b"MSG ="
            )
        ):

            parts = body.split(
                b",",
                2
            )

            if len(parts) == 3:

                (
                    name,
                    expected,
                    payload,
                ) = probes[
                    probe_no
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
                        probe_no + 1,

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


                probe_no += 1
                continue


        out.append(
            line
        )


    if probe_no != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: "
            f"{probe_no}/{len(probes)}"
        )


    patched = b"".join(
        out
    )

    PATCHED_TBL.write_bytes(
        patched
    )


    write_tsv(
        OUT
        / "stage24_probe_map.tsv",
        report,
        [
            "probe",
            "probe_name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ]
    )


# ============================================================
# main
# ============================================================

def main():

    print("=" * 72)
    print("Naruto PSP Stage 24")
    print("Valid-unused-SJIS Hangul hook")
    print("=" * 72)


    cptbl = verify_cptbl()


    print(
        "cptbl SHA256:",
        cptbl["sha256"]
    )

    print(
        "CP932 table:",
        f"0x{cptbl['cp932_offset']:X}",
        f"size=0x{cptbl['cp932_size']:X}"
    )

    print(
        "F0-F9 empty slots:",
        cptbl["f0_f9_free"]
    )


    s17 = load_stage17()
    elf = s17.ELF32(
        BOOT
    )

    original = bytearray(
        elf.data
    )


    relocs = relocation_sites(
        elf
    )


    relocation_report = []


    for site in CALL_SITES:

        off = elf.va_to_offset(
            site
        )

        if off is None:
            raise RuntimeError(
                f"Callsite VA 변환 실패: "
                f"0x{site:08X}"
            )


        original_word = u32(
            elf.data,
            off
        )


        expected_word = JAL(
            ORIGINAL_DECODER
        )


        if original_word != expected_word:
            raise RuntimeError(
                f"Callsite instruction mismatch "
                f"0x{site:08X}: "
                f"0x{original_word:08X}"
            )


        info = relocs.get(
            site,
            []
        )


        # Standard ELF R_MIPS_26 == 4.
        if 4 not in info:
            raise RuntimeError(
                f"R_MIPS_26 relocation 없음: "
                f"0x{site:08X}, "
                f"relocs={info}"
            )


        relocation_report.append({
            "callsite":
                f"0x{site:08X}",

            "file_offset":
                f"0x{off:X}",

            "original":
                f"0x{original_word:08X}",

            "relocation_info":
                ",".join(
                    f"0x{x:X}"
                    for x in info
                ),
        })


    cave = find_loader_gap_cave(
        elf,
        minimum=0xA0
    )


    cave_va = cave["va"]
    cave_off = cave[
        "file_offset"
    ]


    blob, table_va, hook_words = (
        make_hook(
            cave_va
        )
    )


    if len(blob) > cave[
        "available"
    ]:
        raise RuntimeError(
            "Chosen cave too small"
        )


    old_cave = original[
        cave_off:
        cave_off + len(blob)
    ]


    if (
        cave.get(
            "requires_zero",
            True
        )
        and any(old_cave)
    ):
        raise RuntimeError(
            "Chosen cave is not all-zero"
        )


    patched = bytearray(
        original
    )


    patched[
        cave_off:
        cave_off + len(blob)
    ] = blob


    if cave.get(
        "extend_load",
        False
    ):

        phdr_offset = cave[
            "phdr_offset"
        ]

        p_filesz_off = (
            phdr_offset
            + 0x10
        )

        p_memsz_off = (
            phdr_offset
            + 0x14
        )

        actual_old_filesz = u32(
            patched,
            p_filesz_off
        )

        actual_memsz = u32(
            patched,
            p_memsz_off
        )

        if (
            actual_old_filesz
            != cave["old_filesz"]
        ):
            raise RuntimeError(
                "PT_LOAD p_filesz verification failed: "
                f"0x{actual_old_filesz:X} != "
                f"0x{cave['old_filesz']:X}"
            )

        if (
            actual_memsz
            != cave["old_memsz"]
        ):
            raise RuntimeError(
                "PT_LOAD p_memsz verification failed: "
                f"0x{actual_memsz:X} != "
                f"0x{cave['old_memsz']:X}"
            )

        if (
            cave["new_filesz"]
            > actual_memsz
        ):
            raise RuntimeError(
                "New PT_LOAD p_filesz exceeds p_memsz"
            )

        # Only p_filesz changes.
        # p_memsz already includes this BSS memory.
        p32(
            patched,
            p_filesz_off,
            cave["new_filesz"]
        )


    patch_rows = []


    for site in CALL_SITES:

        off = elf.va_to_offset(
            site
        )

        old_word = u32(
            patched,
            off
        )

        new_word = JAL(
            cave_va
        )

        p32(
            patched,
            off,
            new_word
        )


        patch_rows.append({
            "kind":
                "JAL_HOOK",

            "va":
                f"0x{site:08X}",

            "file_offset":
                f"0x{off:X}",

            "old":
                f"0x{old_word:08X}",

            "new":
                f"0x{new_word:08X}",
        })


    patch_rows.append({
        "kind":
            "CODE_CAVE",

        "va":
            f"0x{cave_va:08X}",

        "file_offset":
            f"0x{cave_off:X}",

        "old":
            f"{len(blob)} zero bytes",

        "new":
            f"{len(blob)} byte hook",
    })


    PATCHED_BOOT.write_bytes(
        patched
    )


    write_tsv(
        OUT
        / "stage24_hook_patch.tsv",
        patch_rows,
        [
            "kind",
            "va",
            "file_offset",
            "old",
            "new",
        ]
    )


    write_tsv(
        OUT
        / "stage24_relocations.tsv",
        relocation_report,
        [
            "callsite",
            "file_offset",
            "original",
            "relocation_info",
        ]
    )


    hook_report = []

    for i, word in enumerate(
        hook_words
    ):

        hook_report.append({
            "index":
                i,

            "va":
                f"0x{cave_va + i*4:08X}",

            "word":
                f"0x{word:08X}",
        })


    write_tsv(
        OUT
        / "stage24_hook_words.tsv",
        hook_report,
        [
            "index",
            "va",
            "word",
        ]
    )


    make_probe_tbl()


    changed = [
        i
        for i, (a, b) in enumerate(
            zip(
                original,
                patched
            )
        )
        if a != b
    ]


    summary = (
        OUT
        / "stage24_hook_summary.txt"
    )


    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 24\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"Original BOOT SHA256: "
            f"{sha256_bytes(original)}\n"
        )

        f.write(
            f"Patched BOOT SHA256:  "
            f"{sha256_bytes(patched)}\n"
        )

        f.write(
            f"Changed BOOT bytes: "
            f"{len(changed)}\n\n"
        )

        f.write(
            f"Code cave VA: "
            f"0x{cave_va:08X}\n"
        )

        f.write(
            f"Code cave file offset: "
            f"0x{cave_off:X}\n"
        )

        f.write(
            f"Code cave available: "
            f"{cave['available']}\n"
        )

        f.write(
            f"Hook size: "
            f"{len(blob)}\\n"
        )

        f.write(
            f"Injection method: "
            f"PT_LOAD file-gap / BSS-backed\\n"
        )

        f.write(
            f"PT_LOAD old p_filesz: "
            f"0x{cave['old_filesz']:X}\\n"
        )

        f.write(
            f"PT_LOAD new p_filesz: "
            f"0x{cave['new_filesz']:X}\\n"
        )

        f.write(
            f"PT_LOAD p_memsz: "
            f"0x{cave['old_memsz']:X}\\n"
        )

        f.write(
            f"File gap available: "
            f"0x{cave['file_gap']:X}\\n"
        )

        f.write(
            f"Unicode table VA: "
            f"0x{table_va:08X}\n\n"
        )

        f.write(
            "Patched parser callsites:\n"
        )

        for site in CALL_SITES:
            f.write(
                f"  0x{site:08X}\n"
            )

        f.write(
            "\nCustom mapping:\n"
        )

        for (
            pair,
            internal,
            char,
            uni
        ) in MAPPING:

            f.write(
                f"  "
                f"{pair.hex(' ').upper()} "
                f"-> 0x{internal:04X} "
                f"-> U+{uni:04X} "
                f"{char}\n"
            )

        f.write(
            "\nSony CP932 F0-F9 free slots: "
            f"{cptbl['f0_f9_free']}\n"
        )


    print()
    print("=" * 72)
    print("STAGE24 HOOK READY")
    print("=" * 72)

    print(
        "Code cave:",
        f"0x{cave_va:08X}",
        f"file=0x{cave_off:X}",
        f"available={cave['available']}"
    )

    print(
        "Hook bytes:",
        len(blob)
    )

    print(
        "Patched callsites:",
        len(CALL_SITES)
    )

    print(
        "Patched BOOT:",
        PATCHED_BOOT
    )

    print(
        "Probe TBL:",
        PATCHED_TBL
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
