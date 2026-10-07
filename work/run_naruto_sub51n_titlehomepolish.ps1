# Naruto PSP SUB51N - TitleHomePolish (title high-contrast + nunber ge)
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51n_titlehomepolish\build"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51n_titlehomepolish_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51n_titlehomepolish_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51n_titlehomepolish_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$Succeeded=$false

Start-Transcript -Path $Transcript -Force | Out-Null
try{
    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python not found"}

    $SD=$Root
    Write-Host "=== SUB51N TITLEHOME POLISH ==="
    Write-Host "Title TEX_panel/panel2/panel3 high-contrast + cmnselect TEX_nunber ge."
    Write-Host "Rebuilt from preserved SUB51D + all SUB51L FIX2 assets."

    & $Py.Source (Join-Path $SD "launch_sub51n.py")
    $Code=$LASTEXITCODE
    $PyLog=Join-Path $SD "sub51n_python_output.log"
    if(Test-Path $PyLog){Copy-Item $PyLog (Join-Path $StageDir "sub51n_python_output.log") -Force}
    if($Code -ne 0){throw "SUB51N build failed. ExitCode=$Code"}
    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51N FAILURE",
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
      "SUMMARY.txt","SUB51N_static_verification.json","FAILURE.txt",
      "SUB51N_diagnostic.txt","sub51n_python_output.log","sub51n_preflight.tsv",
      "sub51n_texture_patch.tsv","sub51n_fsts_rebuild.tsv",
      "sub51n_core_verification.tsv","sub51n_movie_preservation.tsv"
    )){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    $SD=$Root
    foreach($n in @("build_sub51n_titlehomepolish.py","launch_sub51n.py",
                    "run_naruto_sub51n_titlehomepolish.ps1")){
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
      Write-Host "SUB51N SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
