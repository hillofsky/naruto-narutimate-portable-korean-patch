# Naruto PSP SUB51G - style-preserving Korean mode-select rebuild
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51g_modesel1_style_rebuild"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51g_modesel1_style_rebuild_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51g_modesel1_style_rebuild_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51g_modesel1_style_rebuild_upload.zip"
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
    Write-Host "=== SUB51G MODE-SELECT STYLE REBUILD ==="
    Write-Host "Uses pre-rendered Korean UI PNGs; no font install required."
    Write-Host "No BC250 / no local LLM / no PPSSPP runtime QA."

    & $Py.Source (Join-Path $SD "build_sub51g_modesel1_style_rebuild.py") `
        --root $Root `
        --assets (Join-Path $SD "assets")
    if($LASTEXITCODE -ne 0){throw "SUB51G build failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51G FAILURE",
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

    foreach($n in @("SUMMARY.txt","SUB51G_static_verification.json","FAILURE.txt",
                    "sub51g_texture_patch.tsv","sub51g_fsts_rebuild.tsv",
                    "sub51g_core_verification.tsv","sub51g_movie_preservation.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    Copy-Item (Join-Path $SD "SUB51G_modesel1_style_preview.png") (Join-Path $Pkg "SUB51G_modesel1_style_preview.png") -Force
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    Copy-Item (Join-Path $SD "build_sub51g_modesel1_style_rebuild.py") (Join-Path $Pkg "build_sub51g_modesel1_style_rebuild.py") -Force
    Copy-Item $PSCommandPath (Join-Path $Pkg "run_naruto_sub51g_modesel1_style_rebuild.ps1") -Force

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB51G SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
