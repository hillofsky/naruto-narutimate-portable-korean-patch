# Naruto PSP SUB51J - safe Mugen UI style translation
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51j_mugen_safe_style"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51j_mugen_safe_style_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51j_mugen_safe_style_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51j_mugen_safe_style_upload.zip"

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
    Write-Host "=== SUB51J MUGEN SAFE STYLE ==="
    Write-Host "Patches only exact Japanese-label boxes in TEX_white/TEX_red/TEX_mg_title."
    Write-Host "Known clean SUB36 payload hashes are required before any edit."
    Write-Host "TEX_yellow / TEX_name / TEX_prv_* are preserved."
    Write-Host "No BC250 / no local LLM / no PPSSPP runtime QA."

    & $Py.Source (Join-Path $SD "build_sub51j_mugen_safe_style.py") `
        --root $Root --assets (Join-Path $SD "assets")
    if($LASTEXITCODE -ne 0){throw "SUB51J build failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51J FAILURE",
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

    foreach($n in @("SUMMARY.txt","SUB51J_static_verification.json","FAILURE.txt",
                    "sub51j_texture_patch.tsv","sub51j_fsts_rebuild.tsv",
                    "sub51j_core_verification.tsv","sub51j_movie_preservation.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }

    $SD=Split-Path -Parent $PSCommandPath
    Copy-Item (Join-Path $SD "SUB51J_mugen_safe_style_preview.png") (Join-Path $Pkg "SUB51J_mugen_safe_style_preview.png") -Force
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    Copy-Item (Join-Path $SD "build_sub51j_mugen_safe_style.py") (Join-Path $Pkg "build_sub51j_mugen_safe_style.py") -Force
    Copy-Item $PSCommandPath (Join-Path $Pkg "run_naruto_sub51j_mugen_safe_style.ps1") -Force

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB51J SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
