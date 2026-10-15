$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root

Write-Host "=== SUB52A FULL STATIC ASSET SWEEP ==="
Write-Host "No PPSSPP. No gameplay. No story automation. No ISO modification."

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){
    & $py.Source -3 ".\qa_sub52a_full_static_asset_sweep.py"
}else{
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){throw "Python not found"}
    & $py.Source ".\qa_sub52a_full_static_asset_sweep.py"
}
if($LASTEXITCODE -ne 0){
    throw "SUB52A static sweep failed: $LASTEXITCODE"
}
