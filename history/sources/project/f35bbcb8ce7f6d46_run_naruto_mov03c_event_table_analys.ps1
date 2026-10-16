# Naruto PSP MOV03C - extract event*.tbl and analyze MOVIE opcode
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="PROJECT_ROOT"
$StageDir=Join-Path $Root "analysis\mov\mov03c_event_table_analysis"
$ExtractDir=Join-Path $StageDir "pidx_extract"
$ToolsDir=Join-Path $Root "tools\quickbms"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03c_event_table_analysis_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03c_event_table_analysis_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03c_event_table_analysis"

$Idx=Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\naruto.idx"
$Dat=Join-Path $Root "kr_extracted\PSP_GAME\USRDIR\naruto.dat"
$Script=Join-Path $Root "run_naruto_mov03c_event_table_analysis.py"

New-Item -ItemType Directory -Force -Path $StageDir,$ExtractDir,$ToolsDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null

function Find-QuickBMS {
    $roots=@(
        $ToolsDir,
        (Join-Path $Root "tools"),
        $Root
    )
    foreach($r in $roots){
        if(-not(Test-Path $r)){continue}
        $q=Get-ChildItem $r -File -Filter "quickbms.exe" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if($q){return $q.FullName}
    }
    return $null
}

function Ensure-QuickBMS {
    $q=Find-QuickBMS
    if($q){return $q}

    Write-Host "QuickBMS not found; downloading official Win32 package..."
    $zip=Join-Path $ToolsDir "quickbms.zip"
    $urls=@(
        "httpLOCAL_PATH",
        "httLOCAL_PATH"
    )
    $ok=$false
    foreach($u in $urls){
        try{
            Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing
            if((Test-Path $zip) -and (Get-Item $zip).Length -gt 100000){$ok=$true;break}
        }catch{
            Write-Host "  download failed: $u"
        }
    }
    if(-not $ok){throw "QuickBMS download failed."}

    Expand-Archive $zip -DestinationPath $ToolsDir -Force
    $q=Find-QuickBMS
    if(-not $q){throw "quickbms.exe missing after extraction."}
    return $q
}

function Ensure-PidxScript {
    $bms=Join-Path $ToolsDir "macross_pidx.bms"
    if((Test-Path $bms) -and (Get-Item $bms).Length -gt 200){return $bms}

    Write-Host "Downloading macross_pidx.bms..."
    $urls=@(
        "httpLOCAL_PATH",
        "httpLOCAL_PATH"
    )
    foreach($u in $urls){
        try{
            Invoke-WebRequest -Uri $u -OutFile $bms -UseBasicParsing
            if((Test-Path $bms) -and (Get-Item $bms).Length -gt 200){return $bms}
        }catch{
            Write-Host "  script download failed: $u"
        }
    }
    throw "macross_pidx.bms download failed."
}

# Archive previous compact results, but keep pidx_extract cache if it already has event TBLs.
$keep=@("pidx_extract")
$old=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue |
    Where-Object {$keep -notcontains $_.Name})
if($old.Count -gt 0){
    $dst=Join-Path $ArchiveDir "previous_results"
    New-Item -ItemType Directory -Force -Path $dst|Out-Null
    foreach($x in $old){Move-Item $x.FullName $dst -Force}
}

Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03C - Event TBL movie opcode analysis"
    Write-Host "========================================================================"

    if(-not(Test-Path $Idx)){throw "naruto.idx not found: $Idx"}
    if(-not(Test-Path $Dat)){throw "naruto.dat not found: $Dat"}
    if(-not(Test-Path $Script)){throw "Python script not found: $Script"}

    $existing=@(Get-ChildItem $ExtractDir -File -Filter "event*.tbl" -Recurse -ErrorAction SilentlyContinue)

    if($existing.Count -eq 0){
        $QuickBMS=Ensure-QuickBMS
        $Bms=Ensure-PidxScript

        Write-Host ""
        Write-Host "[1/2] QuickBMS PIDX extraction - event*.tbl only"
        Write-Host "  quickbms: $QuickBMS"
        Write-Host "  bms     : $Bms"
        Write-Host "  idx     : $Idx"
        Write-Host "  out     : $ExtractDir"

        $QBOut=Join-Path $StageDir "quickbms_extract_stdout.log"
        $QBErr=Join-Path $StageDir "quickbms_extract_stderr.log"

        # -o = overwrite; -F limits extraction to event*.tbl.
        & $QuickBMS "-o" "-F" "event*.tbl" $Bms $Idx $ExtractDir `
            1> $QBOut 2> $QBErr
        $qec=$LASTEXITCODE
        Write-Host "  exit=$qec"

        $existing=@(Get-ChildItem $ExtractDir -File -Filter "event*.tbl" -Recurse -ErrorAction SilentlyContinue)

        # Some PIDX scripts/filter combinations may not honor -F on nested names.
        # If zero files were produced, retry full extraction once.
        if($existing.Count -eq 0){
            Write-Host "  Filter extraction produced 0 event TBLs; retrying full PIDX extraction."
            & $QuickBMS "-o" $Bms $Idx $ExtractDir `
                1>> $QBOut 2>> $QBErr
            $qec2=$LASTEXITCODE
            Write-Host "  full extraction exit=$qec2"
            $existing=@(Get-ChildItem $ExtractDir -File -Filter "event*.tbl" -Recurse -ErrorAction SilentlyContinue)
        }

        if($existing.Count -eq 0){
            throw "QuickBMS produced no event*.tbl files. Upload failure ZIP."
        }
    }else{
        Write-Host "[1/2] Reusing cached event TBL extraction: $($existing.Count) files"
    }

    Write-Host ""
    Write-Host "[2/2] Analyze TBL structure and MOVIE opcode candidates"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){
        & $launcher.Source -3 $Script
    }else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $Script
    }

    if($LASTEXITCODE -ne 0){throw "MOV03C Python exited with code $LASTEXITCODE"}

    $Success=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03C FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
        "Naruto PSP MOV03C FAILED",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    )|Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8

}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt",
        "event_inventory.tsv",
        "direct_string_hits.tsv",
        "printable_audio_tokens.tsv",
        "movie_layout_scores.tsv",
        "movie_command_candidates.tsv",
        "event_movie_best.tsv",
        "boot_reference_table.tsv",
        "quickbms_extract_stdout.log",
        "quickbms_extract_stderr.log"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    # Include per-event diagnostics; small text only.
    $Per=Join-Path $StageDir "per_event"
    if(Test-Path $Per){Copy-Item $Per (Join-Path $Pkg "per_event") -Recurse -Force}

    # Include raw event TBLs only if compact enough for easy offline inspection.
    $eventFiles=@(Get-ChildItem $ExtractDir -File -Filter "event*.tbl" -Recurse -ErrorAction SilentlyContinue)
    $eventBytes=($eventFiles|Measure-Object Length -Sum).Sum
    if($eventFiles.Count -gt 0 -and $eventBytes -le 15728640){
        $Raw=Join-Path $Pkg "raw_event_tbl"
        New-Item -ItemType Directory -Force -Path $Raw|Out-Null
        foreach($f in $eventFiles){Copy-Item $f.FullName (Join-Path $Raw $f.Name) -Force}
    }else{
        @(
            "event_files=$($eventFiles.Count)",
            "event_total_bytes=$eventBytes",
            "raw files omitted because total exceeds 15 MiB"
        )|Set-Content (Join-Path $Pkg "RAW_EVENT_STATUS.txt") -Encoding UTF8
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    foreach($s in @(
        (Join-Path $Root "run_naruto_mov03c_event_table_analysis.ps1"),
        (Join-Path $Root "run_naruto_mov03c_event_table_analysis.py")
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
        Write-Host "MOV03C SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03c_event_table_analysis_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03C FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
