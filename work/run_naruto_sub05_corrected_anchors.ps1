# Naruto PSP SUB05 - Apply visual corrections / corrected shared anchors
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub05_corrected_anchors"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$SharedDir=Join-Path $Root "analysis\shared"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub05_corrected_anchors_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub05_corrected_anchors_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$SharedOut=Join-Path $SharedDir "youtube_subtitle_anchors.tsv"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$SharedDir | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub05_corrected_anchors_*.log" -ErrorAction SilentlyContinue)
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
if(Test-Path $SharedOut){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    Copy-Item $SharedOut (Join-Path $ArchiveDir "youtube_subtitle_anchors_before_sub05.tsv") -Force
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB05 - Apply 108 visual OCR corrections"
    Write-Host "========================================================================"

    $Sub03=Join-Path $Root "analysis\sub\sub03_sequence_timeline\sub03_dialogue_sequence.tsv"
    $Sub04=Join-Path $Root "analysis\sub\sub04_rare_ocr_review\sub04_review_queue.tsv"
    if(-not(Test-Path $Sub03)){throw "SUB03 결과를 찾지 못했습니다: $Sub03"}
    if(-not(Test-Path $Sub04)){throw "SUB04 결과를 찾지 못했습니다: $Sub04"}

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub05_corrected_anchors.py"
    if(-not(Test-Path $PyScript)){throw "SUB05 Python 스크립트를 찾지 못했습니다."}

    Write-Host "SUB03 : $Sub03"
    Write-Host "SUB04 : $Sub04"
    Write-Host "Output: $StageDir"
    Write-Host "Shared: $SharedOut"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir --shared $SharedDir
    if($LASTEXITCODE -ne 0){throw "SUB05 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB05 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host
    @(
        "Naruto SUB05 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($f in @(
        "SUMMARY.txt","sub05_corrected_sequence.tsv","sub05_corrected_sequence.csv",
        "sub05_correction_log.tsv","sub05_unresolved.tsv",
        "sub05_residual_bad_patterns.tsv","sub05_char_frequency.tsv",
        "sub05_unique_hangul.txt","sub05_visual_reviewed_entries.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $SharedOut){Copy-Item $SharedOut $Pkg -Force}
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $Pkg -Force}

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub05_corrected_anchors.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub05_corrected_anchors_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "SUB05 SUCCESS"
        Write-Host "Shared corrected anchors:"
        Write-Host "  $SharedOut"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue|ForEach-Object{
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_sub05_corrected_anchors_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
