# Naruto PSP MOV03B wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03b_static_audio_link"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03b_static_audio_link_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03b_static_audio_link_upload.zip"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03B - Static PMF -> external audio reference scan"
    Write-Host "========================================================================"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){$PyExe=$launcher.Source;$UseLauncher=$true}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3를 찾지 못했습니다."}
        $PyExe=$p.Source;$UseLauncher=$false
    }

    $Script=Join-Path $Root "run_naruto_mov03b_static_audio_link.py"
    if(-not(Test-Path $Script)){throw "Python script not found: $Script"}

    if($UseLauncher){& $PyExe -3 $Script}else{& $PyExe $Script}
    if($LASTEXITCODE -ne 0){throw "MOV03B Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03B FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt",
        "pmf_reference_hits.tsv",
        "pmf_nearby_audio_ids.tsv",
        "pmf_audio_candidates_top30.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $Per=Join-Path $StageDir "per_movie"
    if(Test-Path $Per){
        Copy-Item $Per (Join-Path $Pkg "per_movie") -Recurse -Force
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    foreach($s in @(
        (Join-Path $Root "run_naruto_mov03b_static_audio_link.ps1"),
        (Join-Path $Root "run_naruto_mov03b_static_audio_link.py")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03B SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03b_static_audio_link_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03B FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Success){exit 1}
exit 0
