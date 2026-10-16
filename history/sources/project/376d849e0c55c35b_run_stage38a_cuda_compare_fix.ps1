$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_cuda"
$tools = Join-Path $stage "llama_cuda"
$modelDir = Join-Path $stage "models"
$results = Join-Path $stage "results"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path `
    $stage,$tools,$modelDir,$results,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage38a_cuda_fix_$stamp.log"

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
        Copy-Item -LiteralPath $runLog -Destination $failDir -Force
    }

    Get-ChildItem -LiteralPath $results -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $failDir -Force
        }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 38A-CUDA FIX FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

function Download-Curl {
    param(
        [string]$Url,
        [string]$OutFile
    )

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue

    if (-not $curl) {
        throw "curl.exe를 찾지 못했습니다."
    }

    & $curl.Source `
        -L `
        --fail `
        --retry 5 `
        --retry-delay 3 `
        -C - `
        -o $OutFile `
        $Url

    if ($LASTEXITCODE -ne 0) {
        throw "다운로드 실패: $Url"
    }
}

function Find-MultimodalCli {
    param([string]$Root)

    $names = @(
        "llama-cli.exe",
        "llama-mtmd-cli.exe",
        "llama-qwen2vl-cli.exe"
    )

    foreach ($name in $names) {
        $items = @(
            Get-ChildItem `
                -LiteralPath $Root `
                -Recurse `
                -Filter $name `
                -File `
                -ErrorAction SilentlyContinue
        )

        foreach ($item in $items) {
            $helpFile = Join-Path $stage ("help_" + $item.Name + ".txt")

            $oldPref = $ErrorActionPreference
            $ErrorActionPreference = "Continue"

            & $item.FullName --help 2>&1 |
                Set-Content `
                    -LiteralPath $helpFile `
                    -Encoding UTF8

            $code = $LASTEXITCODE
            $ErrorActionPreference = $oldPref

            if ($code -ne 0) {
                continue
            }

            $help = Get-Content `
                -LiteralPath $helpFile `
                -Raw `
                -ErrorAction SilentlyContinue

            if (
                $help -match "--image" -and
                $help -match "--mmproj"
            ) {
                return $item.FullName
            }
        }
    }

    return $null
}

try {
    Log "Naruto PSP Stage 38A-CUDA FIX"
    Log "RTX 3070 CUDA comparison benchmark"
    Log "Fix: current llama.cpp Windows release may use llama-cli.exe"
    Log "Started: $(Get-Date)"

    # ========================================================
    # Inputs
    # ========================================================

    $payload = Join-Path `
        $base `
        "analysis\stage38a\naruto_stage38a_payload"

    $manifest = Join-Path $payload "stage38a_manifest.tsv"
    $images = Join-Path $payload "images"

    if (-not (Test-Path -LiteralPath $manifest)) {
        throw "Stage38A manifest 없음: $manifest"
    }

    if (-not (Test-Path -LiteralPath $images)) {
        throw "Stage38A images 없음: $images"
    }

    $bc250Result = Join-Path `
        $base `
        "analysis\stage38a\bc250_results\stage38a_results.tsv"

    if (-not (Test-Path -LiteralPath $bc250Result)) {
        $bc250Result = Get-ChildItem `
            -LiteralPath (Join-Path $base "logs") `
            -Recurse `
            -Filter "stage38a_results.tsv" `
            -File `
            -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }

    if ([string]::IsNullOrWhiteSpace($bc250Result) -or
        -not (Test-Path -LiteralPath $bc250Result)) {
        throw "BC250 Stage38A 결과 stage38a_results.tsv를 찾지 못했습니다."
    }

    # ========================================================
    # NVIDIA
    # ========================================================

    Log ""
    Log "[1/5] NVIDIA 확인"

    $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue

    if (-not $nvidiaSmi) {
        throw "nvidia-smi.exe를 찾지 못했습니다."
    }

    & $nvidiaSmi.Source `
        --query-gpu=name,driver_version,memory.total,memory.used `
        --format=csv,noheader |
        ForEach-Object { Log "$_" }

    # ========================================================
    # Official llama.cpp CUDA release
    # ========================================================

    Log ""
    Log "[2/5] llama.cpp Windows CUDA 바이너리 확인"

    $cli = Find-MultimodalCli -Root $tools

    if (-not $cli) {
        Log "기존 압축 해제본에서 multimodal CLI를 못 찾았습니다."
        Log "공식 최신 release를 다시 확인합니다."

        $api = "httpLOCAL_PATH"

        $releases = Invoke-RestMethod `
            -Uri $api `
            -Headers @{ "User-Agent" = "Naruto-Stage38A-CUDA-Fix" }

        $picked = $null
        $binAsset = $null
        $cudaAsset = $null

        foreach ($release in $releases) {
            $b = $release.assets |
                Where-Object {
                    $_.name -match "^llama-.*-bin-win-cuda-12\.4-x64\.zip$"
                } |
                Select-Object -First 1

            $c = $release.assets |
                Where-Object {
                    $_.name -match "^cudart-llama-bin-win-cuda-12\.4-x64\.zip$"
                } |
                Select-Object -First 1

            if ($b -and $c) {
                $picked = $release
                $binAsset = $b
                $cudaAsset = $c
                break
            }
        }

        if (-not $picked) {
            throw "CUDA 12.4 Windows x64 llama.cpp release asset을 찾지 못했습니다."
        }

        Log ("Release: " + $picked.tag_name)
        Log ("Binary asset: " + $binAsset.name)
        Log ("CUDA DLL asset: " + $cudaAsset.name)

        $binZip = Join-Path $stage $binAsset.name
        $cudaZip = Join-Path $stage $cudaAsset.name

        if (-not (Test-Path -LiteralPath $binZip)) {
            Download-Curl `
                -Url $binAsset.browser_download_url `
                -OutFile $binZip
        }

        if (-not (Test-Path -LiteralPath $cudaZip)) {
            Download-Curl `
                -Url $cudaAsset.browser_download_url `
                -OutFile $cudaZip
        }

        Remove-Item `
            -LiteralPath $tools `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue

        New-Item -ItemType Directory -Force -Path $tools | Out-Null

        $binExtract = Join-Path $stage "_bin_extract"
        $cudaExtract = Join-Path $stage "_cuda_extract"

        Remove-Item -LiteralPath $binExtract,$cudaExtract `
            -Recurse -Force -ErrorAction SilentlyContinue

        New-Item -ItemType Directory -Force -Path $binExtract,$cudaExtract | Out-Null

        Expand-Archive `
            -LiteralPath $binZip `
            -DestinationPath $binExtract `
            -Force

        Expand-Archive `
            -LiteralPath $cudaZip `
            -DestinationPath $cudaExtract `
            -Force

        # Flatten both archives into one runtime folder.
        Get-ChildItem -LiteralPath $binExtract -Recurse -File |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (Join-Path $tools $_.Name) `
                    -Force
            }

        Get-ChildItem -LiteralPath $cudaExtract -Recurse -File |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (Join-Path $tools $_.Name) `
                    -Force
            }

        @(
            "release=$($picked.tag_name)"
            "binary_asset=$($binAsset.name)"
            "cuda_asset=$($cudaAsset.name)"
        ) | Set-Content `
            -LiteralPath (Join-Path $tools "release_info.txt") `
            -Encoding UTF8

        $cli = Find-MultimodalCli -Root $tools
    }

    if (-not $cli) {
        $exeList = Get-ChildItem `
            -LiteralPath $tools `
            -Recurse `
            -Filter "*.exe" `
            -File `
            -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Name |
            Sort-Object -Unique

        $exeText = ($exeList -join ", ")

        throw @"
멀티모달 llama.cpp CLI를 찾지 못했습니다.
찾은 EXE:
$exeText
"@
    }

    Log "Multimodal CLI:"
    Log $cli

    # Current official llama-cli supports --image and --mmproj.
    $helpProbe = & $cli --help 2>&1 | Out-String

    if ($helpProbe -notmatch "--image" -or $helpProbe -notmatch "--mmproj") {
        throw "선택된 CLI가 --image/--mmproj를 지원하지 않습니다: $cli"
    }

    # ========================================================
    # Device check
    # ========================================================

    $deviceLog = Join-Path $stage "llama_cuda_devices_probe.txt"

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & $cli --list-devices 2>&1 |
        Set-Content `
            -LiteralPath $deviceLog `
            -Encoding UTF8

    $deviceCode = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($deviceCode -ne 0) {
        throw "llama CLI --list-devices 실패"
    }

    $deviceText = Get-Content -LiteralPath $deviceLog -Raw
    Log $deviceText

    if ($deviceText -notmatch "CUDA") {
        throw "llama.cpp 장치 목록에 CUDA가 없습니다."
    }

    # ========================================================
    # Model
    # ========================================================

    Log ""
    Log "[3/5] Qwen3-VL-2B-Instruct Q8_0 준비"

    $model = Join-Path $modelDir "Qwen3-VL-2B-Instruct-Q8_0.gguf"
    $mmproj = Join-Path $modelDir "mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf"

    $modelUrl = "httpLOCAL_PATH"
    $mmprojUrl = "httpLOCAL_PATH"

    if (-not (Test-Path -LiteralPath $model) -or
        (Get-Item $model).Length -lt 1500000000) {
        Download-Curl -Url $modelUrl -OutFile $model
    }
    else {
        Log "Model cache 재사용"
    }

    if (-not (Test-Path -LiteralPath $mmproj) -or
        (Get-Item $mmproj).Length -lt 300000000) {
        Download-Curl -Url $mmprojUrl -OutFile $mmproj
    }
    else {
        Log "mmproj cache 재사용"
    }

    # ========================================================
    # Same 120-image benchmark
    # ========================================================

    Log ""
    Log "[4/5] RTX 3070 CUDA 120장 벤치마크"

    $packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $batch = Join-Path $packageRoot "stage38a_cuda_compare_fix.py"

    if (-not (Test-Path -LiteralPath $batch)) {
        throw "Python 비교 스크립트 없음: $batch"
    }

    Remove-Item `
        -LiteralPath $results `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Force -Path $results | Out-Null

    Copy-Item `
        -LiteralPath $deviceLog `
        -Destination (Join-Path $results "llama_cuda_devices.txt") `
        -Force

    & $nvidiaSmi.Source `
        --query-gpu=name,driver_version,memory.total,memory.used `
        --format=csv,noheader |
        Set-Content `
            -LiteralPath (Join-Path $results "nvidia_smi_before.txt") `
            -Encoding UTF8

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python `
        -u `
        $batch `
        --binary $cli `
        --model $model `
        --mmproj $mmproj `
        --manifest $manifest `
        --payload-root $payload `
        --bc250-results $bc250Result `
        --output-dir $results 2>&1 |
        ForEach-Object { Log "$_" }

    $benchCode = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($benchCode -ne 0) {
        throw "RTX 3070 CUDA 벤치마크 실패"
    }

    # ========================================================
    # Results
    # ========================================================

    Log ""
    Log "[5/5] 결과 ZIP 준비"

    $required = @(
        "stage38a_cuda_results.tsv",
        "stage38a_cuda_compare.tsv",
        "stage38a_cuda_summary.txt",
        "stage38a_cuda_summary.json",
        "llama_cuda_devices.txt",
        "nvidia_smi_before.txt"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $results $name))) {
            throw "Stage38A-CUDA 결과 누락: $name"
        }
    }

    $archive = Join-Path `
        $oldRoot `
        (Get-Date -Format "yyyyMMdd_HHmmss")

    New-Item -ItemType Directory -Force -Path $archive | Out-Null

    Get-ChildItem -LiteralPath $logs -Force |
        Where-Object {
            $_.Name -ne "old" -and $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item `
                -LiteralPath $_.FullName `
                -Destination $archive `
                -Force
        }

    foreach ($name in $required) {
        Copy-Item `
            -LiteralPath (Join-Path $results $name) `
            -Destination $logs `
            -Force
    }

    $reviewDir = Join-Path $results "review_images"

    if (Test-Path -LiteralPath $reviewDir) {
        Compress-Archive `
            -Path (Join-Path $reviewDir "*") `
            -DestinationPath (Join-Path $logs "stage38a_cuda_review_images.zip") `
            -CompressionLevel Optimal `
            -Force
    }

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    @(
        "Naruto PSP Stage 38A-CUDA FIX"
        "생성: $(Get-Date)"
        ""
        "Fix:"
        " current llama.cpp release may ship multimodal support through llama-cli.exe"
        " selected CLI is verified by --help containing --image and --mmproj"
        ""
        "Same benchmark as BC250:"
        " same 120 images / same model / same prompt"
        ""
        "ChatGPT upload:"
        " naruto_stage38a_cuda_upload.zip"
        ""
        "Previous successful logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath (Join-Path $logs "README_UPLOAD.txt") `
        -Encoding UTF8

    $zip = Join-Path $logs "naruto_stage38a_cuda_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object {
            $_.Name -ne "naruto_stage38a_cuda_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 38A-CUDA FIX SUCCESS"
    Log "=========================================="
    Log "CLI:"
    Log $cli
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}

