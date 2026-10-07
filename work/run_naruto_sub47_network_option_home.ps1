# Naruto PSP SUB47 - network / option / home cleanup
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub47_network_option_home"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub47_network_option_home_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub47_network_option_home_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub47_network_option_home_upload.zip"
New-Item -ItemType Directory -Force -Path $Logs,$StageDir|Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
 $Py=Get-Command python.exe -ErrorAction SilentlyContinue;if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
 if(-not $Py){throw "Python not found."}
 $SD=Split-Path -Parent $PSCommandPath
 Write-Host "=== SUB47 BUILD ==="
 & $Py.Source (Join-Path $SD "build_sub47_network_option_home.py") --root $Root --assets (Join-Path $SD "sub47_assets")
 if($LASTEXITCODE -ne 0){throw "SUB47 build failed. ExitCode=$LASTEXITCODE"}
 Write-Host "=== SUB47 RUNTIME QA ==="
 & $Py.Source (Join-Path $SD "capture_sub47_runtime.py")
 if($LASTEXITCODE -ne 0){throw "SUB47 runtime capture failed. ExitCode=$LASTEXITCODE"}
 $Succeeded=$true
}catch{
 Write-Host "SUB47 FAILED";Write-Host $_.Exception.Message
 @("Naruto SUB47 FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String))|
  Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
 try{Stop-Transcript|Out-Null}catch{}
 $Pkg=Join-Path $StageDir "_upload";if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
 New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
 foreach($f in @("SUMMARY.txt","SUB47_static_verification.json","runtime_qa_report.json","RUNTIME_FAILURE.txt","FAILURE.txt",
 "sub47_text_patch.tsv","sub47_texture_patch.tsv","sub47_fsts_changes.tsv","sub47_discovery_inventory.tsv",
 "sub47_core_verification.tsv","sub47_movie_preservation.tsv","TEX_network_ko.png","TEX_option01_clean_ko.png")){
  $s=Join-Path $StageDir $f;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
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
 foreach($f in @("build_sub47_network_option_home.py","capture_sub47_runtime.py","run_naruto_sub47_network_option_home.ps1")){
  $s=Join-Path $SD $f;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
 }
 $Zip=if($Succeeded){$SuccessZip}else{$FailZip};if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
 Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
 if($Succeeded){Write-Host "SUB47 SUCCESS";Write-Host "Upload ZIP:";Write-Host "  $SuccessZip"}
 else{Write-Host "Failure ZIP:";Write-Host "  $FailZip";exit 1}
}
