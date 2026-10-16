$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage8"

$logs    = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage "stage8_extract_text.py"

New-Item -ItemType Directory -Force -Path $logs    | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage8_$stamp.log"

if (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
}
else {
    throw "Python을 찾을 수 없습니다."
}

# 문법 검사
if ($python -eq "py") {

    & py -3 -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog

}
else {

    & python -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog
}

if ($LASTEXITCODE -ne 0) {

    Copy-Item $runLog $logs -Force
    throw "Stage 8 Python 문법 오류"
}

# 실행
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

    Write-Host "Stage 8 실패"
    Write-Host "기존 logs 유지"

    Copy-Item $runLog $logs -Force

    exit 1
}

$required = @(
    "stage8_summary.txt",
    "codec_notes.txt",
    "three_x_containers.tsv",
    "codec_validation.tsv",
    "tbl_pair_summary.tsv",
    "event_dialogue_pairs.tsv",
    "quiz_pairs.tsv",
    "text_multilang.tsv"
)

foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Copy-Item $runLog $logs -Force

        throw "Stage 8 결과 누락: $name"
    }
}

# ============================================================
# 성공 시 기존 logs 보관
# ============================================================

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
        $_.Name -ne "old"
    } |
    ForEach-Object {

        Move-Item `
            -LiteralPath $_.FullName `
            -Destination $archive `
            -Force
    }

# ============================================================
# 필요한 결과 logs로
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

# 핵심 디코드 샘플
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

$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 8"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage8_upload.zip"
    ""
    "주요 데이터:"
    " event_dialogue_pairs.tsv"
    " quiz_pairs.tsv"
    " text_multilang.tsv"
    " three_x_containers.tsv"
    " codec_validation.tsv"
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8

# ============================================================
# 자동 ZIP
# ============================================================

$zipFile = Join-Path $logs "naruto_stage8_upload.zip"

Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue

$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage8_upload.zip"
    } |
    Select-Object -ExpandProperty FullName

Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force

if (-not (Test-Path $zipFile)) {
    throw "ZIP 생성 실패"
}

Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 8 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
