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
$runLog = Join-Path $stage "naruto_stage38a_cuda_$stamp.log"

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
    Write-Host "STAGE 38A-CUDA FAILED"
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

try {
    Log "Naruto PSP Stage 38A-CUDA"
    Log "RTX 3070 CUDA comparison benchmark"
    Log "Started: $(Get-Date)"

    # ========================================================
    # Inputs from the finished BC250 Stage38A run
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
            -LiteralPath $logs `
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

    Log ""
    Log "Payload:"
    Log $payload
    Log "BC250 result:"
    Log $bc250Result

    # ========================================================
    # NVIDIA check
    # ========================================================

    Log ""
    Log "[1/5] NVIDIA / CUDA 확인"

    $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue

    if (-not $nvidiaSmi) {
        throw "nvidia-smi.exe를 찾지 못했습니다. NVIDIA 드라이버를 확인하세요."
    }

    & $nvidiaSmi.Source `
        --query-gpu=name,driver_version,memory.total,memory.used `
        --format=csv,noheader |
        ForEach-Object { Log "$_" }

    # ========================================================
    # Download official llama.cpp CUDA 12.4 binaries
    # ========================================================

    Log ""
    Log "[2/5] llama.cpp 공식 Windows CUDA 바이너리 준비"

    $mtmd = Join-Path $tools "llama-mtmd-cli.exe"

    if (-not (Test-Path -LiteralPath $mtmd)) {
        $api = "httpLOCAL_PATH"

        Log "GitHub release metadata 조회..."

        $releases = Invoke-RestMethod `
            -Uri $api `
            -Headers @{ "User-Agent" = "Naruto-Stage38A-CUDA" }

        $picked = $null
        $binAsset = $null
        $cudaAsset = $null

        foreach ($release in $releases) {
            $b = $release.assets |
                Where-Object {
                    $_.name -match "bin-win-cuda-12\.4-x64\.zip$"
                } |
                Select-Object -First 1

            $c = $release.assets |
                Where-Object {
                    $_.name -match "^cudart-.*bin-win-cuda-12\.4-x64\.zip$"
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
        Log ("Binary:  " + $binAsset.name)
        Log ("CUDA DLL: " + $cudaAsset.name)

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

        Expand-Archive `
            -LiteralPath $binZip `
            -DestinationPath $tools `
            -Force

        Expand-Archive `
            -LiteralPath $cudaZip `
            -DestinationPath $tools `
            -Force

        $mtmdFound = Get-ChildItem `
            -LiteralPath $tools `
            -Recurse `
            -Filter "llama-mtmd-cli.exe" `
            -File |
            Select-Object -First 1

        if (-not $mtmdFound) {
            throw "압축 해제 후 llama-mtmd-cli.exe를 찾지 못했습니다."
        }

        if ($mtmdFound.DirectoryName -ne $tools) {
            Get-ChildItem `
                -LiteralPath $mtmdFound.DirectoryName `
                -File |
                ForEach-Object {
                    Copy-Item `
                        -LiteralPath $_.FullName `
                        -Destination $tools `
                        -Force
                }
        }

        @(
            "release=$($picked.tag_name)"
            "binary_asset=$($binAsset.name)"
            "cuda_asset=$($cudaAsset.name)"
        ) | Set-Content `
            -LiteralPath (Join-Path $tools "release_info.txt") `
            -Encoding UTF8
    }

    if (-not (Test-Path -LiteralPath $mtmd)) {
        throw "llama-mtmd-cli.exe 없음: $mtmd"
    }

    Log "llama-mtmd-cli:"
    Log $mtmd

    $deviceLog = Join-Path $results "llama_cuda_devices.txt"

    & $mtmd --list-devices 2>&1 |
        Tee-Object -FilePath $deviceLog |
        ForEach-Object { Write-Host $_ }

    if ($LASTEXITCODE -ne 0) {
        throw "llama-mtmd-cli --list-devices 실패"
    }

    $deviceText = Get-Content `
        -LiteralPath $deviceLog `
        -Raw `
        -ErrorAction SilentlyContinue

    if ($deviceText -notmatch "CUDA") {
        throw "llama.cpp가 CUDA 장치를 표시하지 않았습니다."
    }

    if ($deviceText -notmatch "3070") {
        Log "주의: 장치 출력에서 '3070' 문자열을 찾지 못했습니다."
    }

    # ========================================================
    # Model
    # ========================================================

    Log ""
    Log "[3/5] Qwen3-VL-2B-Instruct Q8_0 모델 준비"

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
    # Run exact same 120 images / prompt
    # ========================================================

    Log ""
    Log "[4/5] RTX 3070 CUDA 120장 벤치마크"
    Log "BC250과 동일한 120장, 동일한 Qwen3-VL 2B Q8, 동일한 프롬프트를 사용합니다."

    $packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $batch = Join-Path $packageRoot "stage38a_cuda_compare.py"

    if (-not (Test-Path -LiteralPath $batch)) {
        throw "stage38a_cuda_compare.py 없음: $batch"
    }

    Remove-Item `
        -LiteralPath $results `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Force -Path $results | Out-Null

    # Re-create device report after results dir reset.
    & $mtmd --list-devices 2>&1 |
        Set-Content `
            -LiteralPath (Join-Path $results "llama_cuda_devices.txt") `
            -Encoding UTF8

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
        --binary $mtmd `
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
    # Results / upload
    # ========================================================

    Log ""
    Log "[5/5] 결과 검증 및 업로드 ZIP"

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

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $archive |
        Out-Null

    Get-ChildItem `
        -LiteralPath $logs `
        -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
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
        "Naruto PSP Stage 38A-CUDA"
        "생성: $(Get-Date)"
        ""
        "RTX 3070 Laptop CUDA comparison"
        ""
        "Same as BC250 Stage38A:"
        " - same 120 images"
        " - same Qwen3-VL-2B-Instruct Q8_0"
        " - same mmproj"
        " - same OCR prompt"
        " - n_gpu_layers = 99"
        ""
        "Main files:"
        " stage38a_cuda_summary.txt"
        " stage38a_cuda_results.tsv"
        " stage38a_cuda_compare.tsv"
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

    $inputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
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
    Log " STAGE 38A-CUDA SUCCESS"
    Log "=========================================="
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
