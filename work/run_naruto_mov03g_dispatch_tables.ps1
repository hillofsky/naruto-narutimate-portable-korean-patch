# Naruto PSP MOV03G FIX1 wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03g_dispatch_tables"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03g_dispatch_tables_FIX1_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03g_dispatch_tables_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03g_dispatch_tables"
$PyScript=Join-Path $Root "run_naruto_mov03g_dispatch_tables.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "=============================================================================="
    Write-Host " Naruto PSP MOV03G FIX1 - grounded DM dispatcher table decode"
    Write-Host "=============================================================================="

    if(-not(Test-Path $PyScript)){throw "Missing Python script: $PyScript"}

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript
    }

    if($LASTEXITCODE -ne 0){throw "MOV03G FIX1 Python exited with code $LASTEXITCODE"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03G FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03G FIX1 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
        Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt",
        "address_mapping_sanity.tsv","address_mapping_diagnostics.tsv",
        "primary_pmf_table.tsv","selector_tables.tsv","movie_index_maps.tsv",
        "resolved_dispatch.tsv","table_hex_context.txt",
        "target_function_callers.tsv","target_function_context.txt",
        "dispatcher_code_context.txt",
        "group_number_audio_candidates.tsv","group_number_voice_tbl_usage.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @($PyScript,(Join-Path $Root "run_naruto_mov03g_dispatch_tables.ps1"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03g_dispatch_tables_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03G FIX1 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03g_dispatch_tables_FIX1_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03G FIX1 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
