# Naruto PSP SUB49 - safe rollback of shared atlases
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub49_safe_atlas_rollback"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub49_safe_atlas_rollback_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub49_safe_atlas_rollback_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub49_safe_atlas_rollback_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$StageDir|Out-Null
foreach($f in @("FAILURE.txt","RUNTIME_FAILURE.txt","runtime_qa_report.json")){
    $p=Join-Path $StageDir $f
    if(Test-Path $p){Remove-Item $p -Force -ErrorAction SilentlyContinue}
}

$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}
    $SD=Split-Path -Parent $PSCommandPath

    Write-Host "=== SUB49 SAFE ROLLBACK BUILD ==="
    & $Py.Source (Join-Path $SD "build_sub49_safe_atlas_rollback.py") --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB49 build failed. ExitCode=$LASTEXITCODE"}

    Write-Host "=== SUB49 RUNTIME QA ==="
    & $Py.Source (Join-Path $SD "capture_sub49_runtime.py")
    if($LASTEXITCODE -ne 0){throw "SUB49 runtime capture failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host "SUB49 FAILED";Write-Host $_.Exception.Message
    @("Naruto SUB49 FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String))|
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($f in @(
      "SUMMARY.txt","SUB49_static_verification.json","runtime_qa_report.json",
      "RUNTIME_FAILURE.txt","FAILURE.txt","sub49_rollback_resources.tsv",
      "sub49_rollback_verification.tsv","sub49_fsts_restore.tsv",
      "sub49_core_verification.tsv","sub49_movie_preservation.tsv"
    )){
      $s=Join-Path $StageDir $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }

    $s=Join-Path $StageDir "runtime_screenshots"
    if(Test-Path $s){
      $d=Join-Path $Pkg "runtime_screenshots"
      New-Item -ItemType Directory -Force -Path $d|Out-Null
      Get-ChildItem $s -File -ErrorAction SilentlyContinue|ForEach-Object{
        Copy-Item $_.FullName (Join-Path $d $_.Name)-Force
      }
    }

    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @(
      "build_sub49_safe_atlas_rollback.py",
      "capture_sub49_runtime.py",
      "run_naruto_sub49_safe_atlas_rollback.ps1"
    )){
      $s=Join-Path $SD $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }

    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB49 SUCCESS"
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    }else{
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
      exit 1
    }
}
