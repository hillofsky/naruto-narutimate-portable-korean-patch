# Naruto PSP SUB51C ChatGPT translation - exact local validation only
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51c_chatgpt_translation_validation"
$Logs=Join-Path $Root "logs"
$SuccessZip=Join-Path $Logs "naruto_sub51c_chatgpt_translation_validation_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51c_chatgpt_translation_validation_upload.zip"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51c_chatgpt_translation_validation_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}
    $SD=Split-Path -Parent $PSCommandPath
    Write-Host "=== SUB51C ChatGPT translation exact validation ==="
    Write-Host "No BC250/local LLM. No ISO modification. No PPSSPP."
    & $Py.Source (Join-Path $SD "validate_sub51c_chatgpt_translation.py") `
       --root $Root `
       --translation (Join-Path $SD "translation_candidates_chatgpt_translated.tsv") `
       --out $StageDir
    if($LASTEXITCODE -ne 0){throw "Validator crashed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch {
    @("Naruto SUB51C validation FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($f in @("SUMMARY.txt","validation_report.json","validation_issues.tsv","FAILURE.txt")){
        $s=Join-Path $StageDir $f
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }
    $SD=Split-Path -Parent $PSCommandPath
    foreach($f in @(
      "translation_candidates_chatgpt_translated.tsv",
      "translation_occurrences.tsv",
      "translation_skips.tsv",
      "SUB51C_CHATGPT_TRANSLATION_REPORT.json",
      "validate_sub51c_chatgpt_translation.py",
      "run_naruto_sub51c_chatgpt_translation_validation.ps1"
    )){
        $s=Join-Path $SD $f
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f)-Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force

    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force
    if($Succeeded){
       Write-Host "Upload ZIP:"
       Write-Host "  $SuccessZip"
    } else {
       Write-Host "Failure ZIP:"
       Write-Host "  $FailZip"
       exit 1
    }
}
