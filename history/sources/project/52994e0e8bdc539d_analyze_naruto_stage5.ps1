$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"

$stage5 = Join-Path $base "analysis\stage5"

$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"

$pyFile = Join-Path $stage5 "stage5_mips_trace.py"

New-Item -ItemType Directory -Force -Path $stage5 | Out-Null
New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage5 "naruto_stage5_$stamp.log"


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
Write-Host " Naruto PSP Stage 5"
Write-Host "=========================================="
Write-Host ""


# ------------------------------------------------------------
# Syntax check
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

    Write-Host "Python 문법 오류"

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    exit 1
}


Write-Host "[OK]"
Write-Host ""
Write-Host "Stage 5 실행..."


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
    Write-Host "STAGE 5 FAILED"
    Write-Host "기존 logs는 유지합니다."

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    exit 1
}


# ------------------------------------------------------------
# 필수 결과
# ------------------------------------------------------------

$required = @(
    "stage5_summary.txt",
    "decompressor_candidates.tsv",
    "pidx_field_candidates.tsv",
    "focus_callgraph.tsv",
    "focus_callers.tsv"
)


foreach ($name in $required) {

    $p = Join-Path $stage5 $name

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
# 성공했을 때만 기존 logs -> old
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# 필요한 결과 복사
# ------------------------------------------------------------

$needed = @(
    $runLog,
    (Join-Path $stage5 "stage5_summary.txt"),
    (Join-Path $stage5 "decompressor_candidates.tsv"),
    (Join-Path $stage5 "pidx_field_candidates.tsv"),
    (Join-Path $stage5 "focus_callgraph.tsv"),
    (Join-Path $stage5 "focus_callers.tsv")
)


foreach ($src in $needed) {

    Copy-Item `
        -LiteralPath $src `
        -Destination $logs `
        -Force
}


# ------------------------------------------------------------
# 가장 중요한 함수 덤프만 logs로
# ------------------------------------------------------------

$important = @()

$important += Get-ChildItem `
    -LiteralPath $stage5 `
    -Filter "US_BOOT__FOCUS_*.txt" `
    -File

$important += Get-ChildItem `
    -LiteralPath $stage5 `
    -Filter "US_BOOT__PIDXFIELD*.txt" `
    -File |
    Select-Object -First 20

$important += Get-ChildItem `
    -LiteralPath $stage5 `
    -Filter "US_BOOT__RANK*.txt" `
    -File |
    Select-Object -First 20


$important |
    Sort-Object FullName -Unique |
    ForEach-Object {

        Copy-Item `
            -LiteralPath $_.FullName `
            -Destination $logs `
            -Force
    }


# ------------------------------------------------------------
# README
# ------------------------------------------------------------

$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 5 결과"
    "생성: $(Get-Date)"
    ""
    "logs 폴더의 현재 파일 전체를 ChatGPT에 업로드하세요."
    ""
    "핵심:"
    " - stage5_summary.txt"
    " - decompressor_candidates.tsv"
    " - pidx_field_candidates.tsv"
    " - focus_callgraph.tsv"
    " - focus_callers.tsv"
    " - US_BOOT__FOCUS_*.txt"
    " - US_BOOT__PIDXFIELD*.txt"
    " - US_BOOT__RANK*.txt"
    ""
    "이전 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 5 SUCCESS"
Write-Host "=========================================="
Write-Host ""

Write-Host "업로드 폴더:"
Write-Host $logs
Write-Host ""

Get-ChildItem `
    -LiteralPath $logs |
    Select-Object Name,Length |
    Format-Table -AutoSize
