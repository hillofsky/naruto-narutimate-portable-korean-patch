# Naruto PSP SUB51F - Official Korean UI donor discovery
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51f_official_kr_ui_donor"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51f_official_kr_ui_donor_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51f_official_kr_ui_donor_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51f_official_kr_ui_donor_upload.zip"

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
    Write-Host "=== SUB51F OFFICIAL KOREAN UI DONOR DISCOVERY ==="
    Write-Host "Uses the official Korean ISO as the first-choice visual donor."
    Write-Host "No ISO modification / no PPSSPP / no local LLM."

    & $Py.Source (Join-Path $SD "discover_sub51f_official_kr_ui_donor.py") `
        --root $Root `
        --jp-bundle $SD `
        --out $StageDir

    if($LASTEXITCODE -ne 0){throw "SUB51F failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51F FAILURE",
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
                    "official_kr_ui_texture_comparison.tsv",
                    "modesel1_official_JP_vs_KR.png")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    foreach($d in @("jp_png","official_kr_png","pairs")){
        $s=Join-Path $StageDir $d
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $d)-Recurse -Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($n in @("discover_sub51f_official_kr_ui_donor.py",
                    "run_naruto_sub51f_official_kr_ui_donor.ps1")){
        $s=Join-Path $SD $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB51F SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
