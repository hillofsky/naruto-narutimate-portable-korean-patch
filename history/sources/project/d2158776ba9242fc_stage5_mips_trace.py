from pathlib import Path
import struct
import csv
import hashlib
import sys
import traceback
from collections import defaultdict, deque

BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage5"

OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "KR_BOOT": BASE / "kr_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
    "US_BOOT": BASE / "us_extracted" / "PSP_GAME" / "SYSDIR" / "BOOT.BIN",
}

FOCUS_US = 0x0005FC68

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


def sha256_file(path):

    h = hashlib.sha256()

    with path.open("rb") as f:

        while True:

            b = f.read(1024 * 1024)

            if not b:
                break

            h.update(b)

    return h.hexdigest()


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
    shstr = u16(data, 0x32)

    for i in range(phnum):

        off = phoff + i * phentsize

        if off + 32 > len(data):
            break

        vals = struct.unpack_from(
            "<8I",
            data,
            off
        )

        result["segments"].append({
            "type": vals[0],
            "offset": vals[1],
            "vaddr": vals[2],
            "filesz": vals[4],
            "memsz": vals[5],
            "flags": vals[6],
        })

    raw_sections = []

    for i in range(shnum):

        off = shoff + i * shentsize

        if off + 40 > len(data):
            break

        v = struct.unpack_from(
            "<10I",
            data,
            off
        )

        raw_sections.append({
            "index": i,
            "name_off": v[0],
            "type": v[1],
            "flags": v[2],
            "addr": v[3],
            "offset": v[4],
            "size": v[5],
        })

    names = b""

    if 0 <= shstr < len(raw_sections):

        s = raw_sections[shstr]

        names = data[
            s["offset"]:
            s["offset"] + s["size"]
        ]

    for s in raw_sections:

        n = s["name_off"]

        if n < len(names):

            end = names.find(
                b"\0",
                n
            )

            if end < 0:
                end = len(names)

            name = names[
                n:end
            ].decode(
                "ascii",
                errors="replace"
            )

        else:
            name = ""

        s["name"] = name

        result["sections"].append(s)

    text = next(
        (
            s
            for s in result["sections"]
            if s["name"] == ".text"
        ),
        None
    )

    if text is None:
        raise RuntimeError(".text 없음")

    result["text"] = text

    return result


def va_to_off(elf, va):

    for seg in elf["segments"]:

        if seg["type"] != 1:
            continue

        lo = seg["vaddr"]
        hi = lo + seg["filesz"]

        if lo <= va < hi:

            return (
                seg["offset"]
                + va
                - seg["vaddr"]
            )

    return None


def off_to_va(elf, off):

    for seg in elf["segments"]:

        if seg["type"] != 1:
            continue

        lo = seg["offset"]
        hi = lo + seg["filesz"]

        if lo <= off < hi:

            return (
                seg["vaddr"]
                + off
                - seg["offset"]
            )

    return None


def is_text_va(elf, va):

    s = elf["text"]

    return (
        s["addr"]
        <= va
        < s["addr"] + s["size"]
    )


def branch_target(word, pc):

    imm = word & 0xFFFF

    return (
        pc + 4
        + (s16(imm) << 2)
    ) & 0xFFFFFFFF


def jump_target(word, pc):

    return (
        ((pc + 4) & 0xF0000000)
        |
        ((word & 0x03FFFFFF) << 2)
    )


def decode(word, pc):

    if word == 0:
        return "nop"

    op = (word >> 26) & 0x3F

    rs = (word >> 21) & 31
    rt = (word >> 16) & 31
    rd = (word >> 11) & 31

    imm = word & 0xFFFF

    if op == 0:

        fn = word & 0x3F
        sa = (word >> 6) & 31

        table = {
            0x08: f"jr ${REG[rs]}",
            0x09: f"jalr ${REG[rd]},${REG[rs]}",
            0x21: f"addu ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x23: f"subu ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x24: f"and ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x25: f"or ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x26: f"xor ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x27: f"nor ${REG[rd]},${REG[rs]},${REG[rt]}",
            0x00: f"sll ${REG[rd]},${REG[rt]},{sa}",
            0x02: f"srl ${REG[rd]},${REG[rt]},{sa}",
            0x03: f"sra ${REG[rd]},${REG[rt]},{sa}",
        }

        return table.get(
            fn,
            f".word 0x{word:08X}"
        )

    if op == 0x0F:
        return f"lui ${REG[rt]},0x{imm:04X}"

    if op == 0x09:
        return f"addiu ${REG[rt]},${REG[rs]},{s16(imm)}"

    if op == 0x0C:
        return f"andi ${REG[rt]},${REG[rs]},0x{imm:04X}"

    if op == 0x0D:
        return f"ori ${REG[rt]},${REG[rs]},0x{imm:04X}"

    if op == 0x0E:
        return f"xori ${REG[rt]},${REG[rs]},0x{imm:04X}"

    mem = {
        0x20: "lb",
        0x21: "lh",
        0x23: "lw",
        0x24: "lbu",
        0x25: "lhu",
        0x28: "sb",
        0x29: "sh",
        0x2B: "sw",
    }

    if op in mem:

        return (
            f"{mem[op]} "
            f"${REG[rt]},"
            f"{s16(imm)}"
            f"(${REG[rs]})"
        )

    if op == 0x04:

        return (
            f"beq ${REG[rs]},${REG[rt]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op == 0x05:

        return (
            f"bne ${REG[rs]},${REG[rt]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op == 0x06:

        return (
            f"blez ${REG[rs]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op == 0x07:

        return (
            f"bgtz ${REG[rs]},"
            f"0x{branch_target(word,pc):08X}"
        )

    if op == 0x02:

        return (
            f"j "
            f"0x{jump_target(word,pc):08X}"
        )

    if op == 0x03:

        return (
            f"jal "
            f"0x{jump_target(word,pc):08X}"
        )

    return f".word 0x{word:08X}"


# ============================================================
# Function discovery
# ============================================================

def collect_jal_targets(data, elf):

    text = elf["text"]

    start = text["offset"]
    end = start + text["size"]

    targets = set()

    callers = defaultdict(list)

    for off in range(start, end - 3, 4):

        word = u32(
            data,
            off
        )

        op = (
            word >> 26
        ) & 0x3F

        if op != 3:
            continue

        pc = off_to_va(
            elf,
            off
        )

        if pc is None:
            continue

        target = jump_target(
            word,
            pc
        )

        if not is_text_va(
            elf,
            target
        ):
            continue

        targets.add(
            target
        )

        callers[
            target
        ].append(pc)

    return targets, callers


def guess_function_starts(data, elf):

    targets, callers = (
        collect_jal_targets(
            data,
            elf
        )
    )

    starts = set(targets)

    starts.add(
        elf["entry"]
    )

    # Typical MIPS stack-frame prologues:
    # addiu sp,sp,-N
    text = elf["text"]

    for off in range(
        text["offset"],
        text["offset"]
        + text["size"]
        - 4,
        4
    ):

        w = u32(
            data,
            off
        )

        op = (
            w >> 26
        ) & 0x3F

        rs = (
            w >> 21
        ) & 31

        rt = (
            w >> 16
        ) & 31

        imm = w & 0xFFFF

        if (
            op == 0x09
            and rs == 29
            and rt == 29
            and s16(imm) < 0
        ):

            va = off_to_va(
                elf,
                off
            )

            if va is not None:
                starts.add(va)

    return (
        sorted(starts),
        callers
    )


def function_bounds(starts, elf, va):

    text = elf["text"]

    text_end = (
        text["addr"]
        + text["size"]
    )

    try:
        i = starts.index(va)
    except ValueError:
        return None

    end = (
        starts[i + 1]
        if i + 1 < len(starts)
        else text_end
    )

    # Avoid absurd ranges from missed starts.
    end = min(
        end,
        va + 0x3000
    )

    return va, end


def function_words(data, elf, bounds):

    start, end = bounds

    off = va_to_off(
        elf,
        start
    )

    if off is None:
        return

    size = end - start

    for rel in range(
        0,
        size,
        4
    ):

        fo = off + rel

        if fo + 4 > len(data):
            break

        pc = start + rel

        yield (
            pc,
            fo,
            u32(data, fo)
        )


def analyze_function(data, elf, starts, va):

    bounds = function_bounds(
        starts,
        elf,
        va
    )

    if bounds is None:
        return None

    stats = {
        "va": va,
        "end": bounds[1],
        "bytes": bounds[1] - va,

        "lb": 0,
        "lbu": 0,
        "sb": 0,

        "lw": 0,
        "sw": 0,

        "shift": 0,
        "bitwise": 0,

        "branches": 0,
        "backward_branches": 0,

        "calls": 0,
        "callees": [],

        "entry_0c": 0,
        "entry_10": 0,
        "entry_14": 0,

        "triple_base": 0,
    }

    field_by_base = defaultdict(set)

    for pc, fo, w in function_words(
        data,
        elf,
        bounds
    ):

        op = (
            w >> 26
        ) & 0x3F

        rs = (
            w >> 21
        ) & 31

        imm = w & 0xFFFF

        if op == 0x20:
            stats["lb"] += 1

        elif op == 0x24:
            stats["lbu"] += 1

        elif op == 0x28:
            stats["sb"] += 1

        elif op == 0x23:

            stats["lw"] += 1

            si = s16(imm)

            if si in (
                0x0C,
                0x10,
                0x14
            ):

                field_by_base[
                    rs
                ].add(si)

                if si == 0x0C:
                    stats["entry_0c"] += 1

                elif si == 0x10:
                    stats["entry_10"] += 1

                elif si == 0x14:
                    stats["entry_14"] += 1

        elif op == 0x2B:
            stats["sw"] += 1

        elif op in (
            0x04,
            0x05,
            0x06,
            0x07,
            0x01
        ):

            stats["branches"] += 1

            target = branch_target(
                w,
                pc
            )

            if target < pc:
                stats[
                    "backward_branches"
                ] += 1

        elif op == 0x03:

            target = jump_target(
                w,
                pc
            )

            if is_text_va(
                elf,
                target
            ):

                stats["calls"] += 1
                stats["callees"].append(
                    target
                )

        elif op == 0:

            fn = w & 0x3F

            if fn in (
                0x00,
                0x02,
                0x03,
                0x04,
                0x06,
                0x07
            ):
                stats["shift"] += 1

            if fn in (
                0x24,
                0x25,
                0x26,
                0x27
            ):
                stats["bitwise"] += 1

        elif op in (
            0x0C,
            0x0D,
            0x0E
        ):

            stats["bitwise"] += 1

    for base, fields in (
        field_by_base.items()
    ):

        if {
            0x0C,
            0x10,
            0x14
        }.issubset(fields):

            stats["triple_base"] += 1

    # Heuristic decompressor score
    stats["score"] = (
        stats["lbu"] * 4
        + stats["lb"] * 3
        + stats["sb"] * 5
        + stats["backward_branches"] * 6
        + stats["shift"] * 2
        + stats["bitwise"] * 2
        + stats["triple_base"] * 25
        + min(
            stats["branches"],
            15
        )
    )

    return stats


def dump_function(
    path,
    data,
    elf,
    starts,
    va
):

    bounds = function_bounds(
        starts,
        elf,
        va
    )

    if bounds is None:
        return

    lines = []

    lines.append(
        f"FUNCTION 0x{va:08X}"
    )

    lines.append(
        f"END      0x{bounds[1]:08X}"
    )

    lines.append(
        f"SIZE     0x{bounds[1]-va:X}"
    )

    lines.append("")

    for pc, fo, w in function_words(
        data,
        elf,
        bounds
    ):

        lines.append(
            f"VA 0x{pc:08X} "
            f"OFF 0x{fo:08X} "
            f"{w:08X}  "
            f"{decode(w,pc)}"
        )

    path.write_text(
        "\n".join(lines),
        encoding="utf-8"
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

            w.writerow(
                {
                    k: row.get(k, "")
                    for k in fields
                }
            )


def main():

    print("=" * 72)
    print("Naruto PSP Stage 5")
    print("MIPS callgraph / decompressor candidate scan")
    print("=" * 72)

    all_rank_rows = []
    all_field_rows = []
    graph_rows = []
    caller_rows = []

    dump_requests = []

    for label, path in FILES.items():

        print()
        print(f"[{label}]")

        data = path.read_bytes()
        elf = parse_elf(data)

        starts, callers = (
            guess_function_starts(
                data,
                elf
            )
        )

        print(
            "Function starts:",
            len(starts)
        )

        analyses = {}

        for va in starts:

            a = analyze_function(
                data,
                elf,
                starts,
                va
            )

            if a:
                analyses[va] = a

        # --------------------------------------------
        # Global decompressor ranking
        # --------------------------------------------

        ranked = sorted(
            analyses.values(),
            key=lambda x: (
                x["score"],
                x["lbu"] + x["lb"],
                x["sb"]
            ),
            reverse=True
        )

        print(
            "Top score:",
            ranked[0]["score"]
            if ranked else 0
        )

        for rank, a in enumerate(
            ranked[:60],
            1
        ):

            row = {
                "binary": label,
                "rank": rank,
                "va": f'0x{a["va"]:08X}',
                "end": f'0x{a["end"]:08X}',
                "bytes": a["bytes"],
                "score": a["score"],
                "lb": a["lb"],
                "lbu": a["lbu"],
                "sb": a["sb"],
                "lw": a["lw"],
                "sw": a["sw"],
                "shift": a["shift"],
                "bitwise": a["bitwise"],
                "branches": a["branches"],
                "backward_branches":
                    a["backward_branches"],
                "calls": a["calls"],
                "entry_0c": a["entry_0c"],
                "entry_10": a["entry_10"],
                "entry_14": a["entry_14"],
                "triple_base": a["triple_base"],
            }

            all_rank_rows.append(row)

            if rank <= 20:

                dump_requests.append(
                    (
                        label,
                        data,
                        elf,
                        starts,
                        a["va"],
                        f"{label}__RANK{rank:02d}"
                        f"__0x{a['va']:08X}.txt"
                    )
                )

        # --------------------------------------------
        # PIDX field access candidates
        # --------------------------------------------

        fields = [
            a
            for a in analyses.values()
            if (
                a["entry_0c"]
                or a["entry_10"]
                or a["entry_14"]
            )
        ]

        fields.sort(
            key=lambda a: (
                a["triple_base"],
                a["entry_0c"]
                + a["entry_10"]
                + a["entry_14"],
                a["score"]
            ),
            reverse=True
        )

        for rank, a in enumerate(
            fields[:80],
            1
        ):

            all_field_rows.append({
                "binary": label,
                "rank": rank,
                "va":
                    f'0x{a["va"]:08X}',
                "score":
                    a["score"],
                "entry_0c":
                    a["entry_0c"],
                "entry_10":
                    a["entry_10"],
                "entry_14":
                    a["entry_14"],
                "triple_base":
                    a["triple_base"],
                "lbu":
                    a["lbu"],
                "sb":
                    a["sb"],
                "backward_branches":
                    a["backward_branches"],
            })

            if (
                a["triple_base"]
                or rank <= 12
            ):

                dump_requests.append(
                    (
                        label,
                        data,
                        elf,
                        starts,
                        a["va"],
                        f"{label}__PIDXFIELD"
                        f"{rank:02d}"
                        f"__0x{a['va']:08X}.txt"
                    )
                )

        # --------------------------------------------
        # Focus US 0x5FC68 call graph
        # --------------------------------------------

        if (
            label == "US_BOOT"
            and FOCUS_US in analyses
        ):

            print(
                "Focus function found:",
                f"0x{FOCUS_US:08X}"
            )

            for call_pc in callers.get(
                FOCUS_US,
                []
            ):

                caller_rows.append({
                    "binary": label,
                    "target":
                        f"0x{FOCUS_US:08X}",
                    "caller_pc":
                        f"0x{call_pc:08X}",
                })

            q = deque([
                (FOCUS_US, 0)
            ])

            visited = set()

            while q:

                va, depth = q.popleft()

                if va in visited:
                    continue

                if depth > 5:
                    continue

                visited.add(va)

                a = analyses.get(va)

                if not a:
                    continue

                graph_rows.append({
                    "binary": label,
                    "depth": depth,
                    "va":
                        f"0x{va:08X}",
                    "score":
                        a["score"],
                    "lbu":
                        a["lbu"],
                    "sb":
                        a["sb"],
                    "backward_branches":
                        a["backward_branches"],
                    "calls":
                        a["calls"],
                    "triple_base":
                        a["triple_base"],
                    "callees":
                        ",".join(
                            f"0x{x:08X}"
                            for x
                            in sorted(
                                set(
                                    a["callees"]
                                )
                            )
                        ),
                })

                dump_requests.append(
                    (
                        label,
                        data,
                        elf,
                        starts,
                        va,
                        f"{label}__FOCUS_D{depth}"
                        f"__0x{va:08X}.txt"
                    )
                )

                for c in a["callees"]:

                    if c in analyses:

                        q.append(
                            (
                                c,
                                depth + 1
                            )
                        )

    # --------------------------------------------
    # Write reports
    # --------------------------------------------

    rank_fields = [
        "binary",
        "rank",
        "va",
        "end",
        "bytes",
        "score",
        "lb",
        "lbu",
        "sb",
        "lw",
        "sw",
        "shift",
        "bitwise",
        "branches",
        "backward_branches",
        "calls",
        "entry_0c",
        "entry_10",
        "entry_14",
        "triple_base",
    ]

    write_tsv(
        OUT / "decompressor_candidates.tsv",
        all_rank_rows,
        rank_fields
    )

    write_tsv(
        OUT / "pidx_field_candidates.tsv",
        all_field_rows,
        [
            "binary",
            "rank",
            "va",
            "score",
            "entry_0c",
            "entry_10",
            "entry_14",
            "triple_base",
            "lbu",
            "sb",
            "backward_branches",
        ]
    )

    write_tsv(
        OUT / "focus_callgraph.tsv",
        graph_rows,
        [
            "binary",
            "depth",
            "va",
            "score",
            "lbu",
            "sb",
            "backward_branches",
            "calls",
            "triple_base",
            "callees",
        ]
    )

    write_tsv(
        OUT / "focus_callers.tsv",
        caller_rows,
        [
            "binary",
            "target",
            "caller_pc",
        ]
    )

    # --------------------------------------------
    # Function dumps
    # --------------------------------------------

    unique = {}

    for req in dump_requests:

        key = (
            req[0],
            req[4],
            req[5]
        )

        unique[key] = req

    for req in unique.values():

        label, data, elf, starts, va, name = req

        dump_function(
            OUT / name,
            data,
            elf,
            starts,
            va
        )

    # --------------------------------------------
    # Summary
    # --------------------------------------------

    summary = OUT / "stage5_summary.txt"

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write("Naruto PSP Stage 5\n")
        f.write("=" * 70 + "\n\n")

        f.write(
            f"Decompressor rank rows: "
            f"{len(all_rank_rows)}\n"
        )

        f.write(
            f"PIDX-field rows: "
            f"{len(all_field_rows)}\n"
        )

        f.write(
            f"Focus graph rows: "
            f"{len(graph_rows)}\n"
        )

        f.write(
            f"Focus callers: "
            f"{len(caller_rows)}\n"
        )

        f.write(
            f"Function dumps: "
            f"{len(unique)}\n\n"
        )

        f.write(
            "US focus function: "
            f"0x{FOCUS_US:08X}\n\n"
        )

        f.write(
            "Top US decompressor candidateLOCAL_PATH"
        )

        us_top = [
            r
            for r in all_rank_rows
            if r["binary"] == "US_BOOT"
        ][:15]

        for r in us_top:

            f.write(
                f'  #{r["rank"]:02d} '
                f'{r["va"]} '
                f'score={r["score"]} '
                f'lbu={r["lbu"]} '
                f'sb={r["sb"]} '
                f'back={r["backward_branches"]} '
                f'fields='
                f'{r["entry_0c"]}/'
                f'{r["entry_10"]}/'
                f'{r["entry_14"]} '
                f'triple={r["triple_base"]}\n'
            )

        f.write(
            "\nTop US PIDX-field candidateLOCAL_PATH"
        )

        us_fields = [
            r
            for r in all_field_rows
            if r["binary"] == "US_BOOT"
        ][:20]

        for r in us_fields:

            f.write(
                f'  #{r["rank"]:02d} '
                f'{r["va"]} '
                f'score={r["score"]} '
                f'fields='
                f'{r["entry_0c"]}/'
                f'{r["entry_10"]}/'
                f'{r["entry_14"]} '
                f'triple={r["triple_base"]}\n'
            )

    print()
    print("=" * 72)
    print("Stage 5 complete")
    print("=" * 72)

    print(
        "Rank rows :",
        len(all_rank_rows)
    )

    print(
        "PIDX rows :",
        len(all_field_rows)
    )

    print(
        "Focus graph:",
        len(graph_rows)
    )

    print(
        "Dumps     :",
        len(unique)
    )

    print(
        "Output    :",
        OUT
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:

        traceback.print_exc()
        sys.exit(1)
