$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage35"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage35_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
}

function RunPy {
    param(
        [string]$Label,
        [string[]]$PythonArgs
    )

    Log ""
    Log "===== $Label ====="

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python @PythonArgs 2>&1 |
        ForEach-Object { Log "$_" }

    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPref
    return $code
}

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    if (Test-Path -LiteralPath $runLog) {
        Copy-Item -LiteralPath $runLog -Destination $failDir -Force
    }

    Get-ChildItem -LiteralPath $stage -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -eq ".txt" -or
            $_.Extension -eq ".tsv" -or
            $_.Extension -eq ".json" -or
            $_.Extension -eq ".py"
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
        }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 35 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

try {
    Log "Naruto PSP Stage 35"
    Log "Translation charset / safe glyph-slot allocator"
    Log "Started: $(Get-Date)"

    $analyzer = Join-Path $stage "stage35_charset_allocator.py"

    $analyzerCode = @'
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage35"
OUT.mkdir(parents=True, exist_ok=True)

BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

FONT_FILE_OFF = 0x39CD04
FONT_RUNTIME = 0x08BA0CB0
FONT_W = 18
FONT_H = 18
GLYPH_SIZE = 162
GLYPH_COUNT = 3600

SPECIAL_RUNTIME = 0x08AE2910
SPECIAL_COUNT = 163

LOAD_DELTA = FONT_RUNTIME - FONT_FILE_OFF
SPECIAL_EXPECTED_OFF = SPECIAL_RUNTIME - LOAD_DELTA

STAGE34_SPECIAL_CODES = [
    0xE1C9,
    0xE5BF,
    0xE7B2,
    0x9DDF,
    0xFBFC,
    0xE290,
    0x9E8A,
    0xE165,
    0xE18F,
    0x9CB1,
]

STAGE34_GLYPHS = list(range(3582, 3592))
STAGE34_SEED = "한글테스트가나다라마"

HANGUL_RE = re.compile(r"[\u3131-\u318E\uAC00-\uD7A3]")
JP_RE = re.compile(r"[\u3040-\u30FF\u3400-\u9FFF\uFF61-\uFF9F]")

PREFERRED_KO_HEADERS = [
    "수정 한국어",
    "한국어",
    "현재 한국어",
    "korean",
    "ko",
    "translation_ko",
    "translated_ko",
]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)

    return h.hexdigest()


def write_tsv(path, rows, fields):
    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields,
            extrasaction="ignore",
        )
        w.writeheader()

        for row in rows:
            w.writerow(row)


def is_valid_sjis_trail(b):
    return (
        0x40 <= b <= 0x7E
        or 0x80 <= b <= 0xFC
    )


def is_standard_sjis_lead(b):
    return (
        0x81 <= b <= 0x9F
        or 0xE0 <= b <= 0xEF
    )


def sjis_standard_glyph(code):
    lead = (code >> 8) & 0xFF
    trail = code & 0xFF

    if not is_standard_sjis_lead(lead):
        return None

    if not is_valid_sjis_trail(trail):
        return None

    row = (
        (
            lead
            - (
                0x81
                if lead < 0xA0
                else 0xC1
            )
        )
        * 2
        + 0x21
    )

    if trail >= 0x9F:
        row += 1
        cell = trail - 0x7E
    else:
        cell = (
            trail
            - (
                0x1F
                if trail < 0x7F
                else 0x20
            )
        )

    if not (
        0x21 <= row <= 0x7E
        and 0x21 <= cell <= 0x7E
    ):
        return None

    glyph = (
        (row - 0x21) * 94
        + (cell - 0x21)
    )

    return glyph


def build_standard_map():
    glyph_to_code = {}
    code_to_glyph = {}

    leads = (
        list(range(0x81, 0xA0))
        + list(range(0xE0, 0xF0))
    )

    trails = (
        list(range(0x40, 0x7F))
        + list(range(0x80, 0xFD))
    )

    for lead in leads:
        for trail in trails:
            code = (lead << 8) | trail
            glyph = sjis_standard_glyph(code)

            if glyph is None:
                continue

            if not (0 <= glyph < GLYPH_COUNT):
                continue

            if glyph in glyph_to_code:
                raise RuntimeError(
                    f"duplicate standard glyph mapping: {glyph}"
                )

            glyph_to_code[glyph] = code
            code_to_glyph[code] = glyph

    if len(glyph_to_code) != GLYPH_COUNT:
        raise RuntimeError(
            "standard SJIS map did not cover "
            f"all {GLYPH_COUNT} glyphs: "
            f"{len(glyph_to_code)}"
        )

    # Stage34 / runtime validation:
    # CP932 82A4 ("う") -> JIS linear index 0x11F.
    if glyph_to_code.get(0x11F) != 0x82A4:
        raise RuntimeError(
            "SJIS->glyph formula validation failed "
            "for う / 82A4 / 0x11F"
        )

    return glyph_to_code, code_to_glyph


def decode_special_entry(raw, off, layout):
    b = raw[off:off + 4]

    if len(b) != 4:
        raise ValueError("short special entry")

    if layout == "codeLE_glyphLE":
        code = int.from_bytes(b[0:2], "little")
        glyph = int.from_bytes(b[2:4], "little")

    elif layout == "codeBE_glyphLE":
        code = int.from_bytes(b[0:2], "big")
        glyph = int.from_bytes(b[2:4], "little")

    elif layout == "glyphLE_codeLE":
        glyph = int.from_bytes(b[0:2], "little")
        code = int.from_bytes(b[2:4], "little")

    elif layout == "glyphLE_codeBE":
        glyph = int.from_bytes(b[0:2], "little")
        code = int.from_bytes(b[2:4], "big")

    else:
        raise ValueError(layout)

    return code, glyph


def special_match_score(raw, start, layout):
    score = 0
    start_index = SPECIAL_COUNT - len(STAGE34_SPECIAL_CODES)

    for i, (expected_code, expected_glyph) in enumerate(
        zip(STAGE34_SPECIAL_CODES, STAGE34_GLYPHS)
    ):
        off = start + (start_index + i) * 4

        try:
            code, glyph = decode_special_entry(
                raw,
                off,
                layout,
            )
        except Exception:
            return -1

        if code == expected_code:
            score += 2

        if glyph == expected_glyph:
            score += 2

    return score


def detect_special_table(raw):
    layouts = [
        "codeLE_glyphLE",
        "codeBE_glyphLE",
        "glyphLE_codeLE",
        "glyphLE_codeBE",
    ]

    candidates = []

    for delta in range(-0x100, 0x104, 4):
        start = SPECIAL_EXPECTED_OFF + delta

        if start < 0:
            continue

        if start + SPECIAL_COUNT * 4 > len(raw):
            continue

        for layout in layouts:
            score = special_match_score(
                raw,
                start,
                layout,
            )

            candidates.append({
                "start": start,
                "layout": layout,
                "score": score,
            })

    candidates.sort(
        key=lambda x: (
            -x["score"],
            abs(x["start"] - SPECIAL_EXPECTED_OFF),
            x["layout"],
        )
    )

    best = candidates[0] if candidates else None

    if best is None or best["score"] < 30:
        return None, candidates[:16]

    entries = []

    for i in range(SPECIAL_COUNT):
        off = best["start"] + i * 4
        code, glyph = decode_special_entry(
            raw,
            off,
            best["layout"],
        )

        entries.append({
            "index": i,
            "file_offset": off,
            "code": code,
            "glyph": glyph,
        })

    return (
        {
            "start": best["start"],
            "layout": best["layout"],
            "score": best["score"],
            "entries": entries,
        },
        candidates[:16],
    )


def parse_sjis_codes(data):
    codes = Counter()
    i = 0

    while i < len(data):
        b = data[i]

        if (
            (
                is_standard_sjis_lead(b)
                or 0xF0 <= b <= 0xFC
            )
            and i + 1 < len(data)
            and is_valid_sjis_trail(data[i + 1])
        ):
            code = (b << 8) | data[i + 1]
            codes[code] += 1
            i += 2
            continue

        i += 1

    return codes


def text_to_sjis_codes(text):
    raw = text.encode(
        "cp932",
        errors="ignore",
    )

    return parse_sjis_codes(raw)


def looks_japanese(text):
    return bool(JP_RE.search(text))


def stage_number_from_path(path):
    m = re.search(
        r"[\\/]+stage(\d+)(?:[\\/]|$)",
        str(path),
        re.I,
    )

    if not m:
        return None

    return int(m.group(1))


def discover_original_tbls():
    rows = []
    seen_hashes = set()
    candidates = []

    roots = [
        BASE / "analysis" / "stage9",
        BASE / "analysis" / "stage8",
        BASE / "kr_extracted",
    ]

    for root in roots:
        if not root.exists():
            continue

        for p in root.rglob("*.tbl"):
            if p.is_file():
                candidates.append(p)

    analysis_root = BASE / "analysis"

    if analysis_root.exists():
        for p in analysis_root.rglob("*.tbl"):
            if not p.is_file():
                continue

            stage_no = stage_number_from_path(p)

            if stage_no is not None and stage_no >= 10:
                continue

            name = p.name.lower()
            parent = str(p.parent).lower()

            if (
                name.startswith("entry")
                or "decoded" in parent
                or "extract" in parent
            ):
                candidates.append(p)

    for p in candidates:
        try:
            if p.stat().st_size > 8 * 1024 * 1024:
                continue

            digest = sha256_file(p)
        except OSError:
            continue

        if digest in seen_hashes:
            continue

        seen_hashes.add(digest)

        rows.append({
            "path": p,
            "sha256": digest,
            "size": p.stat().st_size,
            "kind": "decoded_tbl",
        })

    rows.sort(
        key=lambda x: str(x["path"]).lower()
    )

    return rows


def collect_original_usage():
    usage = Counter()
    coverage = []

    tbls = discover_original_tbls()

    for item in tbls:
        p = item["path"]

        try:
            data = p.read_bytes()
        except OSError:
            continue

        counts = parse_sjis_codes(data)
        usage.update(counts)

        coverage.append({
            "source_kind": "decoded_tbl",
            "path": str(p),
            "bytes": len(data),
            "sjis_pairs_counted": sum(counts.values()),
            "unique_sjis_pairs": len(counts),
            "accepted_strings": "",
        })

    # Stage9 reports cover events, quiz, and CCS text samples even
    # if the large decoded extraction tree was cleaned up later.
    report_names = [
        "event_dialogue_pairs_v2.tsv",
        "quiz_kr_questions.tsv",
        "kr_ccs_japanese_scan.tsv",
    ]

    for name in report_names:
        p = BASE / "analysis" / "stage9" / name

        if not p.exists():
            continue

        counts = Counter()

        try:
            with p.open(
                "r",
                encoding="utf-8-sig",
                errors="replace",
                newline="",
            ) as f:
                reader = csv.reader(
                    f,
                    delimiter="\t",
                )

                for row in reader:
                    for cell in row:
                        if looks_japanese(cell):
                            counts.update(
                                text_to_sjis_codes(cell)
                            )

        except Exception:
            continue

        usage.update(counts)

        coverage.append({
            "source_kind": "stage9_report",
            "path": str(p),
            "bytes": p.stat().st_size,
            "sjis_pairs_counted": sum(counts.values()),
            "unique_sjis_pairs": len(counts),
            "accepted_strings": "",
        })

    # Hardcoded Japanese strings in BOOT, but only plausible
    # NUL-separated CP932 strings to avoid binary false positives.
    if BOOT.exists():
        raw = BOOT.read_bytes()
        counts = Counter()
        accepted = 0

        for chunk in raw.split(b"\x00"):
            if not (2 <= len(chunk) <= 256):
                continue

            try:
                text = chunk.decode(
                    "cp932",
                    errors="strict",
                )
            except UnicodeDecodeError:
                continue

            if not looks_japanese(text):
                continue

            printable = sum(
                1
                for ch in text
                if ch.isprintable()
            )

            if not text or printable / len(text) < 0.80:
                continue

            accepted += 1
            counts.update(
                parse_sjis_codes(chunk)
            )

        usage.update(counts)

        coverage.append({
            "source_kind": "boot_cp932_strings",
            "path": str(BOOT),
            "bytes": len(raw),
            "sjis_pairs_counted": sum(counts.values()),
            "unique_sjis_pairs": len(counts),
            "accepted_strings": accepted,
        })

    return usage, coverage, tbls


def read_utf8_if_possible(path):
    raw = path.read_bytes()

    if b"\x00" in raw[:4096]:
        return None

    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(
                enc,
                errors="strict",
            )
        except UnicodeDecodeError:
            continue

    return None


def collect_translation_chars():
    chars = Counter()
    sources = []
    candidates = []

    for suffix in ("*.tbl", "*.tsv"):
        for p in BASE.rglob(suffix):
            if not p.is_file():
                continue

            s = str(p).lower()

            if (
                "\\logs\\old\\" in s
                or "\\logs\\failed\\" in s
            ):
                continue

            stage_no = stage_number_from_path(p)

            # Stage34 and older are source analysis / test probes.
            if stage_no is not None and stage_no <= 34:
                continue

            if (
                "\\us\\" in s
                or "\\us_extracted\\" in s
            ):
                continue

            if p.stat().st_size > 32 * 1024 * 1024:
                continue

            candidates.append(p)

    # Common explicit translation roots are always included.
    explicit_roots = [
        BASE / "translation",
        BASE / "translations",
        BASE / "translated",
        BASE / "translation_utf8",
        BASE / "work",
    ]

    for root in explicit_roots:
        if not root.exists():
            continue

        for p in root.rglob("*"):
            if (
                p.is_file()
                and p.suffix.lower()
                in (".tbl", ".tsv")
            ):
                candidates.append(p)

    unique = {}

    for p in candidates:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()

        unique[key] = p

    for p in sorted(
        unique.values(),
        key=lambda x: str(x).lower(),
    ):
        try:
            text = read_utf8_if_possible(p)
        except OSError:
            continue

        if not text:
            continue

        local = Counter()
        mode = None

        if p.suffix.lower() == ".tbl":
            found = HANGUL_RE.findall(text)

            if not found:
                continue

            local.update(found)
            mode = "utf8_tbl"

        elif p.suffix.lower() == ".tsv":
            try:
                with p.open(
                    "r",
                    encoding="utf-8-sig",
                    newline="",
                ) as f:
                    reader = csv.DictReader(
                        f,
                        delimiter="\t",
                    )

                    headers = reader.fieldnames or []
                    preferred = []

                    for h in headers:
                        normalized = h.strip().lower()

                        if (
                            normalized in PREFERRED_KO_HEADERS
                            or "한국어" in h
                        ):
                            preferred.append(h)

                    if not preferred:
                        continue

                    for row in reader:
                        for h in preferred:
                            value = row.get(h) or ""
                            local.update(
                                HANGUL_RE.findall(value)
                            )

                if not local:
                    continue

                mode = "tsv_columns:" + ",".join(preferred)

            except Exception:
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
        seeded = True
        chars.update(STAGE34_SEED)

        sources.append({
            "path": "(Stage34 verification seed)",
            "mode": "seed_only",
            "hangul_occurrences": len(STAGE34_SEED),
            "unique_hangul": len(set(STAGE34_SEED)),
        })

    return chars, sources, seeded


def describe_unicode(ch):
    cp = ord(ch)

    if 0xAC00 <= cp <= 0xD7A3:
        return "hangul_syllable"

    if 0x3131 <= cp <= 0x318E:
        return "hangul_compat_jamo"

    return "other"


def main():
    print("=" * 72)
    print("Naruto PSP Stage 35")
    print("Translation charset / safe glyph-slot allocator")
    print("=" * 72)

    if not BOOT.exists():
        raise RuntimeError(
            f"BOOT.BIN 없음: {BOOT}"
        )

    raw = BOOT.read_bytes()

    font_end = (
        FONT_FILE_OFF
        + GLYPH_COUNT * GLYPH_SIZE
    )

    if font_end > len(raw):
        raise RuntimeError(
            "BOOT.BIN font range exceeds file size"
        )

    glyph_to_standard, standard_to_glyph = (
        build_standard_map()
    )

    special, special_candidates = detect_special_table(raw)

    special_entries = []

    if special is not None:
        special_entries = special["entries"]

        print(
            "Special table:",
            f"0x{special['start']:X}",
            special["layout"],
            f"score={special['score']}",
        )
    else:
        print(
            "WARNING: special table auto-detection failed."
        )

    # ========================================================
    # Glyph inventory
    # ========================================================

    glyph_rows = []
    glyph_empty = {}
    glyph_nonzero = {}

    for glyph in range(GLYPH_COUNT):
        off = FONT_FILE_OFF + glyph * GLYPH_SIZE
        bitmap = raw[off:off + GLYPH_SIZE]

        nonzero = sum(
            1
            for b in bitmap
            if b != 0
        )

        empty = nonzero == 0

        glyph_empty[glyph] = empty
        glyph_nonzero[glyph] = nonzero

        glyph_rows.append({
            "glyph": glyph,
            "glyph_hex": f"0x{glyph:X}",
            "file_offset": f"0x{off:X}",
            "standard_sjis": f"{glyph_to_standard[glyph]:04X}",
            "bitmap_empty": int(empty),
            "bitmap_nonzero_bytes": nonzero,
            "bitmap_sha256": sha256_bytes(bitmap),
        })

    # ========================================================
    # Special table report
    # ========================================================

    special_rows = []
    special_code_to_glyph = {}
    special_codes_by_glyph = defaultdict(list)

    for entry in special_entries:
        code = entry["code"]
        glyph = entry["glyph"]

        special_code_to_glyph[code] = glyph
        special_codes_by_glyph[glyph].append(code)

        special_rows.append({
            "index": entry["index"],
            "file_offset": f"0x{entry['file_offset']:X}",
            "sjis": f"{code:04X}",
            "glyph": glyph,
            "glyph_hex": f"0x{glyph:X}",
            "glyph_in_range": int(
                0 <= glyph < GLYPH_COUNT
            ),
            "stage34_test_code": int(
                code in STAGE34_SPECIAL_CODES
            ),
        })

    # ========================================================
    # Original usage
    # ========================================================

    usage, coverage, original_tbls = (
        collect_original_usage()
    )

    print(
        "Original decoded TBLs:",
        len(original_tbls)
    )

    print(
        "Distinct SJIS pairs observed:",
        len(usage)
    )

    # ========================================================
    # Slot inventory
    # ========================================================

    inventory = []
    safe_slots = []

    for glyph in range(GLYPH_COUNT):
        standard_code = glyph_to_standard[glyph]
        special_aliases = special_codes_by_glyph.get(
            glyph,
            [],
        )

        overridden = False

        if (
            standard_code in special_code_to_glyph
            and special_code_to_glyph[
                standard_code
            ] != glyph
        ):
            overridden = True

        standard_use = usage[standard_code]

        special_use = sum(
            usage[code]
            for code in special_aliases
        )

        total_use = (
            standard_use
            + special_use
        )

        aliases_text = ",".join(
            f"{x:04X}"
            for x in special_aliases
        )

        candidate = (
            not overridden
            and total_use == 0
        )

        if candidate:
            safety = (
                "A_EMPTY_UNUSED"
                if glyph_empty[glyph]
                else "B_NONEMPTY_UNUSED"
            )
        else:
            safety = "USED_OR_BLOCKED"

        row = {
            "glyph": glyph,
            "glyph_hex": f"0x{glyph:X}",
            "standard_sjis": f"{standard_code:04X}",
            "special_aliases": aliases_text,
            "standard_code_overridden": int(overridden),
            "standard_usage": standard_use,
            "special_alias_usage": special_use,
            "total_observed_usage": total_use,
            "bitmap_empty": int(
                glyph_empty[glyph]
            ),
            "bitmap_nonzero_bytes": glyph_nonzero[glyph],
            "candidate": int(candidate),
            "safety": safety,
        }

        inventory.append(row)

        if candidate:
            safe_slots.append(row)

    safe_slots.sort(
        key=lambda r: (
            0 if r["bitmap_empty"] else 1,
            -r["glyph"],
        )
    )

    # ========================================================
    # Translation corpus
    # ========================================================

    ko_chars, ko_sources, seeded = (
        collect_translation_chars()
    )

    chars_sorted = sorted(
        ko_chars.items(),
        key=lambda kv: (
            -kv[1],
            ord(kv[0]),
        )
    )

    char_rows = []

    for rank, (ch, count) in enumerate(
        chars_sorted,
        1,
    ):
        char_rows.append({
            "rank": rank,
            "char": ch,
            "unicode": f"U+{ord(ch):04X}",
            "category": describe_unicode(ch),
            "frequency": count,
        })

    # ========================================================
    # Draft allocation
    # ========================================================

    allocation = []

    if len(chars_sorted) <= len(safe_slots):
        for (ch, count), slot in zip(
            chars_sorted,
            safe_slots,
        ):
            code = int(
                slot["standard_sjis"],
                16,
            )

            glyph_off = (
                FONT_FILE_OFF
                + slot["glyph"] * GLYPH_SIZE
            )

            allocation.append({
                "char": ch,
                "unicode": f"U+{ord(ch):04X}",
                "frequency": count,
                "sjis": f"{code:04X}",
                "sjis_hex": (
                    f"{code >> 8:02X} "
                    f"{code & 0xFF:02X}"
                ),
                "glyph": slot["glyph"],
                "glyph_hex": slot["glyph_hex"],
                "glyph_file_offset": f"0x{glyph_off:X}",
                "slot_safety": slot["safety"],
                "original_bitmap_empty": slot["bitmap_empty"],
                "special_aliases": slot["special_aliases"],
                "observed_original_usage": slot[
                    "total_observed_usage"
                ],
            })

    # ========================================================
    # Allocation validation
    # ========================================================

    errors = []
    seen_codes = set()
    seen_glyphs = set()

    for row in allocation:
        code = int(row["sjis"], 16)
        glyph = int(row["glyph"])

        if code in seen_codes:
            errors.append(
                f"duplicate SJIS {code:04X}"
            )

        if glyph in seen_glyphs:
            errors.append(
                f"duplicate glyph {glyph}"
            )

        seen_codes.add(code)
        seen_glyphs.add(glyph)

        mapped = sjis_standard_glyph(code)

        if mapped != glyph:
            errors.append(
                f"SJIS {code:04X} maps "
                f"to {mapped}, expected {glyph}"
            )

        if usage[code] != 0:
            errors.append(
                f"allocated code {code:04X} "
                f"has original usage {usage[code]}"
            )

        if (
            code in special_code_to_glyph
            and special_code_to_glyph[code] != glyph
        ):
            errors.append(
                f"allocated code {code:04X} "
                "is overridden by special table"
            )

    # ========================================================
    # Coverage confidence
    # ========================================================

    decoded_tbl_count = sum(
        1
        for x in coverage
        if x["source_kind"] == "decoded_tbl"
    )

    have_stage9_event = any(
        (
            x["source_kind"] == "stage9_report"
            and "event_dialogue_pairs" in x["path"]
        )
        for x in coverage
    )

    have_ccs_report = any(
        (
            x["source_kind"] == "stage9_report"
            and "kr_ccs_japanese_scan" in x["path"]
        )
        for x in coverage
    )

    if (
        decoded_tbl_count >= 40
        and have_stage9_event
    ):
        coverage_grade = "HIGH"
    elif (
        decoded_tbl_count >= 20
        or have_stage9_event
    ):
        coverage_grade = "MEDIUM"
    else:
        coverage_grade = "LOW"

    corpus_status = (
        "SEED_ONLY"
        if seeded
        else "TRANSLATION_CORPUS_FOUND"
    )

    capacity_ok = (
        len(chars_sorted)
        <= len(safe_slots)
    )

    # ========================================================
    # Outputs
    # ========================================================

    write_tsv(
        OUT / "stage35_font_glyphs.tsv",
        glyph_rows,
        [
            "glyph",
            "glyph_hex",
            "file_offset",
            "standard_sjis",
            "bitmap_empty",
            "bitmap_nonzero_bytes",
            "bitmap_sha256",
        ],
    )

    write_tsv(
        OUT / "stage35_special_table.tsv",
        special_rows,
        [
            "index",
            "file_offset",
            "sjis",
            "glyph",
            "glyph_hex",
            "glyph_in_range",
            "stage34_test_code",
        ],
    )

    write_tsv(
        OUT / "stage35_sjis_slot_inventory.tsv",
        inventory,
        [
            "glyph",
            "glyph_hex",
            "standard_sjis",
            "special_aliases",
            "standard_code_overridden",
            "standard_usage",
            "special_alias_usage",
            "total_observed_usage",
            "bitmap_empty",
            "bitmap_nonzero_bytes",
            "candidate",
            "safety",
        ],
    )

    write_tsv(
        OUT / "stage35_source_coverage.tsv",
        coverage,
        [
            "source_kind",
            "path",
            "bytes",
            "sjis_pairs_counted",
            "unique_sjis_pairs",
            "accepted_strings",
        ],
    )

    write_tsv(
        OUT / "stage35_translation_sources.tsv",
        ko_sources,
        [
            "path",
            "mode",
            "hangul_occurrences",
            "unique_hangul",
        ],
    )

    write_tsv(
        OUT / "stage35_translation_chars.tsv",
        char_rows,
        [
            "rank",
            "char",
            "unicode",
            "category",
            "frequency",
        ],
    )

    write_tsv(
        OUT / "stage35_allocation.tsv",
        allocation,
        [
            "char",
            "unicode",
            "frequency",
            "sjis",
            "sjis_hex",
            "glyph",
            "glyph_hex",
            "glyph_file_offset",
            "slot_safety",
            "original_bitmap_empty",
            "special_aliases",
            "observed_original_usage",
        ],
    )

    mapping_json = {
        row["char"]: {
            "unicode": row["unicode"],
            "sjis": row["sjis"],
            "sjis_hex": row["sjis_hex"],
            "glyph": row["glyph"],
            "glyph_file_offset": row["glyph_file_offset"],
            "slot_safety": row["slot_safety"],
        }
        for row in allocation
    }

    (
        OUT / "stage35_allocation.json"
    ).write_text(
        json.dumps(
            mapping_json,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    detector_rows = [
        {
            "rank": i + 1,
            "start": f"0x{x['start']:X}",
            "layout": x["layout"],
            "score": x["score"],
            "distance_from_expected": (
                x["start"]
                - SPECIAL_EXPECTED_OFF
            ),
        }
        for i, x in enumerate(
            special_candidates
        )
    ]

    write_tsv(
        OUT / "stage35_special_detection.tsv",
        detector_rows,
        [
            "rank",
            "start",
            "layout",
            "score",
            "distance_from_expected",
        ],
    )

    summary = {
        "stage": 35,
        "status": "ANALYSIS_ONLY",
        "boot": {
            "path": str(BOOT),
            "sha256": sha256_file(BOOT),
            "font_file_offset": f"0x{FONT_FILE_OFF:X}",
            "font_runtime": f"0x{FONT_RUNTIME:08X}",
            "glyph_count": GLYPH_COUNT,
            "glyph_size": GLYPH_SIZE,
            "empty_glyphs": sum(
                1
                for x in glyph_rows
                if x["bitmap_empty"]
            ),
        },
        "special_table": {
            "expected_file_offset": f"0x{SPECIAL_EXPECTED_OFF:X}",
            "detected": special is not None,
            "detected_file_offset": (
                f"0x{special['start']:X}"
                if special is not None
                else None
            ),
            "layout": (
                special["layout"]
                if special is not None
                else None
            ),
            "score": (
                special["score"]
                if special is not None
                else None
            ),
            "entry_count": len(special_entries),
        },
        "original_usage": {
            "coverage_grade": coverage_grade,
            "decoded_tbl_files": decoded_tbl_count,
            "have_stage9_event_report": have_stage9_event,
            "have_ccs_scan_report": have_ccs_report,
            "distinct_sjis_pairs": len(usage),
            "total_sjis_pair_occurrences": sum(
                usage.values()
            ),
        },
        "translation_corpus": {
            "status": corpus_status,
            "source_files": len(ko_sources),
            "unique_hangul": len(chars_sorted),
            "hangul_occurrences": sum(
                ko_chars.values()
            ),
        },
        "allocation": {
            "safe_candidate_slots": len(safe_slots),
            "empty_unused_slots": sum(
                1
                for x in safe_slots
                if x["bitmap_empty"]
            ),
            "nonempty_unused_slots": sum(
                1
                for x in safe_slots
                if not x["bitmap_empty"]
            ),
            "needed_chars": len(chars_sorted),
            "allocated_chars": len(allocation),
            "capacity_ok": capacity_ok,
            "validation_errors": errors,
        },
    }

    (
        OUT / "stage35_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    text_lines = [
        "Naruto PSP Stage 35",
        "=" * 72,
        "",
        "STATUS: ANALYSIS_ONLY",
        "",
        f"BOOT: {BOOT}",
        f"BOOT SHA256: {summary['boot']['sha256']}",
        "",
        "Verified font model:",
        (
            f"  {GLYPH_COUNT} glyphs, "
            f"{FONT_W}x{FONT_H}, "
            f"{GLYPH_SIZE} bytes/glyph"
        ),
        f"  file offset: 0x{FONT_FILE_OFF:X}",
        f"  runtime: 0x{FONT_RUNTIME:08X}",
        (
            f"  empty glyphs: "
            f"{summary['boot']['empty_glyphs']}"
        ),
        "",
        "SJIS mapping verification:",
        "  82A4 (う) -> glyph 0x11F : PASS",
        (
            f"  standard formula slots: "
            f"{len(glyph_to_standard)}"
        ),
        "",
        "Special table:",
        (
            "  detected: YES"
            if special is not None
            else "  detected: NO"
        ),
        (
            (
                f"  file offset: "
                f"0x{special['start']:X}"
            )
            if special is not None
            else (
                f"  expected near: "
                f"0x{SPECIAL_EXPECTED_OFF:X}"
            )
        ),
        (
            (
                f"  layout: "
                f"{special['layout']}"
            )
            if special is not None
            else ""
        ),
        "",
        "Original Japanese/resource coverage:",
        f"  grade: {coverage_grade}",
        (
            f"  decoded TBL files: "
            f"{decoded_tbl_count}"
        ),
        (
            f"  distinct SJIS pairs: "
            f"{len(usage)}"
        ),
        "",
        "Translation corpus:",
        f"  status: {corpus_status}",
        (
            f"  source files: "
            f"{len(ko_sources)}"
        ),
        (
            f"  unique Hangul: "
            f"{len(chars_sorted)}"
        ),
        (
            f"  Hangul occurrences: "
            f"{sum(ko_chars.values())}"
        ),
        "",
        "Safe candidate capacity:",
        (
            f"  total unused slots: "
            f"{len(safe_slots)}"
        ),
        (
            "  empty + unused: "
            f"{sum(1 for x in safe_slots if x['bitmap_empty'])}"
        ),
        (
            "  nonempty but unused: "
            f"{sum(1 for x in safe_slots if not x['bitmap_empty'])}"
        ),
        f"  needed: {len(chars_sorted)}",
        f"  capacity OK: {capacity_ok}",
        "",
        "Draft allocation:",
        f"  mapped chars: {len(allocation)}",
        f"  validation errors: {len(errors)}",
    ]

    if seeded:
        text_lines.extend([
            "",
            "IMPORTANT:",
            (
                "  전체 UTF-8 한국어 번역 corpus를 찾지 못해 "
                "Stage34 검증 문자열만 seed로 사용했습니다."
            ),
            (
                "  stage35_allocation.tsv는 구조 검증용이며 "
                "전체 번역용 최종 매핑이 아닙니다."
            ),
        ])

    if coverage_grade != "HIGH":
        text_lines.extend([
            "",
            "CAUTION:",
            (
                "  원본 일본어 리소스 사용량 coverage가 HIGH가 아닙니다."
            ),
            (
                "  전체 decoded TBL/텍스트 리소스가 확보되기 전에는 "
                "B_NONEMPTY_UNUSED 슬롯을 최종 확정하지 않습니다."
            ),
        ])

    if errors:
        text_lines.extend([
            "",
            "VALIDATION ERRORS:",
            *[
                "  - " + e
                for e in errors
            ],
        ])

    (
        OUT / "stage35_summary.txt"
    ).write_text(
        "\n".join(text_lines),
        encoding="utf-8",
    )

    # ========================================================
    # Reusable encoder module for Stage36+
    # ========================================================

    mapper_py = r'''from pathlib import Path
import json


class NarutoHangulMapper:
    def __init__(self, mapping_json):
        path = Path(mapping_json)

        self.mapping = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        self.char_to_bytes = {
            ch: bytes.fromhex(
                info["sjis_hex"]
            )
            for ch, info
            in self.mapping.items()
        }

    def encode_text(self, text):
        out = bytearray()

        for ch in text:
            custom = self.char_to_bytes.get(ch)

            if custom is not None:
                out.extend(custom)
                continue

            try:
                out.extend(
                    ch.encode(
                        "cp932",
                        errors="strict",
                    )
                )
            except UnicodeEncodeError as exc:
                raise UnicodeEncodeError(
                    exc.encoding,
                    exc.object,
                    exc.start,
                    exc.end,
                    (
                        "character not present in "
                        "Stage35 custom mapping: "
                        f"{ch!r} U+{ord(ch):04X}"
                    ),
                )

        return bytes(out)

    def encode_tbl_file(
        self,
        source_utf8,
        destination,
    ):
        source_utf8 = Path(source_utf8)
        destination = Path(destination)

        text = source_utf8.read_text(
            encoding="utf-8-sig"
        )

        raw = self.encode_text(text)

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_bytes(raw)
        return destination
'''

    (
        OUT / "stage35_mapper.py"
    ).write_text(
        mapper_py,
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("STAGE35 ANALYSIS COMPLETE")
    print("=" * 72)
    print("Coverage:", coverage_grade)
    print("Translation corpus:", corpus_status)
    print("Unique Hangul:", len(chars_sorted))
    print("Safe candidate slots:", len(safe_slots))
    print(
        "Allocation:",
        len(allocation),
        "/",
        len(chars_sorted),
    )
    print("Validation errors:", len(errors))
    print()
    print(OUT / "stage35_summary.txt")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content `
        -LiteralPath $analyzer `
        -Value $analyzerCode `
        -Encoding UTF8

    $code = RunPy `
        "analyzer syntax" `
        @(
            "-m",
            "py_compile",
            $analyzer
        )

    if ($code -ne 0) {
        throw "Stage35 analyzer Python 문법 오류"
    }

    $code = RunPy `
        "[1/1] charset / slot analysis" `
        @($analyzer)

    if ($code -ne 0) {
        throw "Stage35 분석 실패"
    }

    $required = @(
        "stage35_summary.txt",
        "stage35_summary.json",
        "stage35_font_glyphs.tsv",
        "stage35_special_table.tsv",
        "stage35_sjis_slot_inventory.tsv",
        "stage35_source_coverage.tsv",
        "stage35_translation_sources.tsv",
        "stage35_translation_chars.tsv",
        "stage35_allocation.tsv",
        "stage35_allocation.json",
        "stage35_special_detection.tsv",
        "stage35_mapper.py"
    )

    foreach ($name in $required) {
        $p = Join-Path $stage $name

        if (-not (Test-Path -LiteralPath $p)) {
            throw "Stage35 결과 누락: $name"
        }
    }

    # Success only: archive previous top-level logs.
    $archive = Join-Path `
        $oldRoot `
        (Get-Date -Format "yyyyMMdd_HHmmss")

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $archive |
        Out-Null

    Get-ChildItem `
        -LiteralPath $logs `
        -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item `
                -LiteralPath $_.FullName `
                -Destination $archive `
                -Force
        }

    foreach ($name in $required) {
        Copy-Item `
            -LiteralPath (Join-Path $stage $name) `
            -Destination $logs `
            -Force
    }

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 35"
        "생성: $(Get-Date)"
        ""
        "STATUS:"
        " ANALYSIS_ONLY"
        ""
        "목적:"
        " 전체 번역용 한글 문자 집합 수집"
        " SJIS -> 3600 glyph 표준 mapping 검증"
        " Stage34 special table 검출"
        " 원본 일본어 사용 슬롯 보존 분석"
        " 안전한 미사용 슬롯 자동 배정"
        " Stage36용 mapping JSON + encoder 생성"
        ""
        "핵심 업로드 파일:"
        " stage35_summary.txt"
        " stage35_summary.json"
        " stage35_translation_chars.tsv"
        " stage35_sjis_slot_inventory.tsv"
        " stage35_allocation.tsv"
        " stage35_source_coverage.tsv"
        " stage35_special_table.tsv"
        ""
        "ChatGPT 업로드:"
        " naruto_stage35_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage35_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage35_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $zipInputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 35 SUCCESS"
    Log "=========================================="
    Log ""
    Log "STATUS: ANALYSIS_ONLY"
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
