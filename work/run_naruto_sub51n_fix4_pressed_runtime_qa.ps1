$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51n_pressed_runtime_qa_fix4"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51n_fix4_pressed_runtime_qa_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51n_fix4_pressed_runtime_qa_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51n_fix4_pressed_runtime_qa_upload.zip"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null
try {
  $SD=Split-Path -Parent $PSCommandPath
  $Py=Get-Command python.exe -ErrorAction SilentlyContinue
  if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
  if(-not $Py){throw "Python not found"}
  Write-Host "=== SUB51N FIX4 PRESSED RUNTIME QA ==="
  Write-Host "Validation only: ISO/game assets are NOT modified."
  Write-Host "FIX4: resume debugger-paused CPU, capture via pause/screenshot/resume, then gated START and DOWN-response proof; no START spam."
  & $Py.Source (Join-Path $SD "qa_sub51n_pressed_runtime_fix4.py") --root $Root
  if($LASTEXITCODE -ne 0){throw "SUB51N FIX4 pressed runtime QA failed. ExitCode=$LASTEXITCODE"}
  $Succeeded=$true
}
catch {
  New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
  @("Naruto SUB51N FIX4 PRESSED RUNTIME QA FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String)) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally {
  try{Stop-Transcript|Out-Null}catch{}
  $Pkg=Join-Path $StageDir "_upload"
  if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
  New-Item -ItemType Directory -Force -Path $Pkg | Out-Null
  foreach($n in @("SUMMARY.txt","RESULT.json","preflight.json","FAILURE.txt","ko_runtime.json","jp_runtime.json","pressed_metrics.tsv","pressed_KO_vs_JP_contact.png")){
    $s=Join-Path $StageDir $n;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
  }
  foreach($d in @("ko","jp")){$s=Join-Path $StageDir $d;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $d)-Recurse -Force}}
  if(Test-Path $Transcript){Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force}
  $SD=Split-Path -Parent $PSCommandPath
  foreach($n in @("qa_sub51n_pressed_runtime_fix4.py","run_naruto_sub51n_fix4_pressed_runtime_qa.ps1")){$s=Join-Path $SD $n;if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}}
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
  if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
  [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
  Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
  if($Succeeded){Write-Host "SUCCESS ZIP: $SuccessZip"}else{Write-Host "FAILURE ZIP: $FailZip";exit 1}
}
