# Naruto PSP SUB51L FIX1 - consolidated UI rebuild from preserved SUB51D
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51l_fix1_consolidated_ui"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51l_fix1_consolidated_ui_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51l_fix1_consolidated_ui_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51l_fix1_consolidated_ui_upload.zip"

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
    Write-Host "=== SUB51L FIX1 CONSOLIDATED UI ==="
    Write-Host "Rebuilds G/H/I/J/L UI work directly from preserved SUB51D."
    Write-Host "No dependency on SUB51G/H/I/J intermediate ISOs."
    Write-Host "Python stdout/stderr is captured into the upload ZIP."

    & $Py.Source (Join-Path $SD "launch_sub51l_fix1.py")
    $Code=$LASTEXITCODE
    $PyLog=Join-Path $SD "sub51l_fix1_python_output.log"
    if(Test-Path $PyLog){Copy-Item $PyLog (Join-Path $StageDir "sub51l_fix1_python_output.log") -Force}
    if($Code -ne 0){throw "SUB51L FIX1 build failed. ExitCode=$Code"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51L FIX1 FAILURE",
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
    foreach($n in @(
      "SUMMARY.txt","SUB51L_FIX1_static_verification.json","FAILURE.txt",
      "SUB51L_FIX1_diagnostic.txt","sub51l_fix1_python_output.log",
      "sub51l_fix1_texture_patch.tsv","sub51l_fix1_fsts_rebuild.tsv",
      "sub51l_fix1_core_verification.tsv","sub51l_fix1_movie_preservation.tsv"
    )){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=Split-Path -Parent $PSCommandPath
    foreach($n in @("build_sub51l_fix1_consolidated_ui.py","launch_sub51l_fix1.py",
                    "run_naruto_sub51l_fix1_consolidated_ui.ps1")){
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
      Write-Host "SUB51L FIX1 SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
