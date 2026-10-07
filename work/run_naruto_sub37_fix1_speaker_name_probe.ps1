# Naruto PSP SUB37 FIX1 - speaker-name Korean probe + bounded UI inventory
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub37_fix1_speaker_name_probe"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub37_fix1_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub37_fix1_speaker_name_probe_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub37_fix1_speaker_name_probe_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot|Out-Null
if(Test-Path $StageDir){
    $Archive=Join-Path (Join-Path $OldRoot $Stamp) $StageName
    New-Item -ItemType Directory -Force -Path $Archive|Out-Null
    Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue | ForEach-Object {Move-Item $_.FullName $Archive -Force}
}
New-Item -ItemType Directory -Force -Path $StageDir|Out-Null

$Succeeded=$false
$RuntimeRecord=$null
$RunStart=Get-Date
Start-Transcript -Path $Transcript -Force|Out-Null
try{
    Write-Host "Naruto SUB37 FIX1 - dialogue speaker-name Korean probe"
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}
    $SD=Split-Path -Parent $PSCommandPath
    $P=Join-Path $SD "naruto_sub37_fix1_speaker_name_probe.py"
    & $Py.Source $P --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB37 FIX1 Python failed. ExitCode=$LASTEXITCODE"}

    $Probe=Join-Path $StageDir "Naruto_KR_SUB37_SpeakerNamesProbe.iso"
    if(-not(Test-Path $Probe)){throw "Speaker-name probe ISO missing."}

    Write-Host "Launching probe ISO with naruto.bat..."
    $Macro=Join-Path $Root "generated_macros\naruto.bat"
    $ShotRoot=Join-Path $Root "macro_screenshots"
    if(-not(Test-Path $Macro)){throw "naruto.bat missing."}
    New-Item -ItemType Directory -Force -Path $ShotRoot|Out-Null

    & cmd.exe /d /c "`"$Macro`" `"$Probe`""
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
    if(-not $RuntimeRecord){throw "New screenshot folder not found."}

    $Imgs=@(Get-ChildItem $RuntimeRecord.FullName -File |
        Where-Object {$_.Extension -match '^\.(png|jpg|jpeg)$'} | Sort-Object Name)
    if($Imgs.Count -eq 0){throw "No screenshots in runtime folder."}
    Write-Host "Runtime screenshots: $($Imgs.Count)"

    @(
      "Naruto SUB37 FIX1 Runtime",
      "ProbeISO=$Probe",
      "MacroExitCode=$MacroExit",
      "RuntimeRecord=$($RuntimeRecord.FullName)",
      "ScreenshotCount=$($Imgs.Count)",
      "CheckSpeakerNames=YES"
    )|Set-Content (Join-Path $StageDir "RUNTIME.txt") -Encoding UTF8

    $Succeeded=$true
}catch{
    Write-Host "!!!!!!!! SUB37 FIX1 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("Naruto SUB37 FIX1 FAILURE","Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String))|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
    function Copy-Diag{
      param([string]$Source,[string]$Dest)
      try{
        if(Test-Path $Source){
          $dst=Join-Path $Pkg $Dest;$parent=Split-Path $dst -Parent
          if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
          Copy-Item $Source $dst -Force
        }
      }catch{}
    }
    foreach($f in @(
      "SUMMARY.txt","RUNTIME.txt","FAILURE.txt","sub37_fix1_report.json",
      "speaker_name_pool_patch.tsv","speaker_name_xref_patch.tsv",
      "speaker_special_pointer_report.tsv","ui_static_japanese_strings.tsv",
      "ppsspp_savestate_inventory.tsv","ppsspp_texture_inventory.tsv",
      "iso_core_verification.tsv","movie_preservation.tsv","stage24_console.log"
    )){Copy-Diag (Join-Path $StageDir $f) $f}
    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))}
    $SD=Split-Path -Parent $PSCommandPath
    Copy-Diag (Join-Path $SD "naruto_sub37_fix1_speaker_name_probe.py") "scripts\naruto_sub37_fix1_speaker_name_probe.py"
    if($RuntimeRecord -and (Test-Path $RuntimeRecord.FullName)){
      $D=Join-Path $Pkg "screenshots";New-Item -ItemType Directory -Force -Path $D|Out-Null
      Get-ChildItem $RuntimeRecord.FullName -File | Where-Object {$_.Extension -match '^\.(png|jpg|jpeg)$'} |
        ForEach-Object {Copy-Item $_.FullName (Join-Path $D $_.Name) -Force}
    }
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $Zip -Force
    if($Succeeded){
      Write-Host "SUB37 FIX1 SUCCESS"
      Write-Host "Upload ZIP:";Write-Host "  $SuccessZip"
    }else{
      Write-Host "Failure ZIP:";Write-Host "  $FailZip"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
