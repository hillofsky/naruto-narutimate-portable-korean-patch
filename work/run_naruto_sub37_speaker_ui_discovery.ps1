# Naruto PSP SUB37 - Speaker name / UI discovery
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub37_speaker_ui_discovery"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub37_speaker_ui_discovery_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub37_speaker_ui_discovery_upload.zip"
$FailZip=Join-Path $LogsDir "fail_naruto_sub37_speaker_ui_discovery_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot|Out-Null
if(Test-Path $StageDir){
    $items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
        foreach($x in $items){Move-Item $x.FullName $ArchiveDir -Force}
    }
}
New-Item -ItemType Directory -Force -Path $StageDir|Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
    Write-Host "Naruto SUB37 - Speaker name / UI discovery"
    Write-Host "SUB36 ISO is read-only. No game files are modified."

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $SD=Split-Path -Parent $PSCommandPath
    $P=Join-Path $SD "naruto_sub37_speaker_ui_discovery.py"
    if(-not(Test-Path $P)){throw "SUB37 Python script missing."}

    & $Py.Source $P --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB37 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host "!!!!!!!! SUB37 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
      "Naruto SUB37 FAILURE",
      "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
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
      "SUMMARY.txt","sub37_report.json","speaker_name_occurrences.tsv",
      "speaker_code_occurrences.tsv","speaker_name_clusters.tsv",
      "speaker_name_filesystem_hits.tsv","ppsspp_savestate_inventory.tsv",
      "ppsspp_environment.tsv","ppsspp_texture_inventory.tsv","FAILURE.txt"
    )){Copy-Diag (Join-Path $StageDir $f) $f}

    $SliceDir=Join-Path $StageDir "speaker_candidate_slices"
    if(Test-Path $SliceDir){
        Get-ChildItem $SliceDir -File -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Diag $_.FullName ("speaker_candidate_slices\"+$_.Name)
        }
    }

    Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
    if($PSCommandPath){Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))}
    $SD=Split-Path -Parent $PSCommandPath
    Copy-Diag (Join-Path $SD "naruto_sub37_speaker_ui_discovery.py") "scripts\naruto_sub37_speaker_ui_discovery.py"

    if($Succeeded){
      if(Test-Path $SuccessZip){
        New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
        Copy-Item $SuccessZip (Join-Path $ArchiveDir (Split-Path $SuccessZip -Leaf)) -Force
      }
      if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue}
      Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $SuccessZip -Force
      Write-Host "SUB37 SUCCESS"
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    }else{
      if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue}
      Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
      $fd=Join-Path $FailedRoot $Stamp
      New-Item -ItemType Directory -Force -Path $fd|Out-Null
      Copy-Item $FailZip (Join-Path $fd (Split-Path $FailZip -Leaf)) -Force
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
