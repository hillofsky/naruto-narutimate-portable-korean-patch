$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a"
$payloadDir = Join-Path $stage "naruto_stage38a_payload"
$resultsDir = Join-Path $stage "bc250_results"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path `
    $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage38a_$stamp.log"

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

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 38A FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "기존 성공 logs는 유지됩니다."
    Write-Host "실패 로그:"
    Write-Host $failDir
}

try {
    Log "Naruto PSP Stage 38A"
    Log "BC250 Vulkan VLM OCR benchmark"
    Log "Started: $(Get-Date)"

    $merged = Join-Path `
        $base `
        "analysis\stage37b\stage37b_merged.tsv"

    if (-not (Test-Path -LiteralPath $merged)) {
        throw "Stage37B merged TSV 없음: $merged"
    }

    $packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $linuxRunnerSource = Join-Path $packageRoot "run_stage38a_bc250.sh"
    $batchSource = Join-Path $packageRoot "stage38a_vlm_batch.py"

    foreach ($p in @($linuxRunnerSource,$batchSource)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "Stage38A 배포 파일 없음: $p"
        }
    }

    # ========================================================
    # [1/4] Build deterministic 60 + 60 sample payload
    # ========================================================

    Log ""
    Log "[1/4] 120개 OCR 벤치마크 샘플 준비"

    Remove-Item `
        -LiteralPath $payloadDir `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    $imagesDir = Join-Path $payloadDir "images"
    New-Item -ItemType Directory -Force -Path $imagesDir | Out-Null

    $rows = @(Import-Csv -LiteralPath $merged -Delimiter "`t")

    if ($rows.Count -eq 0) {
        throw "Stage37B merged TSV가 비어 있습니다."
    }

    $selected = New-Object System.Collections.Generic.List[object]

    foreach ($part in @("part1","part2")) {
        $group = @(
            $rows |
                Where-Object { $_.video_part -eq $part } |
                Sort-Object { [int]$_.part_index }
        )

        if ($group.Count -lt 60) {
            throw "$part 프레임 수가 60개 미만입니다: $($group.Count)"
        }

        $used = @{}

        for ($i = 0; $i -lt 60; $i++) {
            $idx = [int][math]::Round(
                $i * ($group.Count - 1) / 59.0
            )

            # Round collisions are unlikely here, but make selection robust.
            while ($used.ContainsKey($idx) -and $idx + 1 -lt $group.Count) {
                $idx++
            }

            if ($used.ContainsKey($idx)) {
                $idx = 0
                while ($used.ContainsKey($idx) -and $idx -lt $group.Count) {
                    $idx++
                }
            }

            if ($idx -ge $group.Count) {
                throw "$part 샘플 인덱스 계산 실패"
            }

            $used[$idx] = $true
            $row = $group[$idx]

            if (-not (Test-Path -LiteralPath $row.crop_file)) {
                throw "crop 파일 없음: $($row.crop_file)"
            }

            $sampleNumber = $selected.Count + 1
            $ext = [IO.Path]::GetExtension($row.crop_file)

            if ([string]::IsNullOrWhiteSpace($ext)) {
                $ext = ".jpg"
            }

            $safeName = "{0:D3}_{1}_p{2}_g{3}{4}" -f `
                $sampleNumber, `
                $part, `
                ([int]$row.part_index), `
                ([int]$row.global_index), `
                $ext.ToLower()

            $dst = Join-Path $imagesDir $safeName

            Copy-Item `
                -LiteralPath $row.crop_file `
                -Destination $dst `
                -Force

            $selected.Add([pscustomobject]@{
                sample_index       = $sampleNumber
                video_part         = $part
                part_index         = [int]$row.part_index
                global_index       = [int]$row.global_index
                timestamp_seconds  = $row.timestamp_seconds
                timestamp          = $row.timestamp
                image_file         = "images/$safeName"
                original_crop_file = $row.crop_file
            })
        }

        Log "$part : $($group.Count)개 중 60개 선택"
    }

    if ($selected.Count -ne 120) {
        throw "Stage38A 샘플 개수 오류: $($selected.Count)"
    }

    $manifest = Join-Path $payloadDir "stage38a_manifest.tsv"

    $selected |
        Export-Csv `
            -LiteralPath $manifest `
            -Delimiter "`t" `
            -NoTypeInformation `
            -Encoding UTF8

    Copy-Item `
        -LiteralPath $linuxRunnerSource `
        -Destination (Join-Path $payloadDir "run_stage38a_bc250.sh") `
        -Force

    Copy-Item `
        -LiteralPath $batchSource `
        -Destination (Join-Path $payloadDir "stage38a_vlm_batch.py") `
        -Force

    @(
        "Naruto PSP Stage38A BC250 payload"
        "=================================="
        ""
        "Samples: 120"
        " Part1: 60"
        " Part2: 60"
        ""
        "Model:"
        " ggml-org/Qwen3-VL-2B-Instruct-GGUF Q8_0"
        ""
        "Backend:"
        " llama.cpp Vulkan"
        " ROCm/PyTorch not used"
        ""
        "The Linux runner installs only build/Vulkan utilities when needed."
    ) | Set-Content `
        -LiteralPath (Join-Path $payloadDir "README.txt") `
        -Encoding UTF8

    Log "Payload: $payloadDir"

    # ========================================================
    # [2/4] Remote target
    # ========================================================

    Log ""
    Log "[2/4] BC250 SSH 대상 확인"

    $remote = $env:BC250_SSH

    if ([string]::IsNullOrWhiteSpace($remote)) {
        Write-Host ""
        Write-Host "BC250 SSH 대상을 입력하세요."
        Write-Host "예: user@192.168.0.123"
        Write-Host ""
        $remote = Read-Host "BC250 SSH"
    }

    $remote = "$remote".Trim()

    if ([string]::IsNullOrWhiteSpace($remote)) {
        throw "BC250 SSH 대상이 입력되지 않았습니다."
    }

    $ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
    $scp = Get-Command scp.exe -ErrorAction SilentlyContinue

    if (-not $ssh) {
        throw "Windows OpenSSH ssh.exe를 찾지 못했습니다."
    }

    if (-not $scp) {
        throw "Windows OpenSSH scp.exe를 찾지 못했습니다."
    }

    Log "Remote: $remote"

    # Delete only transient payload; keep ~/naruto_stage38a_cache
    # so llama.cpp/model downloads are reused on reruns.
    & $ssh.Source `
        $remote `
        "rm -rf ~/naruto_stage38a_payload"

    if ($LASTEXITCODE -ne 0) {
        throw "BC250 원격 준비 실패"
    }

    Log ""
    Log "Payload 전송 중..."

    & $scp.Source `
        -r `
        $payloadDir `
        "${remote}:~/"

    if ($LASTEXITCODE -ne 0) {
        throw "BC250 payload SCP 실패"
    }

    # ========================================================
    # [3/4] Run on BC250
    # ========================================================

    Log ""
    Log "[3/4] BC250 Vulkan VLM OCR 실행"
    Log "첫 실행은 llama.cpp 빌드 + 약 2.3GB 모델 다운로드가 있습니다."
    Log "재실행 시 cache를 재사용합니다."
    Log ""

    $remoteCmd = @'
chmod +x ~/naruto_stage38a_payload/run_stage38a_bc250.sh &&
bash ~/naruto_stage38a_payload/run_stage38a_bc250.sh
'@

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & $ssh.Source `
        -tt `
        $remote `
        $remoteCmd 2>&1 |
        ForEach-Object { Log "$_" }

    $remoteCode = $LASTEXITCODE
    $ErrorActionPreference = $oldPref

    if ($remoteCode -ne 0) {
        # Best-effort remote log retrieval without touching prior success logs.
        $remoteFailDir = Join-Path $stage "remote_failure_$stamp"
        New-Item -ItemType Directory -Force -Path $remoteFailDir | Out-Null

        & $scp.Source `
            "${remote}:~/naruto_stage38a_payload/results/stage38a_remote.log" `
            $remoteFailDir 2>$null

        throw "BC250 Stage38A 실행 실패 (exit=$remoteCode)"
    }

    # ========================================================
    # [4/4] Pull results and create upload ZIP
    # ========================================================

    Log ""
    Log "[4/4] BC250 결과 회수"

    Remove-Item `
        -LiteralPath $resultsDir `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null

    $remoteZipLocal = Join-Path $stage "stage38a_results.zip"

    Remove-Item `
        -LiteralPath $remoteZipLocal `
        -Force `
        -ErrorAction SilentlyContinue

    & $scp.Source `
        "${remote}:~/naruto_stage38a_payload/results/stage38a_results.zip" `
        $remoteZipLocal

    if ($LASTEXITCODE -ne 0) {
        throw "BC250 결과 ZIP SCP 실패"
    }

    Expand-Archive `
        -LiteralPath $remoteZipLocal `
        -DestinationPath $resultsDir `
        -Force

    $required = @(
        "stage38a_results.tsv",
        "stage38a_summary.txt",
        "stage38a_summary.json",
        "vulkaninfo_summary.txt",
        "llama_devices.txt",
        "llama_commit.txt",
        "model_sha256.txt"
    )

    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $resultsDir $name))) {
            throw "Stage38A 결과 누락: $name"
        }
    }

    # Success only: archive previous top-level logs.
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
            -LiteralPath (Join-Path $resultsDir $name) `
            -Destination $logs `
            -Force
    }

    $reviewDir = Join-Path $resultsDir "review_images"

    if (Test-Path -LiteralPath $reviewDir) {
        $reviewZip = Join-Path $logs "stage38a_review_images.zip"

        Compress-Archive `
            -Path (Join-Path $reviewDir "*") `
            -DestinationPath $reviewZip `
            -CompressionLevel Optimal `
            -Force
    }

    $rawDir = Join-Path $resultsDir "raw_logs"

    if (Test-Path -LiteralPath $rawDir) {
        $rawZip = Join-Path $logs "stage38a_raw_logs.zip"

        Compress-Archive `
            -Path (Join-Path $rawDir "*") `
            -DestinationPath $rawZip `
            -CompressionLevel Optimal `
            -Force
    }

    Copy-Item `
        -LiteralPath $manifest `
        -Destination $logs `
        -Force

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 38A"
        "생성: $(Get-Date)"
        ""
        "STATUS: BC250_VULKAN_VLM_BENCHMARK_COMPLETE"
        ""
        "Backend:"
        " llama.cpp Vulkan"
        " ROCm/PyTorch: NOT USED"
        ""
        "Model:"
        " Qwen3-VL-2B-Instruct Q8_0"
        ""
        "Samples:"
        " Part1 60 + Part2 60 = 120"
        ""
        "ChatGPT upload:"
        " naruto_stage38a_upload.zip"
        ""
        "Previous successful logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $uploadZip = Join-Path $logs "naruto_stage38a_upload.zip"

    Remove-Item `
        -LiteralPath $uploadZip `
        -Force `
        -ErrorAction SilentlyContinue

    $inputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage38a_upload.zip"
        } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $inputs `
        -DestinationPath $uploadZip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 38A SUCCESS"
    Log "=========================================="
    Log "ROCm: 사용 안 함"
    Log "Backend: Vulkan"
    Log "ChatGPT 업로드:"
    Log $uploadZip
}
catch {
    Fail $_.Exception.Message
    throw
}
