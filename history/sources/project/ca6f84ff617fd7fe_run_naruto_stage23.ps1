$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage23"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$hookPy = Join-Path `
    $stage `
    "stage23_hangul_hook.py"

$isoPy = Join-Path `
    $stage `
    "stage23_iso_multi_patch.py"

$patcher = Join-Path `
    $base `
    "analysis\stage14\naruto_patcher.py"

$probeTbl = Join-Path `
    $stage `
    "event000_stage23.tbl"

$patchedBoot = Join-Path `
    $stage `
    "BOOT_stage23_hangul_hook.BIN"

$patchOut = Join-Path `
    $stage `
    "patch"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

# ISO는 항상 프로젝트 최상단.
$outIso = Join-Path `
    $base `
    "Naruto - Stage23 Hangul Hook Test.iso"


New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null


$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage23_$stamp.log"


function Write-RunLog {

    param(
        [string]$Text
    )

    Write-Host $Text

    Add-Content `
        -LiteralPath $runLog `
        -Value $Text `
        -Encoding UTF8
}


function Save-Failure {

    param(
        [string]$Reason
    )

    $failDir = Join-Path `
        $failedRoot `
        $stamp

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
                Join-Path `
                    $failDir `
                    "FAILURE.txt"
            ) `
            -Encoding UTF8


    Write-Host ""
    Write-Host "STAGE 23 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host $failDir
}


if (Get-Command python -ErrorAction SilentlyContinue) {

    $python = "python"

}
elseif (Get-Command py -ErrorAction SilentlyContinue) {

    $python = "py"

}
else {

    Save-Failure "Python을 찾을 수 없습니다."
    exit 1
}


foreach ($p in @(
    $hookPy,
    $isoPy,
    $patcher
)) {

    if (-not (Test-Path $p)) {

        Save-Failure "필수 파일 없음: $p"
        exit 1
    }


    if ($python -eq "py") {

        & py -3 -m py_compile $p

    }
    else {

        & python -m py_compile $p
    }


    if ($LASTEXITCODE -ne 0) {

        Save-Failure "Python 문법 오류: $p"
        exit 1
    }
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 23"
Write-Host " F0-F9 Hangul hook test"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# [1/3] executable hook + probe TBL
# ============================================================

Write-Host "[1/3] BOOT 한글 hook 생성"


if ($python -eq "py") {

    & py -3 $hookPy 2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

}
else {

    & python $hookPy 2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage23 hook 생성 실패"
    exit 1
}


if (-not (Test-Path $patchedBoot)) {

    Save-Failure "Patched BOOT가 없습니다."
    exit 1
}


if (-not (Test-Path $probeTbl)) {

    Save-Failure "Stage23 probe TBL이 없습니다."
    exit 1
}


# ============================================================
# [2/3] TBL -> DAT/IDX
# ============================================================

Write-Host ""
Write-Host "[2/3] event000  DAT/IDX 패치"


$replaceArg = "event000.tbl=$probeTbl"


if ($python -eq "py") {

    & py -3 $patcher `
        --root $base `
        --output $patchOut `
        --replace $replaceArg `
        --force `
        2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

}
else {

    & python $patcher `
        --root $base `
        --output $patchOut `
        --replace $replaceArg `
        --force `
        2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage23 DAT/IDX 패치 실패"
    exit 1
}


$patchedDat = Join-Path `
    $patchOut `
    "naruto.dat"

$patchedIdx = Join-Path `
    $patchOut `
    "naruto.idx"


if (-not (Test-Path $patchedDat)) {

    Save-Failure "Patched DAT 없음"
    exit 1
}


if (-not (Test-Path $patchedIdx)) {

    Save-Failure "Patched IDX 없음"
    exit 1
}


# ============================================================
# [3/3] root ISO
# ============================================================

Write-Host ""
Write-Host "[3/3] 한글 hook 테스트 ISO 생성"


Remove-Item `
    -LiteralPath $outIso `
    -Force `
    -ErrorAction SilentlyContinue


if ($python -eq "py") {

    & py -3 $isoPy `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --boot $patchedBoot `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

}
else {

    & python $isoPy `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --boot $patchedBoot `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage23 ISO 생성 실패"
    exit 1
}


if (-not (Test-Path $outIso)) {

    Save-Failure "Stage23 ISO 없음"
    exit 1
}


# ============================================================
# Required reports
# ============================================================

$required = @(
    "stage23_hook_summary.txt",
    "stage23_cptbl_validation.tsv",
    "stage23_code_caves.tsv",
    "stage23_relocations.tsv",
    "stage23_hook_patch.tsv",
    "stage23_hook_words.tsv",
    "stage23_probe_map.tsv",
    "stage23_iso_summary.txt",
    "stage23_iso_validation.tsv"
)


foreach ($name in $required) {

    $p = Join-Path `
        $stage `
        $name

    if (-not (Test-Path $p)) {

        Save-Failure "Stage23 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Runtime instructions
# ============================================================

$runtime = Join-Path `
    $stage `
    "stage23_runtime_test.txt"


@(
    "Stage23 PPSSPP runtime test"
    "=============================================="
    ""
    "ISO:"
    " $outIso"
    ""
    "첫 7개 대사의 예상 결과:"
    ""
    "1. KMAP:한글테스트"
    "2. KMAP:가나다라마"
    "3. KMAP:한글"
    "   테스트       (<br> 실제 줄바꿈)"
    "4. KMAP:한글　테스트"
    "5. MIX:日本:한글"
    "6. JP:日本語確認"
    "7. ASCII:OK"
    ""
    "특히 1번에서 실제 한글이 보이면"
    "F0-F9 custom SJIS  Unicode  Korean font 경로 성공."
) | Set-Content `
    -LiteralPath $runtime `
    -Encoding UTF8


# ============================================================
# Success-only logs
# ============================================================

$archiveStamp = Get-Date -Format "yyyyMMdd_HHmmss"

$archive = Join-Path `
    $oldRoot `
    $archiveStamp


New-Item `
    -ItemType Directory `
    -Force `
    -Path $archive |
    Out-Null


Get-ChildItem `
    -LiteralPath $logs `
    -Force |
    Where-Object {
        $_.Name -ne "old" -and $_.Name -ne "failed"
    } |
    ForEach-Object {

        Move-Item `
            -LiteralPath $_.FullName `
            -Destination $archive `
            -Force
    }


foreach ($name in $required) {

    Copy-Item `
        -LiteralPath (
            Join-Path $stage $name
        ) `
        -Destination $logs `
        -Force
}


Copy-Item `
    -LiteralPath $runtime `
    -Destination $logs `
    -Force


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


# Patcher reports
if (Test-Path $patchOut) {

    Get-ChildItem `
        -LiteralPath $patchOut `
        -File |
        Where-Object {
            ($_.Extension -eq ".tsv" -or $_.Extension -eq ".txt") -and $_.Length -lt 5242880
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
    "Naruto PSP Stage 23"
    "생성: $(Get-Date)"
    ""
    "실제 한글 hook runtime test"
    ""
    "PPSSPP 실행 ISO:"
    " $outIso"
    ""
    "ISO는 프로젝트 최상단에 생성됨."
    ""
    "ChatGPT 업로드:"
    " naruto_stage23_upload.zip"
    ""
    "스크린샷도 함께 업로드 권장."
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage23_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage23_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage23 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 23 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "PPSSPP에서 실행:"
Write-Host $outIso
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
