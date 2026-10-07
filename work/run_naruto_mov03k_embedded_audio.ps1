# Naruto PSP MOV03K FIX5 wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03k_embedded_audio"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$BaseName="naruto_mov03k_embedded_audio_FIX5"
$Transcript=Join-Path $LogsDir ($BaseName+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$BaseName+"_"+$Stamp+".log")

$UploadZip=Join-Path $LogsDir "naruto_mov03k_embedded_audio_upload.zip"
$FailZip=Join-Path $LogsDir ("fail_"+$BaseName+"_upload.zip")

$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03k_embedded_audio"
$PyScript=Join-Path $Root "run_naruto_mov03k_embedded_audio.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV03K FIX5 - Per-AU 8-byte header detection"
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

    if($LASTEXITCODE -ne 0){throw "MOV03K FIX5 Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03K FIX5 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03K FIX5 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    # User preference: failure transcript lives directly in logs with fail_ prefix.
    if(-not $Success -and (Test-Path $Transcript)){
        Move-Item $Transcript $FailTranscript -Force
        $Transcript=$FailTranscript
    }

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
      "SUMMARY.txt","FAILURE.txt",
      "fix5_results.tsv",
      "fix5_transform_trials.tsv",
      "fix5_frame_start_diagnostics.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $L=Join-Path $StageDir "logs"
    if(Test-Path $L){
        Get-ChildItem $L -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match "fix5" } |
          ForEach-Object { Copy-Item $_.FullName $Pkg -Force }
    }

    foreach($dirName in @("raw","audio")){
        $D=Join-Path $StageDir $dirName
        if(Test-Path $D){
            Get-ChildItem $D -File -ErrorAction SilentlyContinue |
              Select-Object Name,Length,LastWriteTime |
              Format-Table -AutoSize | Out-String |
              Set-Content (Join-Path $Pkg ("LOCAL_"+$dirName.ToUpper()+"_MANIFEST.txt")) -Encoding UTF8
        }
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
        Write-Host "MOV03K FIX5 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir ("fail_"+$BaseName+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV03K FIX5 FAILED"
        Write-Host "Failure log:"
        Write-Host "  $Transcript"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
