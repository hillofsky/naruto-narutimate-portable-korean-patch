$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage20"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$mapPy = Join-Path `
    $stage `
    "stage20_hangul_map.py"

$isoPy = Join-Path `
    $stage `
    "stage20_iso_multi_patch.py"

$patcher = Join-Path `
    $base `
    "analysis\stage14\naruto_patcher.py"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$probeTbl = Join-Path `
    $stage `
    "event000_stage20.tbl"

$patchedBoot = Join-Path `
    $stage `
    "BOOT_stage20_patched.BIN"

$patchOut = Join-Path `
    $stage `
    "patch"

# ISO는 항상 최상단.
$outIso = Join-Path `
    $base `
    "Naruto - Stage20 Hangul Map Test.iso"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage20_$stamp.log"


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
    Write-Host "STAGE 20 FAILED"
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


foreach ($p in @(
    $mapPy,
    $isoPy,
    $patcher
)) {
    if (-not (Test-Path $p)) {
        Save-Failure "필수 파일 없음: $p"
        exit 1
    }

    if ($python -eq "py") {
        & py -3 -m py_compile $p
    }
    else {
        & python -m py_compile $p
    }

    if ($LASTEXITCODE -ne 0) {
        Save-Failure "Python 문법 오류: $p"
        exit 1
    }
}


Write-Host ""
Write-Host "=========================================="
Write-Host " Naruto PSP Stage 20"
Write-Host " Hangul mapping-table test"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# [1/3] Table analysis / patch generation
# ============================================================

Write-Host "[1/3] 문자 변환 테이블 분석"

if ($python -eq "py") {
    & py -3 $mapPy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {
    & python $mapPy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {
    Save-Failure "Stage20 table 분석 실패"
    exit 1
}


$statusFile = Join-Path `
    $stage `
    "stage20_status.txt"

if (-not (Test-Path $statusFile)) {
    Save-Failure "stage20_status.txt 없음"
    exit 1
}

$status = (
    Get-Content `
        -LiteralPath $statusFile `
        -Raw
).Trim()


# ============================================================
# If table was not statically patchable,
# package analysis without creating ISO.
# ============================================================

if ($status -ne "PATCHABLE") {

    Write-Host ""
    Write-Host "정적 변환 테이블을 바로 패치할 수 없어"
    Write-Host "Stage20은 분석 결과만 생성했습니다."
    Write-Host ""

}
else {

    # ========================================================
    # [2/3] DAT / IDX
    # ========================================================

    Write-Host ""
    Write-Host "[2/3] 테스트 TBL  DAT/IDX"

    $replaceArg = (
        "event000.tbl=$probeTbl"
    )

    if ($python -eq "py") {

        & py -3 $patcher `
            --root $base `
            --output $patchOut `
            --replace $replaceArg `
            --force `
            2>&1 |
            Tee-Object `
                -FilePath $runLog `
                -Append
    }
    else {

        & python $patcher `
            --root $base `
            --output $patchOut `
            --replace $replaceArg `
            --force `
            2>&1 |
            Tee-Object `
                -FilePath $runLog `
                -Append
    }

    if ($LASTEXITCODE -ne 0) {
        Save-Failure "Stage20 DAT/IDX 생성 실패"
        exit 1
    }


    # ========================================================
    # [3/3] ISO
    # ========================================================

    Write-Host ""
    Write-Host "[3/3] patched ELF 포함 ISO 생성"

    $patchedDat = Join-Path `
        $patchOut `
        "naruto.dat"

    $patchedIdx = Join-Path `
        $patchOut `
        "naruto.idx"

    Remove-Item `
        -LiteralPath $outIso `
        -Force `
        -ErrorAction SilentlyContinue

    if ($python -eq "py") {

        & py -3 $isoPy `
            --source-iso $sourceIso `
            --dat $patchedDat `
            --idx $patchedIdx `
            --boot $patchedBoot `
            --output-iso $outIso `
            --report-dir $stage `
            2>&1 |
            Tee-Object `
                -FilePath $runLog `
                -Append
    }
    else {

        & python $isoPy `
            --source-iso $sourceIso `
            --dat $patchedDat `
            --idx $patchedIdx `
            --boot $patchedBoot `
            --output-iso $outIso `
            --report-dir $stage `
            2>&1 |
            Tee-Object `
                -FilePath $runLog `
                -Append
    }

    if ($LASTEXITCODE -ne 0) {
        Save-Failure "Stage20 ISO 생성 실패"
        exit 1
    }
}


# ============================================================
# Success-only archive
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
# Review bundle
# ============================================================

$reviewNames = @(
    "stage20_status.txt",
    "stage20_summary.txt",
    "conversion_table_candidates.tsv",
    "converter_global_callsites.tsv",
    "converter_global_contexts.txt"
)


if ($status -eq "PATCHABLE") {

    $reviewNames += @(
        "unused_sjis_slots.tsv",
        "hangul_custom_mapping.tsv",
        "mapping_validation.tsv",
        "stage20_probe_map.tsv",
        "boot_diff_summary.txt",
        "event000_stage20.tbl",
        "stage20_iso_summary.txt",
        "stage20_iso_validation.tsv"
    )
}


foreach ($name in $reviewNames) {

    $src = Join-Path `
        $stage `
        $name

    if (Test-Path $src) {

        Copy-Item `
            -LiteralPath $src `
            -Destination $logs `
            -Force
    }
}


if (($status -eq "PATCHABLE") -and (Test-Path $patchOut)) {

    foreach ($name in @(
        "replacement_manifest.tsv",
        "fsts_patch_map.tsv",
        "validation.tsv",
        "stage14_summary.txt"
    )) {

        $src = Join-Path `
            $patchOut `
            $name

        if (Test-Path $src) {

            Copy-Item `
                -LiteralPath $src `
                -Destination (
                    Join-Path `
                        $logs `
                        "patcher_$name"
                ) `
                -Force
        }
    }
}


Copy-Item `
    -LiteralPath $runLog `
    -Destination $logs `
    -Force


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


$readmeLines = @(
    "Naruto PSP Stage 20"
    "생성: $(Get-Date)"
    ""
    "STATUS: $status"
    ""
    "ChatGPT 업로드:"
    " naruto_stage20_upload.zip"
)


if ($status -eq "PATCHABLE") {

    $readmeLines += @(
        ""
        "PPSSPP 실행 ISO:"
        " $outIso"
        ""
        "ISO는 프로젝트 최상단에 생성됨."
        ""
        "첫 이벤트에서 KMAP 한글 문자열이"
        "실제로 한글로 표시되는지 확인."
    )
}


$readmeLines += @(
    ""
    "이전 성공 logs:"
    " $archive"
)


$readmeLines |
    Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage20_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage20_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {
    Save-Failure "Stage20 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 20 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "STATUS:"
Write-Host $status
Write-Host ""


if ($status -eq "PATCHABLE") {

    Write-Host "PPSSPP에서 실행:"
    Write-Host $outIso
    Write-Host ""
}


Write-Host "ChatGPT 업로드:"
Write-Host $zipFile

