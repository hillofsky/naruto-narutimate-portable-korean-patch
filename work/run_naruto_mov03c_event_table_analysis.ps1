# Naruto PSP MOV03C FIX3 - partial-safe decompression + structure analysis
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03c_event_table_analysis"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03c_event_table_analysis_FIX3_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03c_event_table_analysis_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03c_event_table_analysis"

$DecScript=Join-Path $Root "run_naruto_mov03c_decompress_events.py"
$AnalyzeScript=Join-Path $Root "run_naruto_mov03c_event_table_analysis.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03C FIX3 - Partial-safe decompress + analyze"
    Write-Host "========================================================================"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){$Py=$launcher.Source;$Launch=$true}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        $Py=$p.Source;$Launch=$false
    }

    if(-not(Test-Path $DecScript)){throw "Missing: $DecScript"}
    if(-not(Test-Path $AnalyzeScript)){throw "Missing: $AnalyzeScript"}

    Write-Host ""
    Write-Host "[1/2] Decompress event*.tbl (partial-safe)"
    if($Launch){& $Py -3 $DecScript}else{& $Py $DecScript}
    $ec=$LASTEXITCODE
    if($ec -ne 0){throw "Event decompression coverage too low. ExitCode=$ec"}

    Write-Host ""
    Write-Host "[2/2] Analyze exact-size decompressed event structures"
    if($Launch){& $Py -3 $AnalyzeScript}else{& $Py $AnalyzeScript}
    $ec=$LASTEXITCODE
    if($ec -ne 0){throw "Event analysis failed. ExitCode=$ec"}

    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03C FIX3 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV03C FIX3 FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
      "DECOMPRESSION_SUMMARY.txt","DECOMPRESSION_FAILURE.txt","decompression_report.tsv",
      "SUMMARY.txt","FAILURE.txt","event_inventory.tsv","direct_string_hits.tsv",
      "printable_audio_tokens.tsv","movie_layout_scores.tsv",
      "movie_command_candidates.tsv","event_movie_best.tsv","boot_reference_table.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $Decomp=Join-Path $StageDir "decompressed_event"
    if(Test-Path $Decomp){
        $files=@(Get-ChildItem $Decomp -File -Filter "event*.tbl")
        $bytes=($files|Measure-Object Length -Sum).Sum
        if($bytes -le 15728640){
            Copy-Item $Decomp (Join-Path $Pkg "decompressed_event") -Recurse -Force
        }
    }

    # Always include compact diagnostics for the unresolved two.
    $Unres=Join-Path $StageDir "unresolved_decompression"
    if(Test-Path $Unres){
        $uFiles=@(Get-ChildItem $Unres -File -Recurse -ErrorAction SilentlyContinue)
        $uBytes=($uFiles|Measure-Object Length -Sum).Sum
        if($uBytes -le 5242880){
            Copy-Item $Unres (Join-Path $Pkg "unresolved_decompression") -Recurse -Force
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @(
      $DecScript,$AnalyzeScript,
      (Join-Path $Root "run_naruto_mov03c_event_table_analysis.ps1")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03c_event_table_analysis_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03C FIX3 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03c_event_table_analysis_FIX3_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03C FIX3 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
