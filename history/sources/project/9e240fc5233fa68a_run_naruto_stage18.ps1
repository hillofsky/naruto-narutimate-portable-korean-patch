$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage18"

$logs       = Join-Path $base "logs"
$oldRoot    = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$probePy = Join-Path $stage "stage18_make_korean_probe.py"
$tracePy = Join-Path $stage "stage18_font_trace.py"

$patcher = Join-Path `
    $base `
    "analysis\stage14\naruto_patcher.py"

$isoPatcher = Join-Path `
    $base `
    "analysis\stage15\stage15_iso_patcher.py"

$sourceIso = Join-Path `
    $base `
    "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

$probeTbl = Join-Path `
    $stage `
    "event000_stage18.tbl"

$patchOut = Join-Path `
    $stage `
    "patch"

# ISO는 요청대로 프로젝트 최상단에 둡니다.
$outIso = Join-Path `
    $base `
    "Naruto - Stage18 Korean Encoding Probe.iso"

New-Item -ItemType Directory -Force -Path $logs       | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot    | Out-Null
New-Item -ItemType Directory -Force -Path $failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$runLog = Join-Path `
    $stage `
    "naruto_stage18_$stamp.log"


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
    Write-Host "STAGE 18 FAILED"
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


$pythonFiles = @(
    $probePy,
    $tracePy,
    $patcher,
    $isoPatcher
)


foreach ($p in $pythonFiles) {

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
Write-Host " Naruto PSP Stage 18"
Write-Host " Korean encoding probe"
Write-Host "=========================================="
Write-Host ""


# ============================================================
# [1/4] Static trace
# ============================================================

Write-Host "[1/4] 폰트 선택/문자 변환 함수 분석"

if ($python -eq "py") {

    & py -3 $tracePy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $tracePy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage18 static trace 실패"
    exit 1
}


# ============================================================
# [2/4] Probe TBL
# ============================================================

Write-Host ""
Write-Host "[2/4] 한글 인코딩 진단 TBL 생성"

if ($python -eq "py") {

    & py -3 $probePy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $probePy 2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}

if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage18 probe TBL 생성 실패"
    exit 1
}


# ============================================================
# [3/4] DAT/IDX
# ============================================================

Write-Host ""
Write-Host "[3/4] DAT/IDX 패치"

$replaceArg = "event000.tbl=$probeTbl"

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

    Save-Failure "Stage18 DAT/IDX 패치 실패"
    exit 1
}


# ============================================================
# [4/4] ISO — 최상단
# ============================================================

Write-Host ""
Write-Host "[4/4] 테스트 ISO 생성"

$patchedDat = Join-Path $patchOut "naruto.dat"
$patchedIdx = Join-Path $patchOut "naruto.idx"

Remove-Item `
    -LiteralPath $outIso `
    -Force `
    -ErrorAction SilentlyContinue


if ($python -eq "py") {

    & py -3 $isoPatcher `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}
else {

    & python $isoPatcher `
        --source-iso $sourceIso `
        --dat $patchedDat `
        --idx $patchedIdx `
        --output-iso $outIso `
        --report-dir $stage `
        2>&1 |
        Tee-Object `
            -FilePath $runLog `
            -Append
}


if ($LASTEXITCODE -ne 0) {

    Save-Failure "Stage18 ISO 생성 실패"
    exit 1
}


# ============================================================
# Required
# ============================================================

$required = @(
    "stage18_probe_map.tsv",
    "event000_stage18.tbl",
    "kr_font_functions.txt",
    "font_helper_calls.tsv",
    "character_conversion_imports.tsv",
    "stage18_static_summary.txt",
    "stage15_summary.txt",
    "iso_validation.tsv"
)


foreach ($name in $required) {

    if (-not (
        Test-Path (
            Join-Path $stage $name
        )
    )) {

        Save-Failure "Stage18 결과 누락: $name"
        exit 1
    }
}


if (-not (Test-Path $outIso)) {

    Save-Failure "Stage18 ISO가 없습니다."
    exit 1
}


# ============================================================
# Stage summary
# ============================================================

$summary = Join-Path `
    $stage `
    "stage18_summary.txt"


@(
    "Naruto PSP Stage 18"
    "=============================================="
    ""
    "실행 ISO:"
    " $outIso"
    ""
    "대사 순서:"
    " 1 K1 = CP949 한글테스트"
    " 2 K2 = CP949 한글[전각공백]테스트"
    " 3 K3 = CP949 확장문자 똠방각하"
    " 4 U1 = UTF-8 한글테스트"
    " 5 U2 = UTF-8 한글[전각공백]테스트"
    " 6 B1 = UTF-16BE raw 한국"
    " 7 JP = CP932 日本語確認"
    ""
    "판정:"
    " K1 성공 + K3 성공 -> CP949 확장 한글 가능"
    " K1 성공 + K3 실패 -> EUC-KR/KS X 1001 가능성"
    " U1 성공 -> UTF-8 입력 가능"
    " B1 성공 -> 직접 16-bit 경로 조사"
    " JP 성공 -> 기존 CP932 경로 정상"
) | Set-Content `
    -LiteralPath $summary `
    -Encoding UTF8


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


$review = @(
    "stage18_summary.txt",
    "stage18_probe_map.tsv",
    "event000_stage18.tbl",
    "kr_font_functions.txt",
    "font_helper_calls.tsv",
    "character_conversion_imports.tsv",
    "stage18_static_summary.txt",
    "stage15_summary.txt",
    "iso_validation.tsv"
)


foreach ($name in $review) {

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


$readme = Join-Path `
    $logs `
    "README_UPLOAD.txt"


@(
    "Naruto PSP Stage 18"
    "생성: $(Get-Date)"
    ""
    "ChatGPT 업로드:"
    " naruto_stage18_upload.zip"
    ""
    "PPSSPP 테스트 ISO:"
    " $outIso"
    ""
    "ISO는 프로젝트 최상단에 생성됨."
    ""
    "게임에서 K1/K2/K3/U1/U2/B1/JP의"
    "실제 표시 결과를 함께 알려주세요."
    ""
    "이전 성공 logs:"
    " $archive"
) | Set-Content `
    -LiteralPath $readme `
    -Encoding UTF8


$zipFile = Join-Path `
    $logs `
    "naruto_stage18_upload.zip"


Remove-Item `
    -LiteralPath $zipFile `
    -Force `
    -ErrorAction SilentlyContinue


$files = Get-ChildItem `
    -LiteralPath $logs `
    -File |
    Where-Object {
        $_.Name -ne "naruto_stage18_upload.zip"
    } |
    Select-Object `
        -ExpandProperty FullName


Compress-Archive `
    -Path $files `
    -DestinationPath $zipFile `
    -CompressionLevel Optimal `
    -Force


if (-not (Test-Path $zipFile)) {

    Save-Failure "Stage18 ZIP 생성 실패"
    exit 1
}


Write-Host ""
Write-Host "=========================================="
Write-Host " STAGE 18 SUCCESS"
Write-Host "=========================================="
Write-Host ""
Write-Host "PPSSPP 테스트:"
Write-Host $outIso
Write-Host ""
Write-Host "ChatGPT 업로드:"
Write-Host $zipFile
