# Naruto PSP MOV03K wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="PROJECT_ROOT"
$StageDir=Join-Path $Root "analysis\mov\mov03k_embedded_audio"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03k_embedded_audio_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03k_embedded_audio_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03k_embedded_audio"
$PyScript=Join-Path $Root "run_naruto_mov03k_embedded_audio.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV03K - Embedded PMF audio extraction"
    Write-Host "================================================================================"

    if(-not(Test-Path $PyScript)){throw "Missing Python script: $PyScript"}

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript
    }

    if($LASTEXITCODE -ne 0){throw "MOV03K Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03K FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03K FAILED","",$_.Exception.Message,"",($_|Out-String)) |
        Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt",
        "kr_dm_embedded_audio.tsv","us_dm_counterpart_streams.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    # Include command/probe logs only; never include extracted audio in upload ZIP.
    $ProbeLogs=Join-Path $StageDir "logs"
    if(Test-Path $ProbeLogs){
        Copy-Item $ProbeLogs (Join-Path $Pkg "logs") -Recurse -Force
    }

    # Compact manifest for local extracted audio.
    $AudioDir=Join-Path $StageDir "audio"
    if(Test-Path $AudioDir){
        $manifest=Get-ChildItem $AudioDir -File -ErrorAction SilentlyContinue |
            Select-Object Name,Length,LastWriteTime
        $manifest | Format-Table -AutoSize | Out-String |
            Set-Content (Join-Path $Pkg "LOCAL_AUDIO_MANIFEST.txt") -Encoding UTF8
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @($PyScript,(Join-Path $Root "run_naruto_mov03k_embedded_audio.ps1"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03k_embedded_audio_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03K SUCCESS"
        Write-Host "Local extracted audio:"
        Write-Host "  $AudioDir"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03k_embedded_audio_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03K FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
