$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage11"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage11_fsts_map.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path $stage "naruto_stage11_$stamp.log"


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

    $err = Join-Path `
        $stage `
        "stage11_errors.txt"

    if (Test-Path $err) {

        Copy-Item `
            -LiteralPath $err `
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
    Write-Host "기존 성공 logs는 유지합니다."
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

    Save-Failure "Stage 11 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 11"
Write-Host " FSTS duplicate mapping"
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

    Save-Failure "Stage 11 분석 실패"
    exit 1
}


$required = @(
    "stage11_summary.txt",
    "fsts_format_notes.txt",
    "fsts_bundle_summary.tsv",
    "fsts_members.tsv",
    "primary_fsts_copy_map.tsv",
    "translation_fsts_map.tsv",
    "translation_primary_coverage.tsv",
    "event_fsts_coverage.tsv",
    "nonidentical_translation_copies.tsv"
)


foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Save-Failure "Stage 11 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Success: old logs archive
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


# Reports
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


# Strategic extracted members
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


# README
$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 11"
    "생성: $(Get-Date)"
    ""
    "업로드할 파일:"
    " naruto_stage11_upload.zip"
    ""
    "분석 내용:"
    " - 모든 OFFSET2 FSTS 파싱"
    " - FSTS 내부 파일 전수 목록"
    " - primary와 압축 해제 후 SHA256 비교"
    " - event/quiz/text/UI 중복 위치 확인"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ZIP
$zipFile = Join-Path `
    $logs `
    "naruto_stage11_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage11_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage 11 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 11 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "업로드할 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
