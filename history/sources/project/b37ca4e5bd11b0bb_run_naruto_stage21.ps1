$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage21"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path `
    $stage `
    "stage21_trace_runtime_tables.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage21_$stamp.log"


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
    Write-Host "STAGE 21 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
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


if ($python -eq "py") {

    & py -3 -m py_compile $pyFile

}
else {

    & python -m py_compile $pyFile
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage21 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 21"
Write-Host " Runtime conversion-table trace"
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

    Save-Failure "Stage21 분석 실패"
    exit 1
}


$required = @(
    "stage21_summary.txt",
    "setter_pointer_refs.tsv",
    "setter_pointer_contexts.txt",
    "setter_data_xrefs.tsv",
    "conversion_global_accesses.tsv",
    "jalr_calls.tsv",
    "jalr_contexts.txt",
    "resource_scan.tsv",
    "table_source_candidates.tsv",
    "extracted_table_candidates.tsv"
)


foreach ($name in $required) {

    $path = Join-Path `
        $stage `
        $name

    if (-not (Test-Path $path)) {

        Save-Failure "Stage21 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Success-only log archive
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


# Copy small extracted table candidates.
$candidateDir = Join-Path `
    $stage `
    "candidates"

if (Test-Path $candidateDir) {

    Get-ChildItem `
        -LiteralPath $candidateDir `
        -File |
        Select-Object -First 10 |
        ForEach-Object {

            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }
}


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 21"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage21_upload.zip"
    ""
    "분석 내용:"
    " - 0x002AD284 setter의 함수포인터 참조"
    " - BSS 0x004BD5E0~F0 전체 코드 접근"
    " - 간접 jalr 호출부"
    " - KR 추출/Stage9/10/11 리소스의"
    "   실제 JIS<->Unicode 128KB 테이블 검색"
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
    "naruto_stage21_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage21_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage21 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 21 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
