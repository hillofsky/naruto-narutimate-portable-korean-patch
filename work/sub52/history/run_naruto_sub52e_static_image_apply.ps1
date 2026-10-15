$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$Logs=Join-Path $Root "logs"
$Out=Join-Path $Root "analysis\sub\sub52e_static_image_apply"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub52e_static_image_apply_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub52e_static_image_apply_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub52e_static_image_apply_upload.zip"
$Succeeded=$false

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== SUB52E STATIC IMAGE APPLY ==="
    Write-Host "Uses successful SUB52D2 FIX2 as source."
    Write-Host "PPSSPP is still deferred until this static image batch passes."

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 ".\build_sub52e_static_image_apply.py" `
          --root $Root `
          --assets ".\sub52e_assets"
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw "Python not found"}
        & $py.Source ".\build_sub52e_static_image_apply.py" `
          --root $Root `
          --assets ".\sub52e_assets"
    }
    if($LASTEXITCODE -ne 0){throw "SUB52E build failed: $LASTEXITCODE"}

    $Built=Join-Path $Out "Naruto_KR_MOV06E_SUB52E_StaticImages.iso"
    if(-not (Test-Path $Built)){throw "Built ISO missing: $Built"}
    $RootIso=Join-Path $Root "Naruto_KR_MOV06E_SUB52E_StaticImages.iso"
    Copy-Item -LiteralPath $Built -Destination $RootIso -Force
    Write-Host "ISO: $RootIso"
    $Succeeded=$true
}
catch {
    @(
      "Naruto SUB52E FAILURE",
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
      "SUMMARY.txt","SUB52E_static_verification.json",
      "sub52e_texture_patch.tsv","sub52e_primary_rebuild.tsv",
      "sub52e_fsts_rebuild.tsv","sub52e_core_verification.tsv",
      "sub52e_movie_preservation.tsv","FAILURE.txt"
    )){
        $p=Join-Path $Out $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
    }
    Copy-Item $Transcript (Join-Path $Pack (Split-Path $Transcript -Leaf)) -Force
    foreach($n in @("build_sub52e_static_image_apply.py","run_naruto_sub52e_static_image_apply.ps1")){
        $p=Join-Path $Root $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
    }
    if(Test-Path (Join-Path $Root "sub52e_assets\asset_manifest.json")){
        Copy-Item (Join-Path $Root "sub52e_assets\asset_manifest.json") (Join-Path $Pack "asset_manifest.json") -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $z){Remove-Item $z -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pack,$z,[System.IO.Compression.CompressionLevel]::Optimal,$false
    )
    Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Upload ZIP: $z"
    if(-not $Succeeded){exit 1}
}
