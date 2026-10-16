$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage15"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$stage14 = Join-Path `
    $base `
    "analysis\stage14\test_patch"

$patchedDat = Join-Path `
    $stage14 `
    "naruto.dat"

$patchedIdx = Join-Path `
    $stage14 `
    "naruto.idx"

$isoOutDir = Join-Path `
    $stage `
    "iso_test"

$outIso = Join-Path `
    $isoOutDir `
    "Naruto - Narutimate Portable - Stage14 Patch Test.iso"

$pyFile = Join-Path `
    $stage `
    "stage15_iso_patcher.py"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null
New-Item -ItemType Directory -Force -Path $isoOutDir  | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage15_$stamp.log"


function Add-LogLine {
    param(
        [string]$Line
    )

    Write-Host $Line

    Add-Content `
        -LiteralPath $runLog `
        -Value $Line `
        -Encoding UTF8
}


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
    Write-Host "STAGE 15 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host $failDir
}


if (-not (Test-Path $sourceIso)) {
    Save-Failure "원본 KR ISO가 없습니다: $sourceIso"
    exit 1
}

if (-not (Test-Path $patchedDat)) {
    Save-Failure "Stage14 patched naruto.dat가 없습니다."
    exit 1
}

if (-not (Test-Path $patchedIdx)) {
    Save-Failure "Stage14 patched naruto.idx가 없습니다."
    exit 1
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

    $syntaxOutput = & py -3 -m py_compile $pyFile 2>&1

}
else {

    $syntaxOutput = & python -m py_compile $pyFile 2>&1
}


foreach ($line in $syntaxOutput) {
    Add-LogLine "$line"
}


if ($LASTEXITCODE -ne 0) {
    Save-Failure "Stage15 Python 문법 오류"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 15"
Write-Host " Automatic ISO patch"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# Run
# ============================================================

if ($python -eq "py") {

    & py -3 $pyFile `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        ForEach-Object {

            Write-Host $_

            Add-Content `
                -LiteralPath $runLog `
                -Value "$_" `
                -Encoding UTF8
        }

}
else {

    & python $pyFile `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        ForEach-Object {

            Write-Host $_

            Add-Content `
                -LiteralPath $runLog `
                -Value "$_" `
                -Encoding UTF8
        }
}


if ($LASTEXITCODE -ne 0) {
    Save-Failure "Stage15 ISO patch 실패"
    exit 1
}


# ============================================================
# Required outputs
# ============================================================

$required = @(
    "stage15_summary.txt",
    "iso_filesystem_records.tsv",
    "iso_validation.tsv"
)


foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Save-Failure "Stage15 결과 누락: $name"
        exit 1
    }
}


if (-not (Test-Path $outIso)) {
    Save-Failure "패치 ISO가 생성되지 않았습니다."
    exit 1
}


# ============================================================
# Archive old successful logs
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
# ChatGPT review data
# ISO itself is intentionally excluded.
# ============================================================

foreach ($name in $required) {

    Copy-Item `
        -LiteralPath (
            Join-Path $stage $name
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


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 15"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage15_upload.zip"
    ""
    "실제 PPSSPP 실행용 ISO:"
    " $outIso"
    ""
    "ISO에는 Stage14 테스트 패치가 들어 있습니다."
    " event000.tbl / s_a01_000"
    " -> STAGE14 PATCH TEST"
    ""
    "원본 ISO는 수정하지 않았습니다."
    ""
    "패치 방식:"
    " - 원본 ISO 복사"
    " - 새 naruto.dat / naruto.idx를 ISO 끝에 sector-aligned append"
    " - ISO9660/Joliet directory record LBA/size 갱신"
    " - volume space size 갱신"
    " - 완성 ISO에서 DAT/IDX를 재추출하여 SHA256 검증"
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


# ============================================================
# Upload ZIP
# ============================================================

$zipFile = Join-Path `
    $logs `
    "naruto_stage15_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage15_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {
    Save-Failure "Stage15 upload ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 15 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "PPSSPP에서 실행할 ISO:"
Write-Host $outIso
Write-Host ""
Write-Host "ChatGPT에 올릴 파일:"
Write-Host $zipFile
Write-Host ""
Write-Host "ISO size:"
Write-Host ((Get-Item $outIso).Length)
