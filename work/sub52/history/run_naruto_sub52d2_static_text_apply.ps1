$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$Logs=Join-Path $Root "logs"
$Out=Join-Path $Root "analysis\sub\sub52d2_static_text_apply"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub52d2_static_text_apply_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub52d2_static_text_apply_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub52d2_static_text_apply_upload.zip"
$Succeeded=$false

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== SUB52D2 STATIC TEXT APPLY ==="
    Write-Host "PPSSPP will NOT launch yet; runtime QA is deferred until the image batch is merged."

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 ".\build_sub52d2_static_text_apply.py" `
          --root $Root `
          --translations ".\sub52d1_residual_text_translated.tsv"
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw "Python not found"}
        & $py.Source ".\build_sub52d2_static_text_apply.py" `
          --root $Root `
          --translations ".\sub52d1_residual_text_translated.tsv"
    }
    if($LASTEXITCODE -ne 0){throw "SUB52D2 build failed: $LASTEXITCODE"}

    $Built=Join-Path $Out "Naruto_KR_MOV06E_SUB52D2_StaticText.iso"
    if(-not (Test-Path $Built)){throw "Built ISO missing: $Built"}
    $RootIso=Join-Path $Root "Naruto_KR_MOV06E_SUB52D2_StaticText.iso"
    Copy-Item -LiteralPath $Built -Destination $RootIso -Force
    Write-Host "ISO: $RootIso"
    $Succeeded=$true
}
catch {
    @(
      "Naruto SUB52D2 FAILURE",
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
      "SUMMARY.txt","SUB52D2_static_verification.json",
      "new_glyph_mapping_sub52d2.tsv","combined_hangul_mapping_sub52d2.tsv",
      "sub52d2_new_glyph_preview.png","sub52d2_tbl_patch.tsv",
      "sub52d2_primary_rebuild.tsv","sub52d2_fsts_rebuild.tsv",
      "sub52d2_core_verification.tsv","sub52d2_movie_preservation.tsv",
      "FAILURE.txt"
    )){
        $p=Join-Path $Out $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
    }
    Copy-Item $Transcript (Join-Path $Pack (Split-Path $Transcript -Leaf)) -Force
    foreach($n in @("build_sub52d2_static_text_apply.py","run_naruto_sub52d2_static_text_apply.ps1","sub52d1_residual_text_translated.tsv")){
        $p=Join-Path $Root $n
        if(Test-Path $p){Copy-Item $p (Join-Path $Pack $n) -Force}
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
