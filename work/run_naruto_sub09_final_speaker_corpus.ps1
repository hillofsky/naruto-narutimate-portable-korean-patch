# Naruto PSP SUB09 - Final speaker cleanup / canonical subtitle corpus
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub09_final_speaker_corpus"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$SharedDir=Join-Path $Root "analysis\shared"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub09_final_speaker_corpus_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub09_final_speaker_corpus_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$SharedOut=Join-Path $SharedDir "youtube_subtitle_anchors.tsv"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$SharedDir | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub09_final_speaker_corpus_*.log" -ErrorAction SilentlyContinue)
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
    Copy-Item $SharedOut (Join-Path $ArchiveDir "youtube_subtitle_anchors_before_sub09.tsv") -Force
}

New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB09 - Final speaker-corrected subtitle corpus"
    Write-Host "========================================================================"

    $Sub07=Join-Path $Root "analysis\sub\sub07_final_corpus\sub07_final_sequence.tsv"
    $Sub08a=Join-Path $Root "analysis\sub\sub08_speaker_audit\sub08_exact_structure_rows.tsv"
    $Sub08b=Join-Path $Root "analysis\sub\sub08_speaker_audit\sub08_ambiguous_speaker_rows.tsv"

    foreach($p in @($Sub07,$Sub08a,$Sub08b)){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub09_final_speaker_corpus.py"
    if(-not(Test-Path $PyScript)){
        throw "SUB09 Python 스크립트를 찾지 못했습니다: $PyScript"
    }

    Write-Host "SUB07 : $Sub07"
    Write-Host "SUB08 : $Sub08a"
    Write-Host "        $Sub08b"
    Write-Host "Output: $StageDir"
    Write-Host "Shared: $SharedOut"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir --shared $SharedDir
    if($LASTEXITCODE -ne 0){
        throw "SUB09 Python failed. ExitCode=$LASTEXITCODE"
    }

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB09 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB09 FAILURE",
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
        "SUMMARY.txt",
        "sub09_final_sequence.tsv",
        "sub09_final_sequence.csv",
        "sub09_speaker_audit.tsv",
        "sub09_speaker_frequency.tsv",
        "sub09_final_char_frequency.tsv",
        "sub09_final_unique_hangul.txt",
        "sub09_final_dialogue_corpus.txt",
        "sub09_excluded_from_char_corpus.tsv",
        "sub09_structural_residual.tsv",
        "sub09_malformed_speaker_residual.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $SharedOut){Copy-Item $SharedOut $Pkg -Force}
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-Item $PSCommandPath $Pkg -Force
    }

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub09_final_speaker_corpus.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub09_final_speaker_corpus_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB09 SUCCESS"
        Write-Host "Final shared anchors:"
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

        $fz=Join-Path $fd "naruto_sub09_final_speaker_corpus_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
