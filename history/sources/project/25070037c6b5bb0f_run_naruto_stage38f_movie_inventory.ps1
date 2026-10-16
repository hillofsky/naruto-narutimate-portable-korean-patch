# Naruto PSP Stage 38F - PMF Movie Inventory
# KR movie inventory + US counterpart lookup + probe metadata + thumbnails
#
# Output:
#   analysis\stage38f_movie_inventory\
#       movie_inventory.tsv
#       movie_inventory.csv
#       PMF_LIST.txt
#       thumbnail_manifest.tsv
#       thumbnails\*.jpg
#       SUMMARY.txt
#   logs\naruto_stage38f_movie_inventory_upload.zip
#
# Notes:
# - KR expected PMFs: 22
# - Subtitle candidates: DA/DK/DM families; logo_* marked NO
# - ffprobe is preferred. ffmpeg stderr metadata is used as fallback.
# - If ffprobe/ffmpeg are missing, file inventory still completes with explicit status.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "stage38f_movie_inventory"
$StageDir   = Join-Path $Root "analysis\$StageName"
$ThumbDir   = Join-Path $StageDir "thumbnails"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_stage38f_movie_inventory_$Stamp.log"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$TsvPath    = Join-Path $StageDir "movie_inventory.tsv"
$CsvPath    = Join-Path $StageDir "movie_inventory.csv"
$ListTxt    = Join-Path $StageDir "PMF_LIST.txt"
$ThumbTsv   = Join-Path $StageDir "thumbnail_manifest.tsv"
$ToolTxt    = Join-Path $StageDir "TOOLS.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38f_movie_inventory_upload.zip"

$KrMovieDir = Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\movie"
$UsMovieDir = Join-Path $Root "us_extracted\PSP_GAME\USRDIR\movie"

$ExpectedKr = @(
    "da101.pmf","da102.pmf","da103.pmf","da201.pmf",
    "dk101.pmf","dk102.pmf","dk103.pmf","dk104.pmf","dk201.pmf","dk202.pmf",
    "dm001.pmf","dm002.pmf","dm003.pmf","dm004.pmf","dm005.pmf",
    "dm006.pmf","dm007.pmf","dm008.pmf","dm009.pmf","dm010.pmf",
    "logo_a.pmf","logo_c.pmf"
)

New-Item -ItemType Directory -Force -Path $LogsDir,$FailedRoot,$OldRoot | Out-Null

# Rotate transient Stage38F logs and previous success ZIP.
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName
$OldLogs = @(Get-ChildItem $LogsDir -File -Filter "naruto_stage38f_movie_inventory_*.log" -ErrorAction SilentlyContinue)
if ($OldLogs.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach ($f in $OldLogs) {
        Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force
    }
}

if (Test-Path $StageDir) {
    # Preserve previous results before replacing them.
    $oldResults = @(Get-ChildItem $StageDir -File -ErrorAction SilentlyContinue)
    if ($oldResults.Count -gt 0 -or (Test-Path $ThumbDir)) {
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage = Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
            Move-Item $_.FullName $oldStage -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $StageDir,$ThumbDir | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host (" " + $Text)
    Write-Host ("=" * 80)
}

function Find-Tool([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $Root "tools"),
        (Join-Path $Root "ffmpeg"),
        (Join-Path $Root "analysis"),
        "LOCAL_PATH",
        "LOCAL_PATH Files\ffmpeg",
        "LOCAL_PATH Files (x86)\ffmpeg"
    )

    foreach ($d in $candidates) {
        if (-not (Test-Path $d)) { continue }
        $hit = Get-ChildItem $d -File -Recurse -Filter $Name -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Quote-CmdArg([string]$Value) {
    if ($null -eq $Value) { return '""' }
    return '"' + $Value.Replace('"','\"') + '"'
}

function Invoke-NativeCapture {
    param(
        [string]$Exe,
        [string[]]$Arguments
    )

    $argLine = (($Arguments | ForEach-Object { Quote-CmdArg ([string]$_) }) -join " ")
    $cmdLine = (Quote-CmdArg $Exe) + " " + $argLine + " 2>&1"

    $lines = @(& $env:ComSpec /d /s /c $cmdLine)
    $exit = $LASTEXITCODE

    return [PSCustomObject]@{
        ExitCode = [int]$exit
        Lines = @($lines | ForEach-Object { [string]$_ })
        Text = ((@($lines | ForEach-Object { [string]$_ })) -join "`n")
    }
}

function Fraction-ToDouble([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    if ($Value -match '^(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)$') {
        $a = [double]$Matches[1]
        $b = [double]$Matches[2]
        if ($b -eq 0) { return $null }
        return ($a / $b)
    }
    $n = 0.0
    if ([double]::TryParse($Value,[ref]$n)) { return $n }
    return $null
}

function Seconds-ToTimestamp($Seconds) {
    if ($null -eq $Seconds) { return "" }
    try {
        $s = [double]$Seconds
        if ($s -lt 0) { return "" }
        $ts = [TimeSpan]::FromSeconds($s)
        if ($ts.TotalHours -ge 1) {
            return ("{0:00}:{1:00}:{2:00.000}" -f [int]$ts.TotalHours,$ts.Minutes,$ts.Seconds+$ts.Milliseconds/1000.0)
        }
        return ("{0:00}:{1:00.000}" -f $ts.Minutes,$ts.Seconds+$ts.Milliseconds/1000.0)
    } catch {
        return ""
    }
}

function Get-Family([string]$Name) {
    $n = $Name.ToLowerInvariant()
    if ($n -match '^da') { return "DA" }
    if ($n -match '^dk') { return "DK" }
    if ($n -match '^dm') { return "DM" }
    if ($n -match '^logo') { return "LOGO" }
    return "OTHER"
}

function Get-FfmpegFallbackMetadata([string]$FilePath,[string]$Ffmpeg) {
    $result = [ordered]@{
        duration_sec = $null
        width = $null
        height = $null
        fps = $null
        video_codec = ""
        audio_codec = ""
        audio_rate = ""
        audio_channels = ""
        fallback_status = "NOT_RUN"
    }

    if (-not $Ffmpeg) {
        $result.fallback_status = "FFMPEG_NOT_FOUND"
        return [PSCustomObject]$result
    }

    $r = Invoke-NativeCapture $Ffmpeg @("-hide_banner","-i",$FilePath)
    $t = $r.Text
    $result.fallback_status = "PARSED_FFMPEG_STDERR"

    $m = [regex]::Match($t,'DuratioLOCAL_PATH')
    if ($m.Success) {
        $result.duration_sec =
            ([double]$m.Groups[1].Value * 3600.0) +
            ([double]$m.Groups[2].Value * 60.0) +
            [double]$m.Groups[3].Value
    }

    $vm = [regex]::Match($t,'(?im)^\s*Stream .*VideLOCAL_PATH')
    if ($vm.Success) {
        $result.video_codec = $vm.Groups[1].Value.Trim()
        $result.width = [int]$vm.Groups[2].Value
        $result.height = [int]$vm.Groups[3].Value
        if ($vm.Groups[4].Success) { $result.fps = [double]$vm.Groups[4].Value }
    }

    $am = [regex]::Match($t,'(?im)^\s*Stream .*AudiLOCAL_PATH')
    if ($am.Success) {
        $result.audio_codec = $am.Groups[1].Value.Trim()
        if ($am.Groups[2].Success) { $result.audio_rate = $am.Groups[2].Value }
        if ($am.Groups[3].Success) { $result.audio_channels = $am.Groups[3].Value.Trim() }
    }

    return [PSCustomObject]$result
}

function Probe-Pmf([string]$FilePath,[string]$Ffprobe,[string]$Ffmpeg) {
    $out = [ordered]@{
        probe_status = ""
        duration_sec = $null
        width = $null
        height = $null
        fps = $null
        video_codec = ""
        audio_codec = ""
        audio_sample_rate = ""
        audio_channels = ""
        video_streams = 0
        audio_streams = 0
        probe_error = ""
    }

    if ($Ffprobe) {
        $args = @(
            "-v","error",
            "-show_entries","format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels",
            "-of","json",
            $FilePath
        )
        $r = Invoke-NativeCapture $Ffprobe $args

        if ($r.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($r.Text)) {
            try {
                $j = $r.Text | ConvertFrom-Json

                if ($j.format -and $j.format.duration) {
                    $out.duration_sec = [double]$j.format.duration
                }

                $streams = @($j.streams)
                $videos = @($streams | Where-Object codec_type -eq "video")
                $audios = @($streams | Where-Object codec_type -eq "audio")

                $out.video_streams = $videos.Count
                $out.audio_streams = $audios.Count

                if ($videos.Count -gt 0) {
                    $v = $videos[0]
                    if ($v.width) { $out.width = [int]$v.width }
                    if ($v.height) { $out.height = [int]$v.height }
                    if ($v.codec_name) { $out.video_codec = [string]$v.codec_name }

                    $fps = $null
                    if ($v.avg_frame_rate) { $fps = Fraction-ToDouble ([string]$v.avg_frame_rate) }
                    if ($null -eq $fps -and $v.r_frame_rate) {
                        $fps = Fraction-ToDouble ([string]$v.r_frame_rate)
                    }
                    if ($null -ne $fps) { $out.fps = [double]$fps }
                }

                if ($audios.Count -gt 0) {
                    $a = $audios[0]
                    if ($a.codec_name) { $out.audio_codec = [string]$a.codec_name }
                    if ($a.sample_rate) { $out.audio_sample_rate = [string]$a.sample_rate }
                    if ($a.channels) { $out.audio_channels = [string]$a.channels }
                }

                $out.probe_status = "FFPROBE_OK"
                return [PSCustomObject]$out
            } catch {
                $out.probe_error = "ffprobe JSON parse: " + $_.Exception.Message
            }
        } else {
            $out.probe_error = $r.Text
        }
    }

    # Fallback parser from ffmpeg -i stderr.
    $fb = Get-FfmpegFallbackMetadata $FilePath $Ffmpeg
    if ($null -ne $fb.duration_sec) { $out.duration_sec = $fb.duration_sec }
    if ($null -ne $fb.width) { $out.width = $fb.width }
    if ($null -ne $fb.height) { $out.height = $fb.height }
    if ($null -ne $fb.fps) { $out.fps = $fb.fps }
    if ($fb.video_codec) { $out.video_codec = $fb.video_codec }
    if ($fb.audio_codec) { $out.audio_codec = $fb.audio_codec }
    if ($fb.audio_rate) { $out.audio_sample_rate = $fb.audio_rate }
    if ($fb.audio_channels) { $out.audio_channels = $fb.audio_channels }

    if ($fb.fallback_status -eq "PARSED_FFMPEG_STDERR") {
        $out.probe_status = "FFMPEG_FALLBACK"
    } elseif (-not $Ffprobe -and -not $Ffmpeg) {
        $out.probe_status = "NO_PROBE_TOOL"
    } elseif (-not $Ffprobe) {
        $out.probe_status = "FFMPEG_FALLBACK_FAILED"
    } else {
        $out.probe_status = "PROBE_FAILED"
    }

    return [PSCustomObject]$out
}

function Extract-Thumbnail {
    param(
        [string]$Ffmpeg,
        [string]$InputFile,
        [double]$Timestamp,
        [string]$OutputFile
    )

    if (-not $Ffmpeg) { return "FFMPEG_NOT_FOUND" }

    $timeArg = "{0:0.000}" -f [Math]::Max(0.0,$Timestamp)
    $args = @(
        "-y",
        "-hide_banner",
        "-loglevel","error",
        "-ss",$timeArg,
        "-i",$InputFile,
        "-frames:v","1",
        "-vf","scale=480:-2:force_original_aspect_ratio=decrease",
        "-q:v","5",
        $OutputFile
    )

    $r = Invoke-NativeCapture $Ffmpeg $args
    if ($r.ExitCode -eq 0 -and (Test-Path $OutputFile)) { return "OK" }
    return ("FAILED: " + (($r.Text -replace "`r?`n"," ") | ForEach-Object {
        if ($_.Length -gt 180) { $_.Substring(0,180) } else { $_ }
    }))
}

$Succeeded = $false
$Rows = @()
$ThumbRows = @()

Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto Stage38F - PMF Movie Inventory"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "KR dir  : $KrMovieDir"
    Write-Host "US dir  : $UsMovieDir"

    if (-not (Test-Path $KrMovieDir)) {
        throw "KR movie 폴더를 찾지 못했습니다: $KrMovieDir"
    }

    Write-Section "1/6 - Find probe tools"

    $Ffprobe = Find-Tool "ffprobe.exe"
    if (-not $Ffprobe) { $Ffprobe = Find-Tool "ffprobe" }
    $Ffmpeg = Find-Tool "ffmpeg.exe"
    if (-not $Ffmpeg) { $Ffmpeg = Find-Tool "ffmpeg" }

    Write-Host "ffprobe : $(if($Ffprobe){$Ffprobe}else{'NOT FOUND'})"
    Write-Host "ffmpeg  : $(if($Ffmpeg){$Ffmpeg}else{'NOT FOUND'})"

    @(
        "Timestamp=$Stamp",
        "ffprobe=$(if($Ffprobe){$Ffprobe}else{'NOT FOUND'})",
        "ffmpeg=$(if($Ffmpeg){$Ffmpeg}else{'NOT FOUND'})"
    ) | Set-Content $ToolTxt -Encoding UTF8

    Write-Section "2/6 - Enumerate KR PMFs"

    $KrPmfs = @(Get-ChildItem $KrMovieDir -File -Filter "*.pmf" | Sort-Object Name)
    Write-Host "KR PMF count: $($KrPmfs.Count)"

    $actualNames = @($KrPmfs | ForEach-Object { $_.Name.ToLowerInvariant() })
    $missingExpected = @($ExpectedKr | Where-Object { $actualNames -notcontains $_.ToLowerInvariant() })
    $unexpected = @($KrPmfs | Where-Object { $ExpectedKr -notcontains $_.Name })

    if ($missingExpected.Count -gt 0) {
        Write-Host "Missing expected:"
        $missingExpected | ForEach-Object { Write-Host "  $_" }
    }
    if ($unexpected.Count -gt 0) {
        Write-Host "Unexpected KR PMFs:"
        $unexpected | ForEach-Object { Write-Host "  $($_.Name)" }
    }

    Write-Host ""
    $KrPmfs | ForEach-Object {
        Write-Host ("  {0,-12} {1,10:N0} bytes" -f $_.Name,$_.Length)
    }

    Write-Section "3/6 - Probe metadata"

    $i = 0
    foreach ($f in $KrPmfs) {
        $i++
        Write-Host ""
        Write-Host ("[{0,2}/{1}] {2}" -f $i,$KrPmfs.Count,$f.Name)

        $probe = Probe-Pmf $f.FullName $Ffprobe $Ffmpeg
        $hash = (Get-FileHash $f.FullName -Algorithm SHA256).Hash

        $base = [IO.Path]::GetFileNameWithoutExtension($f.Name)
        $sameUs = if (Test-Path $UsMovieDir) { Join-Path $UsMovieDir $f.Name } else { $null }
        $eName = $base + "e.pmf"
        $eUs = if (Test-Path $UsMovieDir) { Join-Path $UsMovieDir $eName } else { $null }

        $sameExists = ($sameUs -and (Test-Path $sameUs))
        $eExists = ($eUs -and (Test-Path $eUs))

        $family = Get-Family $f.Name
        $subtitleCandidate = if ($family -eq "LOGO") { "NO" } else { "YES" }

        $durationText = Seconds-ToTimestamp $probe.duration_sec
        $res = ""
        if ($probe.width -and $probe.height) { $res = "$($probe.width)x$($probe.height)" }

        Write-Host ("  status={0} duration={1} res={2} fps={3} v={4} a={5}" -f
            $probe.probe_status,
            $(if($durationText){$durationText}else{"?"}),
            $(if($res){$res}else{"?"}),
            $(if($null -ne $probe.fps){("{0:N3}" -f [double]$probe.fps)}else{"?"}),
            $(if($probe.video_codec){$probe.video_codec}else{"?"}),
            $(if($probe.audio_codec){$probe.audio_codec}else{"?"})
        )

        $Rows += [PSCustomObject]@{
            filename = $f.Name
            family = $family
            subtitle_candidate = $subtitleCandidate
            kr_bytes = $f.Length
            kr_mib = [Math]::Round($f.Length / 1MB,3)
            sha256 = $hash
            probe_status = $probe.probe_status
            duration_sec = if($null -ne $probe.duration_sec){[Math]::Round([double]$probe.duration_sec,3)}else{""}
            duration = $durationText
            width = if($null -ne $probe.width){$probe.width}else{""}
            height = if($null -ne $probe.height){$probe.height}else{""}
            resolution = $res
            fps = if($null -ne $probe.fps){[Math]::Round([double]$probe.fps,6)}else{""}
            video_codec = $probe.video_codec
            audio_codec = $probe.audio_codec
            audio_sample_rate = $probe.audio_sample_rate
            audio_channels = $probe.audio_channels
            us_same_name_exists = if($sameExists){"YES"}else{"NO"}
            us_same_name_bytes = if($sameExists){(Get-Item $sameUs).Length}else{""}
            us_e_name = $eName
            us_e_exists = if($eExists){"YES"}else{"NO"}
            us_e_bytes = if($eExists){(Get-Item $eUs).Length}else{""}
            probe_error = ($probe.probe_error -replace "`r?`n"," ")
        }
    }

    $Rows | Export-Csv $CsvPath -NoTypeInformation -Encoding UTF8
    $Rows | Export-Csv $TsvPath -Delimiter "`t" -NoTypeInformation -Encoding UTF8

    Write-Section "4/6 - Extract 10% / 50% / 90% thumbnails"

    foreach ($row in $Rows) {
        $src = Join-Path $KrMovieDir $row.filename
        $dur = 0.0
        $hasDuration = $false
        if ($row.duration_sec -ne "") {
            try {
                $dur = [double]$row.duration_sec
                if ($dur -gt 0) { $hasDuration = $true }
            } catch {}
        }

        foreach ($point in @(
            [PSCustomObject]@{label="p10";ratio=0.10},
            [PSCustomObject]@{label="p50";ratio=0.50},
            [PSCustomObject]@{label="p90";ratio=0.90}
        )) {
            $ts = if($hasDuration){[Math]::Max(0.0,[Math]::Min($dur-0.05,$dur*$point.ratio))}else{0.5}
            $base = [IO.Path]::GetFileNameWithoutExtension($row.filename)
            $out = Join-Path $ThumbDir ("{0}_{1}.jpg" -f $base,$point.label)

            $status = Extract-Thumbnail $Ffmpeg $src $ts $out

            Write-Host ("  {0,-12} {1} @ {2:N3}s -> {3}" -f $row.filename,$point.label,$ts,$status)

            $ThumbRows += [PSCustomObject]@{
                filename = $row.filename
                point = $point.label
                ratio = $point.ratio
                timestamp_sec = [Math]::Round($ts,3)
                thumbnail = if(Test-Path $out){[IO.Path]::GetFileName($out)}else{""}
                status = $status
            }
        }
    }

    $ThumbRows | Export-Csv $ThumbTsv -Delimiter "`t" -NoTypeInformation -Encoding UTF8

    Write-Section "5/6 - Summary"

    $candidateRows = @($Rows | Where-Object subtitle_candidate -eq "YES")
    $logoRows = @($Rows | Where-Object subtitle_candidate -eq "NO")
    $probeOk = @($Rows | Where-Object { $_.probe_status -eq "FFPROBE_OK" -or $_.probe_status -eq "FFMPEG_FALLBACK" })
    $thumbOk = @($ThumbRows | Where-Object status -eq "OK")

    $durationSum = 0.0
    foreach ($r in $candidateRows) {
        if ($r.duration_sec -ne "") {
            try { $durationSum += [double]$r.duration_sec } catch {}
        }
    }

    @(
        "Naruto PSP Stage38F - PMF Movie Inventory",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: SUCCESS",
        "",
        "KR PMF count=$($KrPmfs.Count)",
        "Expected KR count=22",
        "Subtitle candidates=$($candidateRows.Count)",
        "Logo/non-subtitle candidates=$($logoRows.Count)",
        "Probe metadata available=$($probeOk.Count)/$($Rows.Count)",
        "Thumbnails OK=$($thumbOk.Count)/$($ThumbRows.Count)",
        ("Candidate total duration sec={0:N3}" -f $durationSum),
        ("Candidate total duration={0}" -f (Seconds-ToTimestamp $durationSum)),
        "",
        "KR movie dir=$KrMovieDir",
        "US movie dir=$UsMovieDir",
        "ffprobe=$(if($Ffprobe){$Ffprobe}else{'NOT FOUND'})",
        "ffmpeg=$(if($Ffmpeg){$Ffmpeg}else{'NOT FOUND'})",
        "",
        "Next:",
        "Use movie_inventory.tsv + thumbnails to identify DA/DK/DM contents,",
        "then map YouTube OCR timeline to each PMF for Stage39B subtitle alignment."
    ) | Set-Content $Summary -Encoding UTF8

    @(
        "KR PMF LIST",
        "===========",
        ""
    ) + @($Rows | ForEach-Object {
        "{0,-12} family={1,-4} subtitle={2,-3} duration={3,-12} res={4,-9} fps={5}" -f
            $_.filename,$_.family,$_.subtitle_candidate,$_.duration,$_.resolution,$_.fps
    }) | Set-Content $ListTxt -Encoding UTF8

    Get-Content $Summary | ForEach-Object { Write-Host $_ }

    $Succeeded = $true

} catch {
    $Succeeded = $false
    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38F FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)

    @(
        "Naruto PSP Stage38F FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        $_.Exception.Message,
        "",
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

} finally {
    Write-Section "6/6 - Package"

    try { Stop-Transcript | Out-Null } catch {}

    $PackageDir = Join-Path $StageDir "_upload_package"
    if (Test-Path $PackageDir) { Remove-Item $PackageDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

    foreach ($f in @(
        $Summary,$TsvPath,$CsvPath,$ListTxt,$ThumbTsv,$ToolTxt,$Transcript,$FailureTxt
    )) {
        if ($f -and (Test-Path $f)) {
            Copy-Item $f $PackageDir -Force
        }
    }

    if ($PSCommandPath -and (Test-Path $PSCommandPath)) {
        Copy-Item $PSCommandPath $PackageDir -Force
    }

    if (Test-Path $ThumbDir) {
        $thumbFiles = @(Get-ChildItem $ThumbDir -File -Filter "*.jpg" -ErrorAction SilentlyContinue)
        if ($thumbFiles.Count -gt 0) {
            $pkgThumb = Join-Path $PackageDir "thumbnails"
            New-Item -ItemType Directory -Force -Path $pkgThumb | Out-Null
            $thumbFiles | ForEach-Object { Copy-Item $_.FullName $pkgThumb -Force }
        }
    }

    if ($Succeeded) {
        if (Test-Path $UploadZip) {
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_stage38f_movie_inventory_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "STAGE 38F SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    } else {
        $failedDir = Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null

        Get-ChildItem $PackageDir -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $rel = $_.FullName.Substring($PackageDir.Length).TrimStart('\')
            $dst = Join-Path $failedDir $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }

        $failedZip = Join-Path $failedDir "naruto_stage38f_movie_inventory_failed_upload.zip"
        Compress-Archive -Path (Join-Path $failedDir "*") -DestinationPath $failedZip -Force

        Write-Host ""
        Write-Host "STAGE 38F FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $failedZip"
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Succeeded) { exit 1 }
exit 0
