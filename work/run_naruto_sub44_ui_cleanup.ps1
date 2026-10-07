# Naruto PSP SUB44 FIX1 - UI text cleanup + runtime QA
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub44_ui_cleanup"
$Logs=Join-Path $Root "logs"
$Old=Join-Path $Logs "old"
$Failed=Join-Path $Logs "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub44_fix1_ui_cleanup_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub44_fix1_ui_cleanup_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub44_fix1_ui_cleanup_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$Old,$Failed|Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try {
  $Py=Get-Command python.exe -ErrorAction SilentlyContinue
  if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
  if(-not $Py){throw "Python not found."}
  $SD=Split-Path -Parent $PSCommandPath
  $Build=Join-Path $SD "build_sub44_ui_cleanup.py"
  $Capture=Join-Path $SD "capture_sub44_runtime.py"
  $Assets=Join-Path $SD "sub44_assets"
  if(-not(Test-Path $Build)){throw "SUB44 builder missing"}
  if(-not(Test-Path $Capture)){throw "SUB44 capture script missing"}
  if(-not(Test-Path $Assets)){throw "SUB44 assets missing"}

  Write-Host "=== SUB44 FIX1 BUILD ==="
  & $Py.Source $Build --root $Root --assets $Assets
  if($LASTEXITCODE -ne 0){throw "SUB44 build failed. ExitCode=$LASTEXITCODE"}

  Write-Host ""
  Write-Host "=== SUB44 RUNTIME QA ==="
  & $Py.Source $Capture
  if($LASTEXITCODE -ne 0){throw "SUB44 runtime QA failed. ExitCode=$LASTEXITCODE"}
  $Succeeded=$true
}
catch {
  Write-Host "!!!!!!!! SUB44 FAILED !!!!!!!!"
  Write-Host $_.Exception.Message
  New-Item -ItemType Directory -Force -Path $StageDir|Out-Null
  @("Naruto SUB44 FAILURE","Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String))|
    Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally {
  try { Stop-Transcript|Out-Null } catch {}
  New-Item -ItemType Directory -Force -Path $StageDir|Out-Null
  $Pkg=Join-Path $StageDir "_upload"
  if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
  New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

  function Copy-Diag { param([string]$Source,[string]$Dest)
    try {
      if(Test-Path $Source){
        $D=Join-Path $Pkg $Dest
        $Par=Split-Path $D -Parent
        if($Par){New-Item -ItemType Directory -Force -Path $Par|Out-Null}
        Copy-Item $Source $D -Force
      }
    } catch {}
  }

  foreach($f in @(
    "SUMMARY.txt","SUB44_static_verification.json","sub44_ui_text_patch.tsv",
    "sub44_remaining_ui_japanese.tsv","sub44_texture_patch.tsv",
    "sub44_iso_core_verification.tsv","sub44_movie_preservation.tsv",
    "runtime_qa_report.json","FAILURE.txt","RUNTIME_FAILURE.txt"
  )){Copy-Diag (Join-Path $StageDir $f) $f}

  $Shots=Join-Path $StageDir "runtime_screenshots"
  if(Test-Path $Shots){
    Get-ChildItem $Shots -File -Filter "*.png"|ForEach-Object{
      Copy-Diag $_.FullName ("screenshots\"+$_.Name)
    }
  }
  Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf))
  $SD=Split-Path -Parent $PSCommandPath
  Copy-Diag (Join-Path $SD "build_sub44_ui_cleanup.py") "scripts\build_sub44_ui_cleanup.py"
  Copy-Diag (Join-Path $SD "capture_sub44_runtime.py") "scripts\capture_sub44_runtime.py"

  $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
  if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
  Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

  if($Succeeded){
    Write-Host "SUB44 SUCCESS"
    Write-Host "Upload ZIP:"
    Write-Host "  $SuccessZip"
  } else {
    Write-Host "Failure ZIP:"
    Write-Host "  $FailZip"
    exit 1
  }
}
