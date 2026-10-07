# Naruto PSP SUB51E FIX3 - pristine source recovery without recursion loop
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51e_fix3_pristine_source_recovery"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51e_fix3_pristine_source_recovery_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51e_fix3_pristine_source_recovery_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51e_fix3_pristine_source_recovery_upload.zip"

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
    Write-Host "=== SUB51E FIX3 PRISTINE SOURCE RECOVERY ==="
    Write-Host "Reuses the 9 pristine CCS files that FIX2 extracted successfully."
    Write-Host "Historical script scan excludes SUB51E/self-generated trees."

    & $Py.Source (Join-Path $SD "recover_sub51e_fix3_pristine_sources.py") `
        --root $Root `
        --bundle $SD `
        --out $StageDir

    if($LASTEXITCODE -ne 0){throw "SUB51E FIX3 failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51E FIX3 FAILURE",
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
                    "pristine_resource_inventory.tsv","historical_script_inventory.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    foreach($d in @("pristine_sub36_ccs","historical_scripts")){
        $s=Join-Path $StageDir $d
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $d)-Recurse -Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force

    $SD=Split-Path -Parent $PSCommandPath
    foreach($n in @("recover_sub51e_fix3_pristine_sources.py",
                    "run_naruto_sub51e_fix3_pristine_source_recovery.ps1")){
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
      Write-Host "SUB51E FIX3 SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
