$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage17"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage17_font_engine.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage17_$stamp.log"


function Write-RunLog {
    param([string]$Line)

    Write-Host $Line

    Add-Content `
        -LiteralPath $runLog `
        -Value $Line `
        -Encoding UTF8
}


function Save-Failure {
    param([string]$Reason)

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
    Write-Host "STAGE 17 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 그대로 유지됩니다."
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
    $syntax = & py -3 -m py_compile $pyFile 2>&1
}
else {
    $syntax = & python -m py_compile $pyFile 2>&1
}

foreach ($line in $syntax) {
    Write-RunLog "$line"
}

if ($LASTEXITCODE -ne 0) {
    Save-Failure "Stage17 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 17"
Write-Host " Font engine tracing"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# Run
# ============================================================

if ($python -eq "py") {

    & py -3 $pyFile 2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

}
else {

    & python $pyFile 2>&1 |
        ForEach-Object {
            Write-RunLog "$_"
        }

}


if ($LASTEXITCODE -ne 0) {
    Save-Failure "Stage17 분석 실패"
    exit 1
}


$required = @(
    "stage17_summary.txt",
    "elf_sections.tsv",
    "font_imports.tsv",
    "font_callsites.tsv",
    "font_callsites.txt",
    "raw_font_nid_hits.tsv",
    "font_signature_hits.tsv"
)


foreach ($name in $required) {
    $path = Join-Path $stage $name

    if (-not (Test-Path $path)) {
        Save-Failure "Stage17 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Success-only archive
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


foreach ($name in $required) {
    Copy-Item `
        -LiteralPath (
            Join-Path $stage $name
        ) `
        -Destination $logs `
        -Force
}


Copy-Item `
    -LiteralPath $pyFile `
    -Destination $logs `
    -Force


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 17"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage17_upload.zip"
    ""
    "분석 내용:"
    " - KR/US BOOT.BIN ELF import table"
    " - sceLibFont NID / import stub"
    " - sceFontGetCharGlyphImage 등 모든 direct callsite"
    " - BOOT/EBOOT 및 Stage9 전체 리소스의 PGF0/.pgf 검색"
    ""
    "이번 Stage에서는 ISO를 만들지 않습니다."
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage17_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage17_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {
    Save-Failure "Stage17 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 17 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
