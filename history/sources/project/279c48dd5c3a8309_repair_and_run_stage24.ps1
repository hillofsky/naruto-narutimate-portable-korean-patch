$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage24"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$srcHook = Join-Path $base "analysis\stage23\stage23_hangul_hook.py"
$srcIso  = Join-Path $base "analysis\stage23\stage23_iso_multi_patch.py"

$builderPy = Join-Path $stage "rebuild_stage24_from_stage23.py"

$hookPy = Join-Path $stage "stage24_hangul_hook.py"
$isoPy  = Join-Path $stage "stage24_iso_multi_patch.py"

$patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$probeTbl = Join-Path $stage "event000_stage24.tbl"
$patchedBoot = Join-Path $stage "BOOT_stage24_hangul_hook.BIN"

$patchOut = Join-Path $stage "patch"

$outIso = Join-Path `
    $base `
    "Naruto - Stage24 Hangul Valid SJIS Test.iso"

New-Item -ItemType Directory -Force -Path $stage      | Out-Null
New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage24_$stamp.log"


function Write-RunLog {
    param([string]$Text)

    Write-Host $Text

    Add-Content `
        -LiteralPath $runLog `
        -Value $Text `
        -Encoding UTF8
}


function Save-Failure {
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


function Invoke-Python {
    param(
        [string]$Label,
        [string[]]$Arguments
    )

    Write-RunLog ""
    Write-RunLog "===== $Label ====="

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python @Arguments 2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

    $code = $LASTEXITCODE

    $ErrorActionPreference = $oldPreference

    return $code
}


try {

    # ========================================================
    # Source checks
    # ========================================================

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
    # Rebuild Stage24 Python sources
    # ========================================================

    $builderCode = @"
from pathlib import Path
import re
import sys

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


def main():

    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    hook = SRC_HOOK.read_text(
        encoding="utf-8-sig"
    )

    # Stage23 must already contain the successful
    # PT_LOAD loader-gap fix.
    if "find_loader_gap_cave" not in hook:
        raise RuntimeError(
            "Stage23 source에 loader-gap fix가 없습니다."
        )

    new_mapping = r'''MAPPING = [
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

    pattern = re.compile(
        r"(?ms)^MAPPING\s*=\s*\[.*?^\]\s*\n"
    )

    hook, count = pattern.subn(
        new_mapping,
        hook,
        count=1
    )

    if count != 1:
        raise RuntimeError(
            f"MAPPING block 교체 실패: {count}"
        )

    # Stage23 hook starts its custom range at 0x7F21.
    # Stage24 starts at 0x222F.
    if "-0x7F21" in hook:
        hook = hook.replace(
            "-0x7F21",
            "-MAPPING[0][1]",
            1
        )

    elif "-MAPPING[0][1]" not in hook:
        raise RuntimeError(
            "Hook range-base expression을 찾지 못했습니다."
        )

    # Output/report names.
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

    # Sanity checks.
    required = [
        r'b"\x81\xAD"',
        "0x222F",
        '"한"',
        "find_loader_gap_cave",
    ]

    for token in required:
        if token not in hook:
            raise RuntimeError(
                f"Stage24 hook sanity check 실패: {token}"
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
    print("Stage24 source rebuild PASS")
    print("=" * 72)

    print(DST_HOOK)
    print(DST_ISO)


if __name__ == "__main__":
    main()
"@

    Set-Content `
        -LiteralPath $builderPy `
        -Value $builderCode `
        -Encoding UTF8


    $code = Invoke-Python `
        "Stage24 source rebuild" `
        @($builderPy)

    if ($code -ne 0) {
        throw "Stage24 source rebuild 실패"
    }


    # ========================================================
    # Verify generated files
    # ========================================================

    if (-not (Test-Path $hookPy)) {
        throw "생성 실패: $hookPy"
    }

    if (-not (Test-Path $isoPy)) {
        throw "생성 실패: $isoPy"
    }


    $code = Invoke-Python `
        "hook py_compile" `
        @("-m", "py_compile", $hookPy)

    if ($code -ne 0) {
        throw "stage24_hangul_hook.py 문법 오류"
    }


    $code = Invoke-Python `
        "ISO py_compile" `
        @("-m", "py_compile", $isoPy)

    if ($code -ne 0) {
        throw "stage24_iso_multi_patch.py 문법 오류"
    }


    # ========================================================
    # Remove stale Stage24 results
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
    # [1/3] Hook + probe TBL
    # ========================================================

    Write-Host ""
    Write-Host "=========================================="
    Write-Host " Naruto PSP Stage 24"
    Write-Host " Valid unused SJIS Hangul test"
    Write-Host "=========================================="
    Write-Host ""

    $code = Invoke-Python `
        "[1/3] Hangul hook / probe TBL" `
        @($hookPy)

    if ($code -ne 0) {
        throw "Stage24 hook 생성 실패"
    }

    if (-not (Test-Path $probeTbl)) {
        throw "event000_stage24.tbl 생성 안 됨"
    }

    if (-not (Test-Path $patchedBoot)) {
        throw "BOOT_stage24_hangul_hook.BIN 생성 안 됨"
    }


    # ========================================================
    # [2/3] DAT / IDX
    # ========================================================

    $replaceArg = "event000.tbl=$probeTbl"

    $code = Invoke-Python `
        "[2/3] DAT / IDX patch" `
        @(
            $patcher,
            "--root",
            $base,
            "--output",
            $patchOut,
            "--replace",
            $replaceArg,
            "--force"
        )

    if ($code -ne 0) {
        throw "Stage24 DAT/IDX patch 실패"
    }


    $patchedDat = Join-Path $patchOut "naruto.dat"
    $patchedIdx = Join-Path $patchOut "naruto.idx"

    if (-not (Test-Path $patchedDat)) {
        throw "Patched naruto.dat 없음"
    }

    if (-not (Test-Path $patchedIdx)) {
        throw "Patched naruto.idx 없음"
    }


    # ========================================================
    # [3/3] ISO
    # ========================================================

    $code = Invoke-Python `
        "[3/3] ISO patch" `
        @(
            $isoPy,
            "--source-iso",
            $sourceIso,
            "--dat",
            $patchedDat,
            "--idx",
            $patchedIdx,
            "--boot",
            $patchedBoot,
            "--output-iso",
            $outIso,
            "--report-dir",
            $stage
        )

    if ($code -ne 0) {
        throw "Stage24 ISO 생성 실패"
    }


    if (-not (Test-Path $outIso)) {
        throw "Stage24 ISO가 생성되지 않았습니다."
    }


    # ========================================================
    # Runtime test note
    # ========================================================

    $runtime = Join-Path `
        $stage `
        "stage24_runtime_test.txt"

    @(
        "Naruto PSP Stage 24"
        "=============================================="
        ""
        "ISO:"
        " $outIso"
        ""
        "Custom SJIS mapping:"
        " 81 AD -> 한"
        " 81 AE -> 글"
        " 81 AF -> 테"
        " 81 B0 -> 스"
        " 81 B1 -> 트"
        " 81 B2 -> 가"
        " 81 B3 -> 나"
        " 81 B4 -> 다"
        " 81 B5 -> 라"
        " 81 B6 -> 마"
        ""
        "예상:"
        " 1 KMAP:한글테스트"
        " 2 KMAP:가나다라마"
        " 3 KMAP:한글 / 테스트"
        " 4 KMAP:한글　테스트"
        " 5 MIX:日本:한글"
        " 6 JP:日本語確認"
        " 7 ASCII:OK"
    ) | Set-Content `
        -LiteralPath $runtime `
        -Encoding UTF8


    # ========================================================
    # Success-only log archive
    # ========================================================

    $archiveStamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $archive = Join-Path $oldRoot $archiveStamp

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
            (
                $_.Name -like "stage24_*.txt"
            ) -or (
                $_.Name -like "stage24_*.tsv"
            )
        } |
        ForEach-Object {

            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }


    if (Test-Path $runLog) {

        Copy-Item `
            -LiteralPath $runLog `
            -Destination $logs `
            -Force
    }


    if (Test-Path $patchOut) {

        Get-ChildItem `
            -LiteralPath $patchOut `
            -File |
            Where-Object {
                $_.Extension -eq ".tsv" -or
                $_.Extension -eq ".txt"
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


    $readme = Join-Path `
        $logs `
        "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 24"
        "생성: $(Get-Date)"
        ""
        "PPSSPP ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage24_upload.zip"
        ""
        "Stage24 sources were rebuilt from the successful Stage23 source."
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8


    $zipFile = Join-Path `
        $logs `
        "naruto_stage24_upload.zip"

    Remove-Item `
        -LiteralPath $zipFile `
        -Force `
        -ErrorAction SilentlyContinue


    $zipFiles = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage24_upload.zip"
        } |
        Select-Object `
            -ExpandProperty FullName


    Compress-Archive `
        -Path $zipFiles `
        -DestinationPath $zipFile `
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
    Write-Host $zipFile

}
catch {

    Save-Failure $_.Exception.Message
    throw
}
