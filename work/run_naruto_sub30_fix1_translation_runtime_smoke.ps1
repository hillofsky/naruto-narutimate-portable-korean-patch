# Naruto PSP SUB30 FIX1 - Korean translation runtime smoke
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub30_fix1_translation_runtime_smoke"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub30_fix1_translation_runtime_smoke_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub30_fix1_translation_runtime_smoke_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub30_fix1_translation_runtime_smoke_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null

if(Test-Path $StageDir){
    $Keep=@("previous_success.iso")
    $items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage=Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $items){
            if($x.Name -notin $Keep){
                Move-Item $x.FullName $oldStage -Force
            }
        }
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB30 FIX1 - Korean Translation Runtime Smoke"
    Write-Host "========================================================================"
    Write-Host "Patches event000 display messages 1..24 only."
    Write-Host "Build chain: decoded TBL -> Stage14 DAT/IDX -> Stage24 ISO -> independent ISO verify."
    Write-Host ""

    $Required=@(
        (Join-Path $Root "analysis\sub\sub29_completed_korean_draft\sub29_full_korean_draft_1976.tsv"),
        (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv"),
        (Join-Path $Root "analysis\sub\sub16_collision_free_boot\BOOT_sub16_collision_free_hangul.bin"),
        (Join-Path $Root "analysis\stage14\naruto_patcher.py"),
        (Join-Path $Root "analysis\stage24\stage24_iso_multi_patch.py"),
        (Join-Path $Root "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso")
    )
    foreach($p in $Required){
        if(-not(Test-Path $p)){throw "Required input missing: $p"}
    }

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub30_fix1_translation_runtime_smoke.py"
    if(-not(Test-Path $PyScript)){throw "SUB30 Python script missing."}

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB30 FIX1 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB30 FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB30 FIX1 FAILURE",
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
        "SUMMARY.txt","sub30_fix1_report.json","TEST_INSTRUCTIONS.txt",
        "sub30_fix1_smoke_rows.tsv","sub30_fix1_expected_checkpoints.tsv",
        "event000_sub30_fix1_smoke.tbl",
        "sub30_fix1_stage14_console.log","sub30_fix1_stage24_console.log",
        "FAILURE.txt"
    )){
        Copy-Diag (Join-Path $StageDir $f) $f
    }

    # Collect only small Stage14/Stage24 reports. Never package DAT or ISO.
    foreach($dirName in @("stage14_build","stage24_report")){
        $d=Join-Path $StageDir $dirName
        if(Test-Path $d){
            foreach($f in @(Get-ChildItem $d -File -Recurse -ErrorAction SilentlyContinue)){
                if($f.Extension -notin @(".dat",".iso",".bin") -and $f.Length -le 5MB){
                    $rel=$f.FullName.Substring($d.Length).TrimStart("\")
                    Copy-Diag $f.FullName ("$dirName\"+$rel)
                }
            }
        }
    }

    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){
        Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))
    }
    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub30_fix1_translation_runtime_smoke.py"
    Copy-Diag $PyScript ("scripts\"+(Split-Path $PyScript -Leaf))

    Copy-Diag (Join-Path $Root "analysis\stage14\naruto_patcher.py") "evidence\naruto_patcher.py"
    Copy-Diag (Join-Path $Root "analysis\stage24\stage24_iso_multi_patch.py") "evidence\stage24_iso_multi_patch.py"
    Copy-Diag (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv") "evidence\event_font_hangul_mapping.tsv"

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
        Write-Host "SUB30 FIX1 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"
        Write-Host "Runtime smoke ISO:"
        Write-Host "  $Root\Naruto - SUB30 FIX1 Korean Translation Runtime Smoke.iso"
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
