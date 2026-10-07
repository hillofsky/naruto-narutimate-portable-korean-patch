# Naruto PSP MOV03F wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03f_movie_audio_pointer_map"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03f_movie_audio_pointer_map_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03f_movie_audio_pointer_map_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03f_movie_audio_pointer_map"
$PyScript=Join-Path $Root "run_naruto_mov03f_movie_audio_pointer_map.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03F - PMF pointer table + AT3 adjacency analysis"
    Write-Host "========================================================================"

    if(-not(Test-Path $PyScript)){throw "Missing Python script: $PyScript"}

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript
    }

    if($LASTEXITCODE -ne 0){throw "MOV03F Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03F FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03F FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
      "SUMMARY.txt","FAILURE.txt",
      "gp_candidates.tsv","movie_slot_table.tsv","movie_slot_pointer_xrefs.tsv",
      "movie_pointer_clusters.tsv","at3_string_inventory.tsv","at3_pointer_xrefs.tsv",
      "movie_at3_pointer_adjacency.tsv","code_lui_xrefs.tsv","gp_relative_xrefs.tsv",
      "movie_pointer_context.txt","grounded_code_context.txt"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @($PyScript,(Join-Path $Root "run_naruto_mov03f_movie_audio_pointer_map.ps1"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03f_movie_audio_pointer_map_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03F SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03f_movie_audio_pointer_map_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03F FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
