# Naruto PSP MOV04C wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov04c_final_batch"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov04c_final_batch"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov04c_final_batch"

$PyScript=Join-Path $Root "run_naruto_mov04c_final_batch.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV04C - FINAL batch DA/DK translated movies"
    Write-Host "================================================================================"

    if(-not(Test-Path $PyScript)){throw "Missing Python script: $PyScript"}

    $ExpectedMarker="MOV04C_REMAINING5_FINAL_BUILDER"
    $PyText=Get-Content -LiteralPath $PyScript -Raw
    if($PyText -notmatch [regex]::Escape($ExpectedMarker)){
        throw "Wrong/stale MOV04C Python runner."
    }

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript
    }

    if($LASTEXITCODE -ne 0){throw "MOV04C Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV04C FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV04C FAILED","",$_.Exception.Message,"",($_|Out-String)) |
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

    foreach($n in @("SUMMARY.txt","FAILURE.txt","FAILURE_WRAPPER.txt","final_batch_results.tsv")){
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

    $SL=Join-Path $StageDir "logs"
    if(Test-Path $SL){
        Get-ChildItem $SL -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match "_08_reflection_mux|_09_Mps2Pmf_final|_11_decode_audio|_12_probe_final" } |
          ForEach-Object { Copy-Item $_.FullName $Pkg -Force }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @(
      $PyScript,
      (Join-Path $Root "run_naruto_mov04c_final_batch.ps1"),
      (Join-Path $Root "invoke_naruto_mov04c_raw_mux.ps1"),
      (Join-Path $Root "mov04c_subtitle_segments_translated.tsv")
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
        Write-Host "MOV04C SUCCESS"
        Write-Host "Final PMFs:"
        Write-Host "  $OutDir"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV04C FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
