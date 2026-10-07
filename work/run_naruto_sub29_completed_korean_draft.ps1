# Naruto PSP SUB29 - Completed Korean draft validation
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub29_completed_korean_draft"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub29_completed_korean_draft_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub29_completed_korean_draft_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub29_completed_korean_draft_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null

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
    Write-Host " Naruto SUB29 - Completed Korean draft validation"
    Write-Host "========================================================================"
    Write-Host "Read-only. 1976 game messages / 407 completed task units."
    Write-Host ""

    $Required=@(
        (Join-Path $Root "analysis\sub\sub28_translation_worklist\sub28_full_translation_manifest_1976.tsv"),
        (Join-Path $Root "analysis\sub\sub28_translation_worklist\sub28_translation_task_units_407.tsv"),
        (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv"),
        (Join-Path $Root "analysis\stage14\naruto_patcher.py")
    )
    foreach($p in $Required){
        if(-not(Test-Path $p)){throw "Required input missing: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub29_completed_korean_draft.py"
    $TranslationJson=Join-Path $ScriptDir "sub29_translations.json"
    if(-not(Test-Path $PyScript)){throw "SUB29 Python script missing."}
    if(-not(Test-Path $TranslationJson)){throw "SUB29 translation JSON missing."}

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB29 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB29 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host
    @(
        "Naruto SUB29 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    function Copy-Diag {
        param([string]$Source,[string]$Dest)
        try{
            if(Test-Path $Source){
                $dst=Join-Path $Pkg $Dest
                $parent=Split-Path $dst -Parent
                if($parent){New-Item -ItemType Directory -Force -Path $parent | Out-Null}
                Copy-Item $Source $dst -Force -ErrorAction Stop
            }
        }catch{}
    }

    foreach($f in @(
        "SUMMARY.txt","sub29_report.json",
        "sub29_full_korean_draft_1976.tsv",
        "sub29_completed_task_units_407.tsv",
        "sub29_payload_size_audit.tsv",
        "sub29_longest_lines_top100.tsv",
        "sub29_font_validation.txt",
        "sub29_control_validation.txt",
        "sub29_runtime_encoding_validation.txt",
        "sub29_patcher_constraint_conclusion.txt",
        "FAILURE.txt"
    )){
        Copy-Diag (Join-Path $StageDir $f) $f
    }

    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))}
    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub29_completed_korean_draft.py"
    $TranslationJson=Join-Path (Split-Path -Parent $PSCommandPath) "sub29_translations.json"
    Copy-Diag $PyScript ("scripts\"+(Split-Path $PyScript -Leaf))
    Copy-Diag $TranslationJson ("scripts\"+(Split-Path $TranslationJson -Leaf))

    Copy-Diag (Join-Path $Root "analysis\sub\sub28_translation_worklist\sub28_full_translation_manifest_1976.tsv") "evidence\sub28_full_translation_manifest_1976.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub28_translation_worklist\sub28_translation_task_units_407.tsv") "evidence\sub28_translation_task_units_407.tsv"
    Copy-Diag (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv") "evidence\event_font_hangul_mapping.tsv"
    Copy-Diag (Join-Path $Root "analysis\stage14\naruto_patcher.py") "evidence\naruto_patcher.py"

    if($Succeeded){
        if(Test-Path $SuccessZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $SuccessZip (Join-Path $ArchiveDir (Split-Path $SuccessZip -Leaf)) -Force
        }
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir (Split-Path $FailZip -Leaf)) -Force
            Remove-Item $FailZip -Force -ErrorAction SilentlyContinue
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $SuccessZip -Force
        Write-Host ""
        Write-Host "SUB29 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"
    }else{
        if(Test-Path $FailZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $FailZip (Join-Path $ArchiveDir (Split-Path $FailZip -Leaf)) -Force
            Remove-Item $FailZip -Force -ErrorAction SilentlyContinue
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Copy-Item $FailZip (Join-Path $fd (Split-Path $FailZip -Leaf)) -Force
        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
