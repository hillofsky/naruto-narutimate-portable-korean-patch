# Naruto PSP MOV03A - dm001 PMF audio extraction test
# 1) Try current FFmpeg directly.
# 2) If PMF audio is not exposed, optionally fetch the latest open-source
#    pmftools-plus release from GitHub and try psmfdump -> OMA -> FFmpeg WAV.
# 3) Leave dm001.wav locally for CapCut sync testing.
# 4) Package only compact diagnostics/logs for upload (WAV is not zipped).

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "mov03a_audio_extract_test"
$StageDir   = Join-Path $Root "analysis\mov\$StageName"
$WorkDir    = Join-Path $StageDir "work"
$ToolsDir   = Join-Path $Root "tools\pmftools-plus"
$LogsDir    = Join-Path $Root "logs"
$OldRoot    = Join-Path $LogsDir "old"
$FailedRoot = Join-Path $LogsDir "failed"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_$Stamp.log"
$UploadZip  = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_upload.zip"
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName

$Pmf = Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\movie\dm001.pmf"
$OutWav = Join-Path $StageDir "dm001.wav"
$ProbeJson = Join-Path $StageDir "ffprobe_dm001.json"
$FfmpegVersion = Join-Path $StageDir "ffmpeg_version.txt"
$DirectLog = Join-Path $StageDir "ffmpeg_direct_extract.log"
$PsmfHelp = Join-Path $StageDir "psmfdump_help.txt"
$PsmfAttempts = Join-Path $StageDir "psmfdump_attempts.txt"
$Summary = Join-Path $StageDir "SUMMARY.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$ToolInfo = Join-Path $StageDir "TOOL_INFO.txt"

New-Item -ItemType Directory -Force -Path $StageDir,$WorkDir,$LogsDir,$OldRoot,$FailedRoot | Out-Null

function Find-FirstFile {
    param([string[]]$Roots,[string]$Filter)
    foreach($r in $Roots){
        if(-not(Test-Path $r)){continue}
        $hit=Get-ChildItem $r -File -Filter $Filter -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if($hit){return $hit.FullName}
    }
    return $null
}

function Run-CmdCapture {
    param(
        [string]$Exe,
        [string[]]$Args,
        [string]$LogPath,
        [string]$WorkingDirectory = ""
    )
    if(Test-Path $LogPath){Remove-Item $LogPath -Force}
    $argLine = ($Args | ForEach-Object {
        if([string]$_ -match '[\s"]'){
            '"' + ([string]$_).Replace('"','\"') + '"'
        }else{
            [string]$_
        }
    }) -join ' '

    $cmd = '"' + $Exe + '" ' + $argLine
    if($WorkingDirectory){
        $old = Get-Location
        Set-Location $WorkingDirectory
    }
    try{
        $output = & cmd.exe /d /s /c "$cmd 2>&1"
        $ec = $LASTEXITCODE
        @($output) | Set-Content $LogPath -Encoding UTF8
        return [PSCustomObject]@{ ExitCode=$ec; Output=@($output); Command=$cmd }
    }finally{
        if($WorkingDirectory){Set-Location $old}
    }
}

function Is-ValidWav {
    param([string]$Path,[string]$Ffprobe)
    if(-not(Test-Path $Path)){return $false}
    $fi=Get-Item $Path
    if($fi.Length -lt 4096){return $false}
    try{
        $json=& $Ffprobe -v error -show_streams -show_format -of json $Path 2>$null
        if($LASTEXITCODE -ne 0){return $false}
        $o=($json -join "`n")|ConvertFrom-Json
        $aud=@($o.streams|Where-Object{$_.codec_type -eq "audio"})
        return ($aud.Count -gt 0)
    }catch{return $false}
}

function Save-WavInfo {
    param([string]$Path,[string]$Ffprobe,[string]$OutPath)
    & $Ffprobe -v error -show_streams -show_format -of json $Path 2>&1 |
        Set-Content $OutPath -Encoding UTF8
}

function Download-PmfToolsPlus {
    param([string]$Dest)
    Write-Host ""
    Write-Host "FFmpeg direct extraction did not produce audio."
    Write-Host "Trying open-source pmftools-plus / psmfdump fallback..."

    New-Item -ItemType Directory -Force -Path $Dest | Out-Null

    $api="httpLOCAL_PATH"
    $headers=@{"User-Agent"="Naruto-MOV03A"}
    try{
        $rel=Invoke-RestMethod -Uri $api -Headers $headers -UseBasicParsing
    }catch{
        throw "pmftools-plus GitHub release metadata download failed: $($_.Exception.Message)"
    }

    $assets=@($rel.assets)
    if($assets.Count -eq 0){throw "pmftools-plus latest release has no assets."}

    # Prefer a Windows/prebuilt zip that is not source-only.
    $asset=$assets |
        Where-Object {
            $_.name -match '\.zip$' -and
            $_.name -notmatch '(?i)source|src'
        } |
        Sort-Object @{
            Expression={
                if($_.name -match '(?i)win|windows|release|pmftools'){0}else{1}
            }
        },name |
        Select-Object -First 1

    if(-not $asset){
        throw "Could not identify a prebuilt ZIP asset in pmftools-plus latest release."
    }

    $zip=Join-Path $Dest $asset.name
    Write-Host "Release: $($rel.tag_name)"
    Write-Host "Asset  : $($asset.name)"
    Write-Host "URL    : $($asset.browser_download_url)"

    Invoke-WebRequest -Uri $asset.browser_download_url -Headers $headers -OutFile $zip -UseBasicParsing

    $hash=(Get-FileHash $zip -Algorithm SHA256).Hash
    @(
        "repo=httpLOCAL_PATH",
        "release=$($rel.tag_name)",
        "asset=$($asset.name)",
        "url=$($asset.browser_download_url)",
        "sha256=$hash"
    ) | Set-Content $ToolInfo -Encoding UTF8

    $extract=Join-Path $Dest "release"
    if(Test-Path $extract){Remove-Item $extract -Recurse -Force}
    Expand-Archive $zip -DestinationPath $extract -Force
    return $extract
}

function Try-PsmfDump {
    param([string]$PsmfDump,[string]$Pmf,[string]$Work,[string]$Ffmpeg,[string]$Ffprobe,[string]$Wav)

    Write-Host "psmfdump: $PsmfDump"

    # Capture help/usage first.
    $help=@()
    foreach($a in @(@("--help"),@("-h"),@())){
        try{
            $r=Run-CmdCapture -Exe $PsmfDump -Args $a -LogPath (Join-Path $Work "psmfdump_help_tmp.txt") -WorkingDirectory $Work
            $help += "COMMAND: $($r.Command)"
            $help += $r.Output
            $help += ""
        }catch{
            $help += "HELP ERROR: $($_.Exception.Message)"
        }
    }
    $help|Set-Content $PsmfHelp -Encoding UTF8

    # Try common psmfdump invocation forms. After every attempt, detect newly
    # created .oma/.at3/.aa3 audio files and ask FFmpeg to decode them.
    $attemptSets=@(
        @($Pmf),
        @($Pmf,$Work),
        @("-i",$Pmf,"-o",$Work),
        @("-i",$Pmf),
        @("--input",$Pmf,"--output",$Work)
    )

    $report=@()
    $attemptNo=0
    foreach($args in $attemptSets){
        $attemptNo++
        Write-Host "  psmfdump attempt $attemptNo/$($attemptSets.Count)"
        $before=@{}
        Get-ChildItem $Work -File -Recurse -ErrorAction SilentlyContinue|ForEach-Object{$before[$_.FullName]=$_.Length}

        $log=Join-Path $Work ("psmfdump_attempt_{0:D2}.log" -f $attemptNo)
        try{
            $r=Run-CmdCapture -Exe $PsmfDump -Args $args -LogPath $log -WorkingDirectory $Work
            $report += "[$attemptNo] exit=$($r.ExitCode) cmd=$($r.Command)"
        }catch{
            $report += "[$attemptNo] ERROR $($_.Exception.Message)"
        }

        $audio=@(
            Get-ChildItem $Work -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {$_.Extension -match '(?i)^\.(oma|at3|aa3|wav)$'} |
            Sort-Object LastWriteTime -Descending
        )

        foreach($af in $audio){
            $report += "  audio_candidate=$($af.FullName) bytes=$($af.Length)"
            if($af.Extension -ieq ".wav"){
                if(Is-ValidWav $af.FullName $Ffprobe){
                    Copy-Item $af.FullName $Wav -Force
                    $report|Set-Content $PsmfAttempts -Encoding UTF8
                    return $true
                }
                continue
            }

            $decLog=Join-Path $Work ("decode_{0}_{1}.log" -f $attemptNo,$af.BaseName)
            $rr=Run-CmdCapture -Exe $Ffmpeg -Args @(
                "-y","-hide_banner","-loglevel","info",
                "-i",$af.FullName,
                "-vn","-c:a","pcm_s16le","-ar","48000","-ac","2",
                $Wav
            ) -LogPath $decLog -WorkingDirectory $Work
            $report += "  decode_exit=$($rr.ExitCode) -> $Wav"

            if(Is-ValidWav $Wav $Ffprobe){
                $report|Set-Content $PsmfAttempts -Encoding UTF8
                return $true
            }
            if(Test-Path $Wav){Remove-Item $Wav -Force}
        }
    }

    $report|Set-Content $PsmfAttempts -Encoding UTF8
    return $false
}

# Rotate only old MOV03A outputs.
if(Test-Path $StageDir){
    $existing=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -ne "work"})
    if($existing.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage=Join-Path $ArchiveDir "previous_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $existing){Move-Item $x.FullName $oldStage -Force}
    }
}
if(Test-Path $WorkDir){Remove-Item $WorkDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false
$Method="NONE"

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03A - dm001 PMF audio extraction test"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "PMF     : $Pmf"

    if(-not(Test-Path $Pmf)){throw "dm001.pmf not found: $Pmf"}

    $ffmpeg=Find-FirstFile -Roots @(
        "LOCAL_PATH","LOCAL_PATH",
        (Join-Path $Root "tools"),
        (Join-Path $Root "analysis")
    ) -Filter "ffmpeg.exe"

    $ffprobe=Find-FirstFile -Roots @(
        "LOCAL_PATH","LOCAL_PATH",
        (Join-Path $Root "tools"),
        (Join-Path $Root "analysis")
    ) -Filter "ffprobe.exe"

    if(-not $ffmpeg -or -not $ffprobe){
        throw "ffmpeg/ffprobe not found. ffmpeg=$ffmpeg ffprobe=$ffprobe"
    }

    Write-Host "ffmpeg : $ffmpeg"
    Write-Host "ffprobe: $ffprobe"

    # Environment diagnostics.
    & $ffmpeg -version 2>&1 | Set-Content $FfmpegVersion -Encoding UTF8
    & $ffprobe -v error -show_streams -show_format -of json $Pmf 2>&1 |
        Set-Content $ProbeJson -Encoding UTF8

    Write-Host ""
    Write-Host "[1/3] Direct FFmpeg PMF -> WAV"
    if(Test-Path $OutWav){Remove-Item $OutWav -Force}

    $r=Run-CmdCapture -Exe $ffmpeg -Args @(
        "-y","-hide_banner","-loglevel","info",
        "-i",$Pmf,
        "-map","0:a:0?","-vn",
        "-c:a","pcm_s16le","-ar","48000","-ac","2",
        $OutWav
    ) -LogPath $DirectLog -WorkingDirectory $WorkDir

    Write-Host "  exit=$($r.ExitCode)"

    if(Is-ValidWav $OutWav $ffprobe){
        $Method="FFMPEG_DIRECT"
        $Success=$true
        Write-Host "  SUCCESS: FFmpeg decoded PMF audio directly."
    }else{
        if(Test-Path $OutWav){Remove-Item $OutWav -Force}

        Write-Host ""
        Write-Host "[2/3] psmfdump fallback"

        # Prefer an already-installed psmfdump.
        $psmfdump=Find-FirstFile -Roots @(
            $ToolsDir,
            (Join-Path $Root "tools"),
            $Root
        ) -Filter "psmfdump.exe"

        if(-not $psmfdump){
            $releaseDir=Download-PmfToolsPlus -Dest $ToolsDir
            $psmfdump=Find-FirstFile -Roots @($releaseDir) -Filter "psmfdump.exe"
        }

        if(-not $psmfdump){
            throw "psmfdump.exe was not found even after pmftools-plus setup."
        }

        $ok=Try-PsmfDump -PsmfDump $psmfdump -Pmf $Pmf -Work $WorkDir `
            -Ffmpeg $ffmpeg -Ffprobe $ffprobe -Wav $OutWav

        if($ok){
            $Method="PSMFDUMP_OMA_FFMPEG"
            $Success=$true
            Write-Host "  SUCCESS: psmfdump audio -> FFmpeg WAV."
        }
    }

    Write-Host ""
    Write-Host "[3/3] Validate output"

    if(-not $Success -or -not(Is-ValidWav $OutWav $ffprobe)){
        throw "Could not create a valid dm001.wav. Upload the failure ZIP; it contains FFmpeg/psmfdump diagnostics."
    }

    $WavInfo=Join-Path $StageDir "dm001_wav_info.json"
    Save-WavInfo -Path $OutWav -Ffprobe $ffprobe -OutPath $WavInfo

    $pmfDur=""
    $wavDur=""
    try{
        $pj=(Get-Content $ProbeJson -Raw|ConvertFrom-Json)
        $pmfDur=[double]$pj.format.duration
    }catch{}
    try{
        $wj=(Get-Content $WavInfo -Raw|ConvertFrom-Json)
        $wavDur=[double]$wj.format.duration
    }catch{}

    $delta=""
    if($pmfDur -ne "" -and $wavDur -ne ""){
        $delta=[math]::Abs([double]$pmfDur-[double]$wavDur)
    }

    @(
        "Naruto PSP MOV03A - dm001 audio extraction",
        ("="*76),
        "",
        "Result=SUCCESS",
        "Method=$Method",
        "PMF=$Pmf",
        "WAV=$OutWav",
        "WAV_bytes=$((Get-Item $OutWav).Length)",
        "PMF_duration_sec=$pmfDur",
        "WAV_duration_sec=$wavDur",
        "duration_abs_delta_sec=$delta",
        "",
        "Next manual test:",
        "1. Import Stage37 source video and dm001.wav into CapCut.",
        "2. Select both timeline items.",
        "3. Use video/audio synchronization (audio waveform sync).",
        "4. Record the matched source timestamp for dm001 start.",
        "",
        "The WAV is intentionally NOT included in the upload ZIP.",
        "It remains here:",
        $OutWav
    ) | Set-Content $Summary -Encoding UTF8

}catch{
    @(
        "Naruto PSP MOV03A FAILED",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
    Write-Host ""
    Write-Host "!!!!!!!! MOV03A FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt","ffprobe_dm001.json","ffmpeg_version.txt",
        "ffmpeg_direct_extract.log","psmfdump_help.txt","psmfdump_attempts.txt",
        "TOOL_INFO.txt","dm001_wav_info.json"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    if(Test-Path $WorkDir){
        $diag=Join-Path $Pkg "work_logs"
        New-Item -ItemType Directory -Force -Path $diag|Out-Null
        Get-ChildItem $WorkDir -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {$_.Extension -in @(".log",".txt")} |
            ForEach-Object {
                Copy-Item $_.FullName (Join-Path $diag $_.Name) -Force
            }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    foreach($s in @(
        (Join-Path $Root "run_naruto_mov03a_audio_extract_test.ps1")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03a_audio_extract_test_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "MOV03A SUCCESS"
        Write-Host "WAV:"
        Write-Host "  $OutWav"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue|ForEach-Object{
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_mov03a_audio_extract_test_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03A FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
