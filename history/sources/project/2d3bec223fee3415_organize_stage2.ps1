$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$stage2 = Join-Path $base "analysis\stage2"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archive = Join-Path $oldRoot $stamp

New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $oldRoot | Out-Null
New-Item -ItemType Directory -Force -Path $archive | Out-Null

Write-Host "=========================================="
Write-Host " Naruto 분석 결과 정리"
Write-Host "=========================================="

# 현재 가장 최근 Stage 2 Python 로그 이름 기억
$latestPythonLog = Get-ChildItem $logs `
    -Filter "naruto_stage2_python_*.log" `
    -File `
    -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$latestStage2Log = Get-ChildItem $logs `
    -Filter "naruto_stage2_*.log" `
    -File `
    -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike "*python*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$pythonLogName = if ($latestPythonLog) {
    $latestPythonLog.Name
} else {
    $null
}

$stage2LogName = if ($latestStage2Log) {
    $latestStage2Log.Name
} else {
    $null
}

# --------------------------------------------------
# 기존 logs 내용 전부 old\<timestamp> 로 이동
# old 자체는 제외
# --------------------------------------------------

Write-Host ""
Write-Host "[1] 기존 logs 보관"
Write-Host " -> $archive"

Get-ChildItem $logs -Force |
    Where-Object { $_.Name -ne "old" } |
    ForEach-Object {

        Write-Host "MOVE: $($_.Name)"

        Move-Item `
            -LiteralPath $_.FullName `
            -Destination $archive `
            -Force
    }

# --------------------------------------------------
# 이번 분석에서 ChatGPT가 확인할 파일 복원/복사
# --------------------------------------------------

Write-Host ""
Write-Host "[2] 필요한 파일을 logs로 수집"

$published = @()

# Python 실행 로그
if ($pythonLogName) {

    $src = Join-Path $archive $pythonLogName

    if (Test-Path $src) {

        Copy-Item $src $logs -Force

        $published += $pythonLogName

        Write-Host "COPY: $pythonLogName"
    }
}

# Stage2 PowerShell 로그도 보관
if ($stage2LogName) {

    $src = Join-Path $archive $stage2LogName

    if (Test-Path $src) {

        Copy-Item $src $logs -Force

        $published += $stage2LogName

        Write-Host "COPY: $stage2LogName"
    }
}

# 현재 제가 분석에 필요한 파일
$neededFiles = @(
    "magic_offsets.tsv",
    "kr_idx_report.txt",
    "kr_dat_sjis.tsv",
    "us_dat_ascii.tsv",
    "kr_idx_ascii.tsv",
    "kr_idx_sjis.tsv",
    "kr_dat_head_tail.txt",
    "us_dat_head_tail.txt",
    "kr_idx_head_tail.txt"
)

foreach ($name in $neededFiles) {

    $src = Join-Path $stage2 $name

    if (Test-Path $src) {

        Copy-Item `
            -LiteralPath $src `
            -Destination $logs `
            -Force

        $published += $name

        Write-Host "COPY: $name"
    }
    else {
        Write-Host "SKIP: $name (없음)"
    }
}

# --------------------------------------------------
# 업로드 안내 파일 생성
# --------------------------------------------------

$readme = Join-Path $logs "README_UPLOAD.txt"

@(
    "Naruto PSP 분석 결과"
    "생성: $(Get-Date)"
    ""
    "아래 logs 폴더의 파일들은 ChatGPT 분석용으로 수집됨:"
    ""
) + ($published | ForEach-Object {
    " - $_"
}) + @(
    ""
    "이전 결과:"
    " $archive"
) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

Write-Host ""
Write-Host "=========================================="
Write-Host " 정리 완료"
Write-Host "=========================================="

Write-Host ""
Write-Host "ChatGPT에 올릴 폴더:"
Write-Host $logs

Write-Host ""
Write-Host "이전 결과:"
Write-Host $archive

Write-Host ""
Get-ChildItem $logs |
    Select-Object Name, Length |
    Format-Table -AutoSize
