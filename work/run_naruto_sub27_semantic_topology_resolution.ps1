# Naruto PSP SUB27 - Manual semantic topology resolution
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub27_semantic_topology_resolution"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub27_semantic_topology_resolution_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub27_semantic_topology_resolution_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub27_semantic_topology_resolution_upload.zip"
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
    Write-Host " Naruto SUB27 - Manual semantic topology resolution"
    Write-Host "========================================================================"
    Write-Host "Read-only. 177 exception blocks, manually reviewed JP/EN/KO topology."
    Write-Host "No game patching."
    Write-Host ""

    $Required=@(
        (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_exception_blocks.tsv"),
        (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_block_subtitles.tsv"),
        (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_block_game_candidates.tsv"),
        (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_stable_anchor_context.tsv"),
        (Join-Path $Root "analysis\sub\sub25_fix2_voice_timeline_reconstruction\sub25_fix2_subtitle_voice_groups.tsv"),
        (Join-Path $Root "analysis\sub\sub19_fix1_event_inventory\sub19_fix1_kr_display_messages.tsv"),
        (Join-Path $Root "analysis\sub\sub19_fix1_event_inventory\sub19_fix1_us_display_messages.tsv"),
        (Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_sequence.tsv")
    )
    foreach($p in $Required){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub27_semantic_topology_resolution.py"
    if(-not(Test-Path $PyScript)){throw "SUB27 Python 스크립트를 찾지 못했습니다."}

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB27 Python failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB27 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB27 FAILURE",
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
        "SUMMARY.txt","sub27_report.json",
        "sub27_semantic_block_resolution.tsv",
        "sub27_mapping_units.tsv",
        "sub27_anchor_overrides.tsv",
        "sub27_subtitle_exclusions.tsv",
        "sub27_exception_game_only_rows.tsv",
        "sub27_all_unmapped_game_rows.tsv",
        "sub27_semantic_resolution_filled.tsv",
        "sub27_semantic_audit_packet.txt",
        "FAILURE.txt"
    )){
        Copy-Diag (Join-Path $StageDir $f) $f
    }

    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){
        Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))
    }
    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub27_semantic_topology_resolution.py"
    Copy-Diag $PyScript ("scripts\"+(Split-Path $PyScript -Leaf))

    # Repro/diagnostic inputs
    Copy-Diag (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_exception_blocks.tsv") "evidence\sub26_exception_blocks.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_block_subtitles.tsv") "evidence\sub26_block_subtitles.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_block_game_candidates.tsv") "evidence\sub26_block_game_candidates.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub26_semantic_exception_bundle\sub26_stable_anchor_context.tsv") "evidence\sub26_stable_anchor_context.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub25_fix2_voice_timeline_reconstruction\sub25_fix2_subtitle_voice_groups.tsv") "evidence\sub25_fix2_subtitle_voice_groups.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub19_fix1_event_inventory\sub19_fix1_kr_display_messages.tsv") "evidence\sub19_kr_display_messages.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub19_fix1_event_inventory\sub19_fix1_us_display_messages.tsv") "evidence\sub19_us_display_messages.tsv"
    Copy-Diag (Join-Path $Root "analysis\sub\sub09_final_speaker_corpus\sub09_final_sequence.tsv") "evidence\sub09_final_sequence.tsv"

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
        Write-Host "SUB27 SUCCESS"
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
