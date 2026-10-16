$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage24"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$srcHook = Join-Path $base "analysis\stage23\stage23_hangul_hook.py"
$srcIso  = Join-Path $base "analysis\stage23\stage23_iso_multi_patch.py"

$builder = Join-Path $stage "build_stage24_clean.py"

$hookPy = Join-Path $stage "stage24_hangul_hook.py"
$isoPy  = Join-Path $stage "stage24_iso_multi_patch.py"

$patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$probeTbl = Join-Path $stage "event000_stage24.tbl"

$patchedBoot = Join-Path `
    $stage `
    "BOOT_stage24_hangul_hook.BIN"

$patchOut = Join-Path $stage "patch"

$outIso = Join-Path `
    $base `
    "Naruto - Stage24 Hangul Valid SJIS Test.iso"

New-Item -ItemType Directory -Force -Path $stage      | Out-Null
New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage24_$stamp.log"


function Write-Log {
    param([string]$Text)

    Write-Host $Text

    Add-Content `
        -LiteralPath $runLog `
        -Value $Text `
        -Encoding UTF8
}


function Run-Python {
    param(
        [string]$Label,
        [string[]]$PythonArgs
    )

    Write-Log ""
    Write-Log "===== $Label ====="

    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python @PythonArgs 2>&1 |
        ForEach-Object {
            Write-Log "$_"
        }

    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $old

    return $exitCode
}


function Fail-Stage {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $failDir |
        Out-Null

    if (Test-Path $runLog) {
        Copy-Item `
            -LiteralPath $runLog `
            -Destination $failDir `
            -Force
    }

    $Reason |
        Set-Content `
            -LiteralPath (
                Join-Path $failDir "FAILURE.txt"
            ) `
            -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 24 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host $failDir
}


try {

    if (-not (Test-Path $srcHook)) {
        throw "Stage23 hook source 없음: $srcHook"
    }

    if (-not (Test-Path $srcIso)) {
        throw "Stage23 ISO patcher 없음: $srcIso"
    }

    if (-not (Test-Path $patcher)) {
        throw "Stage14 patcher 없음: $patcher"
    }


    # ========================================================
    # Python builder
    # ========================================================

    $builderCode = @"
from pathlib import Path
import re

BASE = Path(r"PROJECT_ROOT")

SRC_HOOK = (
    BASE / "analysis" / "stage23"
    / "stage23_hangul_hook.py"
)

SRC_ISO = (
    BASE / "analysis" / "stage23"
    / "stage23_iso_multi_patch.py"
)

OUT = BASE / "analysis" / "stage24"

DST_HOOK = OUT / "stage24_hangul_hook.py"
DST_ISO  = OUT / "stage24_iso_multi_patch.py"


NEW_MAPPING = r'''MAPPING = [
    (b"\x81\xAD", 0x222F, "한", 0xD55C),
    (b"\x81\xAE", 0x2230, "글", 0xAE00),
    (b"\x81\xAF", 0x2231, "테", 0xD14C),
    (b"\x81\xB0", 0x2232, "스", 0xC2A4),
    (b"\x81\xB1", 0x2233, "트", 0xD2B8),

    (b"\x81\xB2", 0x2234, "가", 0xAC00),
    (b"\x81\xB3", 0x2235, "나", 0xB098),
    (b"\x81\xB4", 0x2236, "다", 0xB2E4),
    (b"\x81\xB5", 0x2237, "라", 0xB77C),
    (b"\x81\xB6", 0x2238, "마", 0xB9C8),
]

'''


def replace_mapping(text):

    # Locate only. Do NOT use regex replacement strings,
    # because \x81 etc. would be interpreted by re.sub().
    m = re.search(
        r"(?ms)^MAPPING\s*=\s*\[.*?^\]\s*\n",
        text
    )

    if m is None:
        raise RuntimeError(
            "Stage23 MAPPING block을 찾지 못했습니다."
        )

    return (
        text[:m.start()]
        + NEW_MAPPING
        + text[m.end():]
    )


def main():

    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    hook = SRC_HOOK.read_text(
        encoding="utf-8-sig"
    )

    # The Stage23 source on disk must be the version
    # which already passed the loader-gap hook test.
    if "find_loader_gap_cave" not in hook:
        raise RuntimeError(
            "Stage23 source에 loader-gap fix가 없습니다."
        )

    hook = replace_mapping(
        hook
    )

    # Stage23 custom range was 0x7F21.
    # Stage24 custom range starts at 0x222F.
    if "-0x7F21" in hook:

        hook = hook.replace(
            "-0x7F21",
            "-MAPPING[0][1]",
            1
        )

    elif "-MAPPING[0][1]" not in hook:

        raise RuntimeError(
            "hook range-base 식을 찾지 못했습니다."
        )

    # Rename outputs/reports.
    hook = hook.replace(
        "stage23",
        "stage24"
    )

    hook = hook.replace(
        "Stage23",
        "Stage24"
    )

    hook = hook.replace(
        "STAGE23",
        "STAGE24"
    )

    hook = hook.replace(
        "Stage 23",
        "Stage 24"
    )

    hook = hook.replace(
        "F0-F9 custom Hangul hook",
        "Valid-unused-SJIS Hangul hook"
    )

    hook = hook.replace(
        "F0-F9 Hangul hook",
        "Valid-unused-SJIS Hangul hook"
    )

    checks = [
        r'b"\x81\xAD"',
        r'b"\x81\xB6"',
        "0x222F",
        "0x2238",
        '"한"',
        '"마"',
        "find_loader_gap_cave",
        "-MAPPING[0][1]",
    ]

    for check in checks:
        if check not in hook:
            raise RuntimeError(
                f"Stage24 hook sanity check 실패: {check}"
            )

    DST_HOOK.write_text(
        hook,
        encoding="utf-8"
    )


    iso = SRC_ISO.read_text(
        encoding="utf-8-sig"
    )

    iso = iso.replace(
        "stage23",
        "stage24"
    )

    iso = iso.replace(
        "Stage23",
        "Stage24"
    )

    iso = iso.replace(
        "STAGE23",
        "STAGE24"
    )

    iso = iso.replace(
        "Stage 23",
        "Stage 24"
    )

    DST_ISO.write_text(
        iso,
        encoding="utf-8"
    )


    print("=" * 72)
    print("STAGE24 CLEAN BUILD PASS")
    print("=" * 72)
    print()

    print("Stage23 source:")
    print(SRC_HOOK)

    print()
    print("Stage24 hook:")
    print(DST_HOOK)

    print()
    print("Stage24 ISO patcher:")
    print(DST_ISO)

    print()
    print("Mappings:")

    mappings = [
        ("81 AD", "222F", "한"),
        ("81 AE", "2230", "글"),
        ("81 AF", "2231", "테"),
        ("81 B0", "2232", "스"),
        ("81 B1", "2233", "트"),
        ("81 B2", "2234", "가"),
        ("81 B3", "2235", "나"),
        ("81 B4", "2236", "다"),
        ("81 B5", "2237", "라"),
        ("81 B6", "2238", "마"),
    ]

    for sjis, internal, char in mappings:
        print(
            f"  {sjis} -> "
            f"0x{internal} -> {char}"
        )


if __name__ == "__main__":
    main()
"@

    Set-Content `
        -LiteralPath $builder `
        -Value $builderCode `
        -Encoding UTF8


    # ========================================================
    # [0] build Stage24 sources
    # ========================================================

    $code = Run-Python `
        "Stage24 clean source build" `
        @($builder)

    if ($code -ne 0) {
        throw "Stage24 clean source build 실패"
    }


    if (-not (Test-Path $hookPy)) {
        throw "stage24_hangul_hook.py 생성 실패"
    }

    if (-not (Test-Path $isoPy)) {
        throw "stage24_iso_multi_patch.py 생성 실패"
    }


    # ========================================================
    # Syntax
    # ========================================================

    $code = Run-Python `
        "stage24_hangul_hook.py syntax" `
        @("-m", "py_compile", $hookPy)

    if ($code -ne 0) {
        throw "Stage24 hook Python 문법 오류"
    }


    $code = Run-Python `
        "stage24_iso_multi_patch.py syntax" `
        @("-m", "py_compile", $isoPy)

    if ($code -ne 0) {
        throw "Stage24 ISO Python 문법 오류"
    }


    # ========================================================
    # Remove only stale Stage24 generated outputs
    # ========================================================

    Remove-Item `
        -LiteralPath $patchOut `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    Remove-Item `
        -LiteralPath $probeTbl `
        -Force `
        -ErrorAction SilentlyContinue

    Remove-Item `
        -LiteralPath $patchedBoot `
        -Force `
        -ErrorAction SilentlyContinue

    Remove-Item `
        -LiteralPath $outIso `
        -Force `
        -ErrorAction SilentlyContinue


    # ========================================================
    # [1/3] hook
    # ========================================================

    Write-Host ""
    Write-Host "=========================================="
    Write-Host " Naruto PSP Stage 24"
    Write-Host " Valid unused SJIS test"
    Write-Host "=========================================="

    $code = Run-Python `
        "[1/3] Hangul hook + probe TBL" `
        @($hookPy)

    if ($code -ne 0) {
        throw "Stage24 hook 생성 실패"
    }


    if (-not (Test-Path $patchedBoot)) {
        throw "Stage24 patched BOOT 생성 안 됨"
    }

    if (-not (Test-Path $probeTbl)) {
        throw "Stage24 event000 probe 생성 안 됨"
    }


    # ========================================================
    # [2/3] DAT / IDX
    # ========================================================

    $replaceArg = "event000.tbl=$probeTbl"

    $code = Run-Python `
        "[2/3] DAT / IDX patch" `
        @(
            $patcher,
            "--root", $base,
            "--output", $patchOut,
            "--replace", $replaceArg,
            "--force"
        )

    if ($code -ne 0) {
        throw "Stage24 DAT/IDX 패치 실패"
    }


    $patchedDat = Join-Path $patchOut "naruto.dat"
    $patchedIdx = Join-Path $patchOut "naruto.idx"

    if (-not (Test-Path $patchedDat)) {
        throw "patched naruto.dat 없음"
    }

    if (-not (Test-Path $patchedIdx)) {
        throw "patched naruto.idx 없음"
    }


    # ========================================================
    # [3/3] ISO
    # ========================================================

    $code = Run-Python `
        "[3/3] ISO patch" `
        @(
            $isoPy,
            "--source-iso", $sourceIso,
            "--dat", $patchedDat,
            "--idx", $patchedIdx,
            "--boot", $patchedBoot,
            "--output-iso", $outIso,
            "--report-dir", $stage
        )

    if ($code -ne 0) {
        throw "Stage24 ISO 생성 실패"
    }


    if (-not (Test-Path $outIso)) {
        throw "Stage24 ISO 없음"
    }


    # ========================================================
    # Runtime instructions
    # ========================================================

    $runtime = Join-Path `
        $stage `
        "stage24_runtime_test.txt"

    @(
        "Naruto PSP Stage24"
        "=============================================="
        ""
        "ISO:"
        " $outIso"
        ""
        "Mapping:"
        " 81 AD = 한"
        " 81 AE = 글"
        " 81 AF = 테"
        " 81 B0 = 스"
        " 81 B1 = 트"
        " 81 B2 = 가"
        " 81 B3 = 나"
        " 81 B4 = 다"
        " 81 B5 = 라"
        " 81 B6 = 마"
        ""
        "예상 첫 대사:"
        " KMAP:한글테스트"
    ) | Set-Content `
        -LiteralPath $runtime `
        -Encoding UTF8


    # ========================================================
    # Success-only logs
    # ========================================================

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


    Get-ChildItem `
        -LiteralPath $stage `
        -File |
        Where-Object {
            $_.Name -like "stage24_*.txt" -or
            $_.Name -like "stage24_*.tsv"
        } |
        ForEach-Object {

            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }


    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force


    if (Test-Path $patchOut) {

        Get-ChildItem `
            -LiteralPath $patchOut `
            -File |
            Where-Object {
                $_.Extension -eq ".txt" -or
                $_.Extension -eq ".tsv"
            } |
            ForEach-Object {

                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (
                        Join-Path `
                            $logs `
                            ("patcher_" + $_.Name)
                    ) `
                    -Force
            }
    }


    $readme = Join-Path $logs "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage24"
        "생성: $(Get-Date)"
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT upload:"
        " naruto_stage24_upload.zip"
        ""
        "Stage24 was generated cleanly from"
        "the successful Stage23 loader-gap source."
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8


    $zip = Join-Path `
        $logs `
        "naruto_stage24_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue


    $items = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage24_upload.zip"
        } |
        Select-Object `
            -ExpandProperty FullName


    Compress-Archive `
        -Path $items `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force


    Write-Host ""
    Write-Host "=========================================="
    Write-Host " STAGE 24 SUCCESS"
    Write-Host "=========================================="
    Write-Host ""
    Write-Host "PPSSPP 실행:"
    Write-Host $outIso
    Write-Host ""
    Write-Host "ChatGPT 업로드:"
    Write-Host $zip

}
catch {

    Fail-Stage $_.Exception.Message
    throw
}

