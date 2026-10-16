$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage16"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$prepPy = Join-Path `
    $stage `
    "stage16_make_text_probe.py"

$patcher = Join-Path `
    $base `
    "analysis\stage14\naruto_patcher.py"

$isoPatcher = Join-Path `
    $base `
    "analysis\stage15\stage15_iso_patcher.py"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$probeTbl = Join-Path `
    $stage `
    "event000_stage16.tbl"

$patchOut = Join-Path `
    $stage `
    "patch"

$isoOutDir = Join-Path `
    $stage `
    "iso_test"

$outIso = Join-Path `
    $isoOutDir `
    "Naruto - Narutimate Portable - Stage16 Text Probe.iso"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null
New-Item -ItemType Directory -Force -Path $isoOutDir  | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage16_$stamp.log"


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
    Write-Host "STAGE 16 FAILED"
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
    $prepPy,
    $patcher,
    $isoPatcher,
    $sourceIso
)) {

    if (-not (Test-Path $p)) {

        Save-Failure "필수 파일 없음: $p"
        exit 1
    }
}


# ============================================================
# Syntax checks
# ============================================================

foreach ($script in @(
    $prepPy,
    $patcher,
    $isoPatcher
)) {

    if ($python -eq "py") {

        & py -3 -m py_compile $script

    }
    else {

        & python -m py_compile $script
    }

    if ($LASTEXITCODE -ne 0) {

        Save-Failure "Python 문법 오류: $script"
        exit 1
    }
}


# ============================================================
# 1. Probe TBL
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 16"
Write-Host " Text parser / glyph probe"
Write-Host "=========================================="
Write-Host ""

Write-Host "[1/3] 진단용 event000.tbl 생성"

if ($python -eq "py") {

    & py -3 $prepPy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $prepPy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {

    Save-Failure "Probe TBL 생성 실패"
    exit 1
}


# ============================================================
# 2. DAT/IDX patch
# ============================================================

Write-Host ""
Write-Host "[2/3] DAT / IDX 생성"

$replaceArg = "event000.tbl=$probeTbl"

if ($python -eq "py") {

    & py -3 $patcher `
        --root $base `
        --output $patchOut `
        --replace $replaceArg `
        --force `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $patcher `
        --root $base `
        --output $patchOut `
        --replace $replaceArg `
        --force `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage16 DAT/IDX patch 실패"
    exit 1
}


# ============================================================
# 3. ISO build
# ============================================================

Write-Host ""
Write-Host "[3/3] 테스트 ISO 생성"

$patchedDat = Join-Path $patchOut "naruto.dat"
$patchedIdx = Join-Path $patchOut "naruto.idx"

Remove-Item `
    -LiteralPath $outIso `
    -Force `
    -ErrorAction SilentlyContinue


if ($python -eq "py") {

    & py -3 $isoPatcher `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $isoPatcher `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage16 ISO 생성 실패"
    exit 1
}


# ============================================================
# Check required outputs
# ============================================================

$required = @(
    (Join-Path $stage "stage16_probe_map.tsv"),
    $probeTbl,
    (Join-Path $patchOut "replacement_manifest.tsv"),
    (Join-Path $patchOut "fsts_patch_map.tsv"),
    (Join-Path $patchOut "validation.tsv"),
    (Join-Path $patchOut "stage14_summary.txt"),
    (Join-Path $stage "stage15_summary.txt"),
    (Join-Path $stage "iso_validation.tsv"),
    $outIso
)


foreach ($p in $required) {

    if (-not (Test-Path $p)) {

        Save-Failure "결과 파일 누락: $p"
        exit 1
    }
}


# ============================================================
# Stage16 summary
# ============================================================

$summary = Join-Path `
    $stage `
    "stage16_summary.txt"


@(
    "Naruto PSP Stage 16"
    "=============================================="
    ""
    "목적:"
    " 일본판/KR 실행 코드의 ASCII 공백 및 글리프 처리 확인"
    ""
    "진단 문자열:"
    " 1 NOSPACEABCDEFGHIJ"
    " 2 ASCII SPACE TEST"
    " 3 FULL　WIDTH　SPACE"
    " 4 UPPERABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " 5 lowerabcdefghijklmnopqrstuvwxyz"
    " 6 NUM0123456789-+!?.,:/"
    " 7 LINE1<br>LINE2"
    ""
    "PPSSPP 실행 ISO:"
    " $outIso"
    ""
    "확인할 것:"
    " - 1번이 끝까지 표시되는지"
    " - 2번이 ASCII 첫 공백에서 끊기는지"
    " - 3번 전각 공백 뒤 텍스트가 계속 표시되는지"
    " - 대문자/소문자/숫자/기호 지원 범위"
    " - <br> 줄바꿈이 정상인지"
    ""
    "DAT/IDX 패처 self validation: PASS"
    "ISO 재추출 validation: PASS"
) | Set-Content `
    -LiteralPath $summary `
    -Encoding UTF8


# ============================================================
# Success-only log archive
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
        $_.Name -ne "old" `
        -and $_.Name -ne "failed"
    } |
    ForEach-Object {

        Move-Item `
            -LiteralPath $_.FullName `
            -Destination $archive `
            -Force
    }


# ============================================================
# Review bundle
# ============================================================

$copyMap = @(
    @{
        src = (Join-Path $stage "stage16_probe_map.tsv")
        dst = "stage16_probe_map.tsv"
    },
    @{
        src = $probeTbl
        dst = "event000_stage16.tbl"
    },
    @{
        src = (Join-Path $patchOut "replacement_manifest.tsv")
        dst = "replacement_manifest.tsv"
    },
    @{
        src = (Join-Path $patchOut "fsts_patch_map.tsv")
        dst = "fsts_patch_map.tsv"
    },
    @{
        src = (Join-Path $patchOut "validation.tsv")
        dst = "patch_validation.tsv"
    },
    @{
        src = (Join-Path $patchOut "stage14_summary.txt")
        dst = "patcher_summary.txt"
    },
    @{
        src = (Join-Path $stage "stage15_summary.txt")
        dst = "iso_patcher_summary.txt"
    },
    @{
        src = (Join-Path $stage "iso_validation.tsv")
        dst = "iso_validation.tsv"
    },
    @{
        src = $summary
        dst = "stage16_summary.txt"
    },
    @{
        src = $runLog
        dst = (
            Split-Path $runLog -Leaf
        )
    }
)


foreach ($item in $copyMap) {

    Copy-Item `
        -LiteralPath $item.src `
        -Destination (
            Join-Path $logs $item.dst
        ) `
        -Force
}


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 16"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage16_upload.zip"
    ""
    "PPSSPP 실행 ISO:"
    " $outIso"
    ""
    "각 대사를 넘기면서 화면에 표시된 문자열을 확인."
    "특히 ASCII SPACE TEST와 FULL　WIDTH　SPACE 비교가 핵심."
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage16_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage16_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage16 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 16 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "PPSSPP에서 실행:"
Write-Host $outIso
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile

