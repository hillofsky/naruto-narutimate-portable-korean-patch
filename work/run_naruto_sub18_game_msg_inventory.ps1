# Naruto PSP SUB18 - Game event MSG inventory / subtitle alignment readiness
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub18_game_msg_inventory"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub18_game_msg_inventory_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub18_game_msg_inventory_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub18_game_msg_inventory_*.log" -ErrorAction SilentlyContinue)
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
        foreach($x in $items){Move-Item $x.FullName $oldStage -Force}
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB18 - Game event MSG inventory / alignment readiness"
    Write-Host "========================================================================"

    $TblRoot=Join-Path $Root "analysis\stage3\extracted\kr"
    $Sub09=Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_sequence.tsv"
    foreach($p in @($TblRoot,$Sub09)){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub18_game_msg_inventory.py"
    if(-not(Test-Path $PyScript)){throw "SUB18 Python 스크립트를 찾지 못했습니다."}

    Write-Host "Game TBLs : $TblRoot"
    Write-Host "SUB09     : $Sub09"
    Write-Host "Output    : $StageDir"
    Write-Host ""
    Write-Host "Read-only scan. No patching will be performed."
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB18 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB18 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB18 FAILURE",
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
        "sub18_report.json",
        "sub18_game_msg_inventory.tsv",
        "sub18_event_file_summary.tsv",
        "sub18_game_speaker_code_frequency.tsv",
        "sub18_subtitle_speaker_frequency.tsv",
        "sub18_msg_command_frequency.tsv",
        "sub18_voice_prefix_frequency.tsv",
        "sub18_structural_counts.tsv",
        "sub18_first100_order_preview.tsv",
        "sub18_event_msg_counts.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $Pkg -Force}

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub18_game_msg_inventory.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub18_game_msg_inventory_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB18 SUCCESS"
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

        $fz=Join-Path $fd "naruto_sub18_game_msg_inventory_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
