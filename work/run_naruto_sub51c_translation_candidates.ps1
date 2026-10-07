# Naruto PSP SUB51C - generate all residual text translation candidates
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51c_translation_candidates"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51c_translation_candidates_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51c_translation_candidates_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51c_translation_candidates_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$StageDir|Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}
    $SD=Split-Path -Parent $PSCommandPath

    Write-Host "=== SUB51C FULL TEXT TRANSLATION CANDIDATES ==="
    Write-Host "No ISO modification. No PPSSPP launch."
    Write-Host "Auto-detecting llama.cpp OpenAI-compatible servers on 8080/8081..."
    & $Py.Source (Join-Path $SD "generate_sub51c_translation_candidates.py") --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB51C translation generation failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}catch{
    Write-Host "SUB51C FAILED";Write-Host $_.Exception.Message
    @("Naruto SUB51C FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
    foreach($f in @(
      "SUMMARY.txt","SUB51C_summary.json","FAILURE.txt",
      "translation_candidates.tsv","translation_occurrences.tsv",
      "translation_cache.jsonl"
    )){
      $s=Join-Path $StageDir $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @("generate_sub51c_translation_candidates.py","run_naruto_sub51c_translation_candidates.ps1")){
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
      Write-Host "SUB51C SUCCESS"
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    }else{
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
      exit 1
    }
}
