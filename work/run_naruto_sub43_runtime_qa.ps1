# Naruto PSP SUB43 runtime menu QA capture
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub43_runtime_qa"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub43_runtime_qa_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub43_runtime_qa_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub43_runtime_qa_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$StageDir|Out-Null
$Succeeded=$false
Start-Transcript -Path $Transcript -Force|Out-Null
try {
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found."}

    $SD=Split-Path -Parent $PSCommandPath
    $Script=Join-Path $SD "naruto_sub43_runtime_qa.py"
    if(-not(Test-Path $Script)){throw "Runtime QA Python script missing."}

    & $Py.Source $Script
    if($LASTEXITCODE -ne 0){throw "SUB43 runtime QA failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch {
    Write-Host "SUB43 runtime QA FAILED"
    Write-Host $_.Exception.Message
}
finally {
    try { Stop-Transcript|Out-Null } catch {}

    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($f in @("SUMMARY.txt","runtime_qa_report.json","FAILURE.txt")){
        $s=Join-Path $StageDir $f
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $f) -Force}
    }
    $Shots=Join-Path $StageDir "screenshots"
    if(Test-Path $Shots){
        $D=Join-Path $Pkg "screenshots"
        New-Item -ItemType Directory -Force -Path $D|Out-Null
        Get-ChildItem $Shots -File -Filter "*.png"|ForEach-Object{
            Copy-Item $_.FullName (Join-Path $D $_.Name) -Force
        }
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf)) -Force

    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}

    # Use .NET ZipFile instead of Expand/Compress-Archive to avoid PS5.1 path issues.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
        Write-Host ""
        Write-Host "SUB43 RUNTIME QA CAPTURE SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"
    } else {
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
        exit 1
    }
}
