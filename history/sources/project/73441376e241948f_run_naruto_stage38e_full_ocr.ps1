# Naruto PSP Stage 38E FIX1
# Full 2,086-frame RTX 3070 OCR production run.
#
# - Stage38D corrected B prompt
# - one persistent llama-server
# - auto-discover Stage37/37B completed frames by part/p/g filename
# - require exact global_index 1..2086 before starting
# - checkpoint after every image
# - resume: successful global_index rows are skipped
# - request retry up to 3 attempts; restart server if it died
# - live progress + ETA + transcript
# - old transient logs rotated to logs\old\<timestamp>\stage38e_full_ocr
# - final OCR CSV, review queue, Hangul frequency, unique Hangul corpus
# - compact ChatGPT upload ZIP; no full 2,086 image set included
#
# Expected source count:
#   Part1 = 1498
#   Part2 = 588
#   Total = 2086

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "stage38e_full_ocr"
$StageDir   = Join-Path $Root "analysis\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_stage38e_full_ocr_$Stamp.log"
$Checkpoint = Join-Path $StageDir "ocr_checkpoint.csv"
$FinalCsv   = Join-Path $StageDir "ocr_2086_results.csv"
$Manifest   = Join-Path $StageDir "source_2086_manifest.csv"
$ReviewTsv  = Join-Path $StageDir "review_needed.tsv"
$CharTsv    = Join-Path $StageDir "char_frequency.tsv"
$LowFreqTsv = Join-Path $StageDir "low_frequency_review.tsv"
$UniqueTxt  = Join-Path $StageDir "unique_hangul.txt"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$VersionTxt = Join-Path $StageDir "llama_server_version.txt"
$CmdTxt     = Join-Path $StageDir "SERVER_COMMAND.txt"
$GpuBefore  = Join-Path $StageDir "NVIDIA_BEFORE.txt"
$GpuAfter   = Join-Path $StageDir "NVIDIA_AFTER.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38e_full_ocr_upload.zip"

$Port = 8095
$BaseUrl = "httLOCAL_PATH"
$ExpectedPart1 = 1498
$ExpectedPart2 = 588
$ExpectedTotal = 2086
$MaxAttempts = 3

New-Item -ItemType Directory -Force -Path $LogsDir,$FailedRoot,$OldRoot | Out-Null

# ----------------------------------------------------------------------
# Rotate only transient logs from previous Stage38E runs.
# Keep checkpoint/results in StageDir so interrupted runs can resume.
# ----------------------------------------------------------------------
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName
$OldTransient = @()

if (Test-Path $StageDir) {
    $OldTransient += @(Get-ChildItem $StageDir -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "llama_server_*.log" -or
            $_.Name -like "llama_server_*.err.log"
        })
}
$OldTransient += @(Get-ChildItem $LogsDir -File -Filter "naruto_stage38e_full_ocr_*.log" -ErrorAction SilentlyContinue)

if ($OldTransient.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach ($f in $OldTransient) {
        $dest = Join-Path $ArchiveDir $f.Name
        if (Test-Path $dest) {
            $base = [IO.Path]::GetFileNameWithoutExtension($f.Name)
            $ext  = [IO.Path]::GetExtension($f.Name)
            $dest = Join-Path $ArchiveDir ("{0}_{1}{2}" -f $base,(Get-Date -Format "HHmmssfff"),$ext)
        }
        Move-Item $f.FullName $dest -Force
    }
}

New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
if (Test-Path $FailureTxt) { Remove-Item $FailureTxt -Force }

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host (" " + $Text)
    Write-Host ("=" * 80)
}

function Find-FirstFile {
    param([string[]]$Roots,[string]$Filter,[scriptblock]$Predicate=$null)
    foreach ($r in $Roots) {
        if (-not (Test-Path $r)) { continue }
        $items = Get-ChildItem $r -Filter $Filter -File -Recurse -ErrorAction SilentlyContinue
        if ($Predicate) { $items = $items | Where-Object $Predicate }
        $hit = $items | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Save-NvidiaSmi([string]$Path) {
    if (Test-Path $Path) { Remove-Item $Path -Force }
    $nvsmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvsmi) { $nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue }
    if (-not $nvsmi) {
        "nvidia-smi not found" | Set-Content $Path -Encoding UTF8
        return
    }
    $cmd = '"' + $nvsmi.Source + '" 2>&1'
    & $env:ComSpec /d /s /c $cmd | ForEach-Object {
        $line = [string]$_
        Write-Host $line
        $line | Out-File $Path -Append -Encoding utf8
    }
}

function Normalize-Ocr([string]$Text) {
    if ($null -eq $Text) { return "" }
    return (($Text -replace "`r`n","`n" -replace "`r","`n").Trim())
}

function Extract-Ocr([string]$Raw) {
    if ($null -eq $Raw) { return "" }
    $m = [regex]::Match($Raw,'(?s)<OCR>\s*(.*?)\s*</OCR>')
    if ($m.Success) { return (Normalize-Ocr $m.Groups[1].Value) }
    return (Normalize-Ocr $Raw)
}

function Get-ReviewReason([string]$Text) {
    $x = Normalize-Ocr $Text
    $reasons = New-Object System.Collections.Generic.List[string]

    if ([string]::IsNullOrWhiteSpace($x)) { $reasons.Add("EMPTY_OUTPUT") }
    if ($x -eq "[EMPTY]") { $reasons.Add("MODEL_EMPTY") }
    if ($x.Contains("[불명]")) { $reasons.Add("UNREADABLE") }
    if ($x.Length -gt 260) { $reasons.Add("LONG_OUTPUT") }

    $bad = @(
        "한국어, 일본어, 영어",
        "번역, 의역",
        "판독할 수 없는",
        "이미지에 없는 문장",
        "반드시 아래 형식",
        "화면에 실제로 보이는 글자만",
        "너는 게임 화면 OCR 엔진"
    )
    foreach ($b in $bad) {
        if ($x.Contains($b)) {
            $reasons.Add("PROMPT_LEAK")
            break
        }
    }

    return ($reasons -join ";")
}

function Quote-ProcArg([string]$Value) {
    if ($null -eq $Value) { return '""' }
    return '"' + $Value.Replace('"','\"') + '"'
}

function Get-FrameScore([IO.FileInfo]$File) {
    $p = $File.FullName.ToLowerInvariant()
    $score = 0
    if ($p.Contains("completed")) { $score += 200 }
    elseif ($p.Contains("complete")) { $score += 180 }
    if ($p.Contains("final")) { $score += 100 }
    if ($p.Contains("dialogue")) { $score += 40 }
    if ($p.Contains("candidate")) { $score -= 200 }
    if ($p.Contains("debug")) { $score -= 200 }
    if ($p.Contains("preview")) { $score -= 150 }
    if ($p.Contains("sample")) { $score -= 100 }
    if ($File.Extension.ToLowerInvariant() -eq ".jpg") { $score += 5 }
    return $score
}

function Append-CheckpointRow($Row) {
    $exists = Test-Path $Checkpoint
    if ($exists) {
        $Row | Export-Csv $Checkpoint -NoTypeInformation -Append -Encoding UTF8
    } else {
        $Row | Export-Csv $Checkpoint -NoTypeInformation -Encoding UTF8
    }
}

function Get-ResponseTiming($Response,[string]$Name) {
    if ($null -eq $Response) { return $null }
    $tp = $Response.PSObject.Properties["timings"]
    if (-not $tp) { return $null }
    $p = $Response.timings.PSObject.Properties[$Name]
    if ($p) { return $p.Value }
    return $null
}

# Stage38D corrected B prompt.
$SystemPrompt = @'
너는 게임 화면 OCR 엔진이다.
이미지 안에서 실제로 읽을 수 있는 문자만 복사한다.
배경, 인물, 지식, 문맥으로 보이지 않는 글자를 만들어내지 않는다.
고유명사를 알고 있더라도 이미지에서 읽힌 형태를 우선한다.
설명이나 번역은 출력하지 않는다.
'@

$UserPrompt = @'
이름표가 보이면 이름표부터 읽고, 대사창의 글자를 그 아래에 화면 줄바꿈대로 적어라.
문자가 하나도 보이지 않으면 [EMPTY]만 출력한다.
읽을 수 없는 한 글자만 [불명]으로 적는다.
출력은 <OCR>와 </OCR> 사이에 전사문만 넣어라.
'@

$Succeeded = $false
$Caught = $null
$ServerProc = $null
$ServerSeq = 0
$ServerLogFiles = New-Object System.Collections.Generic.List[string]
$SourceFrames = @()
$SourceByGlobal = @{}

Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto Stage38E FIX1 - Full 2,086-frame RTX 3070 OCR"
    Write-Host "Started       : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Expected      : Part1=$ExpectedPart1 Part2=$ExpectedPart2 Total=$ExpectedTotal"
    Write-Host "Checkpoint    : $Checkpoint"
    if (Test-Path $ArchiveDir) {
        Write-Host "Old logs      : $ArchiveDir"
    }

    Write-Section "1/9 - Runtime / model / mmproj"

    $runtimeRoots = @(
        (Join-Path $Root "analysis\stage38a_cuda\cuda_runtime"),
        (Join-Path $Root "analysis\stage38a_cuda"),
        (Join-Path $Root "analysis")
    )
    $ServerExe = Find-FirstFile $runtimeRoots "llama-server.exe"
    if (-not $ServerExe) { throw "llama-server.exe를 찾지 못했습니다." }

    $modelRoots = @(
        (Join-Path $Root "analysis\stage38a_cuda\models"),
        (Join-Path $Root "models")
    )
    $Model = Find-FirstFile $modelRoots "*Qwen3*VL*2B*Q8_0*.gguf" { $_.Name -notmatch '^mmproj' }
    $Mmproj = Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*Q8_0*.gguf"
    if (-not $Mmproj) { $Mmproj = Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*.gguf" }

    if (-not $Model) { throw "Qwen3-VL-2B Q8_0 모델을 찾지 못했습니다." }
    if (-not $Mmproj) { throw "Qwen3-VL-2B mmproj를 찾지 못했습니다." }

    Write-Host "server : $ServerExe"
    Write-Host "model  : $Model"
    Write-Host "mmproj : $Mmproj"

    $verCmd = '"' + $ServerExe + '" --version 2>&1'
    & $env:ComSpec /d /s /c $verCmd | Set-Content $VersionTxt -Encoding UTF8
    Get-Content $VersionTxt | ForEach-Object { Write-Host $_ }

    Write-Section "2/9 - Discover Stage37 / Stage37B completed frames"

    $Stage37Part1Root = Join-Path $Root "analysis\stage37"
    $Stage37Part2Root = Join-Path $Root "analysis\stage37b"

    if (-not (Test-Path $Stage37Part1Root)) {
        throw "Part1 Stage37 폴더를 찾지 못했습니다: $Stage37Part1Root"
    }
    if (-not (Test-Path $Stage37Part2Root)) {
        throw "Part2 Stage37B 폴더를 찾지 못했습니다: $Stage37Part2Root"
    }

    Write-Host "Part1 root: $Stage37Part1Root"
    Write-Host "Part2 root: $Stage37Part2Root"

    function Get-ImageFiles([string]$Dir) {
        return @(Get-ChildItem $Dir -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|webp)$' })
    }

    function Get-DirectoryImageGroups([string]$RootDir) {
        $imgs = @(Get-ImageFiles $RootDir)
        $groups = @(
            $imgs |
            Group-Object DirectoryName |
            ForEach-Object {
                [PSCustomObject]@{
                    directory = [string]$_.Name
                    count = [int]$_.Count
                    files = @($_.Group)
                }
            } |
            Sort-Object @{Expression="count";Descending=$true}, @{Expression="directory";Descending=$false}
        )
        return $groups
    }

    function Score-CompletedDirectory([string]$Path,[int]$Count,[int]$Expected) {
        $p = $Path.ToLowerInvariant()
        $score = 0
        if ($Count -eq $Expected) { $score += 10000 }
        if ($p.Contains("completed")) { $score += 1000 }
        if ($p.Contains("complete"))  { $score += 800 }
        if ($p.Contains("final"))     { $score += 500 }
        if ($p.Contains("dialog"))    { $score += 250 }
        if ($p.Contains("output"))    { $score += 100 }
        if ($p.Contains("candidate")) { $score -= 1200 }
        if ($p.Contains("debug"))     { $score -= 1200 }
        if ($p.Contains("preview"))   { $score -= 1000 }
        if ($p.Contains("sample"))    { $score -= 800 }
        return $score
    }

    function Select-CompletedDirectory([string]$RootDir,[int]$Expected,[string]$Label) {
        $groups = @(Get-DirectoryImageGroups $RootDir)

        Write-Host ""
        Write-Host "$Label image directory counts:"
        foreach ($g in ($groups | Select-Object -First 20)) {
            Write-Host ("  {0,5}  {1}" -f $g.count,$g.directory)
        }

        $exact = @($groups | Where-Object { $_.count -eq $Expected })
        if ($exact.Count -gt 0) {
            $ranked = @(
                $exact |
                ForEach-Object {
                    [PSCustomObject]@{
                        directory = $_.directory
                        count = $_.count
                        files = $_.files
                        score = (Score-CompletedDirectory $_.directory $_.count $Expected)
                    }
                } |
                Sort-Object @{Expression="score";Descending=$true}, @{Expression="directory";Descending=$false}
            )
            $chosen = $ranked[0]
            Write-Host ""
            Write-Host "$Label exact-count folder selected:"
            Write-Host "  $($chosen.directory)"
            Write-Host "  count=$($chosen.count) score=$($chosen.score)"
            return $chosen
        }

        # Fallback: recursively collect files from paths that look like completed output.
        $all = @(Get-ImageFiles $RootDir)
        $completedLike = @($all | Where-Object {
            $p = $_.DirectoryName.ToLowerInvariant()
            ($p.Contains("completed") -or $p.Contains("complete") -or $p.Contains("final")) -and
            (-not $p.Contains("candidate")) -and
            (-not $p.Contains("debug")) -and
            (-not $p.Contains("preview")) -and
            (-not $p.Contains("sample"))
        })

        if ($completedLike.Count -eq $Expected) {
            Write-Host ""
            Write-Host "$Label completed-like recursive set selected: $($completedLike.Count)"
            return [PSCustomObject]@{
                directory = "$RootDir [recursive completed-like]"
                count = $completedLike.Count
                files = $completedLike
                score = 5000
            }
        }

        throw "$Label 완료 프레임 폴더를 자동 식별하지 못했습니다. 기대=$Expected. 위 directory counts를 확인하세요."
    }

    function Get-NaturalSortKey([string]$Name) {
        # Pad every numeric token so lexical sorting becomes natural sorting.
        return [regex]::Replace($Name,'\d+',{
            param($m)
            return ([int64]$m.Value).ToString("D18")
        })
    }

    function Sort-FramesNatural($Files) {
        return @(
            $Files |
            Sort-Object `
                @{Expression={ Get-NaturalSortKey $_.Name };Ascending=$true},
                @{Expression={$_.Name};Ascending=$true},
                @{Expression={$_.FullName};Ascending=$true}
        )
    }

    $part1Group = Select-CompletedDirectory $Stage37Part1Root $ExpectedPart1 "Part1"
    $part2Group = Select-CompletedDirectory $Stage37Part2Root $ExpectedPart2 "Part2"

    $part1Files = @(Sort-FramesNatural $part1Group.files)
    $part2Files = @(Sort-FramesNatural $part2Group.files)

    if ($part1Files.Count -ne $ExpectedPart1) {
        throw "Part1 선택 결과가 1498장이 아닙니다: $($part1Files.Count)"
    }
    if ($part2Files.Count -ne $ExpectedPart2) {
        throw "Part2 선택 결과가 588장이 아닙니다: $($part2Files.Count)"
    }

    $SourceFrames = @()

    for ($i=0; $i -lt $part1Files.Count; $i++) {
        $f = $part1Files[$i]
        $idx = $i + 1
        $SourceFrames += [PSCustomObject]@{
            global_index = $idx
            video_part = "part1"
            part_index = $idx
            filename = $f.Name
            full_path = $f.FullName
            bytes = $f.Length
            score = $part1Group.score
        }
    }

    for ($i=0; $i -lt $part2Files.Count; $i++) {
        $f = $part2Files[$i]
        $partIdx = $i + 1
        $globalIdx = $ExpectedPart1 + $partIdx
        $SourceFrames += [PSCustomObject]@{
            global_index = $globalIdx
            video_part = "part2"
            part_index = $partIdx
            filename = $f.Name
            full_path = $f.FullName
            bytes = $f.Length
            score = $part2Group.score
        }
    }

    $part1 = @($SourceFrames | Where-Object video_part -eq "part1")
    $part2 = @($SourceFrames | Where-Object video_part -eq "part2")

    Write-Host ""
    Write-Host "Selected source set:"
    Write-Host "  Part1 : $($part1.Count)"
    Write-Host "  Part2 : $($part2.Count)"
    Write-Host "  Total : $($SourceFrames.Count)"
    Write-Host ""
    Write-Host "Ordering preview:"
    foreach ($s in @(
        $SourceFrames[0],
        $SourceFrames[1],
        $SourceFrames[2],
        $SourceFrames[1497],
        $SourceFrames[1498],
        $SourceFrames[1499],
        $SourceFrames[2085]
    )) {
        Write-Host ("  g={0,4} {1} p={2,4} {3}" -f $s.global_index,$s.video_part,$s.part_index,$s.filename)
    }

    if ($SourceFrames.Count -ne $ExpectedTotal) {
        throw "총 소스 수가 2086이 아닙니다: $($SourceFrames.Count)"
    }

    $SourceFrames |
        Select-Object global_index,video_part,part_index,filename,full_path,bytes,score |
        Export-Csv $Manifest -NoTypeInformation -Encoding UTF8

    foreach ($s in $SourceFrames) {
        $SourceByGlobal[[int]$s.global_index] = $s
    }

    Write-Host ""
    Write-Host "Source validation PASS: Part1 1498 + Part2 588 = 2086"

    Write-Section "3/9 - Resume checkpoint"

    $Completed = @{}
    if (Test-Path $Checkpoint) {
        try {
            $oldRows = @(Import-Csv $Checkpoint)
            foreach ($r in $oldRows) {
                if ($r.status -eq "OK") {
                    $Completed[[int]$r.global_index] = $r
                }
            }
            Write-Host "Checkpoint rows : $($oldRows.Count)"
            Write-Host "Already OK      : $($Completed.Count)"
        } catch {
            throw "기존 checkpoint를 읽지 못했습니다: $($_.Exception.Message)"
        }
    } else {
        Write-Host "No checkpoint. Starting fresh."
    }

    if ($Completed.Count -gt $ExpectedTotal) {
        throw "checkpoint OK 개수가 2086을 초과합니다."
    }

    $RemainingFrames = @($SourceFrames | Where-Object { -not $Completed.ContainsKey([int]$_.global_index) })
    Write-Host "Remaining       : $($RemainingFrames.Count)"

    Write-Section "4/9 - GPU / server configuration"
    Save-NvidiaSmi $GpuBefore

    $ServerArgs = @(
        "-m",$Model,
        "--mmproj",$Mmproj,
        "--host","127.0.0.1",
        "--port","$Port",
        "-t","8",
        "-np","4",
        "-c","16384",
        "-ngl","99",
        "--image-max-tokens","512"
    )
    $ArgLine = (($ServerArgs | ForEach-Object { Quote-ProcArg ([string]$_) }) -join " ")
    ('"' + $ServerExe + '" ' + $ArgLine) | Set-Content $CmdTxt -Encoding UTF8
    Get-Content $CmdTxt | ForEach-Object { Write-Host $_ }

    function Stop-LlamaServer {
        if ($script:ServerProc) {
            try {
                if (-not $script:ServerProc.HasExited) {
                    Stop-Process -Id $script:ServerProc.Id -Force -ErrorAction SilentlyContinue
                    $script:ServerProc.WaitForExit(5000) | Out-Null
                }
            } catch {}
            $script:ServerProc = $null
        }
    }

    function Start-LlamaServer {
        Stop-LlamaServer
        $script:ServerSeq++
        $seq = $script:ServerSeq

        $stdout = Join-Path $StageDir ("llama_server_{0}_{1:D2}.log" -f $Stamp,$seq)
        $stderr = Join-Path $StageDir ("llama_server_{0}_{1:D2}.err.log" -f $Stamp,$seq)
        $script:ServerLogFiles.Add($stdout)
        $script:ServerLogFiles.Add($stderr)

        if (Test-Path $stdout) { Remove-Item $stdout -Force }
        if (Test-Path $stderr) { Remove-Item $stderr -Force }

        $script:ServerProc = Start-Process `
            -FilePath $ServerExe `
            -ArgumentList $ArgLine `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru `
            -WindowStyle Hidden

        Write-Host "llama-server PID=$($script:ServerProc.Id) restart#$seq"

        $ready = $false
        $deadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $deadline) {
            if ($script:ServerProc.HasExited) {
                try { $script:ServerProc.WaitForExit() } catch {}
                try { $script:ServerProc.Refresh() } catch {}
                Write-Host "----- llama-server stderr tail -----"
                if (Test-Path $stderr) {
                    Get-Content $stderr -Tail 100 | ForEach-Object { Write-Host $_ }
                }
                $ec = "unknown"
                try { $ec = [string]$script:ServerProc.ExitCode } catch {}
                throw "llama-server가 준비 전에 종료했습니다. ExitCode=$ec"
            }

            try {
                $null = Invoke-RestMethod "$BaseUrl/health" -Method Get -TimeoutSec 3
                $ready = $true
                break
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }

        if (-not $ready) { throw "llama-server가 3분 내 준비되지 않았습니다." }
    }

    if ($RemainingFrames.Count -gt 0) {
        Start-LlamaServer
    } else {
        Write-Host "All 2086 frames are already OK in checkpoint; inference skipped."
    }

    Write-Section "5/9 - Full OCR"

    $runTimer = [Diagnostics.Stopwatch]::StartNew()
    $doneThisRun = 0
    $errorThisRun = 0
    $requestTimes = New-Object System.Collections.Generic.List[double]

    foreach ($s in $RemainingFrames) {
        $g = [int]$s.global_index
        $overallDoneBefore = $Completed.Count + $doneThisRun
        $displayNum = $overallDoneBefore + 1

        Write-Host ""
        Write-Host ("[{0,4}/{1}] g={2} {3} p={4} {5}" -f `
            $displayNum,$ExpectedTotal,$g,$s.video_part,$s.part_index,$s.filename)

        $bytes = [IO.File]::ReadAllBytes($s.full_path)
        $b64 = [Convert]::ToBase64String($bytes)
        $mime = switch ([IO.Path]::GetExtension($s.full_path).ToLowerInvariant()) {
            ".png"  { "image/png" }
            ".webp" { "image/webp" }
            default { "image/jpeg" }
        }
        $dataUri = "data:$mime;base64,$b64"

        $messages = @(
            @{ role="system"; content=$SystemPrompt },
            @{
                role="user"
                content=@(
                    @{ type="image_url"; image_url=@{ url=$dataUri } },
                    @{ type="text"; text=$UserPrompt }
                )
            }
        )

        $body = @{
            model = "qwen3-vl"
            temperature = 0
            max_tokens = 128
            messages = $messages
        } | ConvertTo-Json -Depth 14 -Compress

        $status = "ERROR"
        $ocr = ""
        $raw = ""
        $err = ""
        $wall = 0.0
        $attemptUsed = 0
        $promptMs = $null
        $predictedMs = $null
        $promptN = $null
        $predictedN = $null

        for ($attempt=1; $attempt -le $MaxAttempts; $attempt++) {
            $attemptUsed = $attempt

            if (-not $script:ServerProc -or $script:ServerProc.HasExited) {
                Write-Host "  server unavailable -> restart"
                Start-LlamaServer
            }

            $sw = [Diagnostics.Stopwatch]::StartNew()
            try {
                $resp = Invoke-RestMethod `
                    -Uri "$BaseUrl/v1/chat/completions" `
                    -Method Post `
                    -ContentType "application/json; charset=utf-8" `
                    -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
                    -TimeoutSec 180

                $sw.Stop()
                $wall = [Math]::Round($sw.Elapsed.TotalSeconds,4)
                $raw = [string]$resp.choices[0].message.content
                $ocr = Extract-Ocr $raw
                $promptMs = Get-ResponseTiming $resp "prompt_ms"
                $predictedMs = Get-ResponseTiming $resp "predicted_ms"
                $promptN = Get-ResponseTiming $resp "prompt_n"
                $predictedN = Get-ResponseTiming $resp "predicted_n"
                $status = "OK"
                $err = ""
                break
            } catch {
                $sw.Stop()
                $wall = [Math]::Round($sw.Elapsed.TotalSeconds,4)
                $err = $_.Exception.Message
                Write-Host ("  attempt {0}/{1} failed: {2}" -f $attempt,$MaxAttempts,$err)

                if ($script:ServerProc -and $script:ServerProc.HasExited) {
                    Write-Host "  llama-server exited -> will restart"
                }

                if ($attempt -lt $MaxAttempts) {
                    Start-Sleep -Seconds $attempt
                }
            }
        }

        $reviewReason = ""
        if ($status -eq "OK") {
            $reviewReason = Get-ReviewReason $ocr
        } else {
            $reviewReason = "REQUEST_FAILED"
        }

        $row = [PSCustomObject]@{
            global_index = $g
            video_part = $s.video_part
            part_index = $s.part_index
            filename = $s.filename
            source_path = $s.full_path
            status = $status
            attempts = $attemptUsed
            wall_seconds = $wall
            prompt_ms = $promptMs
            predicted_ms = $predictedMs
            prompt_n = $promptN
            predicted_n = $predictedN
            review_reason = $reviewReason
            ocr_text = $ocr
            raw_model_output = $raw
            error = $err
            completed_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        }

        Append-CheckpointRow $row

        if ($status -eq "OK") {
            $doneThisRun++
            $requestTimes.Add([double]$wall)

            $preview = $ocr -replace "`n"," / "
            if ($preview.Length -gt 90) { $preview = $preview.Substring(0,90) + "..." }

            $mean = ($requestTimes | Measure-Object -Average).Average
            $nowDone = $Completed.Count + $doneThisRun
            $remaining = $ExpectedTotal - $nowDone
            $etaSec = $remaining * $mean
            $eta = [TimeSpan]::FromSeconds([Math]::Max(0,$etaSec))

            Write-Host ("  OK {0:N3}s attempt={1} review={2}" -f $wall,$attemptUsed,($(if($reviewReason){$reviewReason}else{"-"})))
            Write-Host ("  {0}" -f $preview)
            Write-Host ("  progress={0}/{1} mean={2:N3}s ETA={3:hh\:mm\:ss}" -f $nowDone,$ExpectedTotal,$mean,$eta)
        } else {
            $errorThisRun++
            Write-Host ("  FAILED after {0} attempts: {1}" -f $attemptUsed,$err)
        }
    }

    $runTimer.Stop()
    Stop-LlamaServer

    Write-Section "6/9 - Consolidate checkpoint"

    $allRows = @(Import-Csv $Checkpoint)

    # Keep the latest row for each global index. A later OK supersedes an older failure.
    $latestByGlobal = @{}
    foreach ($r in $allRows) {
        $latestByGlobal[[int]$r.global_index] = $r
    }
    $finalRows = @($latestByGlobal.Values | Sort-Object { [int]$_.global_index })

    $finalRows | Export-Csv $FinalCsv -NoTypeInformation -Encoding UTF8

    $okRows = @($finalRows | Where-Object status -eq "OK")
    $failedRows = @($finalRows | Where-Object status -ne "OK")
    $reviewRows = @($finalRows | Where-Object { $_.review_reason -and $_.review_reason.Trim().Length -gt 0 })

    Write-Host "Unique rows : $($finalRows.Count)"
    Write-Host "OK          : $($okRows.Count)"
    Write-Host "Failed      : $($failedRows.Count)"
    Write-Host "Review flag : $($reviewRows.Count)"

    # TSV review queue
    $reviewRows |
        Select-Object global_index,video_part,part_index,filename,review_reason,ocr_text,error |
        Export-Csv $ReviewTsv -Delimiter "`t" -NoTypeInformation -Encoding UTF8

    Write-Section "7/9 - Preliminary Hangul corpus / frequency"

    $charCount = @{}
    $charFrames = @{}
    $charExamples = @{}

    foreach ($r in $okRows) {
        $txt = Normalize-Ocr ([string]$r.ocr_text)
        # Remove sentinel tokens so 불/명/EMPTY do not pollute the corpus.
        $txt = $txt.Replace("[EMPTY]","").Replace("[불명]","")

        $seenThisFrame = @{}
        foreach ($ch in $txt.ToCharArray()) {
            $code = [int][char]$ch
            if ($code -ge 0xAC00 -and $code -le 0xD7A3) {
                $key = [string]$ch
                if (-not $charCount.ContainsKey($key)) { $charCount[$key] = 0 }
                $charCount[$key] = [int]$charCount[$key] + 1

                if (-not $seenThisFrame.ContainsKey($key)) {
                    $seenThisFrame[$key] = $true
                    if (-not $charFrames.ContainsKey($key)) { $charFrames[$key] = 0 }
                    $charFrames[$key] = [int]$charFrames[$key] + 1
                }

                if (-not $charExamples.ContainsKey($key)) {
                    $charExamples[$key] = New-Object System.Collections.Generic.List[string]
                }
                if ($charExamples[$key].Count -lt 3) {
                    $ex = ("g{0}:{1}" -f $r.global_index,$r.filename)
                    if (-not $charExamples[$key].Contains($ex)) {
                        $charExamples[$key].Add($ex)
                    }
                }
            }
        }
    }

    $charRows = foreach ($key in $charCount.Keys) {
        $code = [int][char]$key
        [PSCustomObject]@{
            char = $key
            unicode = ("U+{0:X4}" -f $code)
            count = [int]$charCount[$key]
            frame_count = [int]$charFrames[$key]
            examples = ($charExamples[$key] -join " | ")
        }
    }

    $charRows = @($charRows | Sort-Object @{Expression="count";Descending=$true}, @{Expression="char";Descending=$false})
    $charRows | Export-Csv $CharTsv -Delimiter "`t" -NoTypeInformation -Encoding UTF8

    $lowRows = @($charRows | Where-Object { [int]$_.count -le 2 })
    $lowRows | Export-Csv $LowFreqTsv -Delimiter "`t" -NoTypeInformation -Encoding UTF8

    $uniqueSorted = @($charCount.Keys | Sort-Object { [int][char]$_ })
    ($uniqueSorted -join "") | Set-Content $UniqueTxt -Encoding UTF8

    Write-Host "Unique Hangul syllables : $($uniqueSorted.Count)"
    Write-Host "Low-frequency <=2      : $($lowRows.Count)"

    Write-Section "8/9 - Summary / GPU after"

    Save-NvidiaSmi $GpuAfter

    $times = [double[]]@($okRows | ForEach-Object {
        if ($_.wall_seconds) { [double]$_.wall_seconds }
    })
    $meanSec = if ($times.Count -gt 0) { ($times | Measure-Object -Average).Average } else { 0 }
    $minSec  = if ($times.Count -gt 0) { ($times | Measure-Object -Minimum).Minimum } else { 0 }
    $maxSec  = if ($times.Count -gt 0) { ($times | Measure-Object -Maximum).Maximum } else { 0 }

    @(
        "Naruto PSP Stage 38E - Full OCR",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: $(if($failedRows.Count -eq 0 -and $okRows.Count -eq $ExpectedTotal){'SUCCESS'}else{'PARTIAL'})",
        "",
        "Source:",
        "Part1=$($part1.Count)",
        "Part2=$($part2.Count)",
        "Total=$($SourceFrames.Count)",
        "",
        "OCR:",
        "OK=$($okRows.Count)",
        "Failed=$($failedRows.Count)",
        "ReviewFlag=$($reviewRows.Count)",
        ("MeanSec={0:N4}" -f $meanSec),
        ("MinSec={0:N4}" -f $minSec),
        ("MaxSec={0:N4}" -f $maxSec),
        ("ThisRunWallSec={0:N3}" -f $runTimer.Elapsed.TotalSeconds),
        "ServerRestarts=$($ServerSeq)",
        "",
        "Preliminary Hangul corpus:",
        "UniqueHangul=$($uniqueSorted.Count)",
        "LowFrequencyCountLE2=$($lowRows.Count)",
        "",
        "Prompt:",
        "Stage38D corrected B prompt",
        "",
        "Resume:",
        "Checkpoint=$Checkpoint",
        "",
        "Files:",
        "Results=$FinalCsv",
        "Review=$ReviewTsv",
        "CharFrequency=$CharTsv",
        "LowFrequency=$LowFreqTsv",
        "UniqueHangul=$UniqueTxt"
    ) | Set-Content $Summary -Encoding UTF8

    if ($failedRows.Count -gt 0) {
        throw "OCR 미완료 프레임이 $($failedRows.Count)장 남았습니다. 같은 스크립트를 다시 실행하면 실패분만 재개합니다."
    }
    if ($okRows.Count -ne $ExpectedTotal) {
        throw "OK 행 수가 2086이 아닙니다: $($okRows.Count)"
    }

    $Succeeded = $true

} catch {
    $Caught = $_
    $Succeeded = $false

    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38E FAILED / PARTIAL !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)

    try {
        if (Get-Command Stop-LlamaServer -ErrorAction SilentlyContinue) {
            Stop-LlamaServer
        }
    } catch {}

    @(
        "Naruto PSP Stage 38E FAILURE/PARTIAL",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        "Message:",
        $_.Exception.Message,
        "",
        "Resume note:",
        "성공한 프레임은 ocr_checkpoint.csv에 남아 있습니다.",
        "같은 스크립트를 다시 실행하면 OK 프레임은 건너뜁니다.",
        "",
        "Full error:",
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

} finally {
    Write-Section "9/9 - Package"

    try {
        if (Get-Command Stop-LlamaServer -ErrorAction SilentlyContinue) {
            Stop-LlamaServer
        }
    } catch {}

    try { Stop-Transcript | Out-Null } catch {}

    $PackageDir = Join-Path $StageDir "_upload_package"
    if (Test-Path $PackageDir) { Remove-Item $PackageDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

    $pack = @(
        $Summary,$FinalCsv,$Manifest,$ReviewTsv,$CharTsv,$LowFreqTsv,$UniqueTxt,
        $VersionTxt,$CmdTxt,$GpuBefore,$GpuAfter,$Transcript,$FailureTxt
    )

    # Checkpoint is useful when partial/failure and small enough even on success.
    if (Test-Path $Checkpoint) { $pack += $Checkpoint }

    foreach ($f in $pack) {
        if ($f -and (Test-Path $f)) {
            Copy-Item $f $PackageDir -Force
        }
    }

    foreach ($sl in $ServerLogFiles) {
        if ($sl -and (Test-Path $sl)) {
            Copy-Item $sl $PackageDir -Force
        }
    }

    if ($PSCommandPath -and (Test-Path $PSCommandPath)) {
        Copy-Item $PSCommandPath $PackageDir -Force
    }

    # Include at most 30 review/failure images for ChatGPT inspection.
    try {
        if (Test-Path $FinalCsv) {
            $rr = @(Import-Csv $FinalCsv | Where-Object {
                ($_.status -ne "OK") -or ($_.review_reason -and $_.review_reason.Trim().Length -gt 0)
            } | Select-Object -First 30)

            if ($rr.Count -gt 0) {
                $ReviewImageDir = Join-Path $PackageDir "review_images"
                New-Item -ItemType Directory -Force -Path $ReviewImageDir | Out-Null
                foreach ($r in $rr) {
                    $g = [int]$r.global_index
                    if ($SourceByGlobal.ContainsKey($g)) {
                        $src = $SourceByGlobal[$g].full_path
                        if (Test-Path $src) {
                            $dstName = ("g{0:D4}_{1}" -f $g,[IO.Path]::GetFileName($src))
                            Copy-Item $src (Join-Path $ReviewImageDir $dstName) -Force
                        }
                    }
                }
            }
        }
    } catch {}

    if ($Succeeded) {
        if (Test-Path $UploadZip) {
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_stage38e_full_ocr_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "STAGE 38E SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
        if (Test-Path $ArchiveDir) {
            Write-Host "Old logs/archive:"
            Write-Host "  $ArchiveDir"
        }
    } else {
        $failedDir = Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null

        Get-ChildItem $PackageDir -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $rel = $_.FullName.Substring($PackageDir.Length).TrimStart('\')
            $dst = Join-Path $failedDir $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }

        $failedZip = Join-Path $failedDir "naruto_stage38e_full_ocr_failed_upload.zip"
        Compress-Archive -Path (Join-Path $failedDir "*") -DestinationPath $failedZip -Force

        Write-Host ""
        Write-Host "STAGE 38E PARTIAL/FAILED"
        Write-Host "Checkpoint preserved:"
        Write-Host "  $Checkpoint"
        Write-Host "Failure ZIP:"
        Write-Host "  $failedZip"
        Write-Host ""
        Write-Host "같은 스크립트를 다시 실행하면 OK 프레임은 자동으로 건너뜁니다."
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Succeeded) { exit 1 }
exit 0
