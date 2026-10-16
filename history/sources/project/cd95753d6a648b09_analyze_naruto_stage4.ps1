$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"

$stage4 = Join-Path $base "analysis\stage4"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage4 "stage4_code_scan.py"

New-Item -ItemType Directory -Force -Path $stage4 | Out-Null
New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage4 "naruto_stage4_$stamp.log"

Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 4"
Write-Host "=========================================="
Write-Host ""

if (-not (Test-Path $pyFile)) {
    throw "Python 분석기가 없습니다: $pyFile"
}

# Python 선택
if (Get-Command python -ErrorAction SilentlyContinue) {

    $python = "python"

}
elseif (Get-Command py -ErrorAction SilentlyContinue) {

    $python = "py"

}
else {

    throw "Python을 찾을 수 없습니다."
}

# ------------------------------------------------------------
# Python 문법 검사
# ------------------------------------------------------------

Write-Host "Python 문법 검사..."

if ($python -eq "py") {

    & py -3 -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog

}
else {

    & python -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog
}

if ($LASTEXITCODE -ne 0) {

    Write-Host ""
    Write-Host "PYTHON SYNTAX ERROR"

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    exit 1
}

Write-Host "[OK] Python 문법 검사 통과"
Write-Host ""

# ------------------------------------------------------------
# 분석
# ------------------------------------------------------------

Write-Host "Stage 4 분석 실행..."
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
    Write-Host "STAGE 4 FAILED"
    Write-Host "기존 logs는 유지합니다."

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    exit 1
}

# ------------------------------------------------------------
# 필수 결과 검증
# ------------------------------------------------------------

$requiredResults = @(
    "stage4_summary.txt",
    "elf_layout.tsv",
    "literal_signatures.tsv",
    "constant_loads.tsv",
    "xref_contexts.tsv",
    "compressed_samples.tsv"
)

foreach ($name in $requiredResults) {

    $p = Join-Path $stage4 $name

    if (-not (Test-Path $p)) {

        Write-Host "결과 누락: $p"

        Copy-Item `
            -LiteralPath $runLog `
            -Destination $logs `
            -Force

        exit 1
    }
}

# ------------------------------------------------------------
# 성공한 경우에만 logs -> old
# ------------------------------------------------------------

$archiveStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archive = Join-Path $oldRoot $archiveStamp

New-Item `
    -ItemType Directory `
    -Force `
    -Path $archive |
    Out-Null

Write-Host ""
Write-Host "기존 logs 보관..."

Get-ChildItem `
    -LiteralPath $logs `
    -Force |
    Where-Object {
        $_.Name -ne "old"
    } |
    ForEach-Object {

        Write-Host "MOVE: $($_.Name)"

        Move-Item `
            -LiteralPath $_.FullName `
            -Destination $archive `
            -Force
    }

# ------------------------------------------------------------
# 필요한 결과 수집
# ------------------------------------------------------------

Write-Host ""
Write-Host "ChatGPT 분석용 파일 수집..."

$needed = @(
    $runLog,
    (Join-Path $stage4 "stage4_summary.txt"),
    (Join-Path $stage4 "elf_layout.tsv"),
    (Join-Path $stage4 "literal_signatures.tsv"),
    (Join-Path $stage4 "constant_loads.tsv"),
    (Join-Path $stage4 "xref_contexts.tsv"),
    (Join-Path $stage4 "compressed_samples.tsv")
)

foreach ($src in $needed) {

    Copy-Item `
        -LiteralPath $src `
        -Destination $logs `
        -Force

    Write-Host "COPY: $(Split-Path $src -Leaf)"
}

# ------------------------------------------------------------
# 생성된 코드 컨텍스트도 복사
# 너무 많으면 첫 30개까지만
# ------------------------------------------------------------

$contexts = Get-ChildItem `
    -LiteralPath $stage4 `
    -Filter "*.txt" `
    -File |
    Where-Object {
        $_.Name -ne "stage4_summary.txt"
    } |
    Sort-Object Name |
    Select-Object -First 30

foreach ($f in $contexts) {

    Copy-Item `
        -LiteralPath $f.FullName `
        -Destination $logs `
        -Force

    Write-Host "COPY CTX: $($f.Name)"
}

# ------------------------------------------------------------
# README
# ------------------------------------------------------------

$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 4 결과"
    "생성: $(Get-Date)"
    ""
    "이 logs 폴더의 현재 파일 전체를 ChatGPT에 업로드하세요."
    ""
    "핵심:"
    " - stage4_summary.txt"
    " - elf_layout.tsv"
    " - literal_signatures.tsv"
    " - constant_loads.tsv"
    " - xref_contexts.tsv"
    " - compressed_samples.tsv"
    " - *_XREF_*.txt / *__3_*.txt"
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8

Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 4 SUCCESS"
Write-Host "=========================================="
Write-Host ""

Write-Host "업로드할 폴더:"
Write-Host $logs

Write-Host ""
Write-Host "현재 파일:"
Write-Host ""

Get-ChildItem `
    -LiteralPath $logs |
    Select-Object Name,Length |
    Format-Table -AutoSize
