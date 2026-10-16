$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage19"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$pyFile = Join-Path $stage "stage19_converter_reverse.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage19_$stamp.log"


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
                Join-Path $failDir "FAILURE.txt"
            ) `
            -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 19 FAILED"
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
    Save-Failure "Stage19 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 19"
Write-Host " Full text converter reverse"
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
    Save-Failure "Stage19 분석 실패"
    exit 1
}


$required = @(
    "stage19_summary.txt",
    "kr_converter_full_disasm.txt",
    "kr_converter_region.bin",
    "converter_calls.tsv",
    "converter_call_targets.txt",
    "converter_prologues.tsv",
    "converter_returns.tsv",
    "us_converter_matches.tsv",
    "us_converter_disasm.txt",
    "elf_layout.tsv"
)


foreach ($name in $required) {
    $p = Join-Path $stage $name

    if (-not (Test-Path $p)) {
        Save-Failure "Stage19 결과 누락: $name"
        exit 1
    }
}


# ============================================================
# Success-only logs
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


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


Copy-Item `
    -LiteralPath $pyFile `
    -Destination $logs `
    -Force


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 19"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage19_upload.zip"
    ""
    "분석 목적:"
    " - Stage18에서 조기 return 때문에 잘린"
    "   0x002ACCF4 변환 함수 전체 덤프"
    " - 0x002ACD50 이후 실제 CP932 변환 루프 분석"
    " - 내부 JAL helper 전부 수집"
    " - KR/US 변환기 비교"
    " - 향후 Unicode Hangul escape hook 설계용 ELF layout"
    ""
    "이번 Stage에서는 ISO를 생성하지 않습니다."
    ""
    "다음 ISO 생성 시 위치:"
    " PROJECT_ROOT\"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage19_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage19_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {
    Save-Failure "Stage19 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 19 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
