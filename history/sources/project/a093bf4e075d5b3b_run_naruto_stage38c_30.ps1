# Naruto PSP Stage 38C
# RTX 3070 vs BC250 - 30 image apples-to-apples OCR benchmark
# BC250-equivalent conditions:
#   Qwen3-VL-2B-Instruct Q8_0 + same mmproj
#   Part1 15 + Part2 15 evenly sampled from Stage38A 120-image payload
#   llama.cpp server loaded ONCE, then 30 sequential requests
#   -ngl 99 -b 1024 -ub 1024 --image-max-tokens 512
#   mmproj GPU offload ON (do NOT use --no-mmproj-offload)
#   same OCR prompt / temp 0 / max_tokens 128
# Output: live console + CSV + full log + summary + automatic ZIP

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

# UTF-8 for Korean output on Windows PowerShell 5.1
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "stage38c_30"
$StageDir   = Join-Path $Root "analysis\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_stage38c_30_$Stamp.log"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$CsvPath    = Join-Path $StageDir "ocr_30_results.csv"
$Manifest   = Join-Path $StageDir "sample_30_manifest.csv"
$ServerLog  = Join-Path $StageDir "llama_server_$Stamp.log"
$ServerErr  = Join-Path $StageDir "llama_server_$Stamp.err.log"
$EnvTxt     = Join-Path $StageDir "ENVIRONMENT.txt"
$CmdTxt     = Join-Path $StageDir "SERVER_COMMAND.txt"
$GpuBefore  = Join-Path $StageDir "NVIDIA_BEFORE.txt"
$GpuAfter   = Join-Path $StageDir "NVIDIA_AFTER.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38c_30_upload.zip"

$Port = 8093
$BaseUrl = "httLOCAL_PATH"
$BC250Mean = 3.487

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 76)
    Write-Host (" " + $Text)
    Write-Host ("=" * 76)
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

function Select-Evenly {
    param(
        [Parameter(Mandatory=$true)][object[]]$Items,
        [Parameter(Mandatory=$true)][int]$Count
    )
    if ($Items.Count -lt $Count) {
        throw "균등 샘플에 필요한 파일 수가 부족합니다. 필요=$Count, 발견=$($Items.Count)"
    }
    if ($Count -eq 1) { return @($Items[0]) }

    $selected = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $idx = [int][Math]::Round($i * ($Items.Count - 1) / ($Count - 1))
        $selected += $Items[$idx]
    }
    return $selected
}

function Get-Percentile {
    param(
        [double[]]$Values,
        [double]$P
    )
    if (-not $Values -or $Values.Count -eq 0) { return [double]::NaN }
    $s = @($Values | Sort-Object)
    if ($s.Count -eq 1) { return [double]$s[0] }
    $rank = ($P / 100.0) * ($s.Count - 1)
    $lo = [int][Math]::Floor($rank)
    $hi = [int][Math]::Ceiling($rank)
    if ($lo -eq $hi) { return [double]$s[$lo] }
    $w = $rank - $lo
    return ([double]$s[$lo] * (1.0 - $w)) + ([double]$s[$hi] * $w)
}

function Save-NvidiaSmi([string]$Path) {
    $nvsmi = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if (-not $nvsmi) { $nvsmi = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue }
    if (-not $nvsmi) {
        "nvidia-smi not found" | Set-Content $Path -Encoding UTF8
        return
    }
    # cmd handles native stderr safely under PS 5.1
    $cmd = '"' + $nvsmi.Source + '" 2>&1'
    & $env:ComSpec /d /s /c $cmd | ForEach-Object {
        $line = [string]$_
        Write-Host $line
        $line | Out-File -FilePath $Path -Append -Encoding utf8
    }
}

$Succeeded = $false
$ServerProc = $null
$Caught = $null
$Model = $null
$Mmproj = $null
$ServerExe = $null
$PayloadDir = $null
$Results = @()

Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto PSP Stage 38C - BC250-equivalent 30-image RTX 3070 benchmark"
    Write-Host "Started  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Baseline : BC250 mean = $BC250Mean sec/image"
    Write-Host "Sampling : Part1 15 + Part2 15, evenly distributed"

    Write-Section "1/7 - Locate runtime, model, mmproj, and Stage38A images"

    $runtimeRoots = @(
        (Join-Path $Root "analysis\stage38a_cuda\cuda_runtime"),
        (Join-Path $Root "analysis\stage38a_cuda"),
        (Join-Path $Root "analysis")
    )

    $ServerExe = Find-FirstFile -Roots $runtimeRoots -Filter "llama-server.exe"
    if (-not $ServerExe) {
        throw "llama-server.exe를 찾지 못했습니다. Stage38A CUDA runtime에 llama-server.exe가 필요합니다."
    }

    $modelRoots = @(
        (Join-Path $Root "analysis\stage38a_cuda\models"),
        (Join-Path $Root "models"),
        (Join-Path $Root "analysis\stage38a_cuda")
    )

    $Model = Find-FirstFile `
        -Roots $modelRoots `
        -Filter "*Qwen3*VL*2B*Q8_0*.gguf" `
        -Predicate { $_.Name -notmatch '^mmproj' }

    $Mmproj = Find-FirstFile `
        -Roots $modelRoots `
        -Filter "mmproj*Qwen3*VL*2B*Q8_0*.gguf"

    if (-not $Mmproj) {
        $Mmproj = Find-FirstFile `
            -Roots $modelRoots `
            -Filter "mmproj*Qwen3*VL*2B*.gguf"
    }

    if (-not $Model)  { throw "Qwen3-VL-2B-Instruct-Q8_0.gguf를 찾지 못했습니다." }
    if (-not $Mmproj) { throw "Qwen3-VL-2B mmproj GGUF를 찾지 못했습니다." }

    $payloadCandidates = @(
        (Join-Path $Root "analysis\stage38a\naruto_stage38a_payload\images"),
        (Join-Path $Root "analysis\stage38a\images"),
        (Join-Path $Root "analysis\stage38\images")
    )
    foreach ($d in $payloadCandidates) {
        if (Test-Path $d) {
            $PayloadDir = $d
            break
        }
    }
    if (-not $PayloadDir) {
        throw "Stage38A 샘플 이미지 폴더를 찾지 못했습니다."
    }

    Write-Host "llama-server : $ServerExe"
    Write-Host "model        : $Model"
    Write-Host "mmproj       : $Mmproj"
    Write-Host "images       : $PayloadDir"

    Write-Section "2/7 - Rebuild the same balanced sample, reduced to 30"

    $allImages = @(Get-ChildItem $PayloadDir -File | Where-Object {
        $_.Extension -match '^\.(jpg|jpeg|png|webp)$'
    } | Sort-Object Name)

    $part1 = @($allImages | Where-Object { $_.Name -match 'part1' })
    $part2 = @($allImages | Where-Object { $_.Name -match 'part2' })

    Write-Host "Available Part1 images: $($part1.Count)"
    Write-Host "Available Part2 images: $($part2.Count)"

    if ($part1.Count -lt 15 -or $part2.Count -lt 15) {
        throw "Part1/Part2 각각 15장 이상 필요합니다."
    }

    $sel1 = @(Select-Evenly -Items $part1 -Count 15)
    $sel2 = @(Select-Evenly -Items $part2 -Count 15)

    # Interleave Part1/Part2 to reduce run-order bias.
    $samples = @()
    for ($i = 0; $i -lt 15; $i++) {
        $samples += [PSCustomObject]@{ Seq = 2*$i + 1; Part = "part1"; File = $sel1[$i] }
        $samples += [PSCustomObject]@{ Seq = 2*$i + 2; Part = "part2"; File = $sel2[$i] }
    }

    $manifestRows = foreach ($s in $samples) {
        [PSCustomObject]@{
            seq = $s.Seq
            part = $s.Part
            filename = $s.File.Name
            full_path = $s.File.FullName
            size_bytes = $s.File.Length
        }
    }
    $manifestRows | Export-Csv -Path $Manifest -NoTypeInformation -Encoding UTF8

    Write-Host ""
    Write-Host "Selected 30 images:"
    foreach ($s in $samples) {
        Write-Host ("  {0,2}. [{1}] {2}" -f $s.Seq, $s.Part, $s.File.Name)
    }

    Write-Section "3/7 - Environment / GPU before"

    @(
        "Timestamp=$Stamp",
        "ComputerName=$env:COMPUTERNAME",
        "UserName=$env:USERNAME",
        "PowerShell=$($PSVersionTable.PSVersion)",
        "OS=$([Environment]::OSVersion.VersionString)",
        "SERVER=$ServerExe",
        "MODEL=$Model",
        "MMPROJ=$Mmproj",
        "PAYLOAD=$PayloadDir",
        "SAMPLE_COUNT=30",
        "PART1=15",
        "PART2=15",
        "BC250_MEAN_SEC=$BC250Mean"
    ) | Set-Content $EnvTxt -Encoding UTF8

    Save-NvidiaSmi $GpuBefore

    Write-Section "4/7 - Start llama-server ONCE with BC250-equivalent options"

    # Important: no --no-mmproj-offload here.
    # This keeps mmproj GPU offload enabled, matching the BC250 benchmark intent.
    $ServerArgs = @(
        "-m", $Model,
        "--mmproj", $Mmproj,
        "--host", "127.0.0.1",
        "--port", "$Port",
        "-ngl", "99",
        "-b", "1024",
        "-ub", "1024",
        "--image-max-tokens", "512"
    )

    $displayArgs = foreach ($a in $ServerArgs) {
        if ([string]$a -match '\s') { '"' + $a + '"' } else { [string]$a }
    }
    $serverCommand = '"' + $ServerExe + '" ' + ($displayArgs -join ' ')
    $serverCommand | Set-Content $CmdTxt -Encoding UTF8
    Write-Host $serverCommand

    if (Test-Path $ServerLog) { Remove-Item $ServerLog -Force }
    if (Test-Path $ServerErr) { Remove-Item $ServerErr -Force }

    $ServerProc = Start-Process `
        -FilePath $ServerExe `
        -ArgumentList $ServerArgs `
        -RedirectStandardOutput $ServerLog `
        -RedirectStandardError $ServerErr `
        -PassThru `
        -WindowStyle Hidden

    Write-Host "llama-server PID: $($ServerProc.Id)"
    Write-Host "Waiting for server..."

    $ready = $false
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        if ($ServerProc.HasExited) {
            throw "llama-server가 준비 전에 종료했습니다. ExitCode=$($ServerProc.ExitCode)"
        }
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get -TimeoutSec 3
            $ready = $true
            break
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }

    if (-not $ready) {
        throw "llama-server가 3분 내 준비되지 않았습니다."
    }

    Write-Host "Server ready."

    Write-Section "5/7 - 30-image sequential OCR benchmark"

    # Same Stage38 OCR instruction recovered from the BC250 benchmark.
    $Prompt = "화면에 실제로 보이는 글자만 정확히 전사하세요. 번역·의역·추측하지 마세요. 줄바꿈을 유지하세요. 글자가 없으면 [EMPTY], 읽을 수 없으면 [불명]이라고 출력하세요."

    $runWall = [System.Diagnostics.Stopwatch]::StartNew()

    foreach ($s in $samples) {
        $imageBytes = [System.IO.File]::ReadAllBytes($s.File.FullName)
        $b64 = [Convert]::ToBase64String($imageBytes)

        $ext = $s.File.Extension.ToLowerInvariant()
        $mime = switch ($ext) {
            ".png"  { "image/png" }
            ".webp" { "image/webp" }
            default { "image/jpeg" }
        }

        $dataUri = "data:$mime;base64,$b64"

        $body = @{
            model = "qwen3-vl"
            temperature = 0
            max_tokens = 128
            messages = @(
                @{
                    role = "user"
                    content = @(
                        @{
                            type = "text"
                            text = $Prompt
                        },
                        @{
                            type = "image_url"
                            image_url = @{
                                url = $dataUri
                            }
                        }
                    )
                }
            )
        } | ConvertTo-Json -Depth 10 -Compress

        Write-Host ""
        Write-Host ("[{0,2}/30] {1}" -f $s.Seq, $s.File.Name)

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $status = "OK"
        $ocr = ""
        $err = ""

        try {
            $resp = Invoke-RestMethod `
                -Uri "$BaseUrl/v1/chat/completions" `
                -Method Post `
                -ContentType "application/json; charset=utf-8" `
                -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
                -TimeoutSec 180

            $ocr = [string]$resp.choices[0].message.content
        } catch {
            $status = "ERROR"
            $err = $_.Exception.Message
        }

        $sw.Stop()
        $sec = [Math]::Round($sw.Elapsed.TotalSeconds, 3)

        if ($status -eq "OK") {
            $preview = $ocr -replace "`r"," " -replace "`n"," / "
            if ($preview.Length -gt 120) { $preview = $preview.Substring(0,120) + "..." }
            Write-Host ("  {0:N3} sec | {1}" -f $sec, $preview)
        } else {
            Write-Host ("  FAILED after {0:N3} sec | {1}" -f $sec, $err)
        }

        $Results += [PSCustomObject]@{
            seq = $s.Seq
            part = $s.Part
            filename = $s.File.Name
            seconds = $sec
            status = $status
            ocr_text = $ocr
            error = $err
        }
    }

    $runWall.Stop()
    $Results | Export-Csv -Path $CsvPath -NoTypeInformation -Encoding UTF8

    $ok = @($Results | Where-Object status -eq "OK")
    $fail = @($Results | Where-Object status -ne "OK")
    if ($ok.Count -eq 0) {
        throw "30장 중 성공한 OCR이 없습니다."
    }

    $times = [double[]]@($ok | ForEach-Object { [double]$_.seconds })
    $mean = ($times | Measure-Object -Average).Average
    $median = Get-Percentile -Values $times -P 50
    $p95 = Get-Percentile -Values $times -P 95
    $min = ($times | Measure-Object -Minimum).Minimum
    $max = ($times | Measure-Object -Maximum).Maximum
    $ratio = $mean / $BC250Mean
    $speedup = $BC250Mean / $mean

    Write-Section "6/7 - Results"

    Write-Host ("Success       : {0}/30" -f $ok.Count)
    Write-Host ("Failed        : {0}/30" -f $fail.Count)
    Write-Host ("Mean          : {0:N3} sec/image" -f $mean)
    Write-Host ("Median        : {0:N3} sec/image" -f $median)
    Write-Host ("P95           : {0:N3} sec/image" -f $p95)
    Write-Host ("Min / Max     : {0:N3} / {1:N3} sec" -f $min,$max)
    Write-Host ("30-image wall : {0:N3} sec" -f $runWall.Elapsed.TotalSeconds)
    Write-Host ("BC250 mean    : {0:N3} sec/image" -f $BC250Mean)
    Write-Host ("RTX/BC ratio  : {0:N3}x" -f $ratio)
    Write-Host ("BC/RTX speed  : {0:N3}x" -f $speedup)

    $summaryLines = @(
        "Naruto PSP Stage 38C - 30 image RTX 3070 benchmark",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: SUCCESS",
        "",
        "Conditions:",
        "Model: Qwen3-VL-2B-Instruct-Q8_0",
        "mmproj: $(Split-Path $Mmproj -Leaf)",
        "Sample: Part1 15 + Part2 15 evenly distributed",
        "Server lifetime: one model load, 30 sequential requests",
        "ngl=99",
        "batch=1024",
        "ubatch=1024",
        "image_max_tokens=512",
        "mmproj_gpu_offload=ON",
        "temperature=0",
        "max_tokens=128",
        "Prompt=$Prompt",
        "",
        "RTX 3070 results:",
        "Success=$($ok.Count)/30",
        "Failed=$($fail.Count)/30",
        ("MeanSec={0:N3}" -f $mean),
        ("MedianSec={0:N3}" -f $median),
        ("P95Sec={0:N3}" -f $p95),
        ("MinSec={0:N3}" -f $min),
        ("MaxSec={0:N3}" -f $max),
        ("WallSec={0:N3}" -f $runWall.Elapsed.TotalSeconds),
        "",
        "BC250 baseline:",
        ("MeanSec={0:N3}" -f $BC250Mean),
        "",
        "Comparison:",
        ("RTX_mean_div_BC250_mean={0:N3}x" -f $ratio),
        ("BC250_mean_div_RTX_mean={0:N3}x" -f $speedup),
        "",
        "Files:",
        "CSV=$CsvPath",
        "Manifest=$Manifest",
        "ServerLog=$ServerLog",
        "ServerErr=$ServerErr"
    )
    $summaryLines | Set-Content $Summary -Encoding UTF8

    if ($fail.Count -gt 0) {
        Write-Host ""
        Write-Host "WARNING: 일부 이미지가 실패했습니다. CSV에 기록했습니다."
    }

    Save-NvidiaSmi $GpuAfter
    $Succeeded = ($fail.Count -eq 0)

    if (-not $Succeeded) {
        throw "일부 OCR 요청 실패: $($fail.Count)/30"
    }

} catch {
    $Caught = $_
    $Succeeded = $false

    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38C FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)

    @(
        "Naruto PSP Stage 38C FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        "Message:",
        $_.Exception.Message,
        "",
        "Full error:",
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

} finally {
    Write-Section "7/7 - Stop server / package results"

    if ($ServerProc) {
        try {
            if (-not $ServerProc.HasExited) {
                Stop-Process -Id $ServerProc.Id -Force -ErrorAction SilentlyContinue
                $ServerProc.WaitForExit(5000) | Out-Null
            }
        } catch {}
    }

    try { Stop-Transcript | Out-Null } catch {}

    $PackageDir = Join-Path $StageDir "_upload_package"
    if (Test-Path $PackageDir) {
        Remove-Item $PackageDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

    $packFiles = @(
        $Summary, $CsvPath, $Manifest, $ServerLog, $ServerErr,
        $EnvTxt, $CmdTxt, $GpuBefore, $GpuAfter, $Transcript, $FailureTxt
    )

    foreach ($f in $packFiles) {
        if ($f -and (Test-Path $f)) {
            Copy-Item $f $PackageDir -Force
        }
    }

    if ($PSCommandPath -and (Test-Path $PSCommandPath)) {
        Copy-Item $PSCommandPath $PackageDir -Force
    }

    # Include the 30 selected review frames (small JPEGs) so ChatGPT can
    # compare OCR quality against the exact benchmark inputs.
    if ($samples) {
        $reviewDir = Join-Path $PackageDir "selected_images"
        New-Item -ItemType Directory -Force -Path $reviewDir | Out-Null
        foreach ($s in $samples) {
            if ($s.File -and (Test-Path $s.File.FullName)) {
                Copy-Item $s.File.FullName $reviewDir -Force
            }
        }
    }

    if ($Succeeded) {
        if (Test-Path $UploadZip) {
            $oldDir = Join-Path $OldRoot $Stamp
            New-Item -ItemType Directory -Force -Path $oldDir | Out-Null
            Copy-Item $UploadZip (Join-Path $oldDir "naruto_stage38c_30_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "STAGE 38C SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }
    else {
        $failedDir = Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null

        Get-ChildItem $PackageDir -File -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName $failedDir -Force }

        $failedZip = Join-Path $failedDir "naruto_stage38c_30_failed_upload.zip"
        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $failedZip -Force

        Write-Host ""
        Write-Host "STAGE 38C FAILED"
        Write-Host "정상 업로드 ZIP은 갱신하지 않았습니다."
        Write-Host "Failure ZIP:"
        Write-Host "  $failedZip"
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Succeeded) { exit 1 }
exit 0
