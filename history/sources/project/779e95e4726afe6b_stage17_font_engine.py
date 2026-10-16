from pathlib import Path
import csv
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage17"

OUT.mkdir(parents=True, exist_ok=True)


KR_BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

KR_EBOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "EBOOT.BIN"
)

US_BOOT = (
    BASE / "us_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

US_EBOOT = (
    BASE / "us_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "EBOOT.BIN"
)

STAGE9_KR = (
    BASE / "analysis"
    / "stage9"
    / "extracted"
    / "kr"
)

STAGE9_US = (
    BASE / "analysis"
    / "stage9"
    / "extracted"
    / "us"
)


# ============================================================
# PSP sceLibFont NIDs
# ============================================================

FONT_NIDS = {
    0x67F17ED7: "sceFontNewLib",
    0x574B6FBC: "sceFontDoneLib",
    0x48293280: "sceFontSetResolution",
    0x27F6E642: "sceFontGetNumFontList",
    0xBC75D85B: "sceFontGetFontList",
    0x099EF33C: "sceFontFindOptimumFont",
    0x681E61A7: "sceFontFindFont",
    0x2F67356A: "sceFontCalcMemorySize",
    0x5333322D: "sceFontGetFontInfoByIndexNumber",

    0xA834319D: "sceFontOpen",
    0x57FCB733: "sceFontOpenUserFile",
    0xBB8E7FE6: "sceFontOpenUserMemory",

    0x3AEA8CB6: "sceFontClose",
    0x0DA7535E: "sceFontGetFontInfo",
    0xDCC80C2F: "sceFontGetCharInfo",
    0xAA3DE7B5: "sceFontGetShadowInfo",

    0x5C3E4A9E: "sceFontGetCharImageRect",
    0x48B06520: "sceFontGetShadowImageRect",

    0x980F4895: "sceFontGetCharGlyphImage",
    0xCA1E6945: "sceFontGetCharGlyphImage_Clip",

    0x74B21701: "sceFontPixelToPointH",
    0xF8F0752E: "sceFontPixelToPointV",
    0x472694CD: "sceFontPointToPixelH",
    0x3C4B7E82: "sceFontPointToPixelV",

    0xEE232411: "sceFontSetAltCharacterCode",

    0x568BE516: "sceFontGetShadowGlyphImage",
    0x5DCF6858: "sceFontGetShadowGlyphImage_Clip",

    0x02D7F94B: "sceFontFlush",
}


SIGNATURES = {
    "PGF0":
        b"PGF0",

    "sceLibFont":
        b"sceLibFont",

    ".pgf":
        b".pgf",

    "jpn0.pgf":
        b"jpn0.pgf",

    "kr0.pgf":
        b"kr0.pgf",

    "ltn0.pgf":
        b"ltn0.pgf",

    "flash0:/font":
        b"flash0:/font",
}


def u16(data, off):
    return struct.unpack_from(
        "<H", data, off
    )[0]


def u32(data, off):
    return struct.unpack_from(
        "<I", data, off
    )[0]


def s16(v):
    return (
        v - 0x10000
        if v & 0x8000
        else v
    )


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


def find_all(data, needle):
    start = 0

    while True:
        pos = data.find(
            needle,
            start
        )

        if pos < 0:
            break

        yield pos
        start = pos + 1


def read_cstring(data, off):
    if (
        off is None
        or off < 0
        or off >= len(data)
    ):
        return ""

    end = data.find(
        b"\0",
        off
    )

    if end < 0:
        end = min(
            len(data),
            off + 256
        )

    raw = data[
        off:end
    ]

    return raw.decode(
        "ascii",
        errors="replace"
    )


# ============================================================
# ELF32
# ============================================================

class ELF32:

    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()

        if (
            len(self.data) < 52
            or self.data[:4] != b"\x7FELF"
        ):
            raise RuntimeError(
                f"Not ELF: {path}"
            )

        if self.data[4] != 1:
            raise RuntimeError(
                "Not ELF32"
            )

        if self.data[5] != 1:
            raise RuntimeError(
                "Not little-endian ELF"
            )

        self.e_type = u16(
            self.data,
            16
        )

        self.e_machine = u16(
            self.data,
            18
        )

        self.e_entry = u32(
            self.data,
            24
        )

        self.e_phoff = u32(
            self.data,
            28
        )

        self.e_shoff = u32(
            self.data,
            32
        )

        self.e_phentsize = u16(
            self.data,
            42
        )

        self.e_phnum = u16(
            self.data,
            44
        )

        self.e_shentsize = u16(
            self.data,
            46
        )

        self.e_shnum = u16(
            self.data,
            48
        )

        self.e_shstrndx = u16(
            self.data,
            50
        )

        self.sections = []
        self.programs = []

        self._parse_programs()
        self._parse_sections()

    def _parse_programs(self):
        for i in range(
            self.e_phnum
        ):
            off = (
                self.e_phoff
                + i
                * self.e_phentsize
            )

            if off + 32 > len(
                self.data
            ):
                break

            (
                p_type,
                p_offset,
                p_vaddr,
                p_paddr,
                p_filesz,
                p_memsz,
                p_flags,
                p_align,
            ) = struct.unpack_from(
                "<8I",
                self.data,
                off
            )

            self.programs.append({
                "index": i,
                "type": p_type,
                "offset": p_offset,
                "vaddr": p_vaddr,
                "filesz": p_filesz,
                "memsz": p_memsz,
                "flags": p_flags,
                "align": p_align,
            })

    def _parse_sections(self):
        raw_sections = []

        for i in range(
            self.e_shnum
        ):
            off = (
                self.e_shoff
                + i
                * self.e_shentsize
            )

            if off + 40 > len(
                self.data
            ):
                break

            vals = struct.unpack_from(
                "<10I",
                self.data,
                off
            )

            raw_sections.append({
                "index": i,
                "name_off": vals[0],
                "type": vals[1],
                "flags": vals[2],
                "addr": vals[3],
                "offset": vals[4],
                "size": vals[5],
                "link": vals[6],
                "info": vals[7],
                "align": vals[8],
                "entsize": vals[9],
            })

        shstr = b""

        if (
            self.e_shstrndx
            < len(raw_sections)
        ):
            s = raw_sections[
                self.e_shstrndx
            ]

            shstr = self.data[
                s["offset"]:
                s["offset"]
                + s["size"]
            ]

        for s in raw_sections:
            noff = s[
                "name_off"
            ]

            if noff < len(shstr):
                end = shstr.find(
                    b"\0",
                    noff
                )

                if end < 0:
                    end = len(shstr)

                s["name"] = (
                    shstr[
                        noff:end
                    ].decode(
                        "ascii",
                        errors="replace"
                    )
                )

            else:
                s["name"] = ""

            self.sections.append(s)

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s

        return None

    def va_to_offset(self, va):
        # Prefer section mapping.
        for s in self.sections:
            if (
                s["type"] != 8
                and s["size"]
                and s["addr"]
                <= va
                < s["addr"] + s["size"]
            ):
                return (
                    s["offset"]
                    + va
                    - s["addr"]
                )

        # PT_LOAD mapping.
        for p in self.programs:
            if (
                p["type"] == 1
                and p["filesz"]
                and p["vaddr"]
                <= va
                < p["vaddr"]
                + p["filesz"]
            ):
                return (
                    p["offset"]
                    + va
                    - p["vaddr"]
                )

        # Some PSP ELF/PRX structures use
        # effectively file-relative values.
        if 0 <= va < len(self.data):
            return va

        return None

    def read_cstr_va(self, va):
        return read_cstring(
            self.data,
            self.va_to_offset(
                va
            )
        )


# ============================================================
# PSP import table
# ============================================================

def parse_imports(elf):
    sec = elf.section(
        ".lib.stub"
    )

    rows = []

    if sec is None:
        return rows

    pos = sec["offset"]
    end = (
        sec["offset"]
        + sec["size"]
    )

    while (
        pos + 20
        <= end
    ):
        libname_ptr = u32(
            elf.data,
            pos
        )

        version0 = elf.data[
            pos + 4
        ]

        version1 = elf.data[
            pos + 5
        ]

        attribute = u16(
            elf.data,
            pos + 6
        )

        len_words = elf.data[
            pos + 8
        ]

        vstubcount = elf.data[
            pos + 9
        ]

        stubcount = u16(
            elf.data,
            pos + 10
        )

        nidtable = u32(
            elf.data,
            pos + 12
        )

        stubtable = u32(
            elf.data,
            pos + 16
        )

        if (
            libname_ptr == 0
            and len_words == 0
            and stubcount == 0
        ):
            pos += 4
            continue

        entry_size = (
            len_words * 4
        )

        if (
            entry_size < 20
            or entry_size > 64
            or pos
            + entry_size
            > end
        ):
            pos += 4
            continue

        libname = (
            elf.read_cstr_va(
                libname_ptr
            )
        )

        nid_off = (
            elf.va_to_offset(
                nidtable
            )
        )

        nids = []

        if nid_off is not None:
            for i in range(
                stubcount
            ):
                p = (
                    nid_off
                    + i * 4
                )

                if p + 4 > len(
                    elf.data
                ):
                    break

                nid = u32(
                    elf.data,
                    p
                )

                nids.append(nid)

                rows.append({
                    "library":
                        libname,

                    "stub_index":
                        i,

                    "nid":
                        nid,

                    "nid_hex":
                        f"0x{nid:08X}",

                    "known_name":
                        FONT_NIDS.get(
                            nid,
                            ""
                        ),

                    "stub_va":
                        (
                            stubtable
                            + i * 8
                        ),

                    "stub_va_hex":
                        (
                            f"0x"
                            f"{stubtable + i*8:08X}"
                        ),

                    "stub_record_file_off":
                        pos,

                    "len_words":
                        len_words,

                    "stubcount":
                        stubcount,

                    "vstubcount":
                        vstubcount,

                    "version":
                        (
                            f"{version0}."
                            f"{version1}"
                        ),

                    "attribute_hex":
                        f"0x{attribute:04X}",
                })

        pos += entry_size

    return rows


# ============================================================
# Minimal MIPS disassembly
# ============================================================

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


def decode_mips(
    ins,
    pc,
    known_targets=None
):
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

    if ins == 0:
        return "nop"

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

        if fn == 0x08:
            return f"jr {REG[rs]}"

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

        if fn == 0x21:
            return (
                f"addu {REG[rd]},"
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

    if op in (2, 3):
        target = (
            ((pc + 4) & 0xF0000000)
            |
            ((ins & 0x03FFFFFF) << 2)
        )

        name = ""

        if known_targets:
            name = known_targets.get(
                target,
                ""
            )

        opname = (
            "j"
            if op == 2
            else "jal"
        )

        if name:
            return (
                f"{opname} "
                f"0x{target:08X} "
                f"<{name}>"
            )

        return (
            f"{opname} "
            f"0x{target:08X}"
        )

    if op == 4:
        target = (
            pc + 4
            + (simm << 2)
        )

        return (
            f"beq {REG[rs]},"
            f"{REG[rt]},"
            f"0x{target:08X}"
        )

    if op == 5:
        target = (
            pc + 4
            + (simm << 2)
        )

        return (
            f"bne {REG[rs]},"
            f"{REG[rt]},"
            f"0x{target:08X}"
        )

    if op == 6:
        target = (
            pc + 4
            + (simm << 2)
        )

        return (
            f"blez {REG[rs]},"
            f"0x{target:08X}"
        )

    if op == 7:
        target = (
            pc + 4
            + (simm << 2)
        )

        return (
            f"bgtz {REG[rs]},"
            f"0x{target:08X}"
        )

    if op == 8:
        return (
            f"addi {REG[rt]},"
            f"{REG[rs]},"
            f"{simm}"
        )

    if op == 9:
        return (
            f"addiu {REG[rt]},"
            f"{REG[rs]},"
            f"{simm}"
        )

    if op == 0x0A:
        return (
            f"slti {REG[rt]},"
            f"{REG[rs]},"
            f"{simm}"
        )

    if op == 0x0B:
        return (
            f"sltiu {REG[rt]},"
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

    memops = {
        0x20: "lb",
        0x21: "lh",
        0x23: "lw",
        0x24: "lbu",
        0x25: "lhu",
        0x28: "sb",
        0x29: "sh",
        0x2B: "sw",
    }

    if op in memops:
        return (
            f"{memops[op]} "
            f"{REG[rt]},"
            f"{simm}({REG[rs]})"
        )

    return (
        f".word 0x{ins:08X}"
    )


# ============================================================
# Callsite scan
# ============================================================

def guess_function_start(
    elf,
    section,
    call_off
):
    lower = max(
        section["offset"],
        call_off - 0x400
    )

    p = call_off

    while p >= lower:
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

        # addiu sp,sp,-N
        if (
            op == 9
            and rs == 29
            and rt == 29
            and imm < 0
        ):
            return (
                section["addr"]
                + p
                - section["offset"]
            )

        p -= 4

    return None


def find_callsites(
    elf,
    imports
):
    stub_names = {}

    for r in imports:
        if r["known_name"]:
            stub_names[
                r["stub_va"]
            ] = (
                r["known_name"]
            )

    calls = []

    if not stub_names:
        return calls, stub_names

    for sec in elf.sections:
        # SHF_EXECINSTR
        if not (
            sec["flags"]
            & 0x4
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
                        (ins
                         & 0x03FFFFFF)
                        << 2
                    )
                )

                if target in stub_names:
                    fstart = (
                        guess_function_start(
                            elf,
                            sec,
                            p
                        )
                    )

                    calls.append({
                        "section":
                            sec["name"],

                        "file_offset":
                            p,

                        "file_offset_hex":
                            f"0x{p:X}",

                        "call_va":
                            pc,

                        "call_va_hex":
                            f"0x{pc:08X}",

                        "target_va":
                            target,

                        "target_va_hex":
                            f"0x{target:08X}",

                        "function":
                            stub_names[
                                target
                            ],

                        "caller_start_guess":
                            (
                                ""
                                if fstart
                                is None
                                else
                                f"0x{fstart:08X}"
                            ),
                    })

            p += 4

    return calls, stub_names


def make_call_context(
    elf,
    calls,
    stub_names
):
    lines = []

    sec_by_name = {
        x["name"]: x
        for x in elf.sections
    }

    for index, call in enumerate(
        calls,
        1
    ):
        sec = sec_by_name[
            call["section"]
        ]

        call_off = call[
            "file_offset"
        ]

        start = max(
            sec["offset"],
            call_off - 20 * 4
        )

        end = min(
            sec["offset"]
            + sec["size"],
            call_off + 11 * 4
        )

        lines.append(
            "=" * 78
        )

        lines.append(
            f"CALL {index}: "
            f"{call['function']} "
            f"at {call['call_va_hex']} "
            f"(file {call['file_offset_hex']})"
        )

        lines.append(
            f"caller_start_guess="
            f"{call['caller_start_guess']}"
        )

        lines.append(
            "=" * 78
        )

        p = start

        while p + 4 <= end:
            pc = (
                sec["addr"]
                + p
                - sec["offset"]
            )

            ins = u32(
                elf.data,
                p
            )

            mark = (
                ">>>"
                if p == call_off
                else "   "
            )

            lines.append(
                f"{mark} "
                f"0x{pc:08X}: "
                f"{ins:08X}  "
                f"{decode_mips(ins, pc, stub_names)}"
            )

            p += 4

        lines.append("")

    return "\n".join(lines)


# ============================================================
# Raw NID fallback
# ============================================================

def raw_nid_hits(
    region,
    path
):
    rows = []

    if not path.exists():
        return rows

    data = path.read_bytes()

    for nid, name in (
        FONT_NIDS.items()
    ):
        needle = struct.pack(
            "<I",
            nid
        )

        for pos in find_all(
            data,
            needle
        ):
            rows.append({
                "region":
                    region,

                "file":
                    path.name,

                "nid":
                    f"0x{nid:08X}",

                "function":
                    name,

                "file_offset":
                    pos,

                "file_offset_hex":
                    f"0x{pos:X}",
            })

    return rows


# ============================================================
# Full resource signature scan
# ============================================================

def signature_scan():
    rows = []

    roots = [
        (
            "KR_BOOT",
            KR_BOOT
        ),
        (
            "KR_EBOOT",
            KR_EBOOT
        ),
        (
            "US_BOOT",
            US_BOOT
        ),
        (
            "US_EBOOT",
            US_EBOOT
        ),
    ]

    for label, path in roots:
        if not path.exists():
            continue

        data = path.read_bytes()
        low = data.lower()

        for sig_name, needle in (
            SIGNATURES.items()
        ):
            hay = (
                low
                if (
                    sig_name
                    in (
                        ".pgf",
                        "jpn0.pgf",
                        "kr0.pgf",
                        "ltn0.pgf",
                        "flash0:/font",
                    )
                )
                else data
            )

            n = (
                needle.lower()
                if hay is low
                else needle
            )

            for pos in find_all(
                hay,
                n
            ):
                rows.append({
                    "region":
                        label,

                    "file":
                        str(path),

                    "signature":
                        sig_name,

                    "offset":
                        pos,

                    "offset_hex":
                        f"0x{pos:X}",
                })

    resource_sets = [
        (
            "KR_RESOURCE",
            STAGE9_KR
        ),
        (
            "US_RESOURCE",
            STAGE9_US
        ),
    ]

    for label, root in (
        resource_sets
    ):
        if not root.exists():
            print(
                f"[signature] "
                f"{root} 없음 - skip"
            )

            continue

        files = [
            p
            for p in root.rglob("*")
            if p.is_file()
        ]

        total = len(files)

        for i, path in enumerate(
            files,
            1
        ):
            data = path.read_bytes()
            low = data.lower()

            for sig_name, needle in (
                SIGNATURES.items()
            ):
                hay = (
                    low
                    if (
                        sig_name
                        in (
                            ".pgf",
                            "jpn0.pgf",
                            "kr0.pgf",
                            "ltn0.pgf",
                            "flash0:/font",
                        )
                    )
                    else data
                )

                n = (
                    needle.lower()
                    if hay is low
                    else needle
                )

                hit_count = 0

                for pos in find_all(
                    hay,
                    n
                ):
                    rows.append({
                        "region":
                            label,

                        "file":
                            str(path),

                        "signature":
                            sig_name,

                        "offset":
                            pos,

                        "offset_hex":
                            f"0x{pos:X}",
                    })

                    hit_count += 1

                    if hit_count >= 50:
                        break

            if (
                i % 100 == 0
                or i == total
            ):
                print(
                    f"[signature] "
                    f"{label} "
                    f"{i}/{total}"
                )

    return rows


# ============================================================
# Region analysis
# ============================================================

def analyze_boot(
    region,
    path
):
    if not path.exists():
        return {
            "imports": [],
            "calls": [],
            "sections": [],
            "context": (
                f"{path} 없음"
            ),
        }

    print()
    print(
        f"[{region}] ELF parse: "
        f"{path}"
    )

    elf = ELF32(path)

    sections = []

    for s in elf.sections:
        sections.append({
            "region":
                region,

            "name":
                s["name"],

            "type":
                s["type"],

            "flags_hex":
                f"0x{s['flags']:X}",

            "addr_hex":
                f"0x{s['addr']:08X}",

            "offset_hex":
                f"0x{s['offset']:X}",

            "size":
                s["size"],

            "size_hex":
                f"0x{s['size']:X}",
        })

    imports = parse_imports(
        elf
    )

    font_imports = [
        r
        for r in imports
        if (
            "font"
            in r[
                "library"
            ].lower()
            or r[
                "nid"
            ] in FONT_NIDS
        )
    ]

    calls, stub_names = (
        find_callsites(
            elf,
            font_imports
        )
    )

    for r in font_imports:
        r["region"] = region

    for r in calls:
        r["region"] = region

    context = (
        make_call_context(
            elf,
            calls,
            stub_names
        )
    )

    print(
        f"[{region}] "
        f"font imports: "
        f"{len(font_imports)}"
    )

    print(
        f"[{region}] "
        f"font callsites: "
        f"{len(calls)}"
    )

    return {
        "imports":
            font_imports,

        "calls":
            calls,

        "sections":
            sections,

        "context":
            context,
    }


# ============================================================
# main
# ============================================================

def main():
    print("=" * 72)
    print("Naruto PSP Stage 17")
    print("Font engine / sceLibFont tracing")
    print("=" * 72)

    kr = analyze_boot(
        "KR",
        KR_BOOT
    )

    us = analyze_boot(
        "US",
        US_BOOT
    )

    imports = (
        kr["imports"]
        + us["imports"]
    )

    calls = (
        kr["calls"]
        + us["calls"]
    )

    sections = (
        kr["sections"]
        + us["sections"]
    )

    raw_hits = []

    raw_hits += raw_nid_hits(
        "KR",
        KR_BOOT
    )

    raw_hits += raw_nid_hits(
        "US",
        US_BOOT
    )

    print()
    print(
        "[signature] "
        "PGF/font signatures scan"
    )

    sig_hits = signature_scan()

    # --------------------------------------------------------
    # reports
    # --------------------------------------------------------

    write_tsv(
        OUT / "elf_sections.tsv",
        sections,
        [
            "region",
            "name",
            "type",
            "flags_hex",
            "addr_hex",
            "offset_hex",
            "size",
            "size_hex",
        ]
    )

    write_tsv(
        OUT / "font_imports.tsv",
        imports,
        [
            "region",
            "library",
            "stub_index",
            "nid",
            "nid_hex",
            "known_name",
            "stub_va",
            "stub_va_hex",
            "stub_record_file_off",
            "len_words",
            "stubcount",
            "vstubcount",
            "version",
            "attribute_hex",
        ]
    )

    write_tsv(
        OUT / "font_callsites.tsv",
        calls,
        [
            "region",
            "section",
            "file_offset",
            "file_offset_hex",
            "call_va",
            "call_va_hex",
            "target_va",
            "target_va_hex",
            "function",
            "caller_start_guess",
        ]
    )

    write_tsv(
        OUT / "raw_font_nid_hits.tsv",
        raw_hits,
        [
            "region",
            "file",
            "nid",
            "function",
            "file_offset",
            "file_offset_hex",
        ]
    )

    write_tsv(
        OUT / "font_signature_hits.tsv",
        sig_hits,
        [
            "region",
            "file",
            "signature",
            "offset",
            "offset_hex",
        ]
    )

    context_file = (
        OUT
        / "font_callsites.txt"
    )

    context_file.write_text(
        (
            "===== KR =====\n\n"
            + kr["context"]
            + "\n\n"
            + "===== US =====\n\n"
            + us["context"]
            + "\n"
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # summary
    # --------------------------------------------------------

    def imported(name, region):
        return any(
            r[
                "region"
            ] == region
            and r[
                "known_name"
            ] == name
            for r in imports
        )

    pgf_hits = [
        r
        for r in sig_hits
        if r["signature"] == "PGF0"
    ]

    custom_open_kr = (
        imported(
            "sceFontOpenUserFile",
            "KR"
        )
        or imported(
            "sceFontOpenUserMemory",
            "KR"
        )
    )

    system_open_kr = imported(
        "sceFontOpen",
        "KR"
    )

    glyph_kr = (
        imported(
            "sceFontGetCharGlyphImage",
            "KR"
        )
        or imported(
            "sceFontGetCharGlyphImage_Clip",
            "KR"
        )
    )

    summary = (
        OUT
        / "stage17_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "Naruto PSP Stage 17\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"KR font imports: "
            f"{sum(1 for r in imports if r['region']=='KR')}\n"
        )

        f.write(
            f"US font imports: "
            f"{sum(1 for r in imports if r['region']=='US')}\n"
        )

        f.write(
            f"KR font callsites: "
            f"{sum(1 for r in calls if r['region']=='KR')}\n"
        )

        f.write(
            f"US font callsites: "
            f"{sum(1 for r in calls if r['region']=='US')}\n\n"
        )

        f.write(
            f"KR sceFontOpen imported: "
            f"{system_open_kr}\n"
        )

        f.write(
            f"KR OpenUserFile/OpenUserMemory imported: "
            f"{custom_open_kr}\n"
        )

        f.write(
            f"KR GetCharGlyphImage imported: "
            f"{glyph_kr}\n\n"
        )

        f.write(
            f"PGF0 signatures found: "
            f"{len(pgf_hits)}\n"
        )

        for r in pgf_hits[:50]:
            f.write(
                f"  {r['region']} "
                f"{r['file']} "
                f"{r['offset_hex']}\n"
            )

        f.write("\n")

        f.write(
            "KR imported font functionLOCAL_PATH"
        )

        for r in imports:
            if (
                r["region"] == "KR"
            ):
                f.write(
                    f"  {r['known_name'] or r['nid_hex']} "
                    f"stub={r['stub_va_hex']}\n"
                )

        f.write("\n")

        f.write(
            "KR font callsite countLOCAL_PATH"
        )

        names = sorted({
            r["function"]
            for r in calls
            if r["region"] == "KR"
        })

        for name in names:
            count = sum(
                1
                for r in calls
                if (
                    r["region"] == "KR"
                    and r["function"] == name
                )
            )

            f.write(
                f"  {name}: "
                f"{count}\n"
            )

    print()
    print("=" * 72)
    print("STAGE 17 COMPLETE")
    print("=" * 72)

    print(
        "KR font imports:",
        sum(
            1
            for r in imports
            if r["region"] == "KR"
        )
    )

    print(
        "KR font callsites:",
        sum(
            1
            for r in calls
            if r["region"] == "KR"
        )
    )

    print(
        "PGF0 hits:",
        len(pgf_hits)
    )

    print(
        "sceFontOpen:",
        system_open_kr
    )

    print(
        "OpenUserFile/Memory:",
        custom_open_kr
    )

    print(
        "GetCharGlyphImage:",
        glyph_kr
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
