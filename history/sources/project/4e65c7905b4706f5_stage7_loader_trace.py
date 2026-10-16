from pathlib import Path
from collections import defaultdict, deque
import importlib.util
import csv
import math
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage7"

OUT.mkdir(parents=True, exist_ok=True)

S6_PATH = (
    BASE
    / "analysis"
    / "stage6"
    / "stage6_pidx_trace.py"
)

US_BOOT = (
    BASE
    / "us_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)

KR_BOOT = (
    BASE
    / "kr_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)

TARGETS = [
    0x0005F0B0,
    0x0005F240,
    0x0005F304,
    0x0005F460,
    0x0005F594,
    0x0005F818,
    0x0005F8CC,
    0x0005F910,
    0x0005FB40,
    0x0005FB88,
    0x0005FC68,
    0x0005FC9C,
]

CODEC_TARGETS = [
    0x0005F240,
    0x0005F304,
    0x0005F460,
    0x0005F594,
]

LOADER_TARGETS = [
    0x0005F0B0,
    0x0005FB40,
]

REGION_START = 0x0005EF00
REGION_END   = 0x0005FD00


def load_stage6():

    if not S6_PATH.exists():
        raise RuntimeError(
            f"Stage6 분석기가 없습니다: {S6_PATH}"
        )

    spec = importlib.util.spec_from_file_location(
        "naruto_stage6",
        S6_PATH
    )

    mod = importlib.util.module_from_spec(
        spec
    )

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

        for r in rows:

            w.writerow({
                k: r.get(k, "")
                for k in fields
            })


def build_features(s6, data):

    elf = s6.parse_elf(data)

    starts = s6.discover_functions(
        data,
        elf
    )

    features = {}

    for va in starts:

        f = s6.feature_function(
            data,
            elf,
            starts,
            va
        )

        if f:
            features[va] = f

    callers = defaultdict(set)

    for va, f in features.items():

        for c in f["callees"]:

            if c in features:
                callers[c].add(va)

    return (
        elf,
        starts,
        features,
        callers
    )


def collect_related(
    roots,
    features,
    callers,
    up_depth=4,
    down_depth=3
):

    result = set(roots)

    q = deque()

    for root in roots:
        q.append(
            (root, "root", 0)
        )

    seen = set()

    while q:

        va, direction, depth = q.popleft()

        key = (
            va,
            direction,
            depth
        )

        if key in seen:
            continue

        seen.add(key)

        if va not in features:
            continue

        result.add(va)

        if depth < up_depth:

            for c in callers.get(
                va,
                set()
            ):

                q.append(
                    (
                        c,
                        "up",
                        depth + 1
                    )
                )

        if depth < down_depth:

            for c in features[
                va
            ]["callees"]:

                if c in features:

                    q.append(
                        (
                            c,
                            "down",
                            depth + 1
                        )
                    )

    return result


def find_callsites(
    s6,
    data,
    elf,
    starts,
    targets
):

    t = elf["text"]

    rows = []

    context_blocks = []

    target_set = set(
        targets
    )

    for off in range(
        t["offset"],
        t["offset"] + t["size"] - 4,
        4
    ):

        w = s6.u32(
            data,
            off
        )

        if (
            ((w >> 26) & 0x3f)
            != 3
        ):
            continue

        pc = s6.off_to_va(
            elf,
            off
        )

        if pc is None:
            continue

        target = s6.jump_target(
            w,
            pc
        )

        if target not in target_set:
            continue

        caller = s6.function_for_va(
            starts,
            pc
        )

        rows.append({
            "target":
                f"0x{target:08X}",
            "caller":
                (
                    f"0x{caller:08X}"
                    if caller is not None
                    else ""
                ),
            "call_pc":
                f"0x{pc:08X}",
        })

        context_blocks.append(
            "=" * 72
        )

        context_blocks.append(
            f"TARGET  0x{target:08X}"
        )

        context_blocks.append(
            f"CALLER  "
            + (
                f"0x{caller:08X}"
                if caller is not None
                else "UNKNOWN"
            )
        )

        context_blocks.append(
            f"CALL PC 0x{pc:08X}"
        )

        context_blocks.append(
            "=" * 72
        )

        start_off = max(
            t["offset"],
            off - 20 * 4
        )

        end_off = min(
            t["offset"] + t["size"],
            off + 10 * 4
        )

        for o in range(
            start_off,
            end_off,
            4
        ):

            ww = s6.u32(
                data,
                o
            )

            va = s6.off_to_va(
                elf,
                o
            )

            mark = (
                ">>>"
                if o == off
                else "   "
            )

            context_blocks.append(
                f"{mark} "
                f"VA 0x{va:08X} "
                f"{ww:08X}  "
                f"{s6.decode(ww,va)}"
            )

        context_blocks.append("")

    (
        OUT / "target_callsites.txt"
    ).write_text(
        "\n".join(
            context_blocks
        ),
        encoding="utf-8"
    )

    return rows


def function_region_rows(
    features,
    callers
):

    rows = []

    for va in sorted(
        features
    ):

        if not (
            REGION_START
            <= va
            < REGION_END
        ):
            continue

        f = features[va]

        rows.append({
            "va":
                f"0x{va:08X}",
            "end":
                f'0x{f["end"]:08X}',
            "size":
                f["size"],

            "score":
                f["decode_score"],

            "lb":
                f["lb"],
            "lbu":
                f["lbu"],
            "sb":
                f["sb"],

            "shift":
                f["shift"],
            "bitwise":
                f["bitwise"],

            "branches":
                f["branches"],
            "backward":
                f["backward"],

            "field_0c":
                f["field_0c"],
            "field_10":
                f["field_10"],
            "field_14":
                f["field_14"],

            "callers":
                ",".join(
                    f"0x{x:08X}"
                    for x
                    in sorted(
                        callers.get(
                            va,
                            set()
                        )
                    )
                ),

            "callees":
                ",".join(
                    f"0x{x:08X}"
                    for x
                    in sorted(
                        set(
                            f["callees"]
                        )
                    )
                ),
        })

    return rows


def dump_region(
    s6,
    data,
    elf
):

    lines = []

    for va in range(
        REGION_START,
        REGION_END,
        4
    ):

        off = s6.va_to_off(
            elf,
            va
        )

        if (
            off is None
            or off + 4 > len(data)
        ):
            continue

        w = s6.u32(
            data,
            off
        )

        lines.append(
            f"VA 0x{va:08X} "
            f"OFF 0x{off:08X} "
            f"{w:08X}  "
            f"{s6.decode(w,va)}"
        )

    (
        OUT
        / "us_pidx_module_full.txt"
    ).write_text(
        "\n".join(lines),
        encoding="utf-8"
    )


def cosine(a, b):

    keys = (
        set(a.keys())
        | set(b.keys())
    )

    dot = sum(
        a.get(k,0)
        * b.get(k,0)
        for k in keys
    )

    aa = math.sqrt(
        sum(
            v*v
            for v in a.values()
        )
    )

    bb = math.sqrt(
        sum(
            v*v
            for v in b.values()
        )
    )

    if not aa or not bb:
        return 0.0

    return dot / (
        aa * bb
    )


def kr_matches(
    us_features,
    kr_features
):

    rows = []

    for target in TARGETS:

        uf = us_features.get(
            target
        )

        if not uf:
            continue

        candidates = []

        for kva, kf in (
            kr_features.items()
        ):

            size_ratio = (
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

            if size_ratio < 0.55:
                continue

            sim = cosine(
                uf["op_hist"],
                kf["op_hist"]
            )

            total = (
                sim * 0.85
                + size_ratio * 0.15
            )

            candidates.append(
                (
                    total,
                    sim,
                    size_ratio,
                    kva,
                    kf
                )
            )

        candidates.sort(
            key=lambda x:
                x[0],
            reverse=True
        )

        for rank, item in enumerate(
            candidates[:8],
            1
        ):

            (
                total,
                sim,
                ratio,
                kva,
                kf
            ) = item

            rows.append({
                "us_function":
                    f"0x{target:08X}",
                "rank":
                    rank,
                "kr_function":
                    f"0x{kva:08X}",

                "score":
                    round(
                        total,
                        6
                    ),

                "opcode_similarity":
                    round(
                        sim,
                        6
                    ),

                "size_ratio":
                    round(
                        ratio,
                        6
                    ),

                "us_size":
                    uf["size"],

                "kr_size":
                    kf["size"],

                "us_decode_score":
                    uf[
                        "decode_score"
                    ],

                "kr_decode_score":
                    kf[
                        "decode_score"
                    ],
            })

    return rows


def main():

    print(
        "=" * 72
    )

    print(
        "Naruto PSP Stage 7"
    )

    print(
        "PIDX loader / 3;x codec trace"
    )

    print(
        "=" * 72
    )

    s6 = load_stage6()

    us_data = (
        US_BOOT.read_bytes()
    )

    kr_data = (
        KR_BOOT.read_bytes()
    )

    (
        us_elf,
        us_starts,
        us_features,
        us_callers
    ) = build_features(
        s6,
        us_data
    )

    (
        kr_elf,
        kr_starts,
        kr_features,
        kr_callers
    ) = build_features(
        s6,
        kr_data
    )

    print(
        "US functions:",
        len(us_features)
    )

    print(
        "KR functions:",
        len(kr_features)
    )

    # ========================================================
    # 지역 함수
    # ========================================================

    region_rows = (
        function_region_rows(
            us_features,
            us_callers
        )
    )

    write_tsv(
        OUT
        / "pidx_module_functions.tsv",
        region_rows,
        [
            "va",
            "end",
            "size",
            "score",

            "lb",
            "lbu",
            "sb",

            "shift",
            "bitwise",

            "branches",
            "backward",

            "field_0c",
            "field_10",
            "field_14",

            "callers",
            "callees",
        ]
    )

    # ========================================================
    # 타겟별 caller/callee
    # ========================================================

    relation_rows = []

    for target in TARGETS:

        f = us_features.get(
            target
        )

        if not f:
            continue

        relation_rows.append({
            "target":
                f"0x{target:08X}",

            "callers":
                ",".join(
                    f"0x{x:08X}"
                    for x in sorted(
                        us_callers.get(
                            target,
                            set()
                        )
                    )
                ),

            "callees":
                ",".join(
                    f"0x{x:08X}"
                    for x in sorted(
                        set(
                            f["callees"]
                        )
                    )
                ),

            "size":
                f["size"],

            "score":
                f["decode_score"],

            "lbu":
                f["lbu"],

            "sb":
                f["sb"],

            "shift":
                f["shift"],

            "bitwise":
                f["bitwise"],

            "backward":
                f["backward"],
        })

    write_tsv(
        OUT
        / "target_relations.tsv",
        relation_rows,
        [
            "target",
            "callers",
            "callees",
            "size",
            "score",
            "lbu",
            "sb",
            "shift",
            "bitwise",
            "backward",
        ]
    )

    # ========================================================
    # 호출 직전 인자 설정
    # ========================================================

    call_rows = find_callsites(
        s6,
        us_data,
        us_elf,
        us_starts,
        TARGETS
    )

    write_tsv(
        OUT
        / "target_callsites.tsv",
        call_rows,
        [
            "target",
            "caller",
            "call_pc",
        ]
    )

    # ========================================================
    # 상하 호출 트리
    # ========================================================

    related = collect_related(
        TARGETS,
        us_features,
        us_callers,
        up_depth=4,
        down_depth=3
    )

    related_rows = []

    for va in sorted(
        related
    ):

        f = us_features.get(
            va
        )

        if not f:
            continue

        related_rows.append({
            "va":
                f"0x{va:08X}",

            "size":
                f["size"],

            "score":
                f["decode_score"],

            "lbu":
                f["lbu"],

            "sb":
                f["sb"],

            "shift":
                f["shift"],

            "bitwise":
                f["bitwise"],

            "backward":
                f["backward"],

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
                        us_callers.get(
                            va,
                            set()
                        )
                    )
                ),

            "callees":
                ",".join(
                    f"0x{x:08X}"
                    for x in sorted(
                        set(
                            f["callees"]
                        )
                    )
                ),
        })

    write_tsv(
        OUT
        / "loader_related_functions.tsv",
        related_rows,
        [
            "va",
            "size",
            "score",
            "lbu",
            "sb",
            "shift",
            "bitwise",
            "backward",
            "field_0c",
            "field_10",
            "field_14",
            "callers",
            "callees",
        ]
    )

    # ========================================================
    # 함수 덤프
    # ========================================================

    dump_set = set(
        TARGETS
    )

    # 타겟 caller를 우선 포함
    for t in TARGETS:

        for c in us_callers.get(
            t,
            set()
        ):
            dump_set.add(c)

    # related 중 압축 특성이 강한 함수
    ranked_related = sorted(
        (
            (
                va,
                us_features[va]
            )
            for va in related
            if va in us_features
        ),
        key=lambda x:
            x[1]["decode_score"],
        reverse=True
    )

    for va, f in ranked_related[:30]:

        dump_set.add(va)

    for va in sorted(
        dump_set
    ):

        if va not in us_features:
            continue

        s6.dump_function(
            f"US__0x{va:08X}.txt",
            us_data,
            us_elf,
            us_starts,
            va
        )

    dump_region(
        s6,
        us_data,
        us_elf
    )

    # ========================================================
    # KR 대응 함수
    # ========================================================

    match_rows = kr_matches(
        us_features,
        kr_features
    )

    write_tsv(
        OUT
        / "codec_kr_matches.tsv",
        match_rows,
        [
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

    kr_dump = set()

    for r in match_rows:

        if (
            r["rank"] <= 2
            and r["us_function"]
            in {
                f"0x{x:08X}"
                for x in
                CODEC_TARGETS
            }
        ):

            kr_dump.add(
                int(
                    r["kr_function"],
                    16
                )
            )

    for va in sorted(
        kr_dump
    ):

        if va not in kr_features:
            continue

        s6.dump_function(
            f"KR_CODEC_MATCH__0x{va:08X}.txt",
            kr_data,
            kr_elf,
            kr_starts,
            va
        )

    # ========================================================
    # Summary
    # ========================================================

    summary = (
        OUT
        / "stage7_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 7\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"PIDX-region functions: "
            f"{len(region_rows)}\n"
        )

        f.write(
            f"Target callsites: "
            f"{len(call_rows)}\n"
        )

        f.write(
            f"Related functions: "
            f"{len(related_rows)}\n"
        )

        f.write(
            f"KR match rows: "
            f"{len(match_rows)}\n\n"
        )

        f.write(
            "TargetLOCAL_PATH"
        )

        for r in relation_rows:

            f.write(
                f' {r["target"]}'
                f' size={r["size"]}'
                f' score={r["score"]}'
                f' lbu={r["lbu"]}'
                f' sb={r["sb"]}'
                f' shift={r["shift"]}'
                f' bit={r["bitwise"]}'
                f' back={r["backward"]}\n'
            )

            f.write(
                f'   callers: '
                f'{r["callers"]}\n'
            )

            f.write(
                f'   callees: '
                f'{r["callees"]}\n'
            )

        f.write(
            "\nTop related decode-like functionLOCAL_PATH"
        )

        for va, feat in (
            ranked_related[:25]
        ):

            f.write(
                f" 0x{va:08X}"
                f" score={feat['decode_score']}"
                f" lbu={feat['lbu']}"
                f" sb={feat['sb']}"
                f" shift={feat['shift']}"
                f" bit={feat['bitwise']}"
                f" back={feat['backward']}\n"
            )

    print()
    print(
        "=" * 72
    )

    print(
        "Stage 7 complete"
    )

    print(
        "=" * 72
    )

    print(
        "Region functions:",
        len(region_rows)
    )

    print(
        "Target callsites:",
        len(call_rows)
    )

    print(
        "Related:",
        len(related_rows)
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
