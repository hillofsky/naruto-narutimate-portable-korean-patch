$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"

$stage = Join-Path $base "analysis\stage6"

$logs    = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage "stage6_pidx_trace.py"

New-Item -ItemType Directory -Force -Path $stage   | Out-Null
New-Item -ItemType Directory -Force -Path $logs    | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage6_$stamp.log"

if (Get-Command python -ErrorAction SilentlyContinue) {

    $python = "python"

}
elseif (Get-Command py -ErrorAction SilentlyContinue) {

    $python = "py"

}
else {

    throw "Python을 찾을 수 없습니다."
}

Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 6"
Write-Host "=========================================="
Write-Host ""

# Python 문법 검사
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

    throw "Stage 6 Python 문법 오류"
}

Write-Host "[OK] Python syntax"
Write-Host ""
Write-Host "Stage 6 실행..."

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
    Write-Host "Stage 6 실패"
    Write-Host "기존 logs는 유지합니다."

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    exit 1
}

# 결과 검증
$required = @(
    "stage6_summary.txt",
    "pidx_global_xrefs.tsv",
    "literal_xrefs.tsv",
    "pidx_callgraph.tsv",
    "us_near_pidx.tsv",
    "target_kr_matches.tsv"
)

foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Copy-Item `
            -LiteralPath $runLog `
            -Destination $logs `
            -Force

        throw "Stage 6 결과 누락: $name"
    }
}

# ============================================================
# 성공 시 기존 logs -> old
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
# 필요한 결과 logs로 복사
# ============================================================

$needed = @(
    $runLog,
    (Join-Path $stage "stage6_summary.txt"),
    (Join-Path $stage "pidx_global_xrefs.tsv"),
    (Join-Path $stage "literal_xrefs.tsv"),
    (Join-Path $stage "pidx_callgraph.tsv"),
    (Join-Path $stage "us_near_pidx.tsv"),
    (Join-Path $stage "target_kr_matches.tsv")
)

foreach ($src in $needed) {

    Copy-Item `
        -LiteralPath $src `
        -Destination $logs `
        -Force
}

# 함수 덤프도 수집
Get-ChildItem `
    -LiteralPath $stage `
    -Filter "US__*.txt" `
    -File |
    Select-Object -First 50 |
    ForEach-Object {

        Copy-Item `
            -LiteralPath $_.FullName `
            -Destination $logs `
            -Force
    }

Get-ChildItem `
    -LiteralPath $stage `
    -Filter "KR_MATCH__*.txt" `
    -File |
    Select-Object -First 20 |
    ForEach-Object {

        Copy-Item `
            -LiteralPath $_.FullName `
            -Destination $logs `
            -Force
    }

# README
$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 6 결과"
    "생성: $(Get-Date)"
    ""
    "업로드는 아래 ZIP 하나만 하면 됩니다."
    " naruto_stage6_upload.zip"
    ""
    "개별 분석 파일도 logs에 그대로 남아 있습니다."
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8

# ============================================================
# 자동 ZIP
# ============================================================

$zipFile = Join-Path $logs "naruto_stage6_upload.zip"

Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue

$zipSources = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage6_upload.zip"
    } |
    Select-Object -ExpandProperty FullName

Compress-Archive `
    -Path $zipSources `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force

if (-not (Test-Path $zipFile)) {
    throw "ZIP 생성 실패"
}

Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 6 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드할 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP 크기:"
Write-Host ((Get-Item $zipFile).Length)
