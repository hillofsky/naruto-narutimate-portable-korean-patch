# Naruto PSP SUB15 - Rebuild donor map from actual runtime conversion
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub15_actual_runtime_mapping"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$SharedDir=Join-Path $Root "analysis\shared"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub15_actual_runtime_mapping_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub15_actual_runtime_mapping_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$SharedOut=Join-Path $SharedDir "event_font_hangul_mapping.tsv"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$SharedDir | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub15_actual_runtime_mapping_*.log" -ErrorAction SilentlyContinue)
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

if(Test-Path $SharedOut){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    Copy-Item $SharedOut (Join-Path $ArchiveDir "event_font_hangul_mapping_before_sub15.tsv") -Force
}

New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB15 FIX2 - Actual runtime donor mapping"
    Write-Host "========================================================================"

    $Boot=Join-Path $Root "kr_extracted\PSP_GAME\SYSDIR\BOOT.BIN"
    $Unique=Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_unique_hangul.txt"

    foreach($p in @($Boot,$Unique)){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub15_actual_runtime_mapping_FIX2.py"
    if(-not(Test-Path $PyScript)){
        throw "SUB15 Python 스크립트를 찾지 못했습니다: $PyScript"
    }

    Write-Host "BOOT   : $Boot"
    Write-Host "Hangul : $Unique"
    Write-Host "Output : $StageDir"
    Write-Host "Shared : $SharedOut"
    Write-Host ""
    Write-Host "Runtime formula from 0x088D56EC:"
    Write-Host "  symbols/kana JIS rows 21-25"
    Write-Host "  skip unused JIS rows"
    Write-Host "  kanji starts JIS row 30 at glyph 464"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir --shared $SharedDir
    if($LASTEXITCODE -ne 0){
        throw "SUB15 FIX2 Python failed. ExitCode=$LASTEXITCODE"
    }

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB15 FIX2 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB15 FIX2 FAILURE",
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
        "sub15_report.json",
        "sub15_runtime_hangul_mapping.tsv",
        "sub15_runtime_slot_inventory.tsv",
        "sub15_source_coverage.tsv",
        "sub15_special_table.tsv",
        "sub15_fixed_pinned_status.tsv",
        "sub15_fixed_pinned_collisions.tsv",
        "sub15_runtime_formula_vectors.tsv",
        "sub15_vs_previous_mapping.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $SharedOut){
        Copy-Item $SharedOut $Pkg -Force
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-Item $PSCommandPath $Pkg -Force
    }

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub15_actual_runtime_mapping_FIX2.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub15_actual_runtime_mapping_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB15 FIX2 SUCCESS"
        Write-Host "Corrected shared mapping:"
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

        $fz=Join-Path $fd "naruto_sub15_actual_runtime_mapping_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
