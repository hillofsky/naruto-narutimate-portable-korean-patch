from pathlib import Path
import csv
import hashlib
import json
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage36r"
OUT.mkdir(parents=True, exist_ok=True)

ORIGINAL_BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

STAGE34_ISO = (
    BASE / "Naruto - Stage34 Hangul Event Test.iso"
)

INVENTORY = (
    BASE / "analysis" / "stage35r"
    / "stage35r_slot_inventory.tsv"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = (
    OUT / "BOOT_stage36r_low_standard_donor.BIN"
)

PATCHED_TBL = (
    OUT / "event000_stage36r.tbl"
)

FONT_FILE_OFF = 0x39CD04
GLYPH_SIZE = 162

SPECIAL_GLYPH_BASE = 3429

STAGE34_GLYPH_BASE = 3582
STAGE34_SEED = "한글테스트가나다라마"

EXPECTED_STAGE34_ISO_SHA256 = (
    "3796AA67AB347545C38E431CA84A2A6EC"
    "F4E7DF789CA0D90B499A50A4B2395AD"
)


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)

    return h.hexdigest().upper()


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


def read_iso_directory(iso, lba, size):
    sector = 2048
    iso.seek(lba * sector)
    data = iso.read(size)

    records = []
    pos = 0

    while pos < len(data):
        length = data[pos]

        if length == 0:
            pos = ((pos // sector) + 1) * sector
            continue

        rec = data[pos:pos + length]

        if len(rec) < 34:
            break

        extent = int.from_bytes(rec[2:6], "little")
        file_size = int.from_bytes(rec[10:14], "little")
        flags = rec[25]
        name_len = rec[32]
        name_raw = rec[33:33 + name_len]

        if name_raw == b"\x00":
            name = "."
        elif name_raw == b"\x01":
            name = ".."
        else:
            name = name_raw.decode(
                "ascii",
                errors="replace",
            )
            if ";" in name:
                name = name.split(";", 1)[0]

        records.append({
            "name": name,
            "extent": extent,
            "size": file_size,
            "is_dir": bool(flags & 0x02),
        })

        pos += length

    return records


def find_iso9660_file(path, components):
    sector = 2048

    with path.open("rb") as iso:
        iso.seek(16 * sector)
        pvd = iso.read(sector)

        if (
            len(pvd) != sector
            or pvd[0] != 1
            or pvd[1:6] != b"CD001"
        ):
            raise RuntimeError(
                "ISO9660 PVD를 찾지 못했습니다."
            )

        root_len = pvd[156]
        root = pvd[156:156 + root_len]

        lba = int.from_bytes(root[2:6], "little")
        size = int.from_bytes(root[10:14], "little")

        for idx, wanted in enumerate(components):
            records = read_iso_directory(
                iso,
                lba,
                size,
            )

            match = None

            for rec in records:
                if rec["name"].upper() == wanted.upper():
                    match = rec
                    break

            if match is None:
                raise RuntimeError(
                    "ISO path not found: "
                    + "/".join(components[:idx + 1])
                )

            if idx < len(components) - 1:
                if not match["is_dir"]:
                    raise RuntimeError(
                        f"{wanted} is not a directory"
                    )

                lba = match["extent"]
                size = match["size"]

            else:
                iso.seek(match["extent"] * sector)
                return iso.read(match["size"]), match

    raise RuntimeError("ISO traversal failed")


def load_low_empty_slots():
    rows = []

    with INVENTORY.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        for row in reader:
            glyph = int(row["glyph"])

            if glyph >= SPECIAL_GLYPH_BASE:
                continue

            if row["strict_safe"] != "1":
                continue

            if row["bitmap_empty"] != "1":
                continue

            if row["special_intercept"] != "0":
                continue

            if int(row["kr_tbl_usage"]) != 0:
                continue

            if int(row["ui_sample_usage"]) != 0:
                continue

            rows.append({
                "glyph": glyph,
                "glyph_hex": row["glyph_hex"],
                "sjis": int(
                    row["standard_sjis"],
                    16,
                ),
                "sjis_text": row["standard_sjis"],
                "sjis_hex": row["sjis_hex"],
                "font_file_offset": row["font_file_offset"],
            })

    # Prefer high empty glyphs *within the real standard region*.
    rows.sort(
        key=lambda r: -r["glyph"]
    )

    if len(rows) < len(STAGE34_SEED):
        raise RuntimeError(
            f"Low standard empty donor slots 부족: "
            f"{len(rows)} < {len(STAGE34_SEED)}"
        )

    return rows


def custom_encode(text, mapping):
    out = bytearray()

    for ch in text:
        if ch in mapping:
            code = mapping[ch]["sjis"]

            out.extend([
                (code >> 8) & 0xFF,
                code & 0xFF,
            ])
        else:
            out.extend(
                ch.encode(
                    "cp932",
                    errors="strict",
                )
            )

    return bytes(out)


def build_probe_tbl(mapping):
    raw = SOURCE_TBL.read_bytes()
    lines = raw.splitlines(keepends=True)

    probes = [
        (
            "LOW_STANDARD_1",
            "STD1:한글테스트",
        ),
        (
            "LOW_STANDARD_2",
            "STD2:가나다라마",
        ),
    ]

    out = []
    report = []
    probe_index = 0

    for line_no, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        newline = line[len(body):]

        if (
            probe_index < len(probes)
            and body.startswith(b"MSG =")
        ):
            parts = body.split(b",", 2)

            if len(parts) == 3:
                name, text = probes[probe_index]
                encoded = custom_encode(
                    text,
                    mapping,
                )

                out.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + encoded
                    + newline
                )

                report.append({
                    "probe": probe_index + 1,
                    "name": name,
                    "line": line_no,
                    "msg_id": parts[1].decode(
                        "ascii",
                        errors="replace",
                    ),
                    "expected": text,
                    "encoded_hex": encoded.hex(" "),
                })

                probe_index += 1
                continue

        out.append(line)

    if probe_index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: {probe_index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT / "stage36r_probe_map.tsv",
        report,
        [
            "probe",
            "name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ],
    )


def main():
    print("=" * 72)
    print("Naruto PSP Stage 36R")
    print("Low standard-SJIS donor smoke test")
    print("=" * 72)

    for p in (
        ORIGINAL_BOOT,
        STAGE34_ISO,
        INVENTORY,
        SOURCE_TBL,
    ):
        if not p.exists():
            raise RuntimeError(
                f"필수 파일 없음: {p}"
            )

    stage34_hash = sha256_file(STAGE34_ISO)

    if stage34_hash != EXPECTED_STAGE34_ISO_SHA256:
        raise RuntimeError(
            "Stage34 verified ISO SHA256 mismatcLOCAL_PATH"
            f" expected={EXPECTED_STAGE34_ISO_SHA256}\n"
            f" actual  ={stage34_hash}"
        )

    stage34_boot, iso_record = find_iso9660_file(
        STAGE34_ISO,
        [
            "PSP_GAME",
            "SYSDIR",
            "BOOT.BIN",
        ],
    )

    original = bytearray(
        ORIGINAL_BOOT.read_bytes()
    )

    if len(stage34_boot) != len(original):
        raise RuntimeError(
            "Stage34 BOOT size differs from original"
        )

    # Exact verified Stage34 bitmaps.
    verified = {}

    for i, ch in enumerate(STAGE34_SEED):
        glyph = STAGE34_GLYPH_BASE + i
        off = FONT_FILE_OFF + glyph * GLYPH_SIZE

        block = stage34_boot[
            off:
            off + GLYPH_SIZE
        ]

        if len(block) != GLYPH_SIZE or not any(block):
            raise RuntimeError(
                f"Stage34 verified glyph invalid: {ch}"
            )

        verified[ch] = {
            "glyph": glyph,
            "offset": off,
            "bitmap": block,
        }

    donors = load_low_empty_slots()[
        :len(STAGE34_SEED)
    ]

    mapping = {}
    rows = []

    for ch, donor in zip(
        STAGE34_SEED,
        donors,
    ):
        glyph = donor["glyph"]
        code = donor["sjis"]
        target_off = (
            FONT_FILE_OFF
            + glyph * GLYPH_SIZE
        )

        old = original[
            target_off:
            target_off + GLYPH_SIZE
        ]

        if any(old):
            raise RuntimeError(
                f"Target donor not empty: "
                f"{ch} glyph={glyph}"
            )

        block = verified[ch]["bitmap"]

        original[
            target_off:
            target_off + GLYPH_SIZE
        ] = block

        mapping[ch] = donor

        rows.append({
            "char": ch,
            "unicode": f"U+{ord(ch):04X}",
            "sjis": f"{code:04X}",
            "sjis_hex": donor["sjis_hex"],
            "target_glyph": glyph,
            "target_glyph_hex": f"0x{glyph:X}",
            "target_file_offset": f"0x{target_off:X}",
            "source_stage34_glyph": verified[ch]["glyph"],
            "source_stage34_offset": (
                f"0x{verified[ch]['offset']:X}"
            ),
            "bitmap_sha256": hashlib.sha256(
                block
            ).hexdigest(),
        })

    PATCHED_BOOT.write_bytes(
        original
    )

    build_probe_tbl(
        mapping
    )

    write_tsv(
        OUT / "stage36r_mapping.tsv",
        rows,
        [
            "char",
            "unicode",
            "sjis",
            "sjis_hex",
            "target_glyph",
            "target_glyph_hex",
            "target_file_offset",
            "source_stage34_glyph",
            "source_stage34_offset",
            "bitmap_sha256",
        ],
    )

    # Corrected capacities from Stage35R inventory.
    strict_low = 0
    strict_low_empty = 0
    reclaim_low = 0
    reclaim_low_empty = 0

    with INVENTORY.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        for row in reader:
            glyph = int(row["glyph"])

            if glyph >= SPECIAL_GLYPH_BASE:
                continue

            if row["strict_safe"] == "1":
                strict_low += 1

                if row["bitmap_empty"] == "1":
                    strict_low_empty += 1

            if row["all_tbls_translated_safe"] == "1":
                reclaim_low += 1

                if row["bitmap_empty"] == "1":
                    reclaim_low_empty += 1

    summary = {
        "stage": "36R",
        "special_glyph_base": SPECIAL_GLYPH_BASE,
        "standard_direct_glyph_range": "0..3428",
        "stage36_observation": {
            "working_codes": [
                "81EF",
                "8248",
                "824A",
                "8241",
                "82F7",
                "82F5",
                "825E",
                "825C",
            ],
            "failed_codes": [
                "9455",
                "9457",
            ],
            "failed_formula_glyphs": [
                3593,
                3595,
            ],
        },
        "corrected_capacity": {
            "strict_low_standard_slots": strict_low,
            "strict_low_empty_slots": strict_low_empty,
            "reclaim_low_standard_slots": reclaim_low,
            "reclaim_low_empty_slots": reclaim_low_empty,
        },
        "expected": [
            "STD1:한글테스트",
            "STD2:가나다라마",
        ],
        "mapping": rows,
    }

    (
        OUT / "stage36r_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (
        OUT / "stage36r_summary.txt"
    ).write_text(
        "\n".join([
            "Naruto PSP Stage 36R",
            "=" * 72,
            "",
            "Stage36 runtime result:",
            "  8 / 10 characters rendered correctly.",
            "  Failed: 글=9455(formula glyph 3593), "
            "가=9457(formula glyph 3595).",
            "",
            "Correction:",
            "  Standard direct SJIS donor glyphs must be below "
            f"{SPECIAL_GLYPH_BASE}.",
            "  Glyphs 3429+ belong to the special-table / tail region "
            "and must not be allocated by the linear standard formula.",
            "",
            f"Corrected STRICT capacity: {strict_low}",
            f"  empty: {strict_low_empty}",
            f"Corrected RECLAIM-ALL-TBL capacity: {reclaim_low}",
            f"  empty: {reclaim_low_empty}",
            "",
            "Stage36R maps all ten verified Hangul glyphs only to",
            "empty STRICT donors in glyph range 0..3428.",
            "",
            "Expected runtime:",
            "  STD1:한글테스트",
            "  STD2:가나다라마",
        ]),
        encoding="utf-8",
    )

    print()
    print("Corrected standard range: glyph 0..3428")
    print("STRICT capacity:", strict_low)
    print("RECLAIM capacity:", reclaim_low)
    print()
    print("Mapping:")
    for row in rows:
        print(
            " ",
            row["char"],
            "->",
            row["sjis"],
            "glyph",
            row["target_glyph"],
        )

    print()
    print("Expected:")
    print("  STD1:한글테스트")
    print("  STD2:가나다라마")
    print()
    print(PATCHED_BOOT)
    print(PATCHED_TBL)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
