# Naruto PSP MOV03L FIX2 wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03l_hybrid_pmf_smoke"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov03l_hybrid_pmf_smoke_FIX2"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir "naruto_mov03l_hybrid_pmf_smoke_upload.zip"
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03l_hybrid_pmf_smoke"
$PyScript=Join-Path $Root "run_naruto_mov03l_hybrid_pmf_smoke.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV03L FIX2 - Whole audio PES transplant"
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

    if($LASTEXITCODE -ne 0){throw "MOV03L FIX2 Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03L FIX2 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03L FIX2 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
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
      "SUMMARY.txt","FAILURE.txt",
      "dm001_audio_pes_compare_FIX2.tsv",
      "smoke_result.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $SL=Join-Path $StageDir "logs"
    if(Test-Path $SL){
        Get-ChildItem $SL -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match "FIX2" } |
          ForEach-Object { Copy-Item $_.FullName $Pkg -Force }
    }

    foreach($dirName in @("work","output")){
        $D=Join-Path $StageDir $dirName
        if(Test-Path $D){
            Get-ChildItem $D -File -ErrorAction SilentlyContinue |
              Select-Object Name,Length,LastWriteTime |
              Format-Table -AutoSize | Out-String |
              Set-Content (Join-Path $Pkg ("LOCAL_"+$dirName.ToUpper()+"_MANIFEST.txt")) -Encoding UTF8
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @($PyScript,(Join-Path $Root "run_naruto_mov03l_hybrid_pmf_smoke.ps1"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03l_hybrid_pmf_smoke_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03L FIX2 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir ("fail_"+$Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV03L FIX2 FAILED"
        Write-Host "Failure log:"
        Write-Host "  $Transcript"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
