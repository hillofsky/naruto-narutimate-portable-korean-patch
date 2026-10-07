# Naruto PSP MOV04D FIX1 - fit rebuild + integrated ISO + auto-launch PPSSPP
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
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov04d_FIX1_integrated_iso"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov04d_FIX1"

$FitPy=Join-Path $Root "run_naruto_mov04d_fix1_fit_rebuild.py"
$InstallPy=Join-Path $Root "run_naruto_mov04d_fix1_integrated_iso.py"
$FinalIso=Join-Path $StageDir "output\Naruto_KR_MOV04D_FIX1_AllTranslatedMovies.iso"

function Invoke-Python([string]$Script) {
    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){ & $launcher.Source -3 $Script; return $LASTEXITCODE }

    $p=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $p){throw "Python 3 not found."}
    & $p.Source $Script
    return $LASTEXITCODE
}

function Find-PPSSPP {
    # 1) running PPSSPP process path
    foreach($pn in @("PPSSPPWindows64","PPSSPPWindows")) {
        try {
            $proc=Get-Process -Name $pn -ErrorAction SilentlyContinue | Select-Object -First 1
            if($proc -and $proc.Path -and (Test-Path $proc.Path)){return $proc.Path}
        } catch {}
    }

    # 2) PATH / common project locations
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
    foreach($p in $candidates){if($p -and (Test-Path $p)){return $p}}

    # 3) project tree fallback
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
        Write-Warning "PPSSPP executable not found automatically. ISO creation remains PASS."
        return
    }

    try {
        Write-Host ""
        Write-Host "Auto-launching PPSSPP:"
        Write-Host "  EXE: $exe"
        Write-Host "  ISO: $IsoPath"
        Start-Process -FilePath $exe -ArgumentList @("`"$IsoPath`"")
        Write-Host "PPSSPP launch requested successfully."
    } catch {
        Write-Warning ("PPSSPP auto-launch failed (ISO remains valid): " + $_.Exception.Message)
    }
}

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot | Out-Null
Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV04D FIX1 - fit rebuild + integrated ISO"
    Write-Host "================================================================================"
    Write-Host "Oversize solution: lower video bitrate only; preserve original ISO LBAs."

    foreach($p in @($FitPy,$InstallPy)){
        if(-not(Test-Path $p)){throw "Missing script: $p"}
    }

    Write-Host ""
    Write-Host "[1/2] Rebuilding da101 + dk202 to fit original allocation..."
    $rc=Invoke-Python $FitPy
    if($rc -ne 0){throw "Fit rebuild exited with code $rc"}

    Write-Host ""
    Write-Host "[2/2] Creating integrated ISO..."
    $rc=Invoke-Python $InstallPy
    if($rc -ne 0){throw "Integrated ISO install exited with code $rc"}

    if(-not(Test-Path $FinalIso)){throw "Final ISO missing after successful installer."}

    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV04D FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV04D FIX1 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
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
        (Join-Path $Root "analysis\mov\mov04d_fix1_fit_rebuild\SUMMARY.txt"),
        (Join-Path $Root "analysis\mov\mov04d_fix1_fit_rebuild\fit_rebuild_results.tsv"),
        (Join-Path $Root "analysis\mov\mov04d_fix1_fit_rebuild\FAILURE.txt"),
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
        (Join-Path $Root "run_naruto_mov04d_FIX1.ps1")
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
        Write-Host "MOV04D FIX1 SUCCESS"
        Write-Host "Final integrated ISO:"
        Write-Host "  $FinalIso"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"

        # User preference: automatically open the ISO when runtime verification is useful.
        Start-PPSSPPIso $FinalIso
    }else{
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV04D FIX1 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
