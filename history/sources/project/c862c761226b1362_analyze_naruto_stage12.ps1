$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage12"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage12_storage_verify.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage12_$stamp.log"


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
    Write-Host "FAILED:"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
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


# Python syntax
if ($python -eq "py") {

    & py -3 -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog

}
else {

    & python -m py_compile $pyFile 2>&1 |
        Tee-Object -FilePath $runLog
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage 12 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 12"
Write-Host " FSTS storage verification"
Write-Host "=========================================="
Write-Host ""


# Run
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

    Save-Failure "Stage 12 분석 실패"
    exit 1
}


$required = @(
    "stage12_summary.txt",
    "fsts_members_corrected.tsv",
    "fsts_plus8_verification.tsv",
    "fsts_layout_corrected.tsv",
    "type0_repack_estimate.tsv",
    "fsts_remaining_mismatches.tsv"
)


foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Save-Failure "Stage 12 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Archive previous successful logs
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


# Copy results
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


# README
$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 12"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage12_upload.zip"
    ""
    "검증:"
    " - FSTS zsize=size+8 항목 재검증"
    " - 3;0 / 3;1 저장 규칙"
    " - 모든 FSTS 복사본 SHA256 재비교"
    " - FSTS 0x800 정렬"
    " - 수정 리소스 3;0 재인코딩 가능성"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ZIP
$zipFile = Join-Path `
    $logs `
    "naruto_stage12_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage12_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage 12 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 12 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드할 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
