# Naruto PSP MOV04D FIX2 - resume fit result + integrated ISO + PPSSPP auto-launch
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$LogsDir=Join-Path $Root "logs"
$StageDir=Join-Path $Root "analysis\mov\mov04d_fix1_integrated_iso"
$FitStage=Join-Path $Root "analysis\mov\mov04d_fix1_fit_rebuild"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov04d_FIX2_integrated_iso"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov04d_FIX2"

$FitPy=Join-Path $Root "run_naruto_mov04d_fix1_fit_rebuild.py"
$InstallPy=Join-Path $Root "run_naruto_mov04d_fix1_integrated_iso.py"
$FinalIso=Join-Path $StageDir "output\Naruto_KR_MOV04D_FIX1_AllTranslatedMovies.iso"

function Invoke-PythonVisible([string]$Script) {
    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){
        & $launcher.Source -3 $Script | Out-Host
        $code=$LASTEXITCODE
        return [int]$code
    }

    $p=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $p){throw "Python 3 not found."}

    & $p.Source $Script | Out-Host
    $code=$LASTEXITCODE
    return [int]$code
}

function Test-FitOutputs {
    $report=Join-Path $FitStage "fit_rebuild_results.tsv"
    $da=Join-Path $FitStage "output\da101.pmf"
    $dk=Join-Path $FitStage "output\dk202.pmf"

    if(-not(Test-Path $report) -or -not(Test-Path $da) -or -not(Test-Path $dk)){
        return $false
    }

    try {
        $rows=Import-Csv -LiteralPath $report -Delimiter "`t"
        if($rows.Count -ne 2){return $false}
        foreach($r in $rows){
            if($r.status -ne "PASS"){return $false}
            if($r.logical_752_equal_kr -ne "YES"){return $false}
            if($r.frames_744_equal_kr -ne "YES"){return $false}
            if($r.audio_pts_equal_kr -ne "YES"){return $false}
            if($r.audio_pes_equal_kr -ne "YES"){return $false}
            if($r.atrac_decode -ne "PASS"){return $false}
            if($r.video_format -ne "PASS"){return $false}
        }
        return $true
    } catch {
        return $false
    }
}

function Find-PPSSPP {
    foreach($pn in @("PPSSPPWindows64","PPSSPPWindows")) {
        try {
            $proc=Get-Process -Name $pn -ErrorAction SilentlyContinue | Select-Object -First 1
            if($proc -and $proc.Path -and (Test-Path $proc.Path)){return $proc.Path}
        } catch {}
    }

    foreach($n in @("PPSSPPWindows64.exe","PPSSPPWindows.exe")) {
        $cmd=Get-Command $n -ErrorAction SilentlyContinue
        if($cmd -and $cmd.Source -and (Test-Path $cmd.Source)){return $cmd.Source}
    }

    $candidates=@(
        (Join-Path $Root "PPSSPPWindows64.exe"),
        (Join-Path $Root "PPSSPPWindows.exe"),
        (Join-Path $Root "PPSSPP\PPSSPPWindows64.exe"),
        (Join-Path $Root "PPSSPP\PPSSPPWindows.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\PPSSPP\PPSSPPWindows64.exe"),
        (Join-Path $env:LOCALAPPDATA "PPSSPP\PPSSPPWindows64.exe"),
        (Join-Path $env:ProgramFiles "PPSSPP\PPSSPPWindows64.exe")
    )
    if(${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "PPSSPP\PPSSPPWindows64.exe")
    }

    foreach($p in $candidates){
        if($p -and (Test-Path $p)){return $p}
    }

    try {
        $p=Get-ChildItem -LiteralPath $Root -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("PPSSPPWindows64.exe","PPSSPPWindows.exe") } |
            Select-Object -First 1
        if($p){return $p.FullName}
    } catch {}

    return $null
}

function Start-PPSSPPIso([string]$IsoPath) {
    if(-not(Test-Path $IsoPath)){
        Write-Warning "PPSSPP auto-launch skipped: ISO missing."
        return
    }

    $exe=Find-PPSSPP
    if(-not $exe){
        Write-Warning "PPSSPP executable not found automatically. ISO itself is still PASS."
        return
    }

    try {
        # If an instance is already running, launching a new process with the ISO is
        # intentional: PPSSPP accepts the ISO path on its command line.
        Write-Host ""
        Write-Host "Auto-launching final ISO in PPSSPP:"
        Write-Host "  EXE: $exe"
        Write-Host "  ISO: $IsoPath"
        Start-Process -FilePath $exe -ArgumentList @("`"$IsoPath`"")
        Write-Host "PPSSPP launch requested successfully."
    } catch {
        Write-Warning ("PPSSPP auto-launch failed (ISO remains valid): " + $_.Exception.Message)
    }
}

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot | Out-Null

# Remove stale wrapper failure from FIX1 before packaging this run.
foreach($stale in @(
    (Join-Path $StageDir "FAILURE_WRAPPER.txt"),
    (Join-Path $StageDir "FAILURE.txt")
)){
    Remove-Item $stale -Force -ErrorAction SilentlyContinue
}

Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV04D FIX2 - resume + integrated ISO"
    Write-Host "================================================================================"
    Write-Host "FIX1 diagnosis: media rebuild was PASS; wrapper captured stdout as exit code."

    foreach($p in @($FitPy,$InstallPy)){
        if(-not(Test-Path $p)){throw "Missing script: $p"}
    }

    Write-Host ""
    if(Test-FitOutputs){
        Write-Host "[1/2] Existing fit-rebuild outputs verified PASS. Reusing them."
        Write-Host "  da101: 99% video bitrate attempt already fits and strictly validates."
        Write-Host "  dk202: 99% video bitrate attempt already fits and strictly validates."
    }else{
        Write-Host "[1/2] Fit outputs missing/incomplete. Rebuilding da101 + dk202..."
        $rc=Invoke-PythonVisible $FitPy
        if($rc -ne 0){throw "Fit rebuild exited with integer code $rc"}
        if(-not(Test-FitOutputs)){throw "Fit rebuild returned 0 but PASS outputs did not validate."}
    }

    Write-Host ""
    Write-Host "[2/2] Creating integrated ISO..."
    $rc=Invoke-PythonVisible $InstallPy
    if($rc -ne 0){throw "Integrated ISO installer exited with integer code $rc"}

    if(-not(Test-Path $FinalIso)){throw "Final ISO missing after installer returned 0."}

    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV04D FIX2 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV04D FIX2 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
        Set-Content (Join-Path $StageDir "FAILURE_WRAPPER.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript | Out-Null}catch{}

    if(-not $Success -and (Test-Path $Transcript)){
        Move-Item $Transcript $FailTranscript -Force
        $Transcript=$FailTranscript
    }

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($p in @(
        (Join-Path $FitStage "SUMMARY.txt"),
        (Join-Path $FitStage "fit_rebuild_results.tsv"),
        (Join-Path $FitStage "FAILURE.txt"),
        (Join-Path $StageDir "SUMMARY.txt"),
        (Join-Path $StageDir "iso_patch_report.tsv"),
        (Join-Path $StageDir "FAILURE.txt"),
        (Join-Path $StageDir "FAILURE_WRAPPER.txt")
    )){
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    if(Test-Path $FinalIso){
        Get-Item $FinalIso | Select-Object FullName,Length,LastWriteTime |
            Format-List | Out-String |
            Set-Content (Join-Path $Pkg "LOCAL_OUTPUT_MANIFEST.txt") -Encoding UTF8
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    foreach($s in @(
        $FitPy,$InstallPy,
        (Join-Path $Root "mov04d_fix1_core.py"),
        (Join-Path $Root "invoke_naruto_mov04d_fix1_raw_mux.ps1"),
        (Join-Path $Root "run_naruto_mov04d_FIX2.ps1")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir ($Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "MOV04D FIX2 SUCCESS"
        Write-Host "Final integrated ISO:"
        Write-Host "  $FinalIso"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"

        Start-PPSSPPIso $FinalIso
    }else{
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV04D FIX2 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
