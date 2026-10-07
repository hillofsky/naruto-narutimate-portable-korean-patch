# Naruto PSP SUB51K - residual Japanese UI sweep
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51k_residual_ui_sweep"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51k_residual_ui_sweep_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51k_residual_ui_sweep_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51k_residual_ui_sweep_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$Succeeded=$false

Start-Transcript -Path $Transcript -Force | Out-Null
try{
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found"}

    $SD=Split-Path -Parent $PSCommandPath
    Write-Host "=== SUB51K RESIDUAL UI SWEEP ==="
    Write-Host "Analysis only. No ISO modification, no PPSSPP, no local LLM."

    & $Py.Source (Join-Path $SD "build_sub51k_residual_ui_sweep.py") --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB51K failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51K FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally{
    try{Stop-Transcript | Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($n in @("SUMMARY.txt","SUMMARY.json","FAILURE.txt",
                    "sub51k_ui_resources.tsv","sub51k_ui_textures.tsv",
                    "SUB51K_master_contact.png")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    $sheets=Join-Path $StageDir "contact_sheets"
    if(Test-Path $sheets){Copy-Item $sheets (Join-Path $Pkg "contact_sheets") -Recurse -Force}

    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    Copy-Item (Join-Path $SD "build_sub51k_residual_ui_sweep.py") (Join-Path $Pkg "build_sub51k_residual_ui_sweep.py") -Force
    Copy-Item $PSCommandPath (Join-Path $Pkg "run_naruto_sub51k_residual_ui_sweep.ps1") -Force

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB51K SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
