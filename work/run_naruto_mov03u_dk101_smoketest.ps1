# Naruto PSP MOV03U wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03u_dk101_smoketest"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov03u_dk101_smoketest"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03u_dk101_smoketest"

$PyScript=Join-Path $Root "run_naruto_mov03u_dk101_smoketest.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV03U - dk101 early final-PMF smoke test"
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

    if($LASTEXITCODE -ne 0){throw "MOV03U Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03U FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03U FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE_WRAPPER.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    if(-not $Success -and (Test-Path $Transcript)){
        Move-Item $Transcript $FailTranscript -Force
        $Transcript=$FailTranscript
    }

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
      "SUMMARY.txt","FAILURE.txt","FAILURE_WRAPPER.txt","smoke_patch_report.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $OutDir=Join-Path $StageDir "output"
    if(Test-Path $OutDir){
        Get-ChildItem $OutDir -File -ErrorAction SilentlyContinue |
          Select-Object Name,Length,LastWriteTime |
          Format-Table -AutoSize | Out-String |
          Set-Content (Join-Path $Pkg "LOCAL_OUTPUT_MANIFEST.txt") -Encoding UTF8
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @(
      $PyScript,
      (Join-Path $Root "run_naruto_mov03u_dk101_smoketest.ps1")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir ($Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03U SUCCESS"
        Write-Host "Smoke-test ISO:"
        Write-Host "  $OutDir\Naruto_KR_MOV03U_dk101_as_dm001_smoketest.iso"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir ("fail_"+$Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV03U FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
