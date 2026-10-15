$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$Logs=Join-Path $Root "logs"
$Out=Join-Path $Root "analysis\sub\sub52g_fix1_final_residual_apply"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub52g_fix1_final_residual_apply_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub52g_fix1_final_residual_apply_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub52g_fix1_final_residual_apply_upload.zip"
$Succeeded=$false
$RootIso=Join-Path $Root "Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso"

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== SUB52G FIX1 FINAL RESIDUAL APPLY ==="
    Write-Host "Source: SUB52E"
    Write-Host "Applies 2 confirmed text residuals + 8 residual textures."

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 ".\build_sub52g_fix1_final_residual_apply.py" `
          --root $Root `
          --assets ".\sub52g_assets" `
          --mapping ".\combined_hangul_mapping_sub52d2.tsv"
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw "Python not found"}
        & $py.Source ".\build_sub52g_fix1_final_residual_apply.py" `
          --root $Root `
          --assets ".\sub52g_assets" `
          --mapping ".\combined_hangul_mapping_sub52d2.tsv"
    }
    if($LASTEXITCODE -ne 0){throw "SUB52G build failed: $LASTEXITCODE"}

    $Built=Join-Path $Out "Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso"
    if(-not (Test-Path $Built)){throw "Built ISO missing: $Built"}
    Copy-Item -LiteralPath $Built -Destination $RootIso -Force
    Write-Host "ISO: $RootIso"
    $Succeeded=$true
}
catch {
    @(
      "Naruto SUB52G FIX1 FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $Out "FAILURE.txt") -Encoding UTF8
}
finally {
    try{Stop-Transcript | Out-Null}catch{}
    $Pack=Join-Path $Out "_upload"
    if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    foreach($n in @(
      "SUMMARY.txt","SUB52G_static_verification.json",
      "sub52g_text_patch.tsv","sub52g_texture_patch.tsv",
      "sub52g_primary_rebuild.tsv","sub52g_fsts_rebuild.tsv",
      "sub52g_core_verification.tsv","sub52g_movie_preservation.tsv",
      "FAILURE.txt"
    )){
        $p=Join-Path $Out $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
    }
    if(Test-Path $Transcript){Copy-Item $Transcript (Join-Path $Pack (Split-Path $Transcript -Leaf)) -Force}
    foreach($n in @(
      "build_sub52g_fix1_final_residual_apply.py",
      "run_naruto_sub52g_fix1_final_residual_apply.ps1",
      "combined_hangul_mapping_sub52d2.tsv"
    )){
        $p=Join-Path $Root $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
    }
    if(Test-Path (Join-Path $Root "sub52g_assets\asset_manifest.json")){
        Copy-Item (Join-Path $Root "sub52g_assets\asset_manifest.json") (Join-Path $Pack "asset_manifest.json") -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $z){Remove-Item $z -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pack,$z,[System.IO.Compression.CompressionLevel]::Optimal,$false
    )
    Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Upload ZIP: $z"

    if($Succeeded){
        # Final runtime QA: launch only the exact generated ISO.
        # Do not kill/control any other PPSSPP instance and do not run story macros.
        $PPSSPP="C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe"
        if(Test-Path $PPSSPP){
            Write-Host "Launching exact final ISO in PPSSPP for manual menu QA..."
            $proc=Start-Process -FilePath $PPSSPP -ArgumentList @("`"$RootIso`"") -PassThru
            Write-Host "PPSSPP PID: $($proc.Id)"
        } else {
            Write-Warning "PPSSPP not found at expected path. Build succeeded; launch manually: $RootIso"
        }
    } else {
        exit 1
    }
}
