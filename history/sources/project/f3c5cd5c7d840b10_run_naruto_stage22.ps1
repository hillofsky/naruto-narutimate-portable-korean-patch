$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage22"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage22_probe_cptbl.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage22_$stamp.log"


function Save-Failure {

    param(
        [string]$Reason
    )

    $failDir = Join-Path $failedRoot $stamp

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
                Join-Path $failDir "FAILURE.txt"
            ) `
            -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 22 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
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

    Save-Failure "Stage22 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 22"
Write-Host " cptbl.dat probe"
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

    Save-Failure "Stage22 분석 실패"
    exit 1
}


$required = @(
    "stage22_status.txt",
    "stage22_summary.txt",
    "boot_codepage_strings.tsv",
    "local_firmware_files.tsv",
    "cptbl_table_candidates.tsv"
)


foreach ($name in $required) {

    $path = Join-Path $stage $name

    if (-not (Test-Path $path)) {

        Save-Failure "Stage22 결과 누락: $name"
        exit 1
    }
}


# success-only archive
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
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP Stage 22"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage22_upload.zip"
    ""
    "분석:"
    " - BOOT/EBOOT의 cptbl/codepage 경로 문자열"
    " - 로컬 PPSSPP/PSP cptbl.dat 검색"
    " - cptbl 안의 0x20000 JIS<->Unicode 테이블 검증"
    " - cp949_table.dat / kr0.pgf 존재 여부"
    ""
    "Firmware 파일 원본 자체는 ZIP에 포함하지 않습니다."
    ""
    "이번 Stage에서는 ISO를 생성하지 않습니다."
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage22_upload.zip"

Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage22_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 22 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
