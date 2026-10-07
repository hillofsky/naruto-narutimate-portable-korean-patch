# Naruto PSP SUB46 - UI cleanup + network resource discovery
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub46_ui_cleanup_discovery"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub46_ui_cleanup_discovery_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub46_ui_cleanup_discovery_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub46_ui_cleanup_discovery_upload.zip"
New-Item -ItemType Directory -Force -Path $Logs,$StageDir|Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try {
 $Py=Get-Command python.exe -ErrorAction SilentlyContinue;if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
 if(-not $Py){throw "Python not found."}
 $SD=Split-Path -Parent $PSCommandPath
 Write-Host "=== SUB46 BUILD ==="
 & $Py.Source (Join-Path $SD "build_sub46_ui_cleanup_discovery.py") --root $Root
 if($LASTEXITCODE -ne 0){throw "SUB46 build failed. ExitCode=$LASTEXITCODE"}
 Write-Host "=== SUB46 RUNTIME QA ==="
 & $Py.Source (Join-Path $SD "capture_sub46_runtime.py")
 if($LASTEXITCODE -ne 0){throw "SUB46 runtime capture failed. ExitCode=$LASTEXITCODE"}
 $Succeeded=$true
}
catch {
 Write-Host "SUB46 FAILED";Write-Host $_.Exception.Message
 @("Naruto SUB46 FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String))|
  Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally {
 try{Stop-Transcript|Out-Null}catch{}
 $Pkg=Join-Path $StageDir "_upload";if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
 New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
 foreach($f in @(
   "SUMMARY.txt","SUB46_static_verification.json","runtime_qa_report.json","RUNTIME_FAILURE.txt","FAILURE.txt",
   "sub46_text_patch.tsv","sub46_network_discovery.tsv","sub46_texture_inventory.tsv",
   "sub46_fsts_changes.tsv","sub46_core_verification.tsv","sub46_changed_resource_verification.tsv",
   "sub46_movie_preservation.tsv"
  )){
   $s=Join-Path $StageDir $f
   if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
 }
 foreach($dn in @("runtime_screenshots","discovery_textures")){
   $s=Join-Path $StageDir $dn
   if(Test-Path $s){
    $d=Join-Path $Pkg $dn;New-Item -ItemType Directory -Force -Path $d|Out-Null
    Get-ChildItem $s -File -ErrorAction SilentlyContinue|ForEach-Object{Copy-Item $_.FullName (Join-Path $d $_.Name)-Force}
   }
 }
 Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
 $SD=Split-Path -Parent $PSCommandPath
 foreach($f in @("build_sub46_ui_cleanup_discovery.py","capture_sub46_runtime.py","run_naruto_sub46_ui_cleanup_discovery.ps1")){
   $s=Join-Path $SD $f;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
 }
 $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
 if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
 Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
 if($Succeeded){Write-Host "SUB46 SUCCESS";Write-Host "Upload ZIP:";Write-Host "  $SuccessZip"}
 else{Write-Host "Failure ZIP:";Write-Host "  $FailZip";exit 1}
}
