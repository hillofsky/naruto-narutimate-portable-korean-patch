# Naruto PSP SUB10 FIX1 - Stage35R actual-schema donor allocation
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub10_donor_allocation"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$SharedDir=Join-Path $Root "analysis\shared"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub10_donor_allocation_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub10_donor_allocation_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$SharedOut=Join-Path $SharedDir "event_font_hangul_mapping.tsv"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$SharedDir | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub10_donor_allocation_*.log" -ErrorAction SilentlyContinue)
if($oldLogs.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach($f in $oldLogs){
        Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force
    }
}

if(Test-Path $StageDir){
    $items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage=Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $items){
            Move-Item $x.FullName $oldStage -Force
        }
    }
}

if(Test-Path $SharedOut){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    Copy-Item $SharedOut (Join-Path $ArchiveDir "event_font_hangul_mapping_before_sub10_fix1.tsv") -Force
}

New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB10 FIX1 - Final Hangul -> Stage35R STRICT donors"
    Write-Host "========================================================================"

    $Unique=Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_unique_hangul.txt"
    if(-not(Test-Path $Unique)){
        throw "SUB09 최종 문자셋을 찾지 못했습니다: $Unique"
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub10_donor_allocation_FIX1.py"
    if(-not(Test-Path $PyScript)){
        throw "SUB10 FIX1 Python 스크립트를 찾지 못했습니다: $PyScript"
    }

    Write-Host "Hangul : $Unique"
    Write-Host "Output : $StageDir"
    Write-Host "Shared : $SharedOut"
    Write-Host ""
    Write-Host "Using Stage35R actual schema:"
    Write-Host "  stage35r_slot_candidates.tsv"
    Write-Host "  glyph / donor_code / donor_class / strict_safe / reclaim_safe"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir --shared $SharedDir
    if($LASTEXITCODE -ne 0){
        throw "SUB10 FIX1 Python failed. ExitCode=$LASTEXITCODE"
    }

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB10 FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB10 FIX1 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8

}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($f in @(
        "SUMMARY.txt",
        "sub10_hangul_donor_mapping.tsv",
        "sub10_fixed_stage36r.tsv",
        "sub10_strict_pool_snapshot.tsv",
        "sub10_source_files.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){
            Copy-Item $src $Pkg -Force
        }
    }

    $Evidence=Join-Path $StageDir "source_evidence"
    if(Test-Path $Evidence){
        $dst=Join-Path $Pkg "source_evidence"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        foreach($f in @(Get-ChildItem $Evidence -File -ErrorAction SilentlyContinue)){
            Copy-Item $f.FullName $dst -Force
        }
    }

    if(Test-Path $SharedOut){Copy-Item $SharedOut $Pkg -Force}
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-Item $PSCommandPath $Pkg -Force
    }

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub10_donor_allocation_FIX1.py"
    if(Test-Path $PyScript){
        Copy-Item $PyScript $Pkg -Force
    }

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub10_donor_allocation_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB10 FIX1 SUCCESS"
        Write-Host "Shared mapping:"
        Write-Host "  $SharedOut"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"

    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null

        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }

        $fz=Join-Path $fd "naruto_sub10_donor_allocation_FIX1_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
