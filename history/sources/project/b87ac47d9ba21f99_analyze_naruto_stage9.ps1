$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage9"

$logs    = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage "stage9_full_extract.py"

New-Item -ItemType Directory -Force -Path $logs    | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage9_$stamp.log"

if (Get-Command python -ErrorAction SilentlyContinue) {

    $python = "python"

}
elseif (Get-Command py -ErrorAction SilentlyContinue) {

    $python = "py"

}
else {

    throw "Python을 찾을 수 없습니다."
}


# ============================================================
# Python syntax check
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

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    throw "Stage 9 Python 문법 오류"
}


# ============================================================
# Run
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 9"
Write-Host " Full archive extraction"
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

    Write-Host ""
    Write-Host "STAGE 9 FAILED"
    Write-Host "기존 logs는 유지합니다."

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    $errFile = Join-Path `
        $stage `
        "stage9_errors.txt"

    if (Test-Path $errFile) {

        Copy-Item `
            -LiteralPath $errFile `
            -Destination $logs `
            -Force
    }

    exit 1
}


# ============================================================
# Required reports
# ============================================================

$required = @(
    "stage9_summary.txt",
    "full_extract_validation.tsv",
    "archive_layout.tsv",
    "text_multilang_fixed.tsv",
    "text_encoding_report.tsv",
    "event_dialogue_pairs_v2.tsv",
    "event_structure_summary.tsv",
    "quiz_kr_questions.tsv",
    "quiz_us_questions.tsv",
    "quiz_structure_summary.tsv",
    "kr_ccs_japanese_scan.tsv",
    "font_candidates.tsv"
)

foreach ($name in $required) {

    $p = Join-Path $stage $name

    if (-not (Test-Path $p)) {

        Copy-Item `
            -LiteralPath $runLog `
            -Destination $logs `
            -Force

        throw "Stage 9 결과 누락: $name"
    }
}


# ============================================================
# Successful run -> archive old logs
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
        $_.Name -ne "old"
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


# selected binary samples
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
    "Naruto PSP Stage 9"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage9_upload.zip"
    ""
    "전체 디코드 파일은:"
    " PROJECT_ROOT\analysis\stage9\extracted"
    ""
    "ZIP에는 ChatGPT 검토용 보고서와 일부 UI 샘플만 포함됩니다."
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ============================================================
# ZIP
# ============================================================

$zipFile = Join-Path `
    $logs `
    "naruto_stage9_upload.zip"

Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage9_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {
    throw "Stage 9 ZIP 생성 실패"
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 9 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "전체 추출:"
Write-Host (
    Join-Path $stage "extracted"
)
Write-Host ""
Write-Host "업로드:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
