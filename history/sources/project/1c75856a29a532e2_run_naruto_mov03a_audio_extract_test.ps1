# Naruto PSP MOV03A FIX2 - dm001 PMF audio extraction
# Exact psmfdump invocation:
#   psmfdump <PMF> -a <audio.oma> -v <video.264>
#
# Previous failure cause:
# Run-CmdCapture lost native-tool arguments, so psmfdump was launched with no args.

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
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_FIX2_$Stamp.log"
$UploadZip  = Join-Path $LogsDir "naruto_mov03a_audio_extract_test_upload.zip"
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName

$Pmf        = Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\movie\dm001.pmf"
$AudioOma   = Join-Path $WorkDir "dm001.oma"
$Video264   = Join-Path $WorkDir "dm001.264"
$OutWav     = Join-Path $StageDir "dm001.wav"

$Summary    = Join-Path $StageDir "SUMMARY.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$ProbePmf   = Join-Path $StageDir "ffprobe_dm001_pmf.json"
$ProbeOma   = Join-Path $StageDir "ffprobe_dm001_oma.json"
$ProbeWav   = Join-Path $StageDir "ffprobe_dm001_wav.json"
$PsmfStdout = Join-Path $StageDir "psmfdump_stdout.log"
$PsmfStderr = Join-Path $StageDir "psmfdump_stderr.log"
$DecodeLog  = Join-Path $StageDir "ffmpeg_oma_decode.log"
$CmdTxt     = Join-Path $StageDir "COMMANDS.txt"

New-Item -ItemType Directory -Force -Path $StageDir,$WorkDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

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

function Quote-ProcArg([string]$Value) {
    if($null -eq $Value){ return '""' }
    return '"' + $Value.Replace('"','\"') + '"'
}

function Build-ArgLine {
    param([Parameter(Mandatory=$true)][string[]]$ArgumentItems)

    if($null -eq $ArgumentItems -or $ArgumentItems.Count -eq 0){
        throw "Build-ArgLine received an empty argument array."
    }

    $line=(($ArgumentItems | ForEach-Object { Quote-ProcArg ([string]$_) }) -join " ")
    if([string]::IsNullOrWhiteSpace($line)){
        throw "Build-ArgLine produced an empty ArgumentList."
    }
    return $line
}

function Run-ProcessExact {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$ArgumentItems,
        [Parameter(Mandatory=$true)][string]$Stdout,
        [Parameter(Mandatory=$true)][string]$Stderr,
        [string]$WorkingDirectory = ""
    )

    if(Test-Path $Stdout){Remove-Item $Stdout -Force}
    if(Test-Path $Stderr){Remove-Item $Stderr -Force}

    $argLine=Build-ArgLine -ArgumentItems $ArgumentItems
    if([string]::IsNullOrWhiteSpace($argLine)){
        throw "Run-ProcessExact: ArgumentList unexpectedly empty for $Exe"
    }
    $sp=@{
        FilePath=$Exe
        ArgumentList=$argLine
        RedirectStandardOutput=$Stdout
        RedirectStandardError=$Stderr
        PassThru=$true
        WindowStyle="Hidden"
    }
    if($WorkingDirectory){$sp["WorkingDirectory"]=$WorkingDirectory}

    $proc=Start-Process @sp
    $proc.WaitForExit()
    $proc.Refresh()

    return [PSCustomObject]@{
        ExitCode=$proc.ExitCode
        ArgLine=$argLine
        Command=(Quote-ProcArg $Exe)+" "+$argLine
    }
}

function Write-Probe {
    param([string]$Ffprobe,[string]$Input,[string]$Output)
    $probeArgs=@(
        "-v","error","-show_streams","-show_format","-of","json",$Input
    )
    $argLine=Build-ArgLine -ArgumentItems $probeArgs
    $tmpErr=$Output+".err"
    $p=Start-Process -FilePath $Ffprobe -ArgumentList $argLine `
        -RedirectStandardOutput $Output -RedirectStandardError $tmpErr `
        -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    $p.Refresh()
    if((Test-Path $tmpErr) -and (Get-Item $tmpErr).Length -gt 0){
        Add-Content $Output "`r`n--- STDERR ---"
        Get-Content $tmpErr | Add-Content $Output
    }
    Remove-Item $tmpErr -Force -ErrorAction SilentlyContinue
    return $p.ExitCode
}

function Valid-Wav {
    param([string]$Path,[string]$Ffprobe)
    if(-not(Test-Path $Path)){return $false}
    if((Get-Item $Path).Length -lt 4096){return $false}
    $tmp=Join-Path $WorkDir "wav_validate.json"
    $ec=Write-Probe -Ffprobe $Ffprobe -Input $Path -Output $tmp
    if($ec -ne 0){return $false}
    try{
        $o=Get-Content $tmp -Raw|ConvertFrom-Json
        return (@($o.streams|Where-Object{$_.codec_type -eq "audio"}).Count -gt 0)
    }catch{return $false}
}

# Rotate old MOV03A files except downloaded tools.
if(Test-Path $StageDir){
    $existing=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -ne "work"})
    if($existing.Count -gt 0){
        $oldStage=Join-Path $ArchiveDir "previous_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $existing){
            Move-Item $x.FullName $oldStage -Force
        }
    }
}
if(Test-Path $WorkDir){Remove-Item $WorkDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03A FIX2 - dm001 PMF audio extraction"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host ""

    if(-not(Test-Path $Pmf)){throw "dm001.pmf not found: $Pmf"}

    $ffmpeg=Find-FirstFile -Roots @(
        "LOCAL_PATH","LOCAL_PATH",(Join-Path $Root "tools")
    ) -Filter "ffmpeg.exe"
    $ffprobe=Find-FirstFile -Roots @(
        "LOCAL_PATH","LOCAL_PATH",(Join-Path $Root "tools")
    ) -Filter "ffprobe.exe"
    $psmfdump=Find-FirstFile -Roots @(
        $ToolsDir,(Join-Path $Root "tools")
    ) -Filter "psmfdump.exe"

    if(-not $ffmpeg){throw "ffmpeg.exe not found"}
    if(-not $ffprobe){throw "ffprobe.exe not found"}
    if(-not $psmfdump){
        throw "psmfdump.exe not found. Previous MOV03A should have installed pmftools-plus under $ToolsDir"
    }

    Write-Host "PMF      : $Pmf"
    Write-Host "psmfdump : $psmfdump"
    Write-Host "ffmpeg   : $ffmpeg"
    Write-Host "ffprobe  : $ffprobe"
    Write-Host ""

    Write-Probe -Ffprobe $ffprobe -Input $Pmf -Output $ProbePmf | Out-Null

    if(Test-Path $AudioOma){Remove-Item $AudioOma -Force}
    if(Test-Path $Video264){Remove-Item $Video264 -Force}
    if(Test-Path $OutWav){Remove-Item $OutWav -Force}

    Write-Host "[1/3] psmfdump exact PMF demux"
    $psmfArgs=@(
        $Pmf,
        "-a",$AudioOma,
        "-v",$Video264
    )
    Write-Host "  arg count: $($psmfArgs.Count)"
    for($i=0;$i -lt $psmfArgs.Count;$i++){
        Write-Host ("  arg[{0}] = {1}" -f $i,$psmfArgs[$i])
    }
    $psmf=Run-ProcessExact -Exe $psmfdump -ArgumentItems $psmfArgs `
        -Stdout $PsmfStdout -Stderr $PsmfStderr -WorkingDirectory $WorkDir

    Write-Host "  command: $($psmf.Command)"
    Write-Host "  exit   : $($psmf.ExitCode)"
    Write-Host "  oma    : $(Test-Path $AudioOma)"
    if(Test-Path $AudioOma){Write-Host "  oma bytes: $((Get-Item $AudioOma).Length)"}
    Write-Host "  264    : $(Test-Path $Video264)"
    if(Test-Path $Video264){Write-Host "  264 bytes: $((Get-Item $Video264).Length)"}

    @(
        "PSMFDUMP=$($psmf.Command)"
    ) | Set-Content $CmdTxt -Encoding UTF8

    if($psmf.ExitCode -ne 0){
        throw "psmfdump failed with exit code $($psmf.ExitCode)"
    }
    if(-not(Test-Path $AudioOma)){
        throw "psmfdump returned success but dm001.oma was not created."
    }
    if((Get-Item $AudioOma).Length -lt 1024){
        throw "dm001.oma is unexpectedly small: $((Get-Item $AudioOma).Length) bytes"
    }

    Write-Host ""
    Write-Host "[2/3] Probe OMA"
    $omaProbeExit=Write-Probe -Ffprobe $ffprobe -Input $AudioOma -Output $ProbeOma
    Write-Host "  ffprobe exit: $omaProbeExit"

    Write-Host ""
    Write-Host "[3/3] OMA -> PCM WAV"
    $ffArgs=@(
        "-y","-hide_banner","-loglevel","info",
        "-i",$AudioOma,
        "-vn",
        "-c:a","pcm_s16le",
        "-ar","48000",
        "-ac","2",
        $OutWav
    )

    $decodeOut=Join-Path $WorkDir "ffmpeg_decode_stdout.log"
    $dec=Run-ProcessExact -Exe $ffmpeg -ArgumentItems $ffArgs `
        -Stdout $decodeOut -Stderr $DecodeLog -WorkingDirectory $WorkDir

    Add-Content $CmdTxt ("FFMPEG="+$dec.Command)
    Write-Host "  command: $($dec.Command)"
    Write-Host "  exit   : $($dec.ExitCode)"

    if($dec.ExitCode -ne 0 -or -not(Valid-Wav $OutWav $ffprobe)){
        throw "OMA was extracted, but FFmpeg could not create a valid WAV."
    }

    Write-Probe -Ffprobe $ffprobe -Input $OutWav -Output $ProbeWav | Out-Null

    $pmfDur=""
    $wavDur=""
    $omaCodec=""
    try{
        $p=Get-Content $ProbePmf -Raw|ConvertFrom-Json
        $pmfDur=[double]$p.format.duration
    }catch{}
    try{
        $w=Get-Content $ProbeWav -Raw|ConvertFrom-Json
        $wavDur=[double]$w.format.duration
    }catch{}
    try{
        $o=Get-Content $ProbeOma -Raw|ConvertFrom-Json
        $a=@($o.streams|Where-Object{$_.codec_type -eq "audio"}|Select-Object -First 1)
        if($a.Count -gt 0){$omaCodec=$a[0].codec_name}
    }catch{}

    $delta=""
    if($pmfDur -ne "" -and $wavDur -ne ""){
        $delta=[math]::Abs([double]$pmfDur-[double]$wavDur)
    }

    @(
        "Naruto PSP MOV03A FIX2 - dm001 audio extraction",
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
        "CapCut sync test:",
        "1. Import Stage37 source video and dm001.wav.",
        "2. Put both on timeline.",
        "3. Select both and run video/audio synchronization.",
        "4. Note the source-video timestamp where dm001 starts.",
        "",
        "WAV remains local and is not added to the upload ZIP."
    ) | Set-Content $Summary -Encoding UTF8

    $Success=$true

}catch{
    @(
        "Naruto PSP MOV03A FIX2 FAILED",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

    Write-Host ""
    Write-Host "!!!!!!!! MOV03A FIX2 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message

}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt","COMMANDS.txt",
        "ffprobe_dm001_pmf.json","ffprobe_dm001_oma.json","ffprobe_dm001_wav.json",
        "psmfdump_stdout.log","psmfdump_stderr.log","ffmpeg_oma_decode.log"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    if(Test-Path $AudioOma){
        @(
            "dm001.oma exists",
            "bytes=$((Get-Item $AudioOma).Length)",
            "path=$AudioOma"
        ) | Set-Content (Join-Path $Pkg "OMA_STATUS.txt") -Encoding UTF8
    }

    if(Test-Path $Video264){
        @(
            "dm001.264 exists",
            "bytes=$((Get-Item $Video264).Length)",
            "path=$Video264"
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
        Write-Host "MOV03A FIX2 SUCCESS"
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
        $fz=Join-Path $fd "naruto_mov03a_audio_extract_test_FIX2_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "MOV03A FIX2 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
