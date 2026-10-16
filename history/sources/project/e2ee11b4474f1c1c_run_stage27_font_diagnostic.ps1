$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage27"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage27_$stamp.log"

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

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 27 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "로그:"
    Write-Host $runLog
}

try {
    Log "Naruto PSP Stage 27"
    Log "Japanese-vs-Korean final Unicode renderer diagnostic"
    Log "Started: $(Get-Date)"

    $stage26 = Join-Path $base "analysis\stage26\stage26_final_unicode_hook.py"
    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"
    $isoPatcher = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"

    foreach ($p in @($stage26,$patcher,$isoPatcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage27_renderer_diagnostic.py"

    $driverCode = @'
from pathlib import Path
import csv
import importlib.util
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage27"
OUT.mkdir(parents=True, exist_ok=True)

SOURCE = (
    BASE / "analysis" / "stage26"
    / "stage26_final_unicode_hook.py"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = OUT / "BOOT_stage27_renderer_diag.BIN"
PATCHED_TBL = OUT / "event000_stage27.tbl"


# First 5: Japanese control.
# Last 5: Korean test.
DIAG_MAP = [
    ("α", b"\x83\xBF", 0x03B1, "あ", 0x3042),
    ("β", b"\x83\xC0", 0x03B2, "い", 0x3044),
    ("γ", b"\x83\xC1", 0x03B3, "う", 0x3046),
    ("δ", b"\x83\xC2", 0x03B4, "え", 0x3048),
    ("ε", b"\x83\xC3", 0x03B5, "お", 0x304A),

    ("ζ", b"\x83\xC4", 0x03B6, "가", 0xAC00),
    ("η", b"\x83\xC5", 0x03B7, "나", 0xB098),
    ("θ", b"\x83\xC6", 0x03B8, "다", 0xB2E4),
    ("ι", b"\x83\xC7", 0x03B9, "라", 0xB77C),
    ("κ", b"\x83\xC8", 0x03BA, "마", 0xB9C8),
]


def load_source():
    spec = importlib.util.spec_from_file_location(
        "stage26hook",
        SOURCE
    )
    mod = importlib.util.module_from_spec(spec)
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
        for row in rows:
            w.writerow({
                k: row.get(k, "")
                for k in fields
            })


def make_probe_tbl(mod):
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: {SOURCE_TBL}"
        )

    P = [x[1] for x in DIAG_MAP]

    probes = [
        (
            "JAPANESE_RENDER_CONTROL",
            "JMAP:あいうえお",
            b"JMAP:" + b"".join(P[0:5]),
        ),
        (
            "KOREAN_RENDER_TEST",
            "KMAP:가나다라마",
            b"KMAP:" + b"".join(P[5:10]),
        ),
        (
            "MIX_RENDER_TEST",
            "MIX:あ가いな",
            b"MIX:"
            + P[0] + P[5]
            + P[1] + P[6],
        ),
        (
            "JAPANESE_ORIGINAL_CONTROL",
            "JP:日本語確認",
            b"JP:" + "日本語確認".encode("cp932"),
        ),
        (
            "ASCII_CONTROL",
            "ASCII:OK",
            b"ASCII:OK",
        ),
    ]

    raw = SOURCE_TBL.read_bytes()
    lines = raw.splitlines(keepends=True)

    out = []
    report = []
    index = 0

    for line_no, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        newline = line[len(body):]

        if (
            index < len(probes)
            and body.startswith(b"MSG =")
        ):
            parts = body.split(b",", 2)

            if len(parts) == 3:
                name, expected, payload = probes[index]

                out.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + payload
                    + newline
                )

                report.append({
                    "probe": index + 1,
                    "probe_name": name,
                    "line": line_no,
                    "msg_id": parts[1].decode(
                        "ascii",
                        errors="replace"
                    ),
                    "expected": expected,
                    "encoded_hex": payload.hex(" "),
                })

                index += 1
                continue

        out.append(line)

    if index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: {index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT / "stage27_probe_map.tsv",
        report,
        [
            "probe",
            "probe_name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ],
    )


def main():
    print("=" * 72)
    print("Naruto PSP Stage 27")
    print("Japanese-vs-Korean renderer diagnostic")
    print("=" * 72)

    mod = load_source()

    # Keep the proven Stage26 hook implementation, only replace
    # its Unicode output table and output paths.
    mod.OUT = OUT
    mod.PATCHED_BOOT = PATCHED_BOOT
    mod.PATCHED_TBL = PATCHED_TBL
    mod.PLACEHOLDERS = DIAG_MAP

    def custom_probe():
        make_probe_tbl(mod)

    mod.make_probe_tbl = custom_probe

    mod.main()

    # Stage26 main writes report names with "stage26_".
    for p in list(OUT.glob("stage26_*")):
        dest = p.with_name(
            p.name.replace(
                "stage26_",
                "stage27_",
                1
            )
        )
        if dest.exists():
            dest.unlink()
        p.rename(dest)

    # Write a diagnostic-specific mapping report.
    rows = []
    for greek, sjis, greek_cp, target, target_cp in DIAG_MAP:
        rows.append({
            "source_sjis": sjis.hex(" "),
            "placeholder": greek,
            "placeholder_unicode": f"U+{greek_cp:04X}",
            "target": target,
            "target_unicode": f"U+{target_cp:04X}",
            "font_expected":
                "Japanese"
                if target_cp < 0xAC00
                else "Korean",
        })

    write_tsv(
        OUT / "stage27_diagnostic_mapping.tsv",
        rows,
        [
            "source_sjis",
            "placeholder",
            "placeholder_unicode",
            "target",
            "target_unicode",
            "font_expected",
        ],
    )

    (OUT / "stage27_diagnostic_guide.txt").write_text(
        "\n".join([
            "Naruto PSP Stage27 renderer diagnostic",
            "=" * 72,
            "",
            "Expected runtime:",
            "  1. JMAP:あいうえお",
            "  2. KMAP:가나다라마",
            "  3. MIX:あ가い나",
            "  4. JP:日本語確認",
            "  5. ASCII:OK",
            "",
            "Interpretation:",
            "  Japanese clean + Korean corrupt:",
            "    Unicode hook works; Korean sceFont/kr0 rendering path is the fault.",
            "",
            "  Japanese and Korean both corrupt:",
            "    Stage26 Unicode hook/output table is still wrong.",
            "",
            "  Both clean:",
            "    Korean renderer works and the previous target set/path needs re-check.",
        ]),
        encoding="utf-8"
    )

    print()
    print("Expected:")
    print("  JMAP:あいうえお")
    print("  KMAP:가나다라마")
    print("  MIX:あ가い나")
    print()
    print(PATCHED_BOOT)
    print(PATCHED_TBL)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content -LiteralPath $driver -Value $driverCode -Encoding UTF8

    $code = RunPy "driver syntax" @("-m","py_compile",$driver)
    if ($code -ne 0) {
        throw "Stage27 Python 문법 오류"
    }

    $code = RunPy "[1/3] renderer diagnostic hook" @($driver)
    if ($code -ne 0) {
        throw "Stage27 hook 생성 실패"
    }

    $probeTbl = Join-Path $stage "event000_stage27.tbl"
    $patchedBoot = Join-Path $stage "BOOT_stage27_renderer_diag.BIN"

    if (-not (Test-Path -LiteralPath $probeTbl)) {
        throw "event000_stage27.tbl 없음"
    }

    if (-not (Test-Path -LiteralPath $patchedBoot)) {
        throw "BOOT_stage27_renderer_diag.BIN 없음"
    }

    $patchOut = Join-Path $stage "patch"
    Remove-Item -LiteralPath $patchOut -Recurse -Force -ErrorAction SilentlyContinue

    $replaceArg = "event000.tbl=$probeTbl"

    $code = RunPy "[2/3] DAT/IDX patch" @(
        $patcher,
        "--root",$base,
        "--output",$patchOut,
        "--replace",$replaceArg,
        "--force"
    )

    if ($code -ne 0) {
        throw "Stage27 DAT/IDX patch 실패"
    }

    $dat = Join-Path $patchOut "naruto.dat"
    $idx = Join-Path $patchOut "naruto.idx"

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    $outIso = Join-Path `
        $base `
        "Naruto - Stage27 Korean Font Diagnostic.iso"

    Remove-Item -LiteralPath $outIso -Force -ErrorAction SilentlyContinue

    $code = RunPy "[3/3] ISO patch" @(
        $isoPatcher,
        "--source-iso",$sourceIso,
        "--dat",$dat,
        "--idx",$idx,
        "--boot",$patchedBoot,
        "--output-iso",$outIso,
        "--report-dir",$stage
    )

    if ($code -ne 0) {
        throw "Stage27 ISO patch 실패"
    }

    if (-not (Test-Path -LiteralPath $outIso)) {
        throw "Stage27 ISO 생성 안 됨"
    }

    # Success-only top-level log replacement.
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

    Get-ChildItem -LiteralPath $stage -File |
        Where-Object {
            $_.Extension -eq ".txt" -or
            $_.Extension -eq ".tsv" -or
            $_.Name -eq "stage27_renderer_diagnostic.py"
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $logs -Force
        }

    if (Test-Path -LiteralPath $patchOut) {
        Get-ChildItem -LiteralPath $patchOut -File |
            Where-Object {
                $_.Extension -eq ".txt" -or
                $_.Extension -eq ".tsv"
            } |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (Join-Path $logs ("patcher_" + $_.Name)) `
                    -Force
            }
    }

    Copy-Item -LiteralPath $runLog -Destination $logs -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"
    @(
        "Naruto PSP Stage 27"
        "생성: $(Get-Date)"
        ""
        "목적:"
        " 같은 Stage26 Unicode hook으로"
        " 일본어 5글자와 한글 5글자를 각각 직접 반환하여"
        " hook 문제와 Korean font 문제를 분리 진단."
        ""
        "Expected:"
        " JMAP:あいうえお"
        " KMAP:가나다라마"
        " MIX:あ가い나"
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage27_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content -LiteralPath $readme -Encoding UTF8

    $zip = Join-Path $logs "naruto_stage27_upload.zip"
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object {
            $_.Name -ne "naruto_stage27_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $zipInputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 27 SUCCESS"
    Log "=========================================="
    Log "ISO: $outIso"
    Log "ZIP: $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}
