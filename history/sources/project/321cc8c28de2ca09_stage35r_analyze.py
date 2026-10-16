from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage35r"

BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

FONT_FILE_OFF = 0x39CD04
FONT_RUNTIME = 0x08BA0CB0
GLYPH_SIZE = 162
GLYPH_COUNT = 3600

SPECIAL_RUNTIME = 0x08AE2910
SPECIAL_COUNT = 163
SPECIAL_GLYPH_BASE = 3429

LOAD_DELTA = FONT_RUNTIME - FONT_FILE_OFF
SPECIAL_FILE_OFF = SPECIAL_RUNTIME - LOAD_DELTA

STAGE34_LAST_CODES = [
    0xE1C9, 0xE5BF, 0xE7B2, 0x9DDF, 0xFBFC,
    0xE290, 0x9E8A, 0xE165, 0xE18F, 0x9CB1,
]

STAGE34_LAST_GLYPHS = list(range(3582, 3592))
SEED = "한글테스트가나다라마"

HANGUL_RE = re.compile(r"[\u3131-\u318E\uAC00-\uD7A3]")
JP_RE = re.compile(r"[\u3040-\u30FF\u3400-\u9FFF\uFF61-\uFF9F]")


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_tsv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)


def valid_trail(b):
    return 0x40 <= b <= 0x7E or 0x80 <= b <= 0xFC


def standard_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def standard_glyph(code):
    lead = (code >> 8) & 0xFF
    trail = code & 0xFF

    if not standard_lead(lead) or not valid_trail(trail):
        return None

    row = (
        (
            lead
            - (0x81 if lead < 0xA0 else 0xC1)
        )
        * 2
        + 0x21
    )

    if trail >= 0x9F:
        row += 1
        cell = trail - 0x7E
    else:
        cell = trail - (0x1F if trail < 0x7F else 0x20)

    if not (0x21 <= row <= 0x7E and 0x21 <= cell <= 0x7E):
        return None

    return (row - 0x21) * 94 + (cell - 0x21)


def build_standard_maps():
    glyph_to_code = {}
    code_to_glyph = {}

    leads = list(range(0x81, 0xA0)) + list(range(0xE0, 0xF0))
    trails = list(range(0x40, 0x7F)) + list(range(0x80, 0xFD))

    for lead in leads:
        for trail in trails:
            code = (lead << 8) | trail
            glyph = standard_glyph(code)

            if glyph is None or not (0 <= glyph < GLYPH_COUNT):
                continue

            if glyph in glyph_to_code:
                raise RuntimeError(f"duplicate standard glyph: {glyph}")

            glyph_to_code[glyph] = code
            code_to_glyph[code] = glyph

    if len(glyph_to_code) != GLYPH_COUNT:
        raise RuntimeError(
            f"standard map count {len(glyph_to_code)} != {GLYPH_COUNT}"
        )

    if glyph_to_code.get(0x11F) != 0x82A4:
        raise RuntimeError("82A4 -> glyph 0x11F validation failed")

    return glyph_to_code, code_to_glyph


def read_special_codes(raw):
    if SPECIAL_FILE_OFF < 0:
        raise RuntimeError("negative special table file offset")

    end = SPECIAL_FILE_OFF + SPECIAL_COUNT * 2

    if end > len(raw):
        raise RuntimeError("special table exceeds BOOT")

    block = raw[SPECIAL_FILE_OFF:end]

    candidates = []

    for endian in ("big", "little"):
        codes = [
            int.from_bytes(block[i:i+2], endian)
            for i in range(0, len(block), 2)
        ]

        tail = codes[-10:]
        exact = sum(
            1
            for a, b in zip(tail, STAGE34_LAST_CODES)
            if a == b
        )

        candidates.append((exact, endian, codes))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    exact, endian, codes = candidates[0]

    if exact != 10:
        raise RuntimeError(
            "special 163-code table validation failed: "
            f"best tail match {exact}/10 at file 0x{SPECIAL_FILE_OFF:X}"
        )

    entries = []

    for i, code in enumerate(codes):
        glyph = SPECIAL_GLYPH_BASE + i

        entries.append({
            "index": i,
            "sjis": code,
            "glyph": glyph,
            "file_offset": SPECIAL_FILE_OFF + i * 2,
        })

    for code, glyph in zip(STAGE34_LAST_CODES, STAGE34_LAST_GLYPHS):
        found = [
            e
            for e in entries
            if e["sjis"] == code and e["glyph"] == glyph
        ]

        if not found:
            raise RuntimeError(
                f"Stage34 special validation failed: {code:04X}->{glyph}"
            )

    return endian, entries


def parse_pairs(data):
    i = 0

    while i < len(data):
        b = data[i]

        if (
            (
                standard_lead(b)
                or 0xF0 <= b <= 0xFC
            )
            and i + 1 < len(data)
            and valid_trail(data[i + 1])
        ):
            yield (b << 8) | data[i + 1]
            i += 2
        else:
            i += 1


def decode_usage(data, special_map):
    code_counts = Counter()
    glyph_counts = Counter()

    for code in parse_pairs(data):
        code_counts[code] += 1

        if code in special_map:
            glyph = special_map[code]
        else:
            glyph = standard_glyph(code)

        if glyph is not None and 0 <= glyph < GLYPH_COUNT:
            glyph_counts[glyph] += 1

    return code_counts, glyph_counts


def kr_tbl_sources():
    root = BASE / "analysis" / "stage3" / "extracted" / "kr"

    if not root.exists():
        return []

    return sorted(
        p
        for p in root.glob("*.tbl")
        if p.is_file()
    )


def collect_kr_tbl_usage(special_map):
    code_counts = Counter()
    glyph_counts = Counter()
    coverage = []

    sources = kr_tbl_sources()

    for p in sources:
        data = p.read_bytes()
        c, g = decode_usage(data, special_map)

        code_counts.update(c)
        glyph_counts.update(g)

        coverage.append({
            "kind": "KR_STAGE3_TBL",
            "path": str(p),
            "bytes": len(data),
            "pair_occurrences": sum(c.values()),
            "unique_codes": len(c),
            "unique_glyphs": len(g),
        })

    return code_counts, glyph_counts, coverage


def collect_ui_sample_usage(special_map):
    code_counts = Counter()
    glyph_counts = Counter()
    coverage = []

    p = BASE / "analysis" / "stage9" / "kr_ccs_japanese_scan.tsv"

    if not p.exists():
        return code_counts, glyph_counts, coverage

    sample_count = 0

    with p.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    ) as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            sample = row.get("sample") or ""

            if not sample:
                continue

            try:
                raw = sample.encode("cp932", errors="strict")
            except UnicodeEncodeError:
                raw = sample.encode("cp932", errors="ignore")

            c, g = decode_usage(raw, special_map)
            code_counts.update(c)
            glyph_counts.update(g)
            sample_count += 1

    coverage.append({
        "kind": "KR_CCS_TEXT_SAMPLES",
        "path": str(p),
        "bytes": p.stat().st_size,
        "pair_occurrences": sum(code_counts.values()),
        "unique_codes": len(code_counts),
        "unique_glyphs": len(glyph_counts),
        "samples": sample_count,
    })

    return code_counts, glyph_counts, coverage


def collect_translation_chars():
    chars = Counter()
    sources = []

    roots = [
        OUT / "input_translation",
        BASE / "translation_utf8",
        BASE / "translation",
        BASE / "translations",
        BASE / "translated",
    ]

    candidates = []

    for root in roots:
        if not root.exists():
            continue

        for p in root.rglob("*"):
            if (
                p.is_file()
                and p.suffix.lower() in (".tbl", ".tsv")
            ):
                candidates.append(p)

    seen = set()

    for p in sorted(candidates, key=lambda x: str(x).lower()):
        key = str(p.resolve()).lower()

        if key in seen:
            continue

        seen.add(key)

        raw = p.read_bytes()

        if b"\x00" in raw[:4096]:
            continue

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue

        local = Counter()

        if p.suffix.lower() == ".tbl":
            local.update(HANGUL_RE.findall(text))
            mode = "UTF8_TBL"

        else:
            mode = None

            try:
                with p.open(
                    "r",
                    encoding="utf-8-sig",
                    newline="",
                ) as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    headers = reader.fieldnames or []

                    ko_headers = [
                        h
                        for h in headers
                        if (
                            "한국어" in h
                            or h.strip().lower()
                            in (
                                "ko",
                                "korean",
                                "translation_ko",
                                "translated_ko",
                            )
                        )
                    ]

                    if not ko_headers:
                        continue

                    for row in reader:
                        for h in ko_headers:
                            local.update(
                                HANGUL_RE.findall(row.get(h) or "")
                            )

                    mode = "TSV:" + ",".join(ko_headers)

            except Exception:
                continue

        if not local:
            continue

        chars.update(local)

        sources.append({
            "path": str(p),
            "mode": mode,
            "hangul_occurrences": sum(local.values()),
            "unique_hangul": len(local),
        })

    seeded = False

    if not chars:
        chars.update(SEED)
        seeded = True

        sources.append({
            "path": "(Stage34 seed only)",
            "mode": "SEED_ONLY",
            "hangul_occurrences": len(SEED),
            "unique_hangul": len(set(SEED)),
        })

    return chars, sources, seeded


def main():
    print("=" * 72)
    print("Naruto PSP Stage35R")
    print("Corrected KR-only allocator")
    print("=" * 72)

    if not BOOT.exists():
        raise RuntimeError(f"BOOT missing: {BOOT}")

    raw = BOOT.read_bytes()

    glyph_to_code, code_to_glyph = build_standard_maps()

    endian, special_entries = read_special_codes(raw)

    special_map = {
        e["sjis"]: e["glyph"]
        for e in special_entries
    }

    print(
        "Special table:",
        f"file=0x{SPECIAL_FILE_OFF:X}",
        f"entries={len(special_entries)}",
        f"byte_order={endian}",
        f"glyph_base={SPECIAL_GLYPH_BASE}",
    )

    tbl_codes, tbl_glyphs, tbl_coverage = collect_kr_tbl_usage(
        special_map
    )

    ui_codes, ui_glyphs, ui_coverage = collect_ui_sample_usage(
        special_map
    )

    coverage = tbl_coverage + ui_coverage

    print("KR Stage3 TBL files:", len(tbl_coverage))
    print("KR TBL used glyphs:", len(tbl_glyphs))
    print("UI sample used glyphs:", len(ui_glyphs))

    # Glyph bitmap inventory.
    glyph_empty = {}
    glyph_nonzero = {}

    for glyph in range(GLYPH_COUNT):
        off = FONT_FILE_OFF + glyph * GLYPH_SIZE
        block = raw[off:off + GLYPH_SIZE]

        glyph_empty[glyph] = not any(block)
        glyph_nonzero[glyph] = sum(1 for b in block if b != 0)

    # A raw standard code can only be a donor if the special table
    # does not intercept it to another glyph.
    slots = []

    for glyph in range(GLYPH_COUNT):
        code = glyph_to_code[glyph]

        intercepted = (
            code in special_map
            and special_map[code] != glyph
        )

        tbl_use = tbl_glyphs[glyph]
        ui_use = ui_glyphs[glyph]

        strict_safe = (
            not intercepted
            and tbl_use == 0
            and ui_use == 0
        )

        all_tbls_translated_safe = (
            not intercepted
            and ui_use == 0
        )

        row = {
            "glyph": glyph,
            "glyph_hex": f"0x{glyph:X}",
            "standard_sjis": f"{code:04X}",
            "sjis_hex": f"{code >> 8:02X} {code & 0xFF:02X}",
            "font_file_offset": (
                f"0x{FONT_FILE_OFF + glyph * GLYPH_SIZE:X}"
            ),
            "bitmap_empty": int(glyph_empty[glyph]),
            "bitmap_nonzero_bytes": glyph_nonzero[glyph],
            "special_intercept": int(intercepted),
            "special_target_glyph": (
                special_map.get(code, "")
            ),
            "kr_tbl_usage": tbl_use,
            "ui_sample_usage": ui_use,
            "strict_safe": int(strict_safe),
            "all_tbls_translated_safe": int(all_tbls_translated_safe),
        }

        slots.append(row)

    strict_slots = [
        x for x in slots
        if x["strict_safe"]
    ]

    reclaim_slots = [
        x for x in slots
        if x["all_tbls_translated_safe"]
    ]

    def slot_sort(x):
        return (
            0 if x["bitmap_empty"] else 1,
            -x["glyph"],
        )

    strict_slots.sort(key=slot_sort)
    reclaim_slots.sort(key=slot_sort)

    chars, translation_sources, seeded = collect_translation_chars()

    ordered_chars = sorted(
        chars.items(),
        key=lambda kv: (-kv[1], ord(kv[0])),
    )

    char_rows = [
        {
            "rank": i + 1,
            "char": ch,
            "unicode": f"U+{ord(ch):04X}",
            "frequency": count,
        }
        for i, (ch, count) in enumerate(ordered_chars)
    ]

    def allocate(pool, policy):
        rows = []

        if len(ordered_chars) > len(pool):
            return rows

        for (ch, freq), slot in zip(ordered_chars, pool):
            rows.append({
                "char": ch,
                "unicode": f"U+{ord(ch):04X}",
                "frequency": freq,
                "policy": policy,
                "sjis": slot["standard_sjis"],
                "sjis_hex": slot["sjis_hex"],
                "glyph": slot["glyph"],
                "glyph_hex": slot["glyph_hex"],
                "font_file_offset": slot["font_file_offset"],
                "bitmap_empty_before": slot["bitmap_empty"],
                "kr_tbl_usage_before": slot["kr_tbl_usage"],
                "ui_sample_usage": slot["ui_sample_usage"],
            })

        return rows

    strict_alloc = allocate(
        strict_slots,
        "STRICT_PRESERVE_ALL_KR_TBLS",
    )

    reclaim_alloc = allocate(
        reclaim_slots,
        "RECLAIM_IF_ALL_KR_TBLS_REPLACED",
    )

    # Reports.
    write_tsv(
        OUT / "stage35r_special_table.tsv",
        [
            {
                "index": e["index"],
                "file_offset": f"0x{e['file_offset']:X}",
                "sjis": f"{e['sjis']:04X}",
                "sjis_hex": (
                    f"{e['sjis'] >> 8:02X} "
                    f"{e['sjis'] & 0xFF:02X}"
                ),
                "glyph": e["glyph"],
                "glyph_hex": f"0x{e['glyph']:X}",
                "stage34_tail": int(
                    e["index"] >= SPECIAL_COUNT - 10
                ),
            }
            for e in special_entries
        ],
        [
            "index",
            "file_offset",
            "sjis",
            "sjis_hex",
            "glyph",
            "glyph_hex",
            "stage34_tail",
        ],
    )

    write_tsv(
        OUT / "stage35r_slot_inventory.tsv",
        slots,
        [
            "glyph",
            "glyph_hex",
            "standard_sjis",
            "sjis_hex",
            "font_file_offset",
            "bitmap_empty",
            "bitmap_nonzero_bytes",
            "special_intercept",
            "special_target_glyph",
            "kr_tbl_usage",
            "ui_sample_usage",
            "strict_safe",
            "all_tbls_translated_safe",
        ],
    )

    write_tsv(
        OUT / "stage35r_source_coverage.tsv",
        coverage,
        [
            "kind",
            "path",
            "bytes",
            "pair_occurrences",
            "unique_codes",
            "unique_glyphs",
            "samples",
        ],
    )

    write_tsv(
        OUT / "stage35r_translation_sources.tsv",
        translation_sources,
        [
            "path",
            "mode",
            "hangul_occurrences",
            "unique_hangul",
        ],
    )

    write_tsv(
        OUT / "stage35r_translation_chars.tsv",
        char_rows,
        [
            "rank",
            "char",
            "unicode",
            "frequency",
        ],
    )

    write_tsv(
        OUT / "stage35r_allocation_strict.tsv",
        strict_alloc,
        [
            "char",
            "unicode",
            "frequency",
            "policy",
            "sjis",
            "sjis_hex",
            "glyph",
            "glyph_hex",
            "font_file_offset",
            "bitmap_empty_before",
            "kr_tbl_usage_before",
            "ui_sample_usage",
        ],
    )

    write_tsv(
        OUT / "stage35r_allocation_reclaim_all_tbls.tsv",
        reclaim_alloc,
        [
            "char",
            "unicode",
            "frequency",
            "policy",
            "sjis",
            "sjis_hex",
            "glyph",
            "glyph_hex",
            "font_file_offset",
            "bitmap_empty_before",
            "kr_tbl_usage_before",
            "ui_sample_usage",
        ],
    )

    summary = {
        "stage": "35R",
        "status": "ANALYSIS_ONLY",
        "boot_sha256": sha256_file(BOOT),
        "font": {
            "file_offset": f"0x{FONT_FILE_OFF:X}",
            "runtime": f"0x{FONT_RUNTIME:08X}",
            "glyph_count": GLYPH_COUNT,
            "glyph_size": GLYPH_SIZE,
            "empty_glyphs": sum(
                1
                for v in glyph_empty.values()
                if v
            ),
        },
        "special_table": {
            "runtime": f"0x{SPECIAL_RUNTIME:08X}",
            "file_offset": f"0x{SPECIAL_FILE_OFF:X}",
            "entry_count": len(special_entries),
            "entry_size": 2,
            "byte_order": endian,
            "glyph_base": SPECIAL_GLYPH_BASE,
            "last_10_codes": [
                f"{x:04X}"
                for x in STAGE34_LAST_CODES
            ],
            "last_10_glyphs": STAGE34_LAST_GLYPHS,
            "validation": "PASS",
        },
        "preservation_usage": {
            "kr_stage3_tbl_files": len(tbl_coverage),
            "kr_tbl_unique_codes": len(tbl_codes),
            "kr_tbl_used_glyphs": len(tbl_glyphs),
            "ui_sample_unique_codes": len(ui_codes),
            "ui_sample_used_glyphs": len(ui_glyphs),
            "excluded": [
                "US TBL resources",
                "Stage9 raw extracted TBL duplicates",
                "heuristic BOOT.BIN CP932 string scan",
            ],
        },
        "translation_corpus": {
            "status": (
                "SEED_ONLY"
                if seeded
                else "FOUND"
            ),
            "source_files": len(translation_sources),
            "unique_hangul": len(ordered_chars),
            "occurrences": sum(chars.values()),
        },
        "capacity": {
            "strict_safe_slots": len(strict_slots),
            "strict_empty_slots": sum(
                1 for x in strict_slots
                if x["bitmap_empty"]
            ),
            "reclaim_all_tbls_slots": len(reclaim_slots),
            "reclaim_all_tbls_empty_slots": sum(
                1 for x in reclaim_slots
                if x["bitmap_empty"]
            ),
            "needed_chars": len(ordered_chars),
            "strict_capacity_ok": (
                len(ordered_chars) <= len(strict_slots)
            ),
            "reclaim_capacity_ok": (
                len(ordered_chars) <= len(reclaim_slots)
            ),
        },
    }

    (
        OUT / "stage35r_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "Naruto PSP Stage 35R",
        "=" * 72,
        "",
        "STATUS: ANALYSIS_ONLY",
        "",
        "Corrections from Stage35:",
        "  - KR resources only; US TBL excluded.",
        "  - Raw BOOT CP932 heuristic scan removed.",
        "  - Stage9 extracted duplicate TBL scan removed.",
        "  - Special table is 163 x 2-byte SJIS codes.",
        (
            f"  - special[i] -> glyph "
            f"{SPECIAL_GLYPH_BASE}+i."
        ),
        "",
        "Special table:",
        f"  file offset: 0x{SPECIAL_FILE_OFF:X}",
        f"  byte order: {endian}",
        f"  entries: {len(special_entries)}",
        "  Stage34 last-10 validation: PASS",
        "",
        "Preservation coverage:",
        f"  KR Stage3 TBL files: {len(tbl_coverage)}",
        f"  KR TBL used glyphs: {len(tbl_glyphs)}",
        f"  UI sample used glyphs: {len(ui_glyphs)}",
        "",
        "Translation corpus:",
        (
            "  status: SEED_ONLY"
            if seeded
            else "  status: FOUND"
        ),
        f"  unique Hangul: {len(ordered_chars)}",
        f"  occurrences: {sum(chars.values())}",
        "",
        "Capacity:",
        (
            f"  STRICT (preserve all KR TBL + UI): "
            f"{len(strict_slots)} slots"
        ),
        (
            f"    empty bitmap slots: "
            f"{sum(1 for x in strict_slots if x['bitmap_empty'])}"
        ),
        (
            f"  RECLAIM ALL TBL (preserve UI only): "
            f"{len(reclaim_slots)} slots"
        ),
        (
            f"    empty bitmap slots: "
            f"{sum(1 for x in reclaim_slots if x['bitmap_empty'])}"
        ),
        f"  needed now: {len(ordered_chars)}",
        (
            f"  strict capacity OK: "
            f"{len(ordered_chars) <= len(strict_slots)}"
        ),
        (
            f"  reclaim capacity OK: "
            f"{len(ordered_chars) <= len(reclaim_slots)}"
        ),
    ]

    if seeded:
        lines.extend([
            "",
            "IMPORTANT:",
            "  Full Korean translation corpus was not found.",
            (
                "  Put UTF-8 translated .tbl/.tsv files under "
                r"PROJECT_ROOT\analysis\stage35r\input_translation"
            ),
            "  and rerun this stage for the final character count.",
        ])

    (
        OUT / "stage35r_summary.txt"
    ).write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE35R ANALYSIS COMPLETE")
    print("=" * 72)
    print(
        "Special table:",
        f"0x{SPECIAL_FILE_OFF:X}",
        endian,
        "PASS",
    )
    print("KR TBL files:", len(tbl_coverage))
    print("KR TBL used glyphs:", len(tbl_glyphs))
    print("UI sample used glyphs:", len(ui_glyphs))
    print("Translation chars:", len(ordered_chars))
    print("Strict capacity:", len(strict_slots))
    print("Reclaim-all-TBL capacity:", len(reclaim_slots))
    print()
    print(OUT / "stage35r_summary.txt")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
