# Naruto PSP SUB13 - Full Hangul donor runtime smoke ISO
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub13_runtime_smoke"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$PatchDir=Join-Path $StageDir "patch"
$IsoReportDir=Join-Path $StageDir "iso_report"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub13_runtime_smoke_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub13_runtime_smoke_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$OutIso=Join-Path $Root "Naruto - SUB13 Full Hangul Runtime Smoke.iso"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub13_runtime_smoke_*.log" -ErrorAction SilentlyContinue)
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
    Write-Host " Naruto SUB13 - Full Hangul donor runtime smoke ISO"
    Write-Host "========================================================================"

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $Builder=Join-Path $ScriptDir "naruto_sub13_runtime_smoke.py"
    if(-not(Test-Path $Builder)){throw "SUB13 Python 스크립트를 찾지 못했습니다: $Builder"}

    $SourceIso=Join-Path $Root "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
    $Boot=Join-Path $Root "analysis\sub\sub12_full_glyph_build\BOOT_sub12_full_hangul.bin"
    $Patcher=Join-Path $Root "analysis\stage14\naruto_patcher.py"
    $IsoPatcher=Join-Path $Root "analysis\stage24\stage24_iso_multi_patch.py"

    foreach($p in @($SourceIso,$Boot,$Patcher,$IsoPatcher)){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    Write-Host "[1/4] Build runtime probe TBL"
    & $Py.Source $Builder build --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB13 probe TBL build failed. ExitCode=$LASTEXITCODE"}

    $ProbeTbl=Join-Path $StageDir "event000_sub13_runtime_smoke.tbl"
    if(-not(Test-Path $ProbeTbl)){throw "SUB13 probe TBL missing: $ProbeTbl"}

    if(Test-Path $PatchDir){Remove-Item $PatchDir -Recurse -Force}
    $ReplaceArg="event000.tbl=$ProbeTbl"

    Write-Host ""
    Write-Host "[2/4] Patch naruto.dat / naruto.idx"
    & $Py.Source $Patcher `
        --root $Root `
        --output $PatchDir `
        --replace $ReplaceArg `
        --force
    if($LASTEXITCODE -ne 0){throw "SUB13 DAT/IDX patch failed. ExitCode=$LASTEXITCODE"}

    $Dat=Join-Path $PatchDir "naruto.dat"
    $Idx=Join-Path $PatchDir "naruto.idx"
    foreach($p in @($Dat,$Idx)){
        if(-not(Test-Path $p)){throw "SUB13 patched archive missing: $p"}
    }

    if(Test-Path $IsoReportDir){Remove-Item $IsoReportDir -Recurse -Force}
    if(Test-Path $OutIso){Remove-Item $OutIso -Force}

    Write-Host ""
    Write-Host "[3/4] Build runtime smoke ISO"
    & $Py.Source $IsoPatcher `
        --source-iso $SourceIso `
        --dat $Dat `
        --idx $Idx `
        --boot $Boot `
        --output-iso $OutIso `
        --report-dir $IsoReportDir
    if($LASTEXITCODE -ne 0){throw "SUB13 ISO patch failed. ExitCode=$LASTEXITCODE"}
    if(-not(Test-Path $OutIso)){throw "SUB13 ISO was not created: $OutIso"}

    Write-Host ""
    Write-Host "[4/4] Verify embedded BOOT/DAT/IDX"
    & $Py.Source $Builder verify `
        --root $Root `
        --out $StageDir `
        --iso $OutIso `
        --dat $Dat `
        --idx $Idx `
        --boot $Boot
    if($LASTEXITCODE -ne 0){throw "SUB13 ISO verification failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB13 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host
    @(
        "Naruto SUB13 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8

}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    # ISO and huge DAT are intentionally excluded.
    foreach($f in @(
        "SUMMARY.txt",
        "sub13_build_report.json",
        "sub13_iso_verify.json",
        "sub13_probe_map.tsv",
        "sub13_runtime_checklist.txt",
        "event000_sub13_runtime_smoke.tbl",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $Idx){
        Copy-Item $Idx (Join-Path $Pkg "naruto_sub13.idx") -Force
    }

    if(Test-Path $IsoReportDir){
        $dst=Join-Path $Pkg "iso_report"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        foreach($f in @(Get-ChildItem $IsoReportDir -File -Recurse -ErrorAction SilentlyContinue)){
            if($f.Length -le 4MB){
                $rel=$f.FullName.Substring($IsoReportDir.Length).TrimStart('\')
                $target=Join-Path $dst $rel
                New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
                Copy-Item $f.FullName $target -Force
            }
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $Pkg -Force}
    $Builder=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub13_runtime_smoke.py"
    if(Test-Path $Builder){Copy-Item $Builder $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub13_runtime_smoke_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB13 SUCCESS"
        Write-Host "Runtime test ISO:"
        Write-Host "  $OutIso"
        Write-Host "Checklist:"
        Write-Host "  $(Join-Path $StageDir 'sub13_runtime_checklist.txt')"
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

        $fz=Join-Path $fd "naruto_sub13_runtime_smoke_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
