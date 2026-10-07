# Naruto PSP SUB51B - exact source collection, no game modification
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51b_exact_source_collection"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51b_exact_source_collection_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51b_exact_source_collection_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51b_exact_source_collection_upload.zip"

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
    Write-Host "=== SUB51B EXACT SOURCE COLLECTION ==="
    Write-Host "No ISO modification. No PPSSPP launch."
    & $Py.Source (Join-Path $SD "collect_sub51b_exact_sources.py") --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB51B collection failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}catch{
    Write-Host "SUB51B FAILED";Write-Host $_.Exception.Message
    @("Naruto SUB51B FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String))|
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($f in @(
      "SUMMARY.txt","SUB51B_collection_summary.json","FAILURE.txt",
      "boot_filtered_strings.tsv","text_resource_inventory.tsv",
      "ui_ccs_inventory.tsv","ui_texture_inventory.tsv",
      "primary_index.tsv","fsts_index.tsv",
      "source_sub50_BOOT.bin","source_sub50_naruto.dat","source_sub50_naruto.idx"
    )){
      $s=Join-Path $StageDir $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }

    foreach($dn in @("mappings","text_resources","ui_ccs")){
      $s=Join-Path $StageDir $dn
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $dn)-Recurse -Force}
    }

    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @("collect_sub51b_exact_sources.py","run_naruto_sub51b_exact_source_collection.ps1")){
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
      Write-Host "SUB51B SUCCESS"
      Write-Host "No ISO was modified."
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    }else{
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
      exit 1
    }
}
