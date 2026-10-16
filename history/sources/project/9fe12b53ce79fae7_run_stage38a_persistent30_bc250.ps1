$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_persistent30"
$payload = Join-Path $stage "payload"
$manifest = Join-Path $payload "stage38a_persistent30_manifest.tsv"
$results = Join-Path $stage "results_bc250"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$prepare = Join-Path $base "prepare_stage38a_persistent30.ps1"
$client = Join-Path $base "stage38a_persistent30_client.py"
$remoteSh = Join-Path $base "run_stage38a_persistent30_bc250_remote.sh"

New-Item -ItemType Directory -Force -Path `
    $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "persistent30_bc250_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
}

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    if (Test-Path -LiteralPath $runLog) {
        Copy-Item $runLog -Destination $failDir -Force
    }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "PERSISTENT-30 BC250 FAILED"
    Write-Host $Reason
    Write-Host "실패 로그: $failDir"
}

try {
    Log "Naruto Stage38A Persistent-30 - BC250"
    Log "Model is loaded ONCE and kept resident for all 30 requests."
    Log "Started: $(Get-Date)"
    Log ""

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    if (-not (Test-Path -LiteralPath $manifest)) {
        if (-not (Test-Path -LiteralPath $prepare)) {
            throw "prepare script 없음: $prepare"
        }

        Log "[1/4] 동일 30장 payload 생성"

        powershell.exe `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $prepare

        if ($LASTEXITCODE -ne 0) {
            throw "30장 payload 생성 실패"
        }
    }
    else {
        Log "[1/4] 기존 30장 payload 재사용"
    }

    foreach ($p in @($client,$remoteSh,$manifest)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $remote = $env:BC250_SSH

    if ([string]::IsNullOrWhiteSpace($remote)) {
        Write-Host ""
        $remote = Read-Host "BC250 SSH (예: user@192.168.0.123)"
    }

    $remote = "$remote".Trim()

    if ([string]::IsNullOrWhiteSpace($remote)) {
        throw "BC250 SSH 대상이 없습니다."
    }

    $ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
    $scp = Get-Command scp.exe -ErrorAction SilentlyContinue

    if (-not $ssh -or -not $scp) {
        throw "Windows OpenSSH ssh.exe/scp.exe가 필요합니다."
    }

    Log ""
    Log "[2/4] payload + client 전송"

    & $ssh.Source $remote "rm -rf ~/naruto_stage38a_persistent30 && mkdir -p ~/naruto_stage38a_persistent30"

    if ($LASTEXITCODE -ne 0) {
        throw "BC250 remote directory 준비 실패"
    }

    & $scp.Source `
        -r `
        $payload `
        "${remote}:~/naruto_stage38a_persistent30/"

    if ($LASTEXITCODE -ne 0) {
        throw "payload SCP 실패"
    }

    & $scp.Source `
        $client `
        "${remote}:~/naruto_stage38a_persistent30/stage38a_persistent30_client.py"

    if ($LASTEXITCODE -ne 0) {
        throw "client SCP 실패"
    }

    & $scp.Source `
        $remoteSh `
        "${remote}:~/naruto_stage38a_persistent30/run_bc250.sh"

    if ($LASTEXITCODE -ne 0) {
        throw "remote runner SCP 실패"
    }

    Log ""
    Log "[3/4] BC250 persistent server + 30장 OCR"

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & $ssh.Source `
        -tt `
        $remote `
        "chmod +x ~/naruto_stage38a_persistent30/run_bc250.sh && bash ~/naruto_stage38a_persistent30/run_bc250.sh" 2>&1 |
        ForEach-Object { Log "$_" }

    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($code -ne 0) {
        throw "BC250 persistent benchmark 실패 (exit=$code)"
    }

    Log ""
    Log "[4/4] 결과 회수 및 패키징"

    Remove-Item -LiteralPath $results -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $results | Out-Null

    $remoteZip = Join-Path $stage "persistent30_bc250_results.zip"
    Remove-Item $remoteZip -Force -ErrorAction SilentlyContinue

    & $scp.Source `
        "${remote}:~/naruto_stage38a_persistent30/results_bc250/persistent30_bc250_results.zip" `
        $remoteZip

    if ($LASTEXITCODE -ne 0) {
        throw "BC250 결과 ZIP SCP 실패"
    }

    Expand-Archive `
        -LiteralPath $remoteZip `
        -DestinationPath $results `
        -Force

    foreach ($name in @(
        "persistent30_results.tsv",
        "persistent30_summary.txt",
        "persistent30_summary.json"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $results $name))) {
            throw "결과 누락: $name"
        }
    }

    # Success-only logs.
    $archive = Join-Path $oldRoot (Get-Date -Format "yyyyMMdd_HHmmss")
    New-Item -ItemType Directory -Force -Path $archive | Out-Null

    Get-ChildItem -LiteralPath $logs -Force |
        Where-Object {
            $_.Name -ne "old" -and $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item $_.FullName -Destination $archive -Force
        }

    Get-ChildItem -LiteralPath $results -File |
        ForEach-Object {
            Copy-Item $_.FullName -Destination $logs -Force
        }

    Copy-Item $manifest -Destination $logs -Force
    Copy-Item $runLog -Destination $logs -Force

    @(
        "Naruto Stage38A Persistent-30 BC250"
        ""
        "One llama-server process, one model load, 30 sequential requests."
        "Part1 15 + Part2 15."
        ""
        "Upload:"
        " naruto_persistent30_bc250_upload.zip"
    ) | Set-Content `
        -LiteralPath (Join-Path $logs "README_UPLOAD.txt") `
        -Encoding UTF8

    $zip = Join-Path $logs "naruto_persistent30_bc250_upload.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object { $_.Name -ne "naruto_persistent30_bc250_upload.zip" } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " PERSISTENT-30 BC250 SUCCESS"
    Log "=========================================="
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
