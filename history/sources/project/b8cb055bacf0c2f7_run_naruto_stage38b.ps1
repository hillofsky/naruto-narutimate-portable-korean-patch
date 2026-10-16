# Naruto PSP Stage 38B
# RTX 3070 CUDA / Qwen3-VL single-image smoke test
# Console output + full transcript + failure preservation + upload ZIP

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root       = "PROJECT_ROOT"
$StageName  = "stage38b"
$StageDir   = Join-Path $Root "analysis\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"

$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript = Join-Path $LogsDir "naruto_stage38b_$Stamp.log"
$RunLog     = Join-Path $StageDir "llama_cli_output_$Stamp.log"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$CommandTxt = Join-Path $StageDir "COMMAND.txt"
$EnvTxt     = Join-Path $StageDir "ENVIRONMENT.txt"
$VersionTxt = Join-Path $StageDir "LLAMA_VERSION.txt"
$GpuBefore  = Join-Path $StageDir "NVIDIA_BEFORE.txt"
$GpuAfter   = Join-Path $StageDir "NVIDIA_AFTER.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38b_upload.zip"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host (" " + $Text)
    Write-Host ("=" * 72)
}

function Find-FirstFile {
    param(
        [string[]]$Roots,
        [string]$Filter,
        [scriptblock]$Predicate = $null
    )
    foreach ($r in $Roots) {
        if (-not (Test-Path $r)) { continue }
        $items = Get-ChildItem -Path $r -Filter $Filter -File -Recurse -ErrorAction SilentlyContinue
        if ($Predicate) {
            $items = $items | Where-Object $Predicate
        }
        $hit = $items | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$Succeeded = $false
$ExitCode = $null
$Elapsed = $null
$Llama = $null
$Model = $null
$Mmproj = $null
$Image = $null
$Caught = $null

Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto PSP Stage 38B - RTX 3070 Qwen3-VL smoke test"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Root    : $Root"
    Write-Host "Stage   : $StageDir"

    Write-Section "1/6 - Required files"

    $explicitLlama = Join-Path $Root "analysis\stage38a_cuda\cuda_runtime\llama-cli.exe"
    if (Test-Path $explicitLlama) {
        $Llama = $explicitLlama
    } else {
        $Llama = Find-FirstFile `
            -Roots @(
                (Join-Path $Root "analysis\stage38a_cuda"),
                (Join-Path $Root "analysis")
            ) `
            -Filter "llama-cli.exe"
    }

    $searchRoots = @(
        (Join-Path $Root "analysis\stage38a_cuda"),
        (Join-Path $Root "models"),
        (Join-Path $Root "analysis\stage38"),
        (Join-Path $Root "analysis")
    )

    $Model = Find-FirstFile `
        -Roots $searchRoots `
        -Filter "*Qwen3*VL*2B*Q8_0*.gguf" `
        -Predicate { $_.Name -notmatch '^mmproj' }

    if (-not $Model) {
        $Model = Find-FirstFile `
            -Roots $searchRoots `
            -Filter "*Qwen3*VL*2B*.gguf" `
            -Predicate { $_.Name -notmatch '^mmproj' }
    }

    $Mmproj = Find-FirstFile `
        -Roots $searchRoots `
        -Filter "mmproj*Qwen3*VL*2B*.gguf"

    $explicitImage = Join-Path $Root "analysis\stage38a\naruto_stage38a_payload\images\001_part1_p1_g1.jpg"
    if (Test-Path $explicitImage) {
        $Image = $explicitImage
    } else {
        $Image = Find-FirstFile `
            -Roots @((Join-Path $Root "analysis")) `
            -Filter "001_part1_p1_g1.jpg"
    }

    foreach ($item in @(
        @{Name="llama-cli"; Path=$Llama},
        @{Name="model";     Path=$Model},
        @{Name="mmproj";    Path=$Mmproj},
        @{Name="image";     Path=$Image}
    )) {
        if (-not $item.Path -or -not (Test-Path $item.Path)) {
            throw "필수 파일을 찾지 못했습니다: $($item.Name)"
        }
        $fi = Get-Item $item.Path
        Write-Host ("{0,-10}: {1}" -f $item.Name, $fi.FullName)
        Write-Host ("{0,-10}  {1:N0} bytes" -f "", $fi.Length)
    }

    Write-Section "2/6 - NVIDIA / environment"

    $envLines = @(
        "Timestamp=$Stamp",
        "ComputerName=$env:COMPUTERNAME",
        "UserName=$env:USERNAME",
        "PowerShell=$($PSVersionTable.PSVersion)",
        "OS=$([Environment]::OSVersion.VersionString)",
        "LLAMA=$Llama",
        "MODEL=$Model",
        "MMPROJ=$Mmproj",
        "IMAGE=$Image"
    )
    $envLines | Set-Content -Path $EnvTxt -Encoding UTF8
    $envLines | ForEach-Object { Write-Host $_ }

    try {
        & nvidia-smi | Tee-Object -FilePath $GpuBefore
        if ($LASTEXITCODE -ne 0) {
            throw "nvidia-smi exit code: $LASTEXITCODE"
        }
    } catch {
        $_ | Out-String | Set-Content -Path $GpuBefore -Encoding UTF8
        throw "nvidia-smi 실행 실패: $($_.Exception.Message)"
    }

    Write-Section "3/6 - llama.cpp version / device check"

    & $Llama --version 2>&1 | Tee-Object -FilePath $VersionTxt
    $versionExit = $LASTEXITCODE
    Write-Host "llama-cli --version exit code: $versionExit"

    $deviceTxt = Join-Path $StageDir "LLAMA_DEVICES.txt"
    & $Llama --list-devices 2>&1 | Tee-Object -FilePath $deviceTxt
    $deviceExit = $LASTEXITCODE
    Write-Host "llama-cli --list-devices exit code: $deviceExit"

    Write-Section "4/6 - Stage 38B command"

    # Stage 38B is a stability/diagnostic run, not the final speed benchmark.
    # Keep the language model on CUDA, but keep mmproj on CPU first.
    $Prompt = "Transcribe all visible Korean dialogue and speaker names exactly. Output only the recognized text. Do not explain, translate, or infer missing text."

    $CliArgs = @(
        "-m", $Model,
        "--mmproj", $Mmproj,
        "--image", $Image,
        "-p", $Prompt,
        "-ngl", "99",
        "-c", "2048",
        "-b", "512",
        "-ub", "512",
        "--image-max-tokens", "512",
        "--no-mmproj-offload",
        "--temp", "0",
        "-n", "128"
    )

    $quotedArgs = foreach ($a in $CliArgs) {
        if ($a -match '\s') { '"' + $a.Replace('"','\"') + '"' } else { $a }
    }
    $commandLine = '"' + $Llama + '" ' + ($quotedArgs -join ' ')
    $commandLine | Set-Content -Path $CommandTxt -Encoding UTF8
    Write-Host $commandLine
    Write-Host ""
    Write-Host "NOTE: mmproj GPU offload is disabled for this first smoke test."

    Write-Section "5/6 - OCR smoke test"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & $Llama @CliArgs 2>&1 | Tee-Object -FilePath $RunLog
    $ExitCode = $LASTEXITCODE
    $sw.Stop()
    $Elapsed = $sw.Elapsed.TotalSeconds

    Write-Host ""
    Write-Host ("llama-cli exit code : {0}" -f $ExitCode)
    Write-Host ("elapsed              : {0:N3} sec" -f $Elapsed)

    try {
        & nvidia-smi | Tee-Object -FilePath $GpuAfter
    } catch {
        $_ | Out-String | Set-Content -Path $GpuAfter -Encoding UTF8
    }

    if ($ExitCode -ne 0) {
        throw "llama-cli가 비정상 종료했습니다. Exit code=$ExitCode"
    }

    if (-not (Test-Path $RunLog) -or (Get-Item $RunLog).Length -eq 0) {
        throw "llama-cli 출력 로그가 비어 있습니다."
    }

    $Succeeded = $true

} catch {
    $Caught = $_
    $Succeeded = $false

    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38B FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)

    $failureLines = @(
        "Naruto PSP Stage 38B FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "ExitCode: $ExitCode",
        "ElapsedSeconds: $Elapsed",
        "",
        "Message:",
        $_.Exception.Message,
        "",
        "Full error:",
        ($_ | Out-String)
    )
    $failureLines | Set-Content -Path $FailureTxt -Encoding UTF8

} finally {
    Write-Section "6/6 - Finalize"

    $summaryLines = @(
        "Naruto PSP Stage 38B",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: $(if ($Succeeded) {'SUCCESS'} else {'FAILED'})",
        "ExitCode: $ExitCode",
        "ElapsedSeconds: $(if ($null -ne $Elapsed) { '{0:N3}' -f $Elapsed } else { 'N/A' })",
        "",
        "Goal:",
        "RTX 3070에서 Qwen3-VL 단일 이미지 OCR을 끝까지 실행하는 smoke test.",
        "",
        "Configuration:",
        "n_gpu_layers=99",
        "ctx=2048",
        "batch=512",
        "ubatch=512",
        "image_max_tokens=512",
        "mmproj_offload=OFF",
        "",
        "LLAMA=$Llama",
        "MODEL=$Model",
        "MMPROJ=$Mmproj",
        "IMAGE=$Image",
        "",
        "Transcript=$Transcript",
        "CLI_Output=$RunLog"
    )

    if ($Caught) {
        $summaryLines += ""
        $summaryLines += "Failure=$($Caught.Exception.Message)"
    }

    $summaryLines | Set-Content -Path $Summary -Encoding UTF8

    try { Stop-Transcript | Out-Null } catch {}

    # Build compact upload package. Never include GGUF files.
    $PackageDir = Join-Path $StageDir "_upload_package"
    if (Test-Path $PackageDir) {
        Remove-Item $PackageDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

    $filesToPack = @(
        $Summary,
        $CommandTxt,
        $EnvTxt,
        $VersionTxt,
        $GpuBefore,
        $GpuAfter,
        $RunLog,
        $Transcript,
        (Join-Path $StageDir "LLAMA_DEVICES.txt"),
        $FailureTxt
    )

    foreach ($f in $filesToPack) {
        if ($f -and (Test-Path $f)) {
            Copy-Item $f -Destination $PackageDir -Force
        }
    }

    # Include the single test frame because it is small and useful for OCR review.
    if ($Image -and (Test-Path $Image)) {
        Copy-Item $Image -Destination $PackageDir -Force
    }

    # Include this script itself when it was executed from a saved .ps1 file.
    if ($PSCommandPath -and (Test-Path $PSCommandPath)) {
        Copy-Item $PSCommandPath -Destination $PackageDir -Force
    }

    if ($Succeeded) {
        # Preserve an older normal upload ZIP instead of silently losing it.
        if (Test-Path $UploadZip) {
            $oldDir = Join-Path $OldRoot $Stamp
            New-Item -ItemType Directory -Force -Path $oldDir | Out-Null
            Copy-Item $UploadZip -Destination (Join-Path $oldDir "naruto_stage38b_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "STAGE 38B SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }
    else {
        $failedDir = Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null

        foreach ($f in (Get-ChildItem $PackageDir -File -ErrorAction SilentlyContinue)) {
            Copy-Item $f.FullName -Destination $failedDir -Force
        }

        $failedZip = Join-Path $failedDir "naruto_stage38b_failed_upload.zip"
        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $failedZip -Force

        Write-Host ""
        Write-Host "STAGE 38B FAILED"
        Write-Host "정상 업로드 ZIP은 갱신하지 않았습니다."
        Write-Host "실패 자료:"
        Write-Host "  $failedDir"
        Write-Host "실패 진단 ZIP:"
        Write-Host "  $failedZip"
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Succeeded) {
    exit 1
}
exit 0
