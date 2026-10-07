# Naruto PSP MOV05C FIX1 wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov05c_fix1_dk101_visual_segments"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov05c_FIX1_dk101_visual_segments"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov05c_FIX1"

$PyScript=Join-Path $Root "run_naruto_mov05c_FIX1_dk101_visual_segments.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
foreach($p in @((Join-Path $StageDir "FAILURE.txt"),(Join-Path $StageDir "FAILURE_WRAPPER.txt"))){
    Remove-Item $p -Force -ErrorAction SilentlyContinue
}

Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false
try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV05C FIX1 - independent VISUAL segment matcher"
    Write-Host "================================================================================"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript 2>&1|Out-Host;$rc=$LASTEXITCODE}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript 2>&1|Out-Host;$rc=$LASTEXITCODE
    }

    if([int]$rc -ne 0){throw "MOV05C FIX1 Python exited with code $rc"}
    if(-not(Test-Path (Join-Path $StageDir "visual_segment_map.tsv"))){
        throw "visual_segment_map.tsv missing"
    }
    $Success=$true
}catch{
    Write-Host "";Write-Host "!!!!!!!! MOV05C FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV05C FIX1 FAILED","",$_.Exception.Message,"",($_|Out-String))|
      Set-Content (Join-Path $StageDir "FAILURE_WRAPPER.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    if(-not $Success -and(Test-Path $Transcript)){
        Move-Item $Transcript $FailTranscript -Force
        $Transcript=$FailTranscript
    }

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
      "SUMMARY.txt","FAILURE.txt","FAILURE_WRAPPER.txt",
      "visual_segment_map.tsv","visual_segment_candidates.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $review=Join-Path $StageDir "review"
    if(Test-Path $review){
        Copy-Item $review (Join-Path $Pkg "review") -Recurse -Force
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    foreach($s in @(
      $PyScript,
      (Join-Path $Root "run_naruto_mov05c_FIX1_dk101_visual_segments.ps1")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir ($Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host "";Write-Host "MOV05C FIX1 SUCCESS"
        Write-Host "Upload ZIP:";Write-Host "  $UploadZip"
    }else{
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host "";Write-Host "MOV05C FIX1 FAILED"
        Write-Host "Failure ZIP:";Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Success){exit 1}
exit 0
