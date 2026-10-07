# Naruto PSP SUB45 menu follow-up + runtime QA
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$Stage=Join-Path $Root "analysis\sub\sub45_menu_followup"
$Logs=Join-Path $Root "logs"
$Old=Join-Path $Logs "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub45_fix1_menu_followup_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub45_fix1_menu_followup_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub45_fix1_menu_followup_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$Old|Out-Null
if(Test-Path $Stage){
  $A=Join-Path (Join-Path $Old $Stamp) "sub45_menu_followup"
  New-Item -ItemType Directory -Force -Path $A|Out-Null
  Get-ChildItem $Stage -Force -ErrorAction SilentlyContinue|ForEach-Object{Move-Item $_.FullName $A -Force}
}
New-Item -ItemType Directory -Force -Path $Stage|Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
  $Py=Get-Command python.exe -ErrorAction SilentlyContinue
  if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
  if(-not $Py){throw "Python not found."}
  $SD=Split-Path -Parent $PSCommandPath
  Write-Host "=== SUB45 FIX1 BUILD ==="
  & $Py.Source (Join-Path $SD "build_sub45_menu_followup.py") --root $Root --assets (Join-Path $SD "sub45_assets")
  if($LASTEXITCODE -ne 0){throw "SUB45 build failed. ExitCode=$LASTEXITCODE"}

  Write-Host "=== SUB45 RUNTIME QA ==="
  & $Py.Source (Join-Path $SD "capture_sub45_runtime.py")
  if($LASTEXITCODE -ne 0){throw "SUB45 runtime capture failed. ExitCode=$LASTEXITCODE"}
  $Succeeded=$true
}catch{
  Write-Host "SUB45 FAILED"
  Write-Host $_.Exception.Message
  @("Naruto SUB45 FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String)) |
    Set-Content (Join-Path $Stage "FAILURE.txt") -Encoding UTF8
}finally{
  try{Stop-Transcript|Out-Null}catch{}
  $Pkg=Join-Path $Stage "_upload"
  if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
  New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
  $Names=@(
    "SUMMARY.txt","SUB45_static_verification.json","runtime_qa_report.json",
    "sub45_texture_patch.tsv","sub45_table_text_patch.tsv","sub45_table_discovery.tsv",
    "sub45_fsts_changes.tsv","sub45_core_verification.tsv",
    "sub45_changed_resource_verification.tsv","sub45_movie_preservation.tsv"
  )
  foreach($n in $Names){
    $p=Join-Path $Stage $n
    if(Test-Path $p){Copy-Item $p (Join-Path $Pkg $n) -Force}
  }
  if(-not $Succeeded){
    foreach($n in @("FAILURE.txt","RUNTIME_FAILURE.txt")){
      $p=Join-Path $Stage $n
      if(Test-Path $p){Copy-Item $p (Join-Path $Pkg $n) -Force}
    }
  }
  $Shots=Join-Path $Stage "runtime_screenshots"
  if(Test-Path $Shots){
    $D=Join-Path $Pkg "screenshots";New-Item -ItemType Directory -Force -Path $D|Out-Null
    Get-ChildItem $Shots -File -Filter "*.png"|ForEach-Object{Copy-Item $_.FullName (Join-Path $D $_.Name)-Force}
  }
  Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf)) -Force
  $SD=Split-Path -Parent $PSCommandPath
  foreach($n in @("build_sub45_menu_followup.py","capture_sub45_runtime.py")){
    Copy-Item (Join-Path $SD $n) (Join-Path $Pkg $n) -Force
  }

  $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
  if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
  Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
  if($Succeeded){
    Write-Host "";Write-Host "SUB45 SUCCESS";Write-Host "Upload ZIP:";Write-Host "  $SuccessZip"
  }else{
    Write-Host "Failure ZIP:";Write-Host "  $FailZip";exit 1
  }
}
