$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage36"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage36_$stamp.log"

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
            $_.Extension -in @(".txt",".tsv",".json",".py")
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
        }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 36 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

try {
    Log "Naruto PSP Stage 36"
    Log "Standard SJIS donor smoke test"
    Log "Started: $(Get-Date)"

    $builder = Join-Path $stage "stage36_standard_donor_smoke.py"

    $builderCode = @'
from pathlib import Path
import csv
import hashlib
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage36"
OUT.mkdir(parents=True, exist_ok=True)

ORIGINAL_BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

STAGE34_ISO = (
    BASE / "Naruto - Stage34 Hangul Event Test.iso"
)

STAGE35R_ALLOC = (
    BASE / "analysis" / "stage35r"
    / "stage35r_allocation_strict.tsv"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = (
    OUT / "BOOT_stage36_standard_donor.BIN"
)

PATCHED_TBL = (
    OUT / "event000_stage36.tbl"
)

FONT_FILE_OFF = 0x39CD04
GLYPH_SIZE = 162

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

        extent = int.from_bytes(
            rec[2:6],
            "little",
        )

        file_size = int.from_bytes(
            rec[10:14],
            "little",
        )

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

        if root_len < 34:
            raise RuntimeError(
                "ISO root directory record invalid"
            )

        root = pvd[156:156 + root_len]

        current_lba = int.from_bytes(
            root[2:6],
            "little",
        )

        current_size = int.from_bytes(
            root[10:14],
            "little",
        )

        for idx, wanted in enumerate(components):
            records = read_iso_directory(
                iso,
                current_lba,
                current_size,
            )

            match = None

            for rec in records:
                if rec["name"].upper() == wanted.upper():
                    match = rec
                    break

            if match is None:
                raise RuntimeError(
                    "ISO path not found: "
                    + "/".join(
                        components[:idx + 1]
                    )
                )

            if idx < len(components) - 1:
                if not match["is_dir"]:
                    raise RuntimeError(
                        f"{wanted} is not a directory"
                    )

                current_lba = match["extent"]
                current_size = match["size"]

            else:
                if match["is_dir"]:
                    raise RuntimeError(
                        f"{wanted} is a directory"
                    )

                iso.seek(
                    match["extent"] * sector
                )

                return iso.read(
                    match["size"]
                ), match

    raise RuntimeError(
        "unreachable ISO path traversal"
    )


def load_allocation():
    rows = []

    with STAGE35R_ALLOC.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        for row in reader:
            rows.append(row)

    if len(rows) != 10:
        raise RuntimeError(
            f"Stage35R strict allocation expected 10 rows, got {len(rows)}"
        )

    mapping = {}

    for row in rows:
        ch = row["char"]
        code = int(
            row["sjis"],
            16,
        )
        glyph = int(
            row["glyph"]
        )

        if row.get(
            "bitmap_empty_before",
            ""
        ) not in (
            "1",
            "True",
            "true",
        ):
            raise RuntimeError(
                f"Stage35R smoke donor is not empty: {ch}"
            )

        if int(
            row.get(
                "kr_tbl_usage_before",
                "0"
            )
            or 0
        ) != 0:
            raise RuntimeError(
                f"Stage35R donor used by KR TBL: {ch}"
            )

        if int(
            row.get(
                "ui_sample_usage",
                "0"
            )
            or 0
        ) != 0:
            raise RuntimeError(
                f"Stage35R donor used by UI sample: {ch}"
            )

        mapping[ch] = {
            "code": code,
            "glyph": glyph,
            "row": row,
        }

    missing = [
        ch
        for ch in STAGE34_SEED
        if ch not in mapping
    ]

    if missing:
        raise RuntimeError(
            "Stage35R allocation missing seed chars: "
            + "".join(missing)
        )

    return mapping, rows


def custom_encode(text, mapping):
    out = bytearray()

    for ch in text:
        if ch in mapping:
            code = mapping[ch]["code"]

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
    lines = raw.splitlines(
        keepends=True
    )

    probes = [
        (
            "STANDARD_DONOR_1",
            "STD1:한글테스트",
        ),
        (
            "STANDARD_DONOR_2",
            "STD2:가나다라마",
        ),
    ]

    out = []
    report = []
    probe_index = 0

    for line_no, line in enumerate(
        lines,
        1,
    ):
        body = line.rstrip(
            b"\r\n"
        )

        newline = line[
            len(body):
        ]

        if (
            probe_index < len(probes)
            and body.startswith(b"MSG =")
        ):
            parts = body.split(
                b",",
                2,
            )

            if len(parts) == 3:
                name, text = probes[
                    probe_index
                ]

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
                    "probe":
                        probe_index + 1,
                    "name":
                        name,
                    "line":
                        line_no,
                    "msg_id":
                        parts[1].decode(
                            "ascii",
                            errors="replace",
                        ),
                    "expected":
                        text,
                    "encoded_hex":
                        encoded.hex(" "),
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
        OUT / "stage36_probe_map.tsv",
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
    print("Naruto PSP Stage 36")
    print("Standard SJIS donor smoke test")
    print("=" * 72)

    for p in (
        ORIGINAL_BOOT,
        STAGE34_ISO,
        STAGE35R_ALLOC,
        SOURCE_TBL,
    ):
        if not p.exists():
            raise RuntimeError(
                f"필수 파일 없음: {p}"
            )

    stage34_hash = sha256_file(
        STAGE34_ISO
    )

    if stage34_hash != EXPECTED_STAGE34_ISO_SHA256:
        raise RuntimeError(
            "Stage34 verified ISO SHA256 mismatcLOCAL_PATH"
            f" expected={EXPECTED_STAGE34_ISO_SHA256}\n"
            f" actual  ={stage34_hash}"
        )

    stage34_boot, iso_record = (
        find_iso9660_file(
            STAGE34_ISO,
            [
                "PSP_GAME",
                "SYSDIR",
                "BOOT.BIN",
            ],
        )
    )

    original = bytearray(
        ORIGINAL_BOOT.read_bytes()
    )

    if len(stage34_boot) != len(original):
        raise RuntimeError(
            "Stage34 BOOT size differs from original: "
            f"{len(stage34_boot)} != {len(original)}"
        )

    mapping, alloc_rows = load_allocation()

    # Extract the 10 already-verified Hangul bitmaps from Stage34.
    verified_bitmaps = {}

    source_rows = []

    for i, ch in enumerate(
        STAGE34_SEED
    ):
        glyph = STAGE34_GLYPH_BASE + i
        off = FONT_FILE_OFF + glyph * GLYPH_SIZE

        bitmap = stage34_boot[
            off:
            off + GLYPH_SIZE
        ]

        if len(bitmap) != GLYPH_SIZE:
            raise RuntimeError(
                f"Stage34 glyph short read: {glyph}"
            )

        if not any(bitmap):
            raise RuntimeError(
                f"Stage34 verified glyph unexpectedly empty: {ch} glyph={glyph}"
            )

        verified_bitmaps[ch] = bitmap

        source_rows.append({
            "char": ch,
            "source_glyph": glyph,
            "source_glyph_hex": f"0x{glyph:X}",
            "source_file_offset": f"0x{off:X}",
            "bitmap_sha256": hashlib.sha256(
                bitmap
            ).hexdigest(),
            "nonzero_bytes": sum(
                1
                for b in bitmap
                if b != 0
            ),
        })

    # Copy those verified bitmap bytes into Stage35R standard donor slots.
    target_rows = []

    for ch in STAGE34_SEED:
        info = mapping[ch]
        target_glyph = info["glyph"]
        target_code = info["code"]

        target_off = (
            FONT_FILE_OFF
            + target_glyph
            * GLYPH_SIZE
        )

        old = original[
            target_off:
            target_off + GLYPH_SIZE
        ]

        if len(old) != GLYPH_SIZE:
            raise RuntimeError(
                f"target glyph short read: {target_glyph}"
            )

        if any(old):
            raise RuntimeError(
                f"Stage35R target not empty in original BOOT: "
                f"{ch} glyph={target_glyph}"
            )

        bitmap = verified_bitmaps[
            ch
        ]

        original[
            target_off:
            target_off + GLYPH_SIZE
        ] = bitmap

        # Re-read validation.
        if (
            original[
                target_off:
                target_off + GLYPH_SIZE
            ]
            != bitmap
        ):
            raise RuntimeError(
                f"bitmap write verify failed: {ch}"
            )

        target_rows.append({
            "char":
                ch,
            "sjis":
                f"{target_code:04X}",
            "sjis_hex":
                (
                    f"{target_code >> 8:02X} "
                    f"{target_code & 0xFF:02X}"
                ),
            "target_glyph":
                target_glyph,
            "target_glyph_hex":
                f"0x{target_glyph:X}",
            "target_file_offset":
                f"0x{target_off:X}",
            "source_stage34_glyph":
                STAGE34_GLYPH_BASE
                + STAGE34_SEED.index(ch),
            "bitmap_sha256":
                hashlib.sha256(
                    bitmap
                ).hexdigest(),
        })

    PATCHED_BOOT.write_bytes(
        original
    )

    build_probe_tbl(
        mapping
    )

    write_tsv(
        OUT / "stage36_source_glyphs.tsv",
        source_rows,
        [
            "char",
            "source_glyph",
            "source_glyph_hex",
            "source_file_offset",
            "bitmap_sha256",
            "nonzero_bytes",
        ],
    )

    write_tsv(
        OUT / "stage36_standard_donor_mapping.tsv",
        target_rows,
        [
            "char",
            "sjis",
            "sjis_hex",
            "target_glyph",
            "target_glyph_hex",
            "target_file_offset",
            "source_stage34_glyph",
            "bitmap_sha256",
        ],
    )

    summary = {
        "stage":
            36,
        "purpose":
            "verify arbitrary unused standard SJIS donor slots",
        "stage34_iso_sha256":
            stage34_hash,
        "stage34_iso_boot_lba":
            iso_record["extent"],
        "stage34_iso_boot_size":
            iso_record["size"],
        "original_boot_sha256":
            sha256_file(
                ORIGINAL_BOOT
            ),
        "patched_boot_sha256":
            sha256_file(
                PATCHED_BOOT
            ),
        "font_source":
            "verified Stage34 glyph bitmaps 3582..3591",
        "allocation_source":
            str(
                STAGE35R_ALLOC
            ),
        "probe_tbl":
            str(
                PATCHED_TBL
            ),
        "expected": [
            "STD1:한글테스트",
            "STD2:가나다라마",
        ],
    }

    import json

    (
        OUT / "stage36_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (
        OUT / "stage36_summary.txt"
    ).write_text(
        "\n".join([
            "Naruto PSP Stage 36",
            "=" * 72,
            "",
            "Purpose:",
            "  Verify Stage35R standard-SJIS donor allocation at runtime.",
            "",
            "No new font rendering is performed.",
            "The exact 10 Hangul bitmaps already verified in Stage34",
            "are copied from the verified Stage34 ISO into the new",
            "Stage35R STRICT donor glyph slots.",
            "",
            f"Stage34 ISO SHA256: {stage34_hash}",
            f"Stage34 BOOT extent: {iso_record['extent']}",
            f"Stage34 BOOT size: {iso_record['size']}",
            "",
            "Expected runtime:",
            "  STD1:한글테스트",
            "  STD2:가나다라마",
            "",
            "If both lines are correct, arbitrary unused standard",
            "SJIS codes can be used as the full Korean donor pool.",
        ]),
        encoding="utf-8",
    )

    print()
    print("Stage34 verified ISO:", stage34_hash)
    print("Copied verified glyphs:", len(verified_bitmaps))
    print("Standard donor slots:", len(target_rows))
    print()
    print("Expected runtime:")
    print("  STD1:한글테스트")
    print("  STD2:가나다라마")
    print()
    print(PATCHED_BOOT)
    print(PATCHED_TBL)

    print()
    print("=" * 72)
    print("STAGE36 FONT/TBL READY")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content `
        -LiteralPath $builder `
        -Value $builderCode `
        -Encoding UTF8

    $code = RunPy `
        "builder syntax" `
        @("-m","py_compile",$builder)

    if ($code -ne 0) {
        throw "Stage36 builder Python 문법 오류"
    }

    $code = RunPy `
        "[1/3] build standard-donor BOOT/TBL" `
        @($builder)

    if ($code -ne 0) {
        throw "Stage36 BOOT/TBL 생성 실패"
    }

    $patchedBoot = Join-Path $stage "BOOT_stage36_standard_donor.BIN"
    $probeTbl = Join-Path $stage "event000_stage36.tbl"

    foreach ($p in @($patchedBoot,$probeTbl)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "Stage36 결과 누락: $p"
        }
    }

    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"

    if (-not (Test-Path -LiteralPath $patcher)) {
        throw "Stage14 patcher 없음: $patcher"
    }

    $patchOut = Join-Path $stage "patch"

    Remove-Item `
        -LiteralPath $patchOut `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    $replaceArg = "event000.tbl=$probeTbl"

    $code = RunPy `
        "[2/3] DAT/IDX patch" `
        @(
            $patcher,
            "--root",$base,
            "--output",$patchOut,
            "--replace",$replaceArg,
            "--force"
        )

    if ($code -ne 0) {
        throw "Stage36 DAT/IDX patch 실패"
    }

    $dat = Join-Path $patchOut "naruto.dat"
    $idx = Join-Path $patchOut "naruto.idx"

    $isoPatcher = Join-Path `
        $base `
        "analysis\stage24\stage24_iso_multi_patch.py"

    if (-not (Test-Path -LiteralPath $isoPatcher)) {
        throw "Stage24 ISO patcher 없음: $isoPatcher"
    }

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    $outIso = Join-Path `
        $base `
        "Naruto - Stage36 Standard Donor Hangul Test.iso"

    Remove-Item `
        -LiteralPath $outIso `
        -Force `
        -ErrorAction SilentlyContinue

    $isoReport = Join-Path $stage "iso"

    Remove-Item `
        -LiteralPath $isoReport `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    $code = RunPy `
        "[3/3] ISO patch" `
        @(
            $isoPatcher,
            "--source-iso",$sourceIso,
            "--dat",$dat,
            "--idx",$idx,
            "--boot",$patchedBoot,
            "--output-iso",$outIso,
            "--report-dir",$isoReport
        )

    if ($code -ne 0) {
        throw "Stage36 ISO 생성 실패"
    }

    if (-not (Test-Path -LiteralPath $outIso)) {
        throw "Stage36 ISO 없음"
    }

    $runtime = Join-Path $stage "stage36_runtime_test.txt"

    @(
        "Naruto PSP Stage36"
        "=============================================="
        ""
        "ISO:"
        " $outIso"
        ""
        "Expected first two dialogue lines:"
        " STD1:한글테스트"
        " STD2:가나다라마"
        ""
        "Purpose:"
        " Stage34 special-table donor가 아니라"
        " Stage35R에서 자동 선택한 일반 Shift-JIS donor 코드가"
        " 이벤트 렌더러에서 정상적으로 해당 glyph를 가리키는지 검증."
        ""
        "둘 다 정상:"
        "  전체 번역용 standard SJIS donor pool 사용 가능."
        ""
        "깨짐/다른 문자:"
        "  standard donor 전략을 중단하고 special table 확장/다른 매핑 필요."
    ) | Set-Content `
        -LiteralPath $runtime `
        -Encoding UTF8

    $required = @(
        "stage36_summary.txt",
        "stage36_summary.json",
        "stage36_source_glyphs.tsv",
        "stage36_standard_donor_mapping.tsv",
        "stage36_probe_map.tsv",
        "stage36_runtime_test.txt"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $name))) {
            throw "Stage36 결과 누락: $name"
        }
    }

    # Success only: archive old top-level logs.
    $archive = Join-Path $oldRoot (Get-Date -Format "yyyyMMdd_HHmmss")
    New-Item -ItemType Directory -Force -Path $archive | Out-Null

    Get-ChildItem -LiteralPath $logs -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $archive -Force
        }

    foreach ($name in $required) {
        Copy-Item `
            -LiteralPath (Join-Path $stage $name) `
            -Destination $logs `
            -Force
    }

    Get-ChildItem -LiteralPath $patchOut -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Extension -in @(".txt",".tsv")
        } |
        ForEach-Object {
            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination (
                    Join-Path $logs ("patcher_" + $_.Name)
                ) `
                -Force
        }

    if (Test-Path -LiteralPath $isoReport) {
        Get-ChildItem -LiteralPath $isoReport -File |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (
                        Join-Path $logs ("iso_" + $_.Name)
                    ) `
                    -Force
            }
    }

    Copy-Item -LiteralPath $runLog -Destination $logs -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 36"
        "생성: $(Get-Date)"
        ""
        "목적:"
        " Stage35R STRICT standard-SJIS donor slot runtime smoke test"
        ""
        "Expected:"
        " STD1:한글테스트"
        " STD2:가나다라마"
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT upload:"
        " naruto_stage36_upload.zip"
        ""
        "Previous successful logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path $logs "naruto_stage36_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object {
            $_.Name -ne "naruto_stage36_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 36 SUCCESS"
    Log "=========================================="
    Log "ISO:"
    Log $outIso
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
