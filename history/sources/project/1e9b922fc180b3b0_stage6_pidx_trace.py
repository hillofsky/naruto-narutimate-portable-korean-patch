from pathlib import Path
import struct
import csv
import math
import bisect
import sys
import traceback
from collections import defaultdict, deque, Counter

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage6"

OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "KR_BOOT": BASE / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
    "US_BOOT": BASE / "us_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
}

# Stage5에서 특히 의심되는 US 함수
US_TARGETS = [
    0x0005066C,
    0x000534B8,
    0x00053A60,
    0x000554E4,
    0x0005F9DC,
    0x0005FC68,
]

# 0x5F9DC에서 확인된 PIDX 전역 변수
PIDX_GLOBALS = {
    0x00436F80: "PIDX_BASE",
    0x00436F84: "PIDX_INFO_TABLE",
    0x00436F88: "PIDX_HEADER_14",
    0x00436F8C: "PIDX_OFFSET2_TABLE",
    0x00436F90: "PIDX_OFFSET2_COUNT",
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


def u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def parse_elf(data):

    if (
        len(data) < 52
        or data[:4] != b"\x7fELF"
        or data[4] != 1
        or data[5] != 1
    ):
        raise RuntimeError("ELF32 LE가 아닙니다")

    result = {
        "entry": u32(data, 0x18),
        "segments": [],
        "sections": [],
    }

    phoff = u32(data, 0x1C)
    shoff = u32(data, 0x20)

    phentsize = u16(data, 0x2A)
    phnum = u16(data, 0x2C)

    shentsize = u16(data, 0x2E)
    shnum = u16(data, 0x30)
    shstrndx = u16(data, 0x32)

    for i in range(phnum):

        o = phoff + i * phentsize

        if o + 32 > len(data):
            break

        v = struct.unpack_from("<8I", data, o)

        result["segments"].append({
            "type": v[0],
            "offset": v[1],
            "vaddr": v[2],
            "filesz": v[4],
            "memsz": v[5],
            "flags": v[6],
        })

    raw = []

    for i in range(shnum):

        o = shoff + i * shentsize

        if o + 40 > len(data):
            break

        v = struct.unpack_from("<10I", data, o)

        raw.append({
            "index": i,
            "name_off": v[0],
            "type": v[1],
            "flags": v[2],
            "addr": v[3],
            "offset": v[4],
            "size": v[5],
        })

    names = b""

    if 0 <= shstrndx < len(raw):

        s = raw[shstrndx]

        names = data[
            s["offset"]:
            s["offset"] + s["size"]
        ]

    for s in raw:

        n = s["name_off"]

        if n < len(names):

            e = names.find(b"\0", n)

            if e < 0:
                e = len(names)

            s["name"] = names[n:e].decode(
                "ascii",
                errors="replace"
            )

        else:
            s["name"] = ""

        result["sections"].append(s)

    text = next(
        (
            x
            for x in result["sections"]
            if x["name"] == ".text"
        ),
        None
    )

    if text is None:
        raise RuntimeError(".text 없음")

    result["text"] = text

    return result


def off_to_va(elf, off):

    for s in elf["segments"]:

        if s["type"] != 1:
            continue

        if (
            s["offset"]
            <= off
            < s["offset"] + s["filesz"]
        ):
            return (
                s["vaddr"]
                + off
                - s["offset"]
            )

    return None


def va_to_off(elf, va):

    for s in elf["segments"]:

        if s["type"] != 1:
            continue

        if (
            s["vaddr"]
            <= va
            < s["vaddr"] + s["filesz"]
        ):
            return (
                s["offset"]
                + va
                - s["vaddr"]
            )

    return None


def is_text_va(elf, va):

    t = elf["text"]

    return (
        t["addr"]
        <= va
        < t["addr"] + t["size"]
    )


def branch_target(word, pc):

    imm = s16(word & 0xffff)

    return (
        pc + 4 + imm * 4
    ) & 0xffffffff


def jump_target(word, pc):

    return (
        ((pc + 4) & 0xf0000000)
        |
        ((word & 0x03ffffff) << 2)
    )


def decode(word, pc):

    if word == 0:
        return "nop"

    op = (word >> 26) & 0x3f

    rs = (word >> 21) & 31
    rt = (word >> 16) & 31
    rd = (word >> 11) & 31

    imm = word & 0xffff

    if op == 0:

        fn = word & 0x3f
        sa = (word >> 6) & 31

        table = {
            0x00: f"sll ${REG[rd]},${REG[rt]},{sa}",
            0x02: f"srl ${REG[rd]},${REG[rt]},{sa}",
            0x03: f"sra ${REG[rd]},${REG[rt]},{sa}",
            0x08: f"jr ${REG[rs]}",
            0x09: f"jalr ${REG[rd]},${REG[rs]}",
            0x21: f"addu ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x23: f"subu ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x24: f"and ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x25: f"or ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x26: f"xor ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x27: f"nor ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x2A: f"slt ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x2B: f"sltu ${REG[rd]},${REG[rs]},${REG[rt]}",
        }

        return table.get(
            fn,
            f".word 0x{word:08X}"
        )

    simple = {
        0x08: "addi",
        0x09: "addiu",
        0x0A: "slti",
        0x0B: "sltiu",
        0x0C: "andi",
        0x0D: "ori",
        0x0E: "xori",
    }

    if op == 0x0F:
        return f"lui ${REG[rt]},0x{imm:04X}"

    if op in simple:

        val = (
            s16(imm)
            if op in (0x08,0x09,0x0A,0x0B)
            else imm
        )

        return (
            f"{simple[op]} "
            f"${REG[rt]},${REG[rs]},"
            f"{val if op < 0x0C else f'0x{val:04X}'}"
        )

    mem = {
        0x20:"lb",
        0x21:"lh",
        0x23:"lw",
        0x24:"lbu",
        0x25:"lhu",
        0x28:"sb",
        0x29:"sh",
        0x2B:"sw",
    }

    if op in mem:

        return (
            f"{mem[op]} "
            f"${REG[rt]},"
            f"{s16(imm)}"
            f"(${REG[rs]})"
        )

    if op in (0x04,0x05):

        name = "beq" if op == 0x04 else "bne"

        return (
            f"{name} "
            f"${REG[rs]},${REG[rt]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op in (0x06,0x07):

        name = "blez" if op == 0x06 else "bgtz"

        return (
            f"{name} "
            f"${REG[rs]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op == 0x02:
        return f"j 0x{jump_target(word,pc):08X}"

    if op == 0x03:
        return f"jal 0x{jump_target(word,pc):08X}"

    return f".word 0x{word:08X}"


# ============================================================
# 함수 경계
# ============================================================

def discover_functions(data, elf):

    t = elf["text"]

    starts = {
        elf["entry"]
    }

    # JAL target
    for off in range(
        t["offset"],
        t["offset"] + t["size"] - 4,
        4
    ):

        w = u32(data, off)

        if ((w >> 26) & 0x3f) == 3:

            pc = off_to_va(elf, off)

            target = jump_target(
                w,
                pc
            )

            if is_text_va(elf, target):
                starts.add(target)

    # 일반적인 stack prologue
    for off in range(
        t["offset"],
        t["offset"] + t["size"] - 4,
        4
    ):

        w = u32(data, off)

        op = (w >> 26) & 0x3f
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31

        if (
            op == 0x09
            and rs == 29
            and rt == 29
            and s16(w & 0xffff) < 0
        ):

            va = off_to_va(
                elf,
                off
            )

            if va is not None:
                starts.add(va)

    return sorted(starts)


def function_for_va(starts, va):

    i = bisect.bisect_right(
        starts,
        va
    ) - 1

    if i < 0:
        return None

    return starts[i]


def bounds(starts, elf, start):

    i = bisect.bisect_left(
        starts,
        start
    )

    if (
        i >= len(starts)
        or starts[i] != start
    ):
        return None

    text_end = (
        elf["text"]["addr"]
        + elf["text"]["size"]
    )

    end = (
        starts[i+1]
        if i+1 < len(starts)
        else text_end
    )

    # 이상하게 긴 오탐 함수 제한
    end = min(
        end,
        start + 0x4000
    )

    return start, end


def iter_function(data, elf, starts, start):

    b = bounds(
        starts,
        elf,
        start
    )

    if not b:
        return

    off = va_to_off(
        elf,
        start
    )

    if off is None:
        return

    for rel in range(
        0,
        b[1] - b[0],
        4
    ):

        fo = off + rel

        if fo + 4 > len(data):
            break

        yield (
            start + rel,
            fo,
            u32(data, fo)
        )


# ============================================================
# 함수 특징
# ============================================================

def feature_function(
    data,
    elf,
    starts,
    start
):

    b = bounds(
        starts,
        elf,
        start
    )

    if not b:
        return None

    r = {
        "va": start,
        "end": b[1],
        "size": b[1] - b[0],

        "lb": 0,
        "lbu": 0,
        "sb": 0,

        "lw": 0,
        "sw": 0,

        "shift": 0,
        "bitwise": 0,

        "branches": 0,
        "backward": 0,

        "calls": 0,

        "field_0c": 0,
        "field_10": 0,
        "field_14": 0,

        "callees": [],
        "op_hist": Counter(),
    }

    for pc, fo, w in iter_function(
        data,
        elf,
        starts,
        start
    ):

        op = (w >> 26) & 0x3f

        if op == 0:
            token = 64 + (w & 0x3f)
        else:
            token = op

        r["op_hist"][token] += 1

        rs = (w >> 21) & 31
        imm = s16(w & 0xffff)

        if op == 0x20:
            r["lb"] += 1

        elif op == 0x24:
            r["lbu"] += 1

        elif op == 0x28:
            r["sb"] += 1

        elif op == 0x23:

            r["lw"] += 1

            if imm == 0x0C:
                r["field_0c"] += 1
            elif imm == 0x10:
                r["field_10"] += 1
            elif imm == 0x14:
                r["field_14"] += 1

        elif op == 0x2B:
            r["sw"] += 1

        elif op in (
            0x04,0x05,0x06,0x07,0x01
        ):

            r["branches"] += 1

            if branch_target(w,pc) < pc:
                r["backward"] += 1

        elif op == 3:

            target = jump_target(
                w,
                pc
            )

            if is_text_va(elf,target):

                r["calls"] += 1
                r["callees"].append(target)

        elif op == 0:

            fn = w & 0x3f

            if fn in (
                0x00,0x02,0x03,
                0x04,0x06,0x07
            ):
                r["shift"] += 1

            if fn in (
                0x24,0x25,0x26,0x27
            ):
                r["bitwise"] += 1

        elif op in (
            0x0C,0x0D,0x0E
        ):
            r["bitwise"] += 1

    r["decode_score"] = (
        r["lbu"] * 4
        + r["lb"] * 3
        + r["sb"] * 5
        + r["shift"] * 2
        + r["bitwise"] * 2
        + r["backward"] * 6
    )

    return r


# ============================================================
# PIDX global xref
# ============================================================

MEM_OPS = {
    0x20:"lb",
    0x21:"lh",
    0x23:"lw",
    0x24:"lbu",
    0x25:"lhu",
    0x28:"sb",
    0x29:"sh",
    0x2B:"sw",
}


def find_global_xrefs(
    data,
    elf,
    starts
):

    t = elf["text"]

    rows = []

    for off in range(
        t["offset"],
        t["offset"] + t["size"] - 32,
        4
    ):

        w = u32(data, off)

        op = (w >> 26) & 0x3f

        # LUI reg,0x0043
        if op != 0x0F:
            continue

        rt = (w >> 16) & 31
        hi = w & 0xffff

        if hi != 0x0043:
            continue

        for step in range(1,9):

            o2 = off + step * 4
            w2 = u32(data, o2)

            op2 = (w2 >> 26) & 0x3f

            rs2 = (w2 >> 21) & 31

            if (
                op2 not in MEM_OPS
                or rs2 != rt
            ):
                continue

            lo = s16(
                w2 & 0xffff
            )

            addr = (
                (0x0043 << 16)
                + lo
            ) & 0xffffffff

            if addr not in PIDX_GLOBALS:
                continue

            pc = off_to_va(
                elf,
                o2
            )

            func = function_for_va(
                starts,
                pc
            )

            rows.append({
                "function_va": func,
                "instruction_va": pc,
                "global_addr": addr,
                "global_name":
                    PIDX_GLOBALS[addr],
                "operation":
                    MEM_OPS[op2],
                "register":
                    REG[(w2 >> 16) & 31],
            })

    return rows


# ============================================================
# literal xref
# ============================================================

def find_all(data, needle):

    result = []
    p = 0

    while True:

        p = data.find(
            needle,
            p
        )

        if p < 0:
            break

        result.append(p)
        p += 1

    return result


def find_address_loads(
    data,
    elf,
    starts,
    target
):

    t = elf["text"]

    rows = []

    for off in range(
        t["offset"],
        t["offset"] + t["size"] - 24,
        4
    ):

        w = u32(data, off)

        if ((w >> 26) & 0x3f) != 0x0F:
            continue

        rt = (w >> 16) & 31
        hi = w & 0xffff

        for step in range(1,6):

            o2 = off + step*4
            w2 = u32(data,o2)

            op2 = (w2 >> 26) & 0x3f
            rs2 = (w2 >> 21) & 31
            rt2 = (w2 >> 16) & 31

            if (
                rs2 != rt
                or rt2 != rt
            ):
                continue

            low = w2 & 0xffff

            if op2 == 0x0D:

                value = (
                    (hi << 16)
                    | low
                )

            elif op2 == 0x09:

                value = (
                    (hi << 16)
                    + s16(low)
                ) & 0xffffffff

            else:
                continue

            if value != target:
                continue

            pc = off_to_va(
                elf,
                off
            )

            rows.append({
                "function_va":
                    function_for_va(
                        starts,
                        pc
                    ),
                "instruction_va":
                    pc,
            })

    return rows


# ============================================================
# dump
# ============================================================

def dump_function(
    filename,
    data,
    elf,
    starts,
    start
):

    b = bounds(
        starts,
        elf,
        start
    )

    if not b:
        return

    lines = [
        f"FUNCTION 0x{start:08X}",
        f"END      0x{b[1]:08X}",
        f"SIZE     0x{b[1]-start:X}",
        "",
    ]

    for pc, fo, w in iter_function(
        data,
        elf,
        starts,
        start
    ):

        lines.append(
            f"VA 0x{pc:08X} "
            f"OFF 0x{fo:08X} "
            f"{w:08X}  "
            f"{decode(w,pc)}"
        )

    (OUT / filename).write_text(
        "\n".join(lines),
        encoding="utf-8"
    )


def cosine(a,b):

    keys = (
        set(a.keys())
        | set(b.keys())
    )

    dot = sum(
        a.get(k,0) * b.get(k,0)
        for k in keys
    )

    na = math.sqrt(
        sum(v*v for v in a.values())
    )

    nb = math.sqrt(
        sum(v*v for v in b.values())
    )

    if not na or not nb:
        return 0

    return dot / (na*nb)


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
                k: row.get(k,"")
                for k in fields
            })


def main():

    print("="*72)
    print("Naruto PSP Stage 6")
    print("PIDX runtime xref / loader trace")
    print("="*72)

    parsed = {}

    for label,path in FILES.items():

        data = path.read_bytes()
        elf = parse_elf(data)

        starts = discover_functions(
            data,
            elf
        )

        features = {}

        for s in starts:

            f = feature_function(
                data,
                elf,
                starts,
                s
            )

            if f:
                features[s] = f

        parsed[label] = {
            "path":path,
            "data":data,
            "elf":elf,
            "starts":starts,
            "features":features,
        }

        print(
            label,
            "functions:",
            len(starts)
        )

    # ========================================================
    # US PIDX globals
    # ========================================================

    us = parsed["US_BOOT"]

    gx = find_global_xrefs(
        us["data"],
        us["elf"],
        us["starts"]
    )

    print(
        "US PIDX global xrefs:",
        len(gx)
    )

    gx_rows = []

    for r in gx:

        gx_rows.append({
            "binary":"US_BOOT",
            "function_va":
                f'0x{r["function_va"]:08X}',
            "instruction_va":
                f'0x{r["instruction_va"]:08X}',
            "global_addr":
                f'0x{r["global_addr"]:08X}',
            "global_name":
                r["global_name"],
            "operation":
                r["operation"],
            "register":
                r["register"],
        })

    write_tsv(
        OUT / "pidx_global_xrefs.tsv",
        gx_rows,
        [
            "binary",
            "function_va",
            "instruction_va",
            "global_addr",
            "global_name",
            "operation",
            "register",
        ]
    )

    xref_funcs = sorted(
        {
            r["function_va"]
            for r in gx
            if r["function_va"] is not None
        }
    )

    # ========================================================
    # Literal strings
    # ========================================================

    literal_rows = []

    for literal in (
        b"PIDX0",
        b"naruto.dat",
        b"naruto.idx",
    ):

        for fo in find_all(
            us["data"],
            literal
        ):

            va = off_to_va(
                us["elf"],
                fo
            )

            if va is None:
                continue

            refs = find_address_loads(
                us["data"],
                us["elf"],
                us["starts"],
                va
            )

            for ref in refs:

                literal_rows.append({
                    "literal":
                        literal.decode(
                            "ascii",
                            errors="replace"
                        ),
                    "literal_va":
                        f"0x{va:08X}",
                    "function_va":
                        (
                            f'0x{ref["function_va"]:08X}'
                            if ref["function_va"]
                            is not None
                            else ""
                        ),
                    "instruction_va":
                        f'0x{ref["instruction_va"]:08X}',
                })

    write_tsv(
        OUT / "literal_xrefs.tsv",
        literal_rows,
        [
            "literal",
            "literal_va",
            "function_va",
            "instruction_va",
        ]
    )

    # ========================================================
    # Call graph
    # ========================================================

    callers = defaultdict(set)

    for start,f in us["features"].items():

        for c in f["callees"]:
            callers[c].add(start)

    # xref 함수 + Stage5 핵심 타겟
    seeds = set(xref_funcs)

    for t in US_TARGETS:

        f = function_for_va(
            us["starts"],
            t
        )

        if f is not None:
            seeds.add(f)

    trace_rows = []
    traced = {}

    q = deque(
        (s,0,s)
        for s in sorted(seeds)
    )

    seen = set()

    while q:

        va,depth,root = q.popleft()

        key = (
            root,
            va,
            depth
        )

        if key in seen:
            continue

        seen.add(key)

        if depth > 4:
            continue

        f = us["features"].get(va)

        if not f:
            continue

        trace_rows.append({
            "root":
                f"0x{root:08X}",
            "depth":
                depth,
            "va":
                f"0x{va:08X}",
            "size":
                f["size"],
            "decode_score":
                f["decode_score"],
            "lbu":
                f["lbu"],
            "lb":
                f["lb"],
            "sb":
                f["sb"],
            "shift":
                f["shift"],
            "bitwise":
                f["bitwise"],
            "backward":
                f["backward"],
            "calls":
                f["calls"],
            "field_0c":
                f["field_0c"],
            "field_10":
                f["field_10"],
            "field_14":
                f["field_14"],
            "callers":
                ",".join(
                    f"0x{x:08X}"
                    for x in sorted(
                        callers.get(
                            va,
                            set()
                        )
                    )
                ),
            "callees":
                ",".join(
                    f"0x{x:08X}"
                    for x in sorted(
                        set(f["callees"])
                    )
                ),
        })

        traced[va] = f

        for c in f["callees"]:

            if c in us["features"]:
                q.append(
                    (c,depth+1,root)
                )

    write_tsv(
        OUT / "pidx_callgraph.tsv",
        trace_rows,
        [
            "root",
            "depth",
            "va",
            "size",
            "decode_score",
            "lbu",
            "lb",
            "sb",
            "shift",
            "bitwise",
            "backward",
            "calls",
            "field_0c",
            "field_10",
            "field_14",
            "callers",
            "callees",
        ]
    )

    # ========================================================
    # 0x4F000 ~ 0x61000 주변 함수
    # ========================================================

    near = []

    for va,f in us["features"].items():

        if not (
            0x0004F000
            <= va
            < 0x00061000
        ):
            continue

        near.append({
            "va":
                f"0x{va:08X}",
            "size":
                f["size"],
            "decode_score":
                f["decode_score"],
            "lbu":
                f["lbu"],
            "lb":
                f["lb"],
            "sb":
                f["sb"],
            "shift":
                f["shift"],
            "bitwise":
                f["bitwise"],
            "backward":
                f["backward"],
            "calls":
                f["calls"],
            "field_0c":
                f["field_0c"],
            "field_10":
                f["field_10"],
            "field_14":
                f["field_14"],
            "pidx_global_xrefs":
                sum(
                    1 for x in gx
                    if x["function_va"] == va
                ),
        })

    near.sort(
        key=lambda r: (
            r["pidx_global_xrefs"],
            r["field_0c"]
            + r["field_10"]
            + r["field_14"],
            r["decode_score"]
        ),
        reverse=True
    )

    write_tsv(
        OUT / "us_near_pidx.tsv",
        near,
        [
            "va",
            "size",
            "decode_score",
            "lbu",
            "lb",
            "sb",
            "shift",
            "bitwise",
            "backward",
            "calls",
            "field_0c",
            "field_10",
            "field_14",
            "pidx_global_xrefs",
        ]
    )

    # ========================================================
    # KR 대응 함수 유사도
    # ========================================================

    kr = parsed["KR_BOOT"]

    match_rows = []

    for target in US_TARGETS[:4]:

        us_start = function_for_va(
            us["starts"],
            target
        )

        uf = us["features"].get(
            us_start
        )

        if not uf:
            continue

        candidates = []

        for kva,kf in kr["features"].items():

            ratio = (
                min(
                    uf["size"],
                    kf["size"]
                )
                /
                max(
                    uf["size"],
                    kf["size"]
                )
            )

            if ratio < 0.45:
                continue

            sim = cosine(
                uf["op_hist"],
                kf["op_hist"]
            )

            score = (
                sim * 0.8
                + ratio * 0.2
            )

            candidates.append(
                (
                    score,
                    sim,
                    ratio,
                    kva,
                    kf
                )
            )

        candidates.sort(
            reverse=True,
            key=lambda x:x[0]
        )

        for rank,c in enumerate(
            candidates[:10],
            1
        ):

            score,sim,ratio,kva,kf = c

            match_rows.append({
                "us_target":
                    f"0x{target:08X}",
                "us_function":
                    f"0x{us_start:08X}",
                "rank":
                    rank,
                "kr_function":
                    f"0x{kva:08X}",
                "score":
                    round(score,6),
                "opcode_similarity":
                    round(sim,6),
                "size_ratio":
                    round(ratio,6),
                "us_size":
                    uf["size"],
                "kr_size":
                    kf["size"],
                "us_decode_score":
                    uf["decode_score"],
                "kr_decode_score":
                    kf["decode_score"],
            })

    write_tsv(
        OUT / "target_kr_matches.tsv",
        match_rows,
        [
            "us_target",
            "us_function",
            "rank",
            "kr_function",
            "score",
            "opcode_similarity",
            "size_ratio",
            "us_size",
            "kr_size",
            "us_decode_score",
            "kr_decode_score",
        ]
    )

    # ========================================================
    # 함수 덤프
    # ========================================================

    dump_set = set(seeds)

    # xref/target callgraph에서 디코더 점수가 높은 것
    ranked_trace = sorted(
        traced.items(),
        key=lambda x:
            x[1]["decode_score"],
        reverse=True
    )

    for va,_ in ranked_trace[:40]:
        dump_set.add(va)

    for va in sorted(dump_set):

        if va not in us["features"]:
            continue

        dump_function(
            f"US__0x{va:08X}.txt",
            us["data"],
            us["elf"],
            us["starts"],
            va
        )

    # KR 매치 상위 3개씩
    kr_dump = set()

    for r in match_rows:

        if r["rank"] <= 3:

            kr_dump.add(
                int(
                    r["kr_function"],
                    16
                )
            )

    for va in sorted(kr_dump):

        if va not in kr["features"]:
            continue

        dump_function(
            f"KR_MATCH__0x{va:08X}.txt",
            kr["data"],
            kr["elf"],
            kr["starts"],
            va
        )

    # ========================================================
    # Summary
    # ========================================================

    summary = (
        OUT / "stage6_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 6\n"
        )

        f.write(
            "="*70
            + "\n\n"
        )

        f.write(
            f"PIDX global xrefs: "
            f"{len(gx)}\n"
        )

        f.write(
            f"Functions touching PIDX globals: "
            f"{len(xref_funcs)}\n"
        )

        f.write(
            f"Literal xrefs: "
            f"{len(literal_rows)}\n"
        )

        f.write(
            f"Traced callgraph rows: "
            f"{len(trace_rows)}\n"
        )

        f.write(
            f"US functions near PIDX: "
            f"{len(near)}\n"
        )

        f.write(
            f"KR match rows: "
            f"{len(match_rows)}\n\n"
        )

        f.write(
            "PIDX global functionLOCAL_PATH"
        )

        for va in xref_funcs:

            feat = us["features"].get(va)

            refs = [
                x for x in gx
                if x["function_va"] == va
            ]

            f.write(
                f"  0x{va:08X}"
            )

            if feat:

                f.write(
                    f" score={feat['decode_score']}"
                    f" lbu={feat['lbu']}"
                    f" sb={feat['sb']}"
                    f" fields="
                    f"{feat['field_0c']}/"
                    f"{feat['field_10']}/"
                    f"{feat['field_14']}"
                )

            f.write("\n")

            for x in refs:

                f.write(
                    f"    "
                    f"{x['operation']} "
                    f"{x['global_name']} "
                    f"@0x{x['instruction_va']:08X}\n"
                )

        f.write(
            "\nTop descendant decode candidateLOCAL_PATH"
        )

        for va,feat in ranked_trace[:25]:

            f.write(
                f"  0x{va:08X}"
                f" score={feat['decode_score']}"
                f" lbu={feat['lbu']}"
                f" sb={feat['sb']}"
                f" shift={feat['shift']}"
                f" bit={feat['bitwise']}"
                f" back={feat['backward']}"
                f" fields="
                f"{feat['field_0c']}/"
                f"{feat['field_10']}/"
                f"{feat['field_14']}\n"
            )

    print()
    print("="*72)
    print("Stage 6 complete")
    print("="*72)

    print(
        "PIDX xrefs:",
        len(gx)
    )

    print(
        "PIDX functions:",
        len(xref_funcs)
    )

    print(
        "Trace rows:",
        len(trace_rows)
    )

    print(
        "KR matches:",
        len(match_rows)
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
