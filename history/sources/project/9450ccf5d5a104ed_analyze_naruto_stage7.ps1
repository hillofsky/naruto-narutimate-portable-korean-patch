$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage7"

$logs    = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage "stage7_loader_trace.py"

New-Item -ItemType Directory -Force -Path $logs    | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage7_$stamp.log"

if (Get-Command python -ErrorAction SilentlyContinue) {

    $python = "python"

} elseif (Get-Command py -ErrorAction SilentlyContinue) {

    $python = "py"

} else {

    throw "Python을 찾을 수 없습니다."
}

# 문법 검사
if ($python -eq "py") {

    & py -3 -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog

} else {

    & python -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog
}

if ($LASTEXITCODE -ne 0) {

    Copy-Item $runLog $logs -Force

    throw "Stage 7 Python 문법 오류"
}

# 실행
if ($python -eq "py") {

    & py -3 $pyFile 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append

} else {

    & python $pyFile 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {

    Write-Host "Stage 7 실패"
    Write-Host "기존 logs 유지"

    Copy-Item $runLog $logs -Force

    exit 1
}

$required = @(
    "stage7_summary.txt",
    "pidx_module_functions.tsv",
    "target_relations.tsv",
    "target_callsites.tsv",
    "target_callsites.txt",
    "loader_related_functions.tsv",
    "codec_kr_matches.tsv",
    "us_pidx_module_full.txt"
)

foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Copy-Item $runLog $logs -Force

        throw "결과 누락: $name"
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

# 결과 복사
$required |
    ForEach-Object {

        Copy-Item `
            -LiteralPath (
                Join-Path $stage $_
            ) `
            -Destination $logs `
            -Force
    }

Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force

# US 함수 덤프
Get-ChildItem `
    -LiteralPath $stage `
    -Filter "US__*.txt" `
    -File |
    ForEach-Object {

        Copy-Item `
            -LiteralPath $_.FullName `
            -Destination $logs `
            -Force
    }

# KR codec 대응 함수
Get-ChildItem `
    -LiteralPath $stage `
    -Filter "KR_CODEC_MATCH__*.txt" `
    -File |
    ForEach-Object {

        Copy-Item `
            -LiteralPath $_.FullName `
            -Destination $logs `
            -Force
    }

# README
$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 7"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage7_upload.zip"
    ""
    "개별 파일은 logs에도 유지됩니다."
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8

# ============================================================
# ZIP 자동 생성
# ============================================================

$zipFile = Join-Path $logs "naruto_stage7_upload.zip"

Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue

$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage7_upload.zip"
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
Write-Host " STAGE 7 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드할 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "크기:"
Write-Host ((Get-Item $zipFile).Length)
