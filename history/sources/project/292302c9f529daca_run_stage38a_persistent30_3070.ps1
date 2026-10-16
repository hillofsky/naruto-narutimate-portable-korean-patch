$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_persistent30"
$payload = Join-Path $stage "payload"
$manifest = Join-Path $payload "stage38a_persistent30_manifest.tsv"
$results = Join-Path $stage "results_3070"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$sourceStage = Join-Path $base "analysis\stage38a_cuda"
$runtime = Join-Path $sourceStage "cuda_runtime"
$server = Join-Path $runtime "llama-server.exe"
$model = Join-Path $sourceStage "models\Qwen3-VL-2B-Instruct-Q8_0.gguf"
$mmproj = Join-Path $sourceStage "models\mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf"

$prepare = Join-Path $base "prepare_stage38a_persistent30.ps1"
$client = Join-Path $base "stage38a_persistent30_client.py"

$port = 8091
$serverUrl = "httLOCAL_PATH"

New-Item -ItemType Directory -Force -Path `
    $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "persistent30_3070_$stamp.log"
$serverLog = Join-Path $stage "llama_server_3070_$stamp.log"
$serverErr = Join-Path $stage "llama_server_3070_${stamp}_stderr.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
}

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    foreach ($p in @($runLog,$serverLog,$serverErr)) {
        if (Test-Path -LiteralPath $p) {
            Copy-Item -LiteralPath $p -Destination $failDir -Force
        }
    }

    if (Test-Path -LiteralPath $results) {
        Get-ChildItem -LiteralPath $results -File -ErrorAction SilentlyContinue |
            ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
            }
    }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "PERSISTENT-30 RTX 3070 FAILED"
    Write-Host $Reason
    Write-Host "실패 로그: $failDir"
}

$serverProc = $null

try {
    Log "Naruto Stage38A Persistent-30 - RTX 3070"
    Log "Model is loaded ONCE and kept resident for all 30 requests."
    Log "Started: $(Get-Date)"
    Log ""

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

    if (-not (Test-Path -LiteralPath $manifest)) {
        if (-not (Test-Path -LiteralPath $prepare)) {
            throw "prepare script 없음: $prepare"
        }

        Log "[1/5] 동일 30장 payload 생성"
        powershell.exe `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $prepare

        if ($LASTEXITCODE -ne 0) {
            throw "30장 payload 생성 실패"
        }
    }
    else {
        Log "[1/5] 기존 30장 payload 재사용"
    }

    foreach ($p in @($client,$model,$mmproj)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    Log ""
    Log "[2/5] llama-server CUDA runtime 확인"

    if (-not (Test-Path -LiteralPath $server)) {
        $binZip = Get-ChildItem `
            -LiteralPath $sourceStage `
            -File `
            -Filter "*.zip" `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^llama-.*-bin-win-cuda-12\.4-x64\.zip$' -and
                $_.Name -notmatch '^cudart-'
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        $dllZip = Get-ChildItem `
            -LiteralPath $sourceStage `
            -File `
            -Filter "*.zip" `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^cudart-llama-bin-win-cuda-12\.4-x64\.zip$'
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if (-not $binZip -or -not $dllZip) {
            throw "llama-server.exe가 없고 기존 CUDA release ZIP도 찾지 못했습니다. Avast 격리 여부도 확인하세요."
        }

        $tmpBin = Join-Path $sourceStage "_persistent_server_bin"
        $tmpDll = Join-Path $sourceStage "_persistent_server_dll"

        Remove-Item $tmpBin,$tmpDll -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $runtime,$tmpBin,$tmpDll | Out-Null

        Expand-Archive -LiteralPath $binZip.FullName -DestinationPath $tmpBin -Force
        Expand-Archive -LiteralPath $dllZip.FullName -DestinationPath $tmpDll -Force

        Get-ChildItem $tmpBin -Recurse -File |
            ForEach-Object {
                Copy-Item $_.FullName (Join-Path $runtime $_.Name) -Force
            }

        Get-ChildItem $tmpDll -Recurse -File |
            ForEach-Object {
                Copy-Item $_.FullName (Join-Path $runtime $_.Name) -Force
            }
    }

    if (-not (Test-Path -LiteralPath $server)) {
        throw "llama-server.exe 없음: $server (Avast 격리 여부 확인)"
    }

    $help = & $server --help 2>&1 | Out-String

    if ($help -notmatch "--mmproj" -or $help -notmatch "--image-max-tokens") {
        throw "현재 llama-server가 필요한 multimodal 옵션을 지원하지 않습니다."
    }

    $dev = & (Join-Path $runtime "llama-cli.exe") --list-devices 2>&1 | Out-String
    Log $dev.Trim()

    if ($dev -notmatch "CUDA0") {
        throw "CUDA0 장치를 찾지 못했습니다."
    }

    Log ""
    Log "[3/5] llama-server 1회 시작"

    Remove-Item -LiteralPath $results -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $results | Out-Null

    $serverArgs = @(
        "-m", $model,
        "--mmproj", $mmproj,
        "-ngl", "99",
        "-c", "4096",
        "-b", "1024",
        "-ub", "1024",
        "--image-max-tokens", "512",
        "--host", "127.0.0.1",
        "--port", "$port",
        "--jinja"
    )

    $sw = [Diagnostics.Stopwatch]::StartNew()

    $serverProc = Start-Process `
        -FilePath $server `
        -ArgumentList $serverArgs `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError $serverErr `
        -PassThru `
        -WindowStyle Hidden

    $ready = $false

    for ($i = 0; $i -lt 240; $i++) {
        if ($serverProc.HasExited) {
            throw "llama-server가 준비 전에 종료되었습니다. stderr를 확인하세요."
        }

        try {
            $null = Invoke-RestMethod `
                -Uri "$serverUrl/v1/models" `
                -Method Get `
                -TimeoutSec 2

            $ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    $sw.Stop()

    if (-not $ready) {
        throw "llama-server 준비 timeout"
    }

    $startup = $sw.Elapsed.TotalSeconds
    Log ("Server ready: {0:N3} sec" -f $startup)

    Log ""
    Log "[4/5] 동일 30장 persistent HTTP OCR"

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python `
        -u `
        $client `
        --server-url $serverUrl `
        --manifest $manifest `
        --payload-root $payload `
        --output-dir $results `
        --backend "llama.cpp CUDA persistent server" `
        --device "RTX 3070 Laptop GPU" `
        --startup-seconds $startup `
        --nvidia-smi 2>&1 |
        ForEach-Object { Log "$_" }

    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($code -ne 0) {
        throw "Persistent-30 client 실패 (exit=$code)"
    }

    Log ""
    Log "[5/5] 결과 패키징"

    Copy-Item $serverLog,$serverErr -Destination $results -Force -ErrorAction SilentlyContinue

    $required = @(
        "persistent30_results.tsv",
        "persistent30_summary.txt",
        "persistent30_summary.json"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $results $name))) {
            throw "결과 누락: $name"
        }
    }

    if ($serverProc -and -not $serverProc.HasExited) {
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
        $serverProc = $null
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

    Copy-Item -LiteralPath $manifest -Destination $logs -Force
    Copy-Item -LiteralPath $runLog -Destination $logs -Force

    @(
        "Naruto Stage38A Persistent-30 RTX 3070"
        ""
        "One llama-server process, one model load, 30 sequential requests."
        "Part1 15 + Part2 15."
        ""
        "Upload:"
        " naruto_persistent30_3070_upload.zip"
    ) | Set-Content `
        -LiteralPath (Join-Path $logs "README_UPLOAD.txt") `
        -Encoding UTF8

    $zip = Join-Path $logs "naruto_persistent30_3070_upload.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object { $_.Name -ne "naruto_persistent30_3070_upload.zip" } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " PERSISTENT-30 RTX 3070 SUCCESS"
    Log "=========================================="
    Log $zip
}
catch {
    if ($serverProc -and -not $serverProc.HasExited) {
        Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue
    }

    Fail $_.Exception.Message
    throw
}
