# Naruto PSP MOV03A FIX3 - dm001 PMF audio extraction
#
# FIX3 deliberately avoids Start-Process ArgumentList builders and generic
# parameter names such as $Args / $Input. Native tools are invoked directly
# with PowerShell's call operator (&), which preserves each quoted variable as
# a distinct argument even when paths contain spaces.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "D:\narutimate portable"
$StageName  = "mov03a_audio_extract_test"
$StageDir   = Join-Path $Root "analysis\mov\$StageName"
$WorkDir    = Join-Path $StageDir "work"
$ToolsDir   = Join-Path $Root "tools\pmftools-plus"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_FIX3_$Stamp.log"
$UploadZip  = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_upload.zip"
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName

$Pmf      = Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\movie\dm001.pmf"
$AudioOma = Join-Path $WorkDir "dm001.oma"
$Video264 = Join-Path $WorkDir "dm001.264"
$OutWav   = Join-Path $StageDir "dm001.wav"

$Summary    = Join-Path $StageDir "SUMMARY.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$ProbePmf   = Join-Path $StageDir "ffprobe_dm001_pmf.json"
$ProbeOma   = Join-Path $StageDir "ffprobe_dm001_oma.json"
$ProbeWav   = Join-Path $StageDir "ffprobe_dm001_wav.json"
$PsmfStdout = Join-Path $StageDir "psmfdump_stdout.log"
$PsmfStderr = Join-Path $StageDir "psmfdump_stderr.log"
$DecodeOut  = Join-Path $StageDir "ffmpeg_oma_decode_stdout.log"
$DecodeErr  = Join-Path $StageDir "ffmpeg_oma_decode_stderr.log"
$Commands   = Join-Path $StageDir "COMMANDS.txt"

New-Item -ItemType Directory -Force -Path $StageDir,$WorkDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

function Find-FirstFile {
    param(
        [string[]]$SearchRoots,
        [string]$FileFilter
    )
    foreach($rootPath in $SearchRoots){
        if(-not(Test-Path $rootPath)){continue}
        $hit=Get-ChildItem $rootPath -File -Filter $FileFilter -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if($hit){return $hit.FullName}
    }
    return $null
}

function Save-Probe {
    param(
        [string]$ProbeExe,
        [string]$MediaPath,
        [string]$JsonPath
    )
    $errPath=$JsonPath+".stderr.txt"
    if(Test-Path $JsonPath){Remove-Item $JsonPath -Force}
    if(Test-Path $errPath){Remove-Item $errPath -Force}

    & $ProbeExe -v error -show_streams -show_format -of json $MediaPath `
        1> $JsonPath 2> $errPath
    $code=$LASTEXITCODE

    if((Test-Path $errPath) -and (Get-Item $errPath).Length -gt 0){
        Add-Content $JsonPath "`r`n--- STDERR ---"
        Get-Content $errPath | Add-Content $JsonPath
    }
    Remove-Item $errPath -Force -ErrorAction SilentlyContinue
    return $code
}

function Test-ValidWav {
    param(
        [string]$WavPath,
        [string]$ProbeExe
    )
    if(-not(Test-Path $WavPath)){return $false}
    if((Get-Item $WavPath).Length -lt 4096){return $false}

    $tmp=Join-Path $WorkDir "wav_validate.json"
    if(Test-Path $tmp){Remove-Item $tmp -Force}
    & $ProbeExe -v error -show_streams -show_format -of json $WavPath 1> $tmp 2>$null
    if($LASTEXITCODE -ne 0){return $false}
    try{
        $obj=Get-Content $tmp -Raw | ConvertFrom-Json
        return (@($obj.streams | Where-Object {$_.codec_type -eq "audio"}).Count -gt 0)
    }catch{
        return $false
    }
}

# Rotate previous MOV03A result files, but downloaded tools remain outside StageDir.
if(Test-Path $StageDir){
    $existing=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -ne "work"})
    if($existing.Count -gt 0){
        $oldStage=Join-Path $ArchiveDir "previous_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($item in $existing){
            Move-Item $item.FullName $oldStage -Force
        }
    }
}
if(Test-Path $WorkDir){Remove-Item $WorkDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03A FIX3 - dm001 PMF audio extraction"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host ""

    if(-not(Test-Path $Pmf)){throw "dm001.pmf not found: $Pmf"}

    $ffmpeg=Find-FirstFile `
        -SearchRoots @("C:\ffmpeg1","C:\ffmpeg",(Join-Path $Root "tools")) `
        -FileFilter "ffmpeg.exe"

    $ffprobe=Find-FirstFile `
        -SearchRoots @("C:\ffmpeg1","C:\ffmpeg",(Join-Path $Root "tools")) `
        -FileFilter "ffprobe.exe"

    $psmfdump=Find-FirstFile `
        -SearchRoots @($ToolsDir,(Join-Path $Root "tools")) `
        -FileFilter "psmfdump.exe"

    if(-not $ffmpeg){throw "ffmpeg.exe not found"}
    if(-not $ffprobe){throw "ffprobe.exe not found"}
    if(-not $psmfdump){throw "psmfdump.exe not found under $ToolsDir"}

    Write-Host "PMF      : $Pmf"
    Write-Host "psmfdump : $psmfdump"
    Write-Host "ffmpeg   : $ffmpeg"
    Write-Host "ffprobe  : $ffprobe"
    Write-Host ""

    @(
        'PSMFDUMP: "'+$psmfdump+'" "'+$Pmf+'" -a "'+$AudioOma+'" -v "'+$Video264+'"',
        'FFMPEG  : "'+$ffmpeg+'" -y -i "'+$AudioOma+'" -vn -c:a pcm_s16le -ar 48000 -ac 2 "'+$OutWav+'"'
    ) | Set-Content $Commands -Encoding UTF8

    Write-Host "[0/3] Probe PMF"
    $probeCode=Save-Probe -ProbeExe $ffprobe -MediaPath $Pmf -JsonPath $ProbePmf
    Write-Host "  ffprobe exit: $probeCode"

    foreach($target in @($AudioOma,$Video264,$OutWav,$PsmfStdout,$PsmfStderr,$DecodeOut,$DecodeErr)){
        if(Test-Path $target){Remove-Item $target -Force}
    }

    Write-Host ""
    Write-Host "[1/3] psmfdump exact PMF demux"
    Write-Host "  argv[0] = $Pmf"
    Write-Host "  argv[1] = -a"
    Write-Host "  argv[2] = $AudioOma"
    Write-Host "  argv[3] = -v"
    Write-Host "  argv[4] = $Video264"

    # Native invocation: each token below is a separate argument.
    & $psmfdump $Pmf "-a" $AudioOma "-v" $Video264 `
        1> $PsmfStdout 2> $PsmfStderr
    $psmfExit=$LASTEXITCODE

    Write-Host "  exit      : $psmfExit"
    Write-Host "  OMA exists: $(Test-Path $AudioOma)"
    if(Test-Path $AudioOma){
        Write-Host "  OMA bytes : $((Get-Item $AudioOma).Length)"
    }
    Write-Host "  264 exists: $(Test-Path $Video264)"
    if(Test-Path $Video264){
        Write-Host "  264 bytes : $((Get-Item $Video264).Length)"
    }

    if($psmfExit -ne 0){
        throw "psmfdump failed with exit code $psmfExit"
    }
    if(-not(Test-Path $AudioOma)){
        throw "psmfdump completed but dm001.oma was not created."
    }
    if((Get-Item $AudioOma).Length -lt 1024){
        throw "dm001.oma is unexpectedly small: $((Get-Item $AudioOma).Length) bytes"
    }

    Write-Host ""
    Write-Host "[2/3] Probe extracted OMA"
    $omaProbeCode=Save-Probe -ProbeExe $ffprobe -MediaPath $AudioOma -JsonPath $ProbeOma
    Write-Host "  ffprobe exit: $omaProbeCode"

    Write-Host ""
    Write-Host "[3/3] OMA -> 48 kHz stereo PCM WAV"
    & $ffmpeg -y -hide_banner -loglevel info `
        -i $AudioOma `
        -vn `
        -c:a pcm_s16le `
        -ar 48000 `
        -ac 2 `
        $OutWav `
        1> $DecodeOut 2> $DecodeErr
    $decodeExit=$LASTEXITCODE

    Write-Host "  ffmpeg exit: $decodeExit"
    Write-Host "  WAV exists : $(Test-Path $OutWav)"
    if(Test-Path $OutWav){
        Write-Host "  WAV bytes  : $((Get-Item $OutWav).Length)"
    }

    if($decodeExit -ne 0){
        throw "FFmpeg could not decode dm001.oma. Exit=$decodeExit"
    }
    if(-not(Test-ValidWav -WavPath $OutWav -ProbeExe $ffprobe)){
        throw "FFmpeg returned success but dm001.wav did not validate as audio."
    }

    Save-Probe -ProbeExe $ffprobe -MediaPath $OutWav -JsonPath $ProbeWav | Out-Null

    $pmfDur=""
    $wavDur=""
    $omaCodec=""
    try{
        $obj=Get-Content $ProbePmf -Raw | ConvertFrom-Json
        $pmfDur=[double]$obj.format.duration
    }catch{}
    try{
        $obj=Get-Content $ProbeWav -Raw | ConvertFrom-Json
        $wavDur=[double]$obj.format.duration
    }catch{}
    try{
        $obj=Get-Content $ProbeOma -Raw | ConvertFrom-Json
        $aud=@($obj.streams | Where-Object {$_.codec_type -eq "audio"} | Select-Object -First 1)
        if($aud.Count -gt 0){$omaCodec=$aud[0].codec_name}
    }catch{}

    $delta=""
    if($pmfDur -ne "" -and $wavDur -ne ""){
        $delta=[math]::Abs([double]$pmfDur-[double]$wavDur)
    }

    @(
        "Naruto PSP MOV03A FIX3 - dm001 audio extraction",
        ("="*76),
        "",
        "Result=SUCCESS",
        "Method=PSMFDUMP_OMA_FFMPEG",
        "PMF=$Pmf",
        "OMA=$AudioOma",
        "OMA_bytes=$((Get-Item $AudioOma).Length)",
        "OMA_codec=$omaCodec",
        "WAV=$OutWav",
        "WAV_bytes=$((Get-Item $OutWav).Length)",
        "PMF_duration_sec=$pmfDur",
        "WAV_duration_sec=$wavDur",
        "duration_abs_delta_sec=$delta",
        "",
        "CapCut:",
        "Import dm001.wav + Stage37 source video and run audio synchronization.",
        "The WAV stays local and is intentionally excluded from the upload ZIP."
    ) | Set-Content $Summary -Encoding UTF8

    $Success=$true

}catch{
    @(
        "Naruto PSP MOV03A FIX3 FAILED",
        "",
        $_.Exception.Message,
        "",
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

    Write-Host ""
    Write-Host "!!!!!!!! MOV03A FIX3 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message

}finally{
    try{Stop-Transcript | Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($name in @(
        "SUMMARY.txt","FAILURE.txt","COMMANDS.txt",
        "ffprobe_dm001_pmf.json","ffprobe_dm001_oma.json","ffprobe_dm001_wav.json",
        "psmfdump_stdout.log","psmfdump_stderr.log",
        "ffmpeg_oma_decode_stdout.log","ffmpeg_oma_decode_stderr.log"
    )){
        $item=Join-Path $StageDir $name
        if(Test-Path $item){Copy-Item $item $Pkg -Force}
    }

    if(Test-Path $AudioOma){
        @(
            "path=$AudioOma",
            "bytes=$((Get-Item $AudioOma).Length)"
        ) | Set-Content (Join-Path $Pkg "OMA_STATUS.txt") -Encoding UTF8
    }
    if(Test-Path $Video264){
        @(
            "path=$Video264",
            "bytes=$((Get-Item $Video264).Length)"
        ) | Set-Content (Join-Path $Pkg "H264_STATUS.txt") -Encoding UTF8
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    $self=Join-Path $Root "run_naruto_mov03a_audio_extract_test.ps1"
    if(Test-Path $self){Copy-Item $self $Pkg -Force}

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03a_audio_extract_test_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "MOV03A FIX3 SUCCESS"
        Write-Host "WAV:"
        Write-Host "  $OutWav"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"

    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object{
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }

        $fz=Join-Path $fd "naruto_mov03a_audio_extract_test_FIX3_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "MOV03A FIX3 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
