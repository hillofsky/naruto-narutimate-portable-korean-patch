$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$ActualOut=Join-Path $Root "analysis\sub\sub52h_residual_fix2"
$Built=Join-Path $ActualOut "Naruto_KR_MOV06E_SUB52H_FIX3.iso"
$RootIso=Join-Path $Root "Naruto_KR_MOV06E_SUB52H_FIX3.iso"
$Logs=Join-Path $Root "logs"
$SuccessZip=Join-Path $Logs "naruto_sub52h_fix3_recovered_upload.zip"
$ExpectedSHA="87e1d9ad950e8b2ed9674e3569a139c21a39f93db7cbbd66997ee03f3162f194"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

Write-Host "=== SUB52H FIX3 RECOVERY ==="
Write-Host "The previous Python build completed successfully."
Write-Host "Recovering the already-built ISO from the directory the builder actually used."

if(-not (Test-Path $Built)){
    throw "Built ISO not found: $Built"
}

$hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $Built).Hash.ToLowerInvariant()
Write-Host "Built ISO SHA256: $hash"
if($hash -ne $ExpectedSHA){
    throw "Unexpected ISO SHA256. Expected $ExpectedSHA"
}

Copy-Item -LiteralPath $Built -Destination $RootIso -Force
Write-Host "Recovered ISO: $RootIso"

$Pack=Join-Path $ActualOut "_recovery_upload"
if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
New-Item -ItemType Directory -Force -Path $Pack | Out-Null

foreach($n in @(
  "SUMMARY.txt","SUB52H_static_verification.json",
  "sub52h_boot_patch.tsv","sub52h_text_patch.tsv","sub52h_texture_patch.tsv",
  "sub52h_primary_rebuild.tsv","sub52h_fsts_rebuild.tsv",
  "sub52h_core_verification.tsv","sub52h_movie_preservation.tsv"
)){
    $p=Join-Path $ActualOut $n
    if(Test-Path $p){Copy-Item $p $Pack -Force}
}

@(
  "RecoveredFrom=$Built",
  "RecoveredTo=$RootIso",
  "SHA256=$hash",
  "Note=Previous run was a false runner failure: Python built and verified the ISO, but the PowerShell runner looked in the wrong output folder.",
  "Important=Static report showed boot_cstring_rows_patched=0, so do not assume runtime character-name/tree-climb string issues are fixed until manual QA."
) | Set-Content -Encoding UTF8 (Join-Path $Pack "RECOVERY.txt")

Add-Type -AssemblyName System.IO.Compression.FileSystem
if(Test-Path $SuccessZip){Remove-Item $SuccessZip -Force}
[System.IO.Compression.ZipFile]::CreateFromDirectory(
  $Pack,$SuccessZip,[System.IO.Compression.CompressionLevel]::Optimal,$false
)
Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Recovery ZIP: $SuccessZip"

$PPSSPP="C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe"
if(Test-Path $PPSSPP){
    Write-Host "Launching exact recovered ISO for manual QA..."
    Start-Process -FilePath $PPSSPP -ArgumentList @("`"$RootIso`"") | Out-Null
}else{
    Write-Warning "PPSSPP not found. Launch manually: $RootIso"
}
