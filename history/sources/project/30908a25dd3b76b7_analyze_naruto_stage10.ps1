$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage10"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage10_offset2.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage10_$stamp.log"


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

    $errFile = Join-Path `
        $stage `
        "stage10_errors.txt"

    if (Test-Path $errFile) {

        Copy-Item `
            -LiteralPath $errFile `
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
    Write-Host "FAILED:"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 건드리지 않았습니다."
    Write-Host "실패 자료:"
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


# ============================================================
# Syntax
# ============================================================

if ($python -eq "py") {

    & py -3 -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog

}
else {

    & python -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage 10 Python 문법 오류"
    exit 1
}


# ============================================================
# Run
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 10"
Write-Host " OFFSET2 second file table"
Write-Host "=========================================="
Write-Host ""


if ($python -eq "py") {

    & py -3 $pyFile 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append

}
else {

    & python $pyFile 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage 10 분석 실패"
    exit 1
}


# ============================================================
# Results
# ============================================================

$required = @(
    "stage10_summary.txt",
    "pidx_variants.tsv",
    "kr_index_diff_ranges.tsv",
    "kr_primary_compare.tsv",
    "kr_offset2_compare.tsv",
    "offset2_records.tsv",
    "offset2_layout.tsv",
    "offset2_translation_candidates.tsv"
)


foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Save-Failure "Stage 10 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Success -> archive previous top-level files
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
# Copy reports
# ============================================================

foreach ($name in $required) {

    Copy-Item `
        -LiteralPath (
            Join-Path $stage $name
        ) `
        -Destination $logs `
        -Force
}


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


# Small strategic OFFSET2 files
$share = Join-Path $stage "share"

if (Test-Path $share) {

    Get-ChildItem `
        -LiteralPath $share `
        -File |
        ForEach-Object {

            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }
}


# ============================================================
# README
# ============================================================

$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 10"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage10_upload.zip"
    ""
    "분석 대상:"
    " - KR external IDX vs DAT embedded PIDX"
    " - OFFSET2 second file table"
    " - primary/secondary duplicate detection"
    " - translation-related second-copy resources"
    ""
    "전체 OFFSET2 추출:"
    " PROJECT_ROOT\analysis\stage10\offset2_extracted"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ============================================================
# ZIP
# ============================================================

$zipFile = Join-Path `
    $logs `
    "naruto_stage10_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage10_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage 10 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 10 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드할 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
