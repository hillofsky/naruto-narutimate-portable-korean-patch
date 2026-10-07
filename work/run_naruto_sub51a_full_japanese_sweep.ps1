# Naruto PSP SUB51A - full Japanese residual inventory (NO game modification)
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51a_full_japanese_sweep"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51a_full_japanese_sweep_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51a_full_japanese_sweep_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51a_full_japanese_sweep_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs|Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir|Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try{
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $SD=Split-Path -Parent $PSCommandPath
    Write-Host "=== SUB51A FULL JAPANESE SWEEP INVENTORY ==="
    Write-Host "This stage does NOT modify the ISO and does NOT launch PPSSPP."
    & $Py.Source (Join-Path $SD "scan_sub51a_full_japanese_sweep.py") --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB51A scan failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}catch{
    Write-Host "SUB51A FAILED";Write-Host $_.Exception.Message
    @("Naruto SUB51A FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String))|
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($f in @(
      "SUMMARY.txt","SUB51A_scan_summary.json","FAILURE.txt",
      "boot_japanese_strings.tsv","resource_japanese_strings.tsv",
      "primary_resource_scan.tsv","all_ccs_texture_inventory.tsv",
      "ui_contact_sheet_inventory.tsv","priority_texture_inventory.tsv"
    )){
      $s=Join-Path $StageDir $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }

    foreach($dn in @("contact_sheets","priority_textures")){
      $s=Join-Path $StageDir $dn
      if(Test-Path $s){
        $d=Join-Path $Pkg $dn
        New-Item -ItemType Directory -Force -Path $d|Out-Null
        Get-ChildItem $s -File -ErrorAction SilentlyContinue|ForEach-Object{
          Copy-Item $_.FullName (Join-Path $d $_.Name)-Force
        }
      }
    }

    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @("scan_sub51a_full_japanese_sweep.py","run_naruto_sub51a_full_japanese_sweep.ps1")){
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
      Write-Host "SUB51A SUCCESS"
      Write-Host "No ISO was modified."
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    }else{
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
      exit 1
    }
}
