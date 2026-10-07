# Naruto PSP SUB35 - 23 chars x 2 lines final integration
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub35_mov06e_sub_23x2"
$StageRoot=Join-Path $Root "analysis\integrated\$StageName"
$Work=Join-Path $StageRoot "work"
$OutputDir=Join-Path $StageRoot "output"
$FinalIso=Join-Path $OutputDir "Naruto_KR_MOV06E_SUB35_23x2_Final.iso"
$LayoutDir=Join-Path $Root "analysis\sub\sub35_23x2_layout"

$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub35_fix1_23x2_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub35_fix1_23x2_final_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub35_fix1_23x2_final_upload.zip"
$FailureTxt=Join-Path $Work "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$StageRoot,$OutputDir,$LayoutDir|Out-Null

$ScriptDir=Split-Path -Parent $PSCommandPath
Copy-Item (Join-Path $ScriptDir "sub35_patcher_ready_1976_23x2.tsv") (Join-Path $LayoutDir "sub35_patcher_ready_1976_23x2.tsv") -Force
Copy-Item (Join-Path $ScriptDir "sub35_layout_changes_79.tsv") (Join-Path $LayoutDir "sub35_layout_changes_79.tsv") -Force
Copy-Item (Join-Path $ScriptDir "sub35_layout_report.json") (Join-Path $LayoutDir "sub35_layout_report.json") -Force

if(Test-Path $Work){Remove-Item $Work -Recurse -Force}
New-Item -ItemType Directory -Force -Path $Work|Out-Null

$Succeeded=$false
$RuntimeRecord=$null
$RunStart=Get-Date

Start-Transcript -Path $Transcript -Force|Out-Null
try{
    Write-Host "Naruto SUB35 FIX1 - MOV06E + final Korean 23x2 layout"
    Write-Host "Layout rule: max 23 visible chars per line, max 2 lines."
    Write-Host "A0 narrow spaces retained."

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $P=Join-Path $ScriptDir "naruto_sub35_mov06e_sub_23x2_integration.py"
    $M=Join-Path $ScriptDir "sub35_integration_manifest.json"
    if(-not(Test-Path $P)){throw "SUB35 Python missing."}
    if(-not(Test-Path $M)){throw "SUB35 manifest missing."}

    & $Py.Source $P --root $Root --work $Work
    if($LASTEXITCODE -ne 0){throw "SUB35 integration failed. ExitCode=$LASTEXITCODE"}
    if(-not(Test-Path $FinalIso)){throw "SUB35 final ISO missing: $FinalIso"}

    Write-Host "Static integration PASS. Running runtime screenshot macro..."

    $Macro=Join-Path $Root "generated_macros\naruto.bat"
    $ShotRoot=Join-Path $Root "macro_screenshots"
    if(-not(Test-Path $Macro)){throw "Runtime macro missing: $Macro"}
    New-Item -ItemType Directory -Force -Path $ShotRoot|Out-Null

    & cmd.exe /d /c "`"$Macro`" `"$FinalIso`""
    $MacroExit=$LASTEXITCODE
    Write-Host "Macro exit code: $MacroExit"

    $Deadline=(Get-Date).AddMinutes(2)
    do{
        $RuntimeRecord=Get-ChildItem $ShotRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.Name -like "naruto_*" -or $_.Name -like "record_*") -and
                $_.LastWriteTime -ge $RunStart.AddSeconds(-2)
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if(-not $RuntimeRecord){Start-Sleep -Seconds 2}
    }while((-not $RuntimeRecord) -and ((Get-Date) -lt $Deadline))

    if(-not $RuntimeRecord){throw "No new naruto_* / record_* screenshot folder found."}

    $Imgs=@(Get-ChildItem $RuntimeRecord.FullName -File -ErrorAction SilentlyContinue |
        Where-Object {$_.Extension -match '^\.(png|jpg|jpeg)$'} |
        Sort-Object Name)
    if($Imgs.Count -eq 0){throw "Runtime screenshot folder is empty."}

    Write-Host "Runtime folder: $($RuntimeRecord.FullName)"
    Write-Host "Screenshots: $($Imgs.Count)"

    $ManifestLines=@(
        "Naruto SUB35 screenshot manifest",
        "IntegratedISO=$FinalIso",
        "RecordFolder=$($RuntimeRecord.FullName)",
        "ScreenshotCount=$($Imgs.Count)",
        ""
    )
    foreach($img in $Imgs){
        $h=(Get-FileHash $img.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $ManifestLines += "$($img.Name)`t$($img.Length)`t$h"
    }
    $ManifestLines|Set-Content (Join-Path $Work "screenshots_manifest.txt") -Encoding UTF8

    @(
        "Naruto PSP SUB35 Runtime Validation",
        "IntegratedISO=$FinalIso",
        "MacroExitCode=$MacroExit",
        "RuntimeRecord=$($RuntimeRecord.FullName)",
        "ScreenshotCount=$($Imgs.Count)",
        "LayoutMaxVisibleChars=23",
        "LayoutMaxLines=2",
        "A0Space=VALIDATED",
        "VisualReviewPending=YES"
    )|Set-Content (Join-Path $Work "RUNTIME.txt") -Encoding UTF8

    $Succeeded=$true
}catch{
    Write-Host "!!!!!!!! SUB35 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
        "Naruto SUB35 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $Work "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    function Copy-Diag{
        param([string]$Source,[string]$Dest)
        try{
            if(Test-Path $Source){
                $dst=Join-Path $Pkg $Dest
                $parent=Split-Path $dst -Parent
                if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
                Copy-Item $Source $dst -Force
            }
        }catch{}
    }

    foreach($f in @(
        "SUMMARY.txt","RUNTIME.txt","FAILURE.txt",
        "sub34_integration_report.json","sub34_event_patch_manifest.tsv",
        "sub34_iso_target_verification.tsv","sub34_movie_preservation.tsv",
        "sub34_stage14_console.log","sub34_stage24_console.log",
        "screenshots_manifest.txt"
    )){Copy-Diag (Join-Path $Work $f) $f}

    Copy-Diag (Join-Path $LayoutDir "sub35_patcher_ready_1976_23x2.tsv") "layout\sub35_patcher_ready_1976_23x2.tsv"
    Copy-Diag (Join-Path $LayoutDir "sub35_layout_changes_79.tsv") "layout\sub35_layout_changes_79.tsv"
    Copy-Diag (Join-Path $LayoutDir "sub35_layout_report.json") "layout\sub35_layout_report.json"
    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))

    if($RuntimeRecord -and (Test-Path $RuntimeRecord.FullName)){
        $ShotDest=Join-Path $Pkg "screenshots"
        New-Item -ItemType Directory -Force -Path $ShotDest|Out-Null
        Get-ChildItem $RuntimeRecord.FullName -File -ErrorAction SilentlyContinue |
            Where-Object {$_.Extension -match '^\.(png|jpg|jpeg)$'} |
            ForEach-Object {Copy-Item $_.FullName (Join-Path $ShotDest $_.Name) -Force}
    }

    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $Zip -Force

    if($Succeeded){
        Write-Host "SUB35 SUCCESS"
        Write-Host "Final ISO:"
        Write-Host "  $FinalIso"
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"
    }else{
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
