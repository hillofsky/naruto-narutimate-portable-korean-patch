# Naruto PSP SUB51D FIX2 - full ChatGPT text apply + font extension
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51d_full_text_apply"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51d_fix2_full_text_apply_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51d_fix2_full_text_apply_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51d_fix2_full_text_apply_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$StageDir | Out-Null
foreach($f in @("FAILURE.txt","RUNTIME_FAILURE.txt")){
    $p=Join-Path $StageDir $f
    if(Test-Path $p){Remove-Item $p -Force -ErrorAction SilentlyContinue}
}

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $SD=Split-Path -Parent $PSCommandPath

    Write-Host "=== SUB51D FIX2 FULL TEXT APPLY ==="
    Write-Host "Translation engine: ChatGPT"
    Write-Host "BC250/local LLM: NOT USED"
    Write-Host "PPSSPP runtime QA: deferred until UI image sweep is complete"

    Write-Host "Running FIX2 builder self-test..."
    & $Py.Source (Join-Path $SD "sub51d_fix2_builder_selftest.py")
    if($LASTEXITCODE -ne 0){throw "SUB51D FIX2 builder self-test failed."}

    & $Py.Source (Join-Path $SD "build_sub51d_full_text_apply.py") `
        --root $Root `
        --inventory (Join-Path $SD "sub51d_stage35r_slot_inventory.tsv") `
        --translated (Join-Path $SD "sub51d_translation_candidates_chatgpt_translated.tsv") `
        --occurrences (Join-Path $SD "sub51d_translation_occurrences.tsv")

    if($LASTEXITCODE -ne 0){throw "SUB51D build failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch {
    Write-Host "SUB51D FIX2 FAILED"
    Write-Host $_.Exception.Message
    @(
      "Naruto SUB51D FIX2 FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}

    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($f in @(
      "SUMMARY.txt","SUB51D_static_verification.json","FAILURE.txt",
      "new_glyph_mapping_sub51d.tsv","combined_hangul_mapping_sub51d.tsv",
      "sub51d_new_glyph_preview.png","sub51d_boot_text_patch.tsv",
      "sub51d_tbl_text_patch.tsv","sub51d_primary_rebuild.tsv",
      "sub51d_fsts_rebuild.tsv","sub51d_core_verification.tsv",
      "sub51d_movie_preservation.tsv"
    )){
      $s=Join-Path $StageDir $f
      if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }

    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force

    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @(
      "build_sub51d_full_text_apply.py",
      "sub51d_fix2_builder_selftest.py",
      "run_naruto_sub51d_fix2_full_text_apply.ps1"
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
      Write-Host "SUB51D FIX2 SUCCESS"
      Write-Host "Upload ZIP:"
      Write-Host "  $SuccessZip"
    } else {
      Write-Host "Failure ZIP:"
      Write-Host "  $FailZip"
      exit 1
    }
}
