$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage14"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "naruto_patcher.py"

$testOut = Join-Path `
    $stage `
    "test_patch"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage14_$stamp.log"


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
    Write-Host "STAGE 14 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 그대로 유지됩니다."
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


# ============================================================
# Python syntax
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

    Save-Failure "naruto_patcher.py 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 14"
Write-Host " Real replacement patch test"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# Stage14 test build
# ============================================================

if ($python -eq "py") {

    & py -3 $pyFile `
        --root $base `
        --output $testOut `
        --stage14-test `
        --force `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $pyFile `
        --root $base `
        --output $testOut `
        --stage14-test `
        --force `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage 14 patch build 실패"
    exit 1
}


# ============================================================
# Required outputs
# ============================================================

$requiredTest = @(
    "naruto.dat",
    "naruto.idx",
    "event000_original.tbl",
    "event000_patched.tbl",
    "replacement_manifest.tsv",
    "primary_patch_map.tsv",
    "fsts_patch_map.tsv",
    "validation.tsv",
    "stage14_summary.txt",
    "stage14_test_change.txt",
    "TEST_INSTRUCTIONS.txt"
)


foreach ($name in $requiredTest) {

    $p = Join-Path $testOut $name

    if (-not (Test-Path $p)) {

        Save-Failure "Stage 14 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Successful run -> archive previous logs
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


# ============================================================
# ChatGPT review files only
# Do NOT put huge DAT in logs/upload ZIP.
# ============================================================

$reviewFiles = @(
    "replacement_manifest.tsv",
    "primary_patch_map.tsv",
    "fsts_patch_map.tsv",
    "validation.tsv",
    "stage14_summary.txt",
    "stage14_test_change.txt",
    "TEST_INSTRUCTIONS.txt",
    "event000_original.tbl",
    "event000_patched.tbl"
)


foreach ($name in $reviewFiles) {

    Copy-Item `
        -LiteralPath (
            Join-Path $testOut $name
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


# ============================================================
# README
# ============================================================

$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 14"
    "생성: $(Get-Date)"
    ""
    "ChatGPT에 업로드:"
    " naruto_stage14_upload.zip"
    ""
    "실제 PPSSPP 테스트용 파일은 ZIP에 넣지 않았습니다."
    "로컬 위치:"
    " $testOut\naruto.dat"
    " $testOut\naruto.idx"
    ""
    "변경 내용:"
    " event000.tbl"
    " s_a01_000 -> STAGE14 PATCH TEST"
    ""
    "패처 자체 검증:"
    " primary 재추출 검증"
    " FSTS 모든 복사본 재추출 검증"
    " embedded/external PIDX 의미상 일치 검증"
    " 미수정 primary 데이터 보존 검증"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ============================================================
# Automatic upload ZIP
# ============================================================

$zipFile = Join-Path `
    $logs `
    "naruto_stage14_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage14_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage 14 upload ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 14 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "PPSSPP 테스트용:"
Write-Host (Join-Path $testOut "naruto.dat")
Write-Host (Join-Path $testOut "naruto.idx")
Write-Host ""
Write-Host "ChatGPT 업로드용:"
Write-Host $zipFile
Write-Host ""
Write-Host "ZIP size:"
Write-Host ((Get-Item $zipFile).Length)
