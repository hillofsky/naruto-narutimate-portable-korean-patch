$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$Logs=Join-Path $Root "logs"
$Out=Join-Path $Root "analysis\sub\sub52f_final_static_residual_sweep"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub52f_final_static_residual_sweep_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub52f_final_static_residual_sweep_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub52f_final_static_residual_sweep_upload.zip"
$Succeeded=$false

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== SUB52F FINAL STATIC RESIDUAL SWEEP ==="
    Write-Host "No PPSSPP / no gameplay / no ISO modification."

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){$Python=$py.Source;$PyArgs=@("-3")}
    else{
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw "Python not found"}
        $Python=$py.Source;$PyArgs=@()
    }

    # Pillow is allowed by user; install only when missing.
    & $Python @PyArgs -c "import PIL" 2>$null
    if($LASTEXITCODE -ne 0){
        Write-Host "Pillow not found; installing..."
        & $Python @PyArgs -m pip install --user Pillow
        if($LASTEXITCODE -ne 0){throw "Pillow installation failed"}
    }

    & $Python @PyArgs ".\qa_sub52f_final_static_residual_sweep.py" --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB52F residual sweep failed: $LASTEXITCODE"}
    $Succeeded=$true
}
catch {
    @(
      "Naruto SUB52F FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $Out "FAILURE.txt") -Encoding UTF8
}
finally {
    try{Stop-Transcript | Out-Null}catch{}
    if(-not $Succeeded){
        $Pack=Join-Path $Out "_fail_upload"
        if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force}
        New-Item -ItemType Directory -Force -Path $Pack | Out-Null
        Get-ChildItem $Out -File | ForEach-Object {Copy-Item $_.FullName $Pack -Force}
        Copy-Item $Transcript $Pack -Force
        Copy-Item (Join-Path $Root "qa_sub52f_final_static_residual_sweep.py") $Pack -Force
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if(Test-Path $FailZip){Remove-Item $FailZip -Force}
        [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$FailZip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
        Remove-Item $Pack -Recurse -Force
        Write-Host "Upload ZIP: $FailZip"
        exit 1
    } else {
        Write-Host "Upload ZIP: $SuccessZip"
    }
}
