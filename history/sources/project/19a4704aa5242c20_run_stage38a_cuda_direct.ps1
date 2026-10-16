$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_cuda"
$results = Join-Path $stage "results"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

$cli = Join-Path $stage "cuda_runtime\llama-cli.exe"
$model = Join-Path $stage "models\Qwen3-VL-2B-Instruct-Q8_0.gguf"
$mmproj = Join-Path $stage "models\mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf"

$payload = Join-Path $base "analysis\stage38a\naruto_stage38a_payload"
$manifest = Join-Path $payload "stage38a_manifest.tsv"
$bc250 = Join-Path $base "analysis\stage38a\bc250_results\stage38a_results.tsv"

$py = Join-Path $base "stage38a_cuda_compare_fix.py"

New-Item -ItemType Directory -Force -Path `
    $stage,$results,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage38a_cuda_direct_$stamp.log"

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
    Write-Host "STAGE 38A-CUDA DIRECT FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

try {
    Log "Naruto PSP Stage 38A-CUDA DIRECT"
    Log "RTX 3070 direct benchmark runner"
    Log "Started: $(Get-Date)"
    Log ""

    foreach ($p in @($cli,$model,$mmproj,$manifest,$bc250,$py)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    Log "[1/4] CUDA 장치 확인"

    $deviceText = & $cli --list-devices 2>&1 | Out-String
    Log $deviceText.Trim()

    if ($deviceText -notmatch "CUDA0") {
        throw "llama-cli가 CUDA0 장치를 찾지 못했습니다."
    }

    if ($deviceText -notmatch "3070") {
        Log "주의: 장치 문자열에서 3070을 찾지 못했습니다."
    }

    Log ""
    Log "[2/4] Python 벤치마크 스크립트 안전 옵션 확인"

    $text = Get-Content -LiteralPath $py -Raw

    if ($text -notmatch "--image-max-tokens") {
        $backup = "$py.bak_" + (Get-Date -Format "yyyyMMdd_HHmmss")
        Copy-Item -LiteralPath $py -Destination $backup -Force

        $old = '"-c", "4096",'
        $new = '"-c", "4096", "-b", "1024", "-ub", "1024", "--image-max-tokens", "512",'

        if (-not $text.Contains($old)) {
            throw "Python 스크립트에서 -c 4096 인수 위치를 찾지 못했습니다."
        }

        $text = $text.Replace($old, $new)

        Set-Content `
            -LiteralPath $py `
            -Value $text `
            -Encoding UTF8

        Log "안전 옵션 추가 완료:"
        Log "  -b 1024 -ub 1024 --image-max-tokens 512"
        Log "Backup: $backup"
    }
    else {
        Log "안전 옵션이 이미 들어 있습니다."
    }

    Log ""
    Log "[3/4] 120장 CUDA 벤치마크 실행"

    Remove-Item `
        -LiteralPath $results `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Force -Path $results | Out-Null

    & nvidia-smi.exe `
        --query-gpu=name,driver_version,memory.total,memory.used,memory.free `
        --format=csv,noheader |
        Set-Content `
            -LiteralPath (Join-Path $results "nvidia_smi_before.txt") `
            -Encoding UTF8

    $deviceText |
        Set-Content `
            -LiteralPath (Join-Path $results "llama_cuda_devices.txt") `
            -Encoding UTF8

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python `
        -u `
        $py `
        --binary $cli `
        --model $model `
        --mmproj $mmproj `
        --manifest $manifest `
        --payload-root $payload `
        --bc250-results $bc250 `
        --output-dir $results 2>&1 |
        ForEach-Object { Log "$_" }

    $benchCode = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($benchCode -ne 0) {
        throw "RTX 3070 120장 벤치마크 실패 (exit=$benchCode)"
    }

    Log ""
    Log "[4/4] 결과 검증 및 업로드 ZIP 생성"

    $required = @(
        "stage38a_cuda_results.tsv",
        "stage38a_cuda_compare.tsv",
        "stage38a_cuda_summary.txt",
        "stage38a_cuda_summary.json",
        "llama_cuda_devices.txt",
        "nvidia_smi_before.txt"
    )

    foreach ($name in $required) {
        $p = Join-Path $results $name
        if (-not (Test-Path -LiteralPath $p)) {
            throw "결과 파일 누락: $name"
        }
    }

    # Success-only: archive previous top-level log files.
    $archive = Join-Path $oldRoot (Get-Date -Format "yyyyMMdd_HHmmss")
    New-Item -ItemType Directory -Force -Path $archive | Out-Null

    Get-ChildItem -LiteralPath $logs -Force |
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

    $rawDir = Join-Path $results "raw_logs"
    if (Test-Path -LiteralPath $rawDir) {
        Compress-Archive `
            -Path (Join-Path $rawDir "*") `
            -DestinationPath (Join-Path $logs "stage38a_cuda_raw_logs.zip") `
            -CompressionLevel Optimal `
            -Force
    }

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    @(
        "Naruto PSP Stage 38A-CUDA DIRECT"
        "생성: $(Get-Date)"
        ""
        "Backend: llama.cpp CUDA"
        "Device: RTX 3070 Laptop"
        ""
        "Settings:"
        " -ngl 99"
        " -c 4096"
        " -b 1024"
        " -ub 1024"
        " --image-max-tokens 512"
        ""
        "Same 120 images / same model / same prompt as BC250 Stage38A."
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
    Log " STAGE 38A-CUDA DIRECT SUCCESS"
    Log "=========================================="
    Log "ChatGPT 업로드:"
    Log $zip
}
catch {
    Fail $_.Exception.Message
    throw
}
