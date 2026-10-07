# Naruto PSP SUB18 FIX1 - Discover decoded event source / patcher decode path
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub18_fix3_decode_discovery"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub18_fix3_decode_discovery_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub18_fix3_decode_discovery_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub18_fix3_decode_discovery_*.log" -ErrorAction SilentlyContinue)
if($oldLogs.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach($f in $oldLogs){Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force}
}

if(Test-Path $StageDir){
    $items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage=Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $items){Move-Item $x.FullName $oldStage -Force}
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB18 FIX3 - Decoded event source discovery"
    Write-Host "========================================================================"

    $Patcher=Join-Path $Root "analysis\stage14\naruto_patcher.py"
    if(-not(Test-Path $Patcher)){throw "stage14 naruto_patcher.py를 찾지 못했습니다: $Patcher"}

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub18_fix3_decode_discovery.py"
    if(-not(Test-Path $PyScript)){throw "SUB18 FIX1 Python 스크립트를 찾지 못했습니다."}

    Write-Host "Patcher: $Patcher"
    Write-Host "Output : $StageDir"
    Write-Host ""
    Write-Host "Read-only: decoded TBL discovery + patcher source inspection"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB18 FIX3 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB18 FIX3 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host
    @(
        "Naruto SUB18 FIX3 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    function Copy-DiagnosticFile {
        param(
            [string]$Source,
            [string]$DestinationName
        )
        try {
            if(Test-Path $Source){
                $dst=Join-Path $Pkg $DestinationName
                $parent=Split-Path $dst -Parent
                if($parent){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
                Copy-Item $Source $dst -Force -ErrorAction Stop
            }
        } catch {
            # Packaging must never mask the original failure.
        }
    }

    # Always include stage outputs that exist, even partial ones.
    foreach($f in @(
        "SUMMARY.txt",
        "sub18_fix1_report.json",
        "sub18_fix1_all_tbl_inventory.tsv",
        "sub18_fix1_decoded_tbl_candidates.tsv",
        "sub18_fix1_patcher_function_inventory.tsv",
        "sub18_fix1_patcher_snippets.tsv",
        "sub18_fix1_related_text_hits.tsv",
        "FAILURE.txt"
    )){
        Copy-DiagnosticFile (Join-Path $StageDir $f) $f
    }

    # Always include runner + python + transcript.
    if(Test-Path $Transcript){
        Copy-DiagnosticFile $Transcript ("logs\" + (Split-Path $Transcript -Leaf))
    }
    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-DiagnosticFile $PSCommandPath ("scripts\" + (Split-Path $PSCommandPath -Leaf))
    }

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub18_fix3_decode_discovery.py"
    if(Test-Path $PyScript){
        Copy-DiagnosticFile $PyScript ("scripts\" + (Split-Path $PyScript -Leaf))
    }

    # Always include the most important small source evidence.
    $PatcherEvidence=Join-Path $Root "analysis\stage14\naruto_patcher.py"
    Copy-DiagnosticFile $PatcherEvidence "evidence\naruto_patcher.py"

    $KnownDecoded=Join-Path $Root "analysis\stage14\test_patch\event000_original.tbl"
    Copy-DiagnosticFile $KnownDecoded "evidence\event000_original.tbl"

    $Sub09=Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_sequence.tsv"
    Copy-DiagnosticFile $Sub09 "evidence\sub09_final_sequence.tsv"

    # Include any evidence/partial results already generated by Python.
    $EvidenceDir=Join-Path $StageDir "evidence"
    if(Test-Path $EvidenceDir){
        foreach($f in @(Get-ChildItem $EvidenceDir -File -Recurse -ErrorAction SilentlyContinue)){
            try{
                if($f.Length -gt 6MB){continue}
                $rel=$f.FullName.Substring($StageDir.Length).TrimStart('\')
                Copy-DiagnosticFile $f $rel
            }catch{}
        }
    }

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub18_fix3_decode_discovery_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB18 FIX3 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        # Canonical failure ZIP: directly under logs with fail_ prefix.
        $FailZip=Join-Path $LogsDir "fail_naruto_sub18_fix3_decode_discovery_upload.zip"

        # Archive previous canonical fail ZIP if present.
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir "fail_naruto_sub18_fix3_decode_discovery_upload.zip") -Force -ErrorAction SilentlyContinue
            Remove-Item $FailZip -Force -ErrorAction SilentlyContinue
        }

        # Also keep timestamped failed folder for history.
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null

        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            try{
                $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
                $dst=Join-Path $fd $rel
                New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
                Copy-Item $_.FullName $dst -Force
            }catch{}
        }

        # Create fail_ ZIP in logs and timestamped copy in logs\failed\<stamp>.
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        $FailedArchiveZip=Join-Path $fd "fail_naruto_sub18_fix3_decode_discovery_upload.zip"
        Copy-Item $FailZip $FailedArchiveZip -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
        Write-Host "Archived copy:"
        Write-Host "  $FailedArchiveZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
