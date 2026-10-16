from pathlib import Path
import struct
import csv
import hashlib
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage4"
STAGE3_SHARE = BASE / "analysis" / "stage3" / "share"

OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "KR_BOOT": BASE / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
    "KR_EBOOT": BASE / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN",
    "US_BOOT": BASE / "us_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
    "US_EBOOT": BASE / "us_extracted" / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN",
}

SIGNATURES = {
    "PIDX0": b"PIDX0",
    "3_0": b" 3;0",
    "3_1": b" 3;1",
    "SEGS": b"segs",
    "CCS": b"CCS",
}

CONSTANTS = {
    "PIDX_LE32": 0x58444950,   # bytes: 50 49 44 58 = PIDX
    "3_0_LE32":  0x303B3320,   # bytes: 20 33 3B 30
    "3_1_LE32":  0x313B3320,   # bytes: 20 33 3B 31
    "SEGS_LE32": 0x73676573,
}


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def find_all(data, needle):
    out = []
    pos = 0

    while True:
        pos = data.find(needle, pos)

        if pos < 0:
            break

        out.append(pos)
        pos += 1

    return out


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


# ============================================================
# ELF parser
# ============================================================

def parse_elf(data):

    result = {
        "is_elf": False,
        "entry": None,
        "phoff": None,
        "phnum": None,
        "shoff": None,
        "shnum": None,
        "segments": [],
        "sections": [],
    }

    if len(data) < 52:
        return result

    if data[:4] != b"\x7fELF":
        return result

    # PSP = ELF32 little endian
    if data[4] != 1 or data[5] != 1:
        return result

    result["is_elf"] = True

    e_entry = u32(data, 0x18)
    e_phoff = u32(data, 0x1C)
    e_shoff = u32(data, 0x20)

    e_phentsize = u16(data, 0x2A)
    e_phnum = u16(data, 0x2C)

    e_shentsize = u16(data, 0x2E)
    e_shnum = u16(data, 0x30)
    e_shstrndx = u16(data, 0x32)

    result["entry"] = e_entry
    result["phoff"] = e_phoff
    result["phnum"] = e_phnum
    result["shoff"] = e_shoff
    result["shnum"] = e_shnum

    for i in range(e_phnum):

        off = e_phoff + i * e_phentsize

        if off + 32 > len(data):
            continue

        (
            p_type,
            p_offset,
            p_vaddr,
            p_paddr,
            p_filesz,
            p_memsz,
            p_flags,
            p_align,
        ) = struct.unpack_from("<8I", data, off)

        result["segments"].append({
            "index": i,
            "type": p_type,
            "offset": p_offset,
            "vaddr": p_vaddr,
            "filesz": p_filesz,
            "memsz": p_memsz,
            "flags": p_flags,
            "align": p_align,
        })

    # section names
    raw_sections = []

    for i in range(e_shnum):

        off = e_shoff + i * e_shentsize

        if off + 40 > len(data):
            continue

        values = struct.unpack_from("<10I", data, off)

        raw_sections.append({
            "index": i,
            "name_off": values[0],
            "type": values[1],
            "flags": values[2],
            "addr": values[3],
            "offset": values[4],
            "size": values[5],
        })

    names = b""

    if 0 <= e_shstrndx < len(raw_sections):

        sec = raw_sections[e_shstrndx]

        start = sec["offset"]
        end = start + sec["size"]

        if end <= len(data):
            names = data[start:end]

    for sec in raw_sections:

        n = sec["name_off"]

        if n < len(names):

            end = names.find(b"\0", n)

            if end < 0:
                end = len(names)

            name = names[n:end].decode(
                "ascii",
                errors="replace"
            )

        else:
            name = ""

        sec["name"] = name

        result["sections"].append(sec)

    return result


def fileoff_to_va(elf, off):

    if not elf["is_elf"]:
        return None

    for seg in elf["segments"]:

        if seg["type"] != 1:
            continue

        start = seg["offset"]
        end = start + seg["filesz"]

        if start <= off < end:

            return (
                seg["vaddr"]
                + (off - start)
            )

    return None


def va_to_fileoff(elf, va):

    if not elf["is_elf"]:
        return None

    for seg in elf["segments"]:

        if seg["type"] != 1:
            continue

        start = seg["vaddr"]
        end = start + seg["filesz"]

        if start <= va < end:

            return (
                seg["offset"]
                + (va - start)
            )

    return None


# ============================================================
# minimal MIPS decoder
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


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def decode_mips(word, pc):

    op = (word >> 26) & 0x3F

    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F

    imm = word & 0xFFFF

    if word == 0:
        return "nop"

    if op == 0:

        funct = word & 0x3F

        if funct == 0x08:
            return f"jr ${REG[rs]}"

        if funct == 0x09:
            return f"jalr ${REG[rd]},${REG[rs]}"

        if funct == 0x21:
            return f"addu ${REG[rd]},${REG[rs]},${REG[rt]}"

        if funct == 0x23:
            return f"subu ${REG[rd]},${REG[rs]},${REG[rt]}"

        if funct == 0x00:
            sa = (word >> 6) & 0x1F
            return f"sll ${REG[rd]},${REG[rt]},{sa}"

    if op == 0x0F:
        return f"lui ${REG[rt]},0x{imm:04X}"

    if op == 0x0D:
        return f"ori ${REG[rt]},${REG[rs]},0x{imm:04X}"

    if op == 0x09:
        return f"addiu ${REG[rt]},${REG[rs]},{s16(imm)}"

    if op == 0x23:
        return f"lw ${REG[rt]},{s16(imm)}(${REG[rs]})"

    if op == 0x2B:
        return f"sw ${REG[rt]},{s16(imm)}(${REG[rs]})"

    if op == 0x20:
        return f"lb ${REG[rt]},{s16(imm)}(${REG[rs]})"

    if op == 0x24:
        return f"lbu ${REG[rt]},{s16(imm)}(${REG[rs]})"

    if op == 0x28:
        return f"sb ${REG[rt]},{s16(imm)}(${REG[rs]})"

    if op == 0x04:

        target = pc + 4 + (s16(imm) << 2)

        return (
            f"beq ${REG[rs]},${REG[rt]},"
            f"0x{target:08X}"
        )

    if op == 0x05:

        target = pc + 4 + (s16(imm) << 2)

        return (
            f"bne ${REG[rs]},${REG[rt]},"
            f"0x{target:08X}"
        )

    if op == 0x02:

        target = (
            ((pc + 4) & 0xF0000000)
            | ((word & 0x03FFFFFF) << 2)
        )

        return f"j 0x{target:08X}"

    if op == 0x03:

        target = (
            ((pc + 4) & 0xF0000000)
            | ((word & 0x03FFFFFF) << 2)
        )

        return f"jal 0x{target:08X}"

    return f".word 0x{word:08X}"


# ============================================================
# 32bit constant-load detection
# ============================================================

def find_constant_loads(data, elf, wanted):

    hits = []

    # MIPS instructions are 4-byte aligned
    for off in range(0, len(data) - 8, 4):

        w1 = u32(data, off)

        op1 = (w1 >> 26) & 0x3F

        if op1 != 0x0F:
            continue

        rt1 = (w1 >> 16) & 0x1F
        hi = w1 & 0xFFFF

        # check next 1..4 instructions
        for step in range(1, 5):

            off2 = off + step * 4

            if off2 + 4 > len(data):
                break

            w2 = u32(data, off2)

            op2 = (w2 >> 26) & 0x3F

            rs2 = (w2 >> 21) & 0x1F
            rt2 = (w2 >> 16) & 0x1F

            lo = w2 & 0xFFFF

            if rt2 != rt1 or rs2 != rt1:
                continue

            value = None
            kind = None

            if op2 == 0x0D:  # ori

                value = (
                    (hi << 16)
                    | lo
                )

                kind = "LUI+ORI"

            elif op2 == 0x09:  # addiu

                value = (
                    ((hi << 16) + s16(lo))
                    & 0xFFFFFFFF
                )

                kind = "LUI+ADDIU"

            if value == wanted:

                hits.append({
                    "file_offset": off,
                    "file_offset2": off2,
                    "va": fileoff_to_va(
                        elf,
                        off
                    ),
                    "reg": REG[rt1],
                    "kind": kind,
                    "value": value,
                })

    return hits


def disasm_context(data, elf, center, before=20, after=40):

    start = max(
        0,
        center - before * 4
    )

    start &= ~3

    end = min(
        len(data),
        center + after * 4
    )

    out = []

    for off in range(start, end, 4):

        if off + 4 > len(data):
            break

        word = u32(data, off)

        va = fileoff_to_va(
            elf,
            off
        )

        pc = (
            va
            if va is not None
            else off
        )

        marker = ">>" if off == center else "  "

        out.append(
            f"{marker} "
            f"OFF 0x{off:08X} "
            f"VA 0x{pc:08X}  "
            f"{word:08X}  "
            f"{decode_mips(word, pc)}"
        )

    return "\n".join(out)


# ============================================================
# Share sample 3;x headers
# ============================================================

def scan_stage3_samples():

    rows = []

    if not STAGE3_SHARE.exists():
        return rows

    for p in sorted(
        STAGE3_SHARE.iterdir()
    ):

        if not p.is_file():
            continue

        data = p.read_bytes()

        if len(data) < 8:
            continue

        sig = data[:4]

        if sig not in (
            b" 3;0",
            b" 3;1"
        ):
            continue

        unpacked = u32(data, 4)

        rows.append({
            "name": p.name,
            "compressed_file_size": len(data),
            "signature": sig.decode(
                "ascii",
                errors="replace"
            ),
            "unpacked_size_field": unpacked,
            "payload_size": len(data) - 8,
            "ratio": (
                round(
                    len(data) / unpacked,
                    4
                )
                if unpacked
                else 0
            ),
            "first32":
                data[:32].hex(" "),
        })

    return rows


# ============================================================
# MAIN
# ============================================================

def main():

    summary = []

    elf_rows = []
    sig_rows = []
    const_rows = []
    xref_rows = []

    print("=" * 72)
    print("Naruto PSP Stage 4")
    print("BOOT/EBOOT compression routine search")
    print("=" * 72)

    for label, path in FILES.items():

        print()
        print(f"[{label}]")

        if not path.exists():

            print("MISSING")

            summary.append(
                f"{label}: MISSING"
            )

            continue

        data = path.read_bytes()

        sha = sha256_file(path)

        elf = parse_elf(data)

        print("Path   :", path)
        print("Size   :", len(data))
        print("SHA256 :", sha)
        print("ELF    :", elf["is_elf"])

        summary.append(
            f"{label}: size={len(data)} "
            f"ELF={elf['is_elf']} "
            f"SHA256={sha}"
        )

        if elf["is_elf"]:

            print(
                "Entry  :",
                f'0x{elf["entry"]:08X}'
            )

            print(
                "Segments:",
                len(elf["segments"])
            )

            print(
                "Sections:",
                len(elf["sections"])
            )

        # ELF segments
        for seg in elf["segments"]:

            elf_rows.append({
                "binary": label,
                "kind": "SEGMENT",
                "index": seg["index"],
                "name": "",
                "type": seg["type"],
                "flags": f'0x{seg["flags"]:X}',
                "file_offset": f'0x{seg["offset"]:X}',
                "vaddr": f'0x{seg["vaddr"]:08X}',
                "size": seg["filesz"],
                "mem_size": seg["memsz"],
            })

        # ELF sections
        for sec in elf["sections"]:

            elf_rows.append({
                "binary": label,
                "kind": "SECTION",
                "index": sec["index"],
                "name": sec["name"],
                "type": sec["type"],
                "flags": f'0x{sec["flags"]:X}',
                "file_offset": f'0x{sec["offset"]:X}',
                "vaddr": f'0x{sec["addr"]:08X}',
                "size": sec["size"],
                "mem_size": "",
            })

        # literal signature search
        print()
        print("Literal signatures:")

        for sig_name, sig in SIGNATURES.items():

            hits = find_all(
                data,
                sig
            )

            print(
                f"  {sig_name}: {len(hits)}"
            )

            for off in hits:

                va = fileoff_to_va(
                    elf,
                    off
                )

                sig_rows.append({
                    "binary": label,
                    "signature": sig_name,
                    "file_offset":
                        f"0x{off:X}",
                    "virtual_address":
                        (
                            f"0x{va:08X}"
                            if va is not None
                            else ""
                        ),
                })

        # constant load search
        print()
        print("MIPS constant loaders:")

        for const_name, value in CONSTANTS.items():

            hits = find_constant_loads(
                data,
                elf,
                value
            )

            print(
                f"  {const_name}: "
                f"{len(hits)}"
            )

            for index, h in enumerate(hits):

                const_rows.append({
                    "binary": label,
                    "constant": const_name,
                    "value":
                        f"0x{value:08X}",
                    "file_offset":
                        f'0x{h["file_offset"]:X}',
                    "virtual_address":
                        (
                            f'0x{h["va"]:08X}'
                            if h["va"] is not None
                            else ""
                        ),
                    "register": h["reg"],
                    "load_type": h["kind"],
                })

                ctx_name = (
                    f"{label}"
                    f"__{const_name}"
                    f"__{index:03d}"
                    f"__0x{h['file_offset']:X}"
                    f".txt"
                )

                ctx = disasm_context(
                    data,
                    elf,
                    h["file_offset"],
                    24,
                    48
                )

                (
                    OUT / ctx_name
                ).write_text(
                    ctx,
                    encoding="utf-8"
                )

                xref_rows.append({
                    "binary": label,
                    "constant": const_name,
                    "context_file": ctx_name,
                    "file_offset":
                        f'0x{h["file_offset"]:X}',
                    "virtual_address":
                        (
                            f'0x{h["va"]:08X}'
                            if h["va"] is not None
                            else ""
                        ),
                })

        # ====================================================
        # xrefs to literal signatures using loaded VA
        # ====================================================

        if elf["is_elf"]:

            for sig_name, sig in SIGNATURES.items():

                for sig_off in find_all(
                    data,
                    sig
                ):

                    sig_va = fileoff_to_va(
                        elf,
                        sig_off
                    )

                    if sig_va is None:
                        continue

                    refs = find_constant_loads(
                        data,
                        elf,
                        sig_va
                    )

                    for index, h in enumerate(refs):

                        context_name = (
                            f"{label}"
                            f"__XREF_{sig_name}"
                            f"__0x{sig_va:08X}"
                            f"__{index:03d}.txt"
                        )

                        (
                            OUT / context_name
                        ).write_text(
                            disasm_context(
                                data,
                                elf,
                                h["file_offset"],
                                32,
                                64
                            ),
                            encoding="utf-8"
                        )

                        xref_rows.append({
                            "binary": label,
                            "constant":
                                f"XREF_{sig_name}"
                                f"_VA_0x{sig_va:08X}",
                            "context_file":
                                context_name,
                            "file_offset":
                                f'0x{h["file_offset"]:X}',
                            "virtual_address":
                                (
                                    f'0x{h["va"]:08X}'
                                    if h["va"] is not None
                                    else ""
                                ),
                        })

    # ========================================================
    # Stage3 compressed sample headers
    # ========================================================

    sample_rows = scan_stage3_samples()

    print()
    print(
        "Stage3 3;x samples:",
        len(sample_rows)
    )

    # ========================================================
    # write reports
    # ========================================================

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
                w.writerow(row)

    write_tsv(
        OUT / "elf_layout.tsv",
        elf_rows,
        [
            "binary",
            "kind",
            "index",
            "name",
            "type",
            "flags",
            "file_offset",
            "vaddr",
            "size",
            "mem_size",
        ]
    )

    write_tsv(
        OUT / "literal_signatures.tsv",
        sig_rows,
        [
            "binary",
            "signature",
            "file_offset",
            "virtual_address",
        ]
    )

    write_tsv(
        OUT / "constant_loads.tsv",
        const_rows,
        [
            "binary",
            "constant",
            "value",
            "file_offset",
            "virtual_address",
            "register",
            "load_type",
        ]
    )

    write_tsv(
        OUT / "xref_contexts.tsv",
        xref_rows,
        [
            "binary",
            "constant",
            "context_file",
            "file_offset",
            "virtual_address",
        ]
    )

    write_tsv(
        OUT / "compressed_samples.tsv",
        sample_rows,
        [
            "name",
            "compressed_file_size",
            "signature",
            "unpacked_size_field",
            "payload_size",
            "ratio",
            "first32",
        ]
    )

    summary_path = (
        OUT / "stage4_summary.txt"
    )

    with summary_path.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 4\n"
        )

        f.write(
            "=" * 70
            + "\n\n"
        )

        for line in summary:
            f.write(line + "\n")

        f.write("\n")

        f.write(
            f"Literal signature hits: "
            f"{len(sig_rows)}\n"
        )

        f.write(
            f"Constant-load hits: "
            f"{len(const_rows)}\n"
        )

        f.write(
            f"Generated xref contexts: "
            f"{len(xref_rows)}\n"
        )

        f.write(
            f"3;x compressed samples: "
            f"{len(sample_rows)}\n"
        )

        f.write("\nInteresting constant summarLOCAL_PATH")

        for name in CONSTANTS:

            n = sum(
                1
                for r in const_rows
                if r["constant"] == name
            )

            f.write(
                f"  {name}: {n}\n"
            )

        f.write("\nLiteral summarLOCAL_PATH")

        for name in SIGNATURES:

            n = sum(
                1
                for r in sig_rows
                if r["signature"] == name
            )

            f.write(
                f"  {name}: {n}\n"
            )

    print()
    print("=" * 72)
    print("Stage 4 complete")
    print("=" * 72)

    print(
        "Literal hits :",
        len(sig_rows)
    )

    print(
        "Const loads  :",
        len(const_rows)
    )

    print(
        "Xref contexts:",
        len(xref_rows)
    )

    print(
        "3;x samples  :",
        len(sample_rows)
    )

    print()
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
