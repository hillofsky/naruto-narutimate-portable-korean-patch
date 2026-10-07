# Naruto PSP SUB34 - integrate final SUB work onto exact MOV06E ISO base
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub34_mov06e_sub_integration"
$StageRoot=Join-Path $Root "analysis\integrated\$StageName"
$Work=Join-Path $StageRoot "work"
$OutputDir=Join-Path $StageRoot "output"
$FinalIso=Join-Path $OutputDir "Naruto_KR_MOV06E_SUB34_AllTranslated_Final.iso"

$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub34_mov06e_sub_integration_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub34_mov06e_sub_integration_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub34_mov06e_sub_integration_upload.zip"
$FailureTxt=Join-Path $Work "FAILURE.txt"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot,$StageRoot,$OutputDir|Out-Null

if(Test-Path $Work){
    $items=@(Get-ChildItem $Work -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
        foreach($x in $items){Move-Item $x.FullName $ArchiveDir -Force}
    }
}
New-Item -ItemType Directory -Force -Path $Work|Out-Null

$Succeeded=$false
$RuntimeRecord=$null

Start-Transcript -Path $Transcript -Force|Out-Null
try{
    Write-Host "Naruto SUB34 - MOV06E + SUB final integration"
    Write-Host "MOV06E base is mandatory. No fallback to old KR ISO."

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub34_mov06e_sub_integration.py"
    $Manifest=Join-Path $ScriptDir "sub34_integration_manifest.json"
    if(-not(Test-Path $PyScript)){throw "SUB34 Python script missing."}
    if(-not(Test-Path $Manifest)){throw "SUB34 manifest missing."}

    & $Py.Source $PyScript --root $Root --work $Work
    if($LASTEXITCODE -ne 0){
        throw "SUB34 integration Python failed. ExitCode=$LASTEXITCODE"
    }
    if(-not(Test-Path $FinalIso)){
        throw "Integrated final ISO was not created: $FinalIso"
    }

    Write-Host ""
    Write-Host "Static integration passed."
    Write-Host "Running Naruto runtime screenshot macro on the integrated ISO..."

    $Macro=Join-Path $Root "generated_macros\naruto.bat"
    $ShotRoot=Join-Path $Root "macro_screenshots"
    if(-not(Test-Path $Macro)){
        throw "Runtime macro missing: $Macro"
    }
    New-Item -ItemType Directory -Force -Path $ShotRoot|Out-Null

    $Before=@{}
    Get-ChildItem $ShotRoot -Directory -Filter "record_*" -ErrorAction SilentlyContinue | ForEach-Object {
        $Before[$_.FullName]=$true
    }

    & cmd.exe /d /c "`"$Macro`" `"$FinalIso`""
    $MacroExit=$LASTEXITCODE
    Write-Host "Macro exit code: $MacroExit"

    # Find the new record folder. The BAT may return before all captures finish,
    # so wait for a new record and then wait until image count stabilizes.
    $Deadline=(Get-Date).AddMinutes(10)
    do{
        $RuntimeRecord=Get-ChildItem $ShotRoot -Directory -Filter "record_*" -ErrorAction SilentlyContinue |
            Where-Object { -not $Before.ContainsKey($_.FullName) } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if(-not $RuntimeRecord){Start-Sleep -Seconds 2}
    }while((-not $RuntimeRecord) -and ((Get-Date) -lt $Deadline))

    if(-not $RuntimeRecord){
        throw "No new macro_screenshots\record_* folder was created."
    }

    Write-Host "New runtime record: $($RuntimeRecord.FullName)"

    $StableCount=-1
    $StableRounds=0
    do{
        $imgs=@(Get-ChildItem $RuntimeRecord.FullName -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -match '^\.(png|jpg|jpeg)$' })
        $Count=$imgs.Count
        if($Count -eq $StableCount -and $Count -gt 0){
            $StableRounds++
        }else{
            $StableRounds=0
            $StableCount=$Count
        }
        if($StableRounds -lt 3){Start-Sleep -Seconds 4}
    }while(($StableRounds -lt 3) -and ((Get-Date) -lt $Deadline))

    $Imgs=@(Get-ChildItem $RuntimeRecord.FullName -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '^\.(png|jpg|jpeg)$' } |
        Sort-Object Name)
    if($Imgs.Count -eq 0){
        throw "Runtime record folder contains no screenshots."
    }
    Write-Host "Runtime screenshots: $($Imgs.Count)"

    $ManifestLines=@(
        "Naruto SUB34 runtime screenshot manifest",
        "IntegratedISO=$FinalIso",
        "RecordFolder=$($RuntimeRecord.FullName)",
        "ScreenshotCount=$($Imgs.Count)",
        ""
    )
    foreach($img in $Imgs){
        $hash=(Get-FileHash $img.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $ManifestLines += "$($img.Name)`t$($img.Length)`t$hash"
    }
    $ManifestLines | Set-Content (Join-Path $Work "screenshots_manifest.txt") -Encoding UTF8

    @(
        "Naruto PSP SUB34 Runtime Validation",
        "IntegratedISO=$FinalIso",
        "RuntimeRecord=$($RuntimeRecord.FullName)",
        "ScreenshotCount=$($Imgs.Count)",
        "MacroExitCode=$MacroExit",
        "SpaceEncoding=A0_NARROW_PROBE",
        "VisualReviewPending=YES"
    ) | Set-Content (Join-Path $Work "RUNTIME.txt") -Encoding UTF8

    $Succeeded=$true
}catch{
    Write-Host "!!!!!!!! SUB34 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
        "Naruto SUB34 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "FinalIsoExpected=$FinalIso",
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
        "sub34_integration_report.json",
        "sub34_event_patch_manifest.tsv",
        "sub34_iso_target_verification.tsv",
        "sub34_movie_preservation.tsv",
        "sub34_stage14_console.log",
        "sub34_stage24_console.log",
        "screenshots_manifest.txt"
    )){
        Copy-Diag (Join-Path $Work $f) $f
    }

    foreach($f in @(
        "stage14_summary.txt","replacement_manifest.tsv","validation.tsv",
        "primary_patch_map.tsv","fsts_patch_map.tsv"
    )){
        Copy-Diag (Join-Path (Join-Path $Work "stage14_build") $f) ("stage14_build\"+$f)
    }

    $Stage24Dir=Join-Path $Work "stage24_report"
    if(Test-Path $Stage24Dir){
        Get-ChildItem $Stage24Dir -File -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Diag $_.FullName ("stage24_report\"+$_.Name)
        }
    }

    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){
        Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))
    }
    $ScriptDir=Split-Path -Parent $PSCommandPath
    Copy-Diag (Join-Path $ScriptDir "naruto_sub34_mov06e_sub_integration.py") "scripts\naruto_sub34_mov06e_sub_integration.py"
    Copy-Diag (Join-Path $ScriptDir "sub34_integration_manifest.json") "scripts\sub34_integration_manifest.json"

    Copy-Diag (Join-Path $Root "analysis\sub\sub33_merge_final_semantic_review\sub33_patcher_ready_1976.tsv") "evidence\sub33_patcher_ready_1976.tsv"
    Copy-Diag (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv") "evidence\event_font_hangul_mapping.tsv"

    if($RuntimeRecord -and (Test-Path $RuntimeRecord.FullName)){
        $ShotDest=Join-Path $Pkg "screenshots"
        New-Item -ItemType Directory -Force -Path $ShotDest|Out-Null
        Get-ChildItem $RuntimeRecord.FullName -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -match '^\.(png|jpg|jpeg)$' } |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $ShotDest $_.Name) -Force }
    }

    if($Succeeded){
        if(Test-Path $SuccessZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $SuccessZip (Join-Path $ArchiveDir (Split-Path $SuccessZip -Leaf)) -Force
        }
        if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue}
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $SuccessZip -Force

        Write-Host ""
        Write-Host "SUB34 SUCCESS"
        Write-Host "Integrated ISO:"
        Write-Host "  $FinalIso"
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"
    }else{
        if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue}
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item $FailZip (Join-Path $fd (Split-Path $FailZip -Leaf)) -Force
        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
        if(Test-Path $FinalIso){
            Write-Host "Integrated ISO remains locally for diagnosis:"
            Write-Host "  $FinalIso"
        }
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
