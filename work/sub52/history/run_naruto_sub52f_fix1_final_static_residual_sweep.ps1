$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$Logs=Join-Path $Root "logs"
$Out=Join-Path $Root "analysis\sub\sub52f_final_static_residual_sweep"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub52f_fix1_final_static_residual_sweep_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub52f_fix1_final_static_residual_sweep_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub52f_fix1_final_static_residual_sweep_upload.zip"
$Succeeded=$false

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Host "=== SUB52F FIX1 FINAL STATIC RESIDUAL SWEEP ==="
    Write-Host "No PPSSPP / no gameplay / no ISO modification."

    $pycmd=Get-Command py.exe -ErrorAction SilentlyContinue
    if($pycmd){
        $Python=$pycmd.Source
        $PyArgs=@("-3")
    } else {
        $pycmd=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $pycmd){throw "Python not found"}
        $Python=$pycmd.Source
        $PyArgs=@()
    }

    # PowerShell 5.1 turns native stderr into ErrorRecord objects. With
    # ErrorActionPreference=Stop, a simple failed `import PIL` probe terminates
    # before the install branch can run. Avoid that by invoking the probe and
    # installer with non-terminating native-error handling and checking only
    # the process exit code.
    Write-Host "[dependency] Checking Pillow..."
    $OldEAP=$ErrorActionPreference
    $ErrorActionPreference="Continue"
    try {
        & $Python @PyArgs -c "import PIL; print(PIL.__version__)" 2>$null
        $PillowProbeExit=$LASTEXITCODE
    } finally {
        $ErrorActionPreference=$OldEAP
    }

    if($PillowProbeExit -ne 0){
        Write-Host "[dependency] Pillow not found. Installing with pip..."
        $OldEAP=$ErrorActionPreference
        $ErrorActionPreference="Continue"
        try {
            & $Python @PyArgs -m pip install --user --disable-pip-version-check Pillow
            $PipExit=$LASTEXITCODE
        } finally {
            $ErrorActionPreference=$OldEAP
        }
        if($PipExit -ne 0){throw "Pillow installation failed: exit=$PipExit"}

        # Verify after installation, again without letting PS 5.1 native stderr
        # become a terminating PowerShell error.
        $OldEAP=$ErrorActionPreference
        $ErrorActionPreference="Continue"
        try {
            & $Python @PyArgs -c "from PIL import Image,ImageDraw,ImageFont; print('Pillow import PASS')"
            $PillowVerifyExit=$LASTEXITCODE
        } finally {
            $ErrorActionPreference=$OldEAP
        }
        if($PillowVerifyExit -ne 0){throw "Pillow was installed but import verification failed"}
    } else {
        Write-Host "[dependency] Pillow already available."
    }

    Write-Host "[scan] Starting static residual sweep..."
    & $Python @PyArgs ".\qa_sub52f_fix1_final_static_residual_sweep.py" --root $Root
    if($LASTEXITCODE -ne 0){throw "SUB52F FIX1 residual sweep failed: $LASTEXITCODE"}

    if(-not (Test-Path $SuccessZip)){
        throw "Scanner finished but success ZIP was not created: $SuccessZip"
    }
    $Succeeded=$true
}
catch {
    @(
      "Naruto SUB52F FIX1 FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $Out "FAILURE.txt") -Encoding UTF8
}
finally {
    try{Stop-Transcript | Out-Null}catch{}

    # The Python scanner uses the old success filename internally.
    $OldSuccessZip=Join-Path $Logs "naruto_sub52f_final_static_residual_sweep_upload.zip"
    if($Succeeded -and (Test-Path $OldSuccessZip)){
        Copy-Item -LiteralPath $OldSuccessZip -Destination $SuccessZip -Force
    }

    if(-not $Succeeded){
        $Pack=Join-Path $Out "_fail_upload_fix1"
        if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
        New-Item -ItemType Directory -Force -Path $Pack | Out-Null

        Get-ChildItem $Out -File -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName $Pack -Force
        }
        if(Test-Path $Transcript){Copy-Item $Transcript $Pack -Force}
        foreach($n in @(
            "qa_sub52f_fix1_final_static_residual_sweep.py",
            "run_naruto_sub52f_fix1_final_static_residual_sweep.ps1"
        )){
            $p=Join-Path $Root $n
            if(Test-Path $p){Copy-Item $p $Pack -Force}
        }

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if(Test-Path $FailZip){Remove-Item $FailZip -Force}
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $Pack,$FailZip,[System.IO.Compression.CompressionLevel]::Optimal,$false
        )
        Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Upload ZIP: $FailZip"
        exit 1
    } else {
        Write-Host "Upload ZIP: $SuccessZip"
    }
}
