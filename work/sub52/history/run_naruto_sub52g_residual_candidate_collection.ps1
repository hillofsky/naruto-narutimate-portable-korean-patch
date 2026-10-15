$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root

Write-Host "=== SUB52G RESIDUAL CANDIDATE COLLECTION ==="
Write-Host "Static only. No PPSSPP / no gameplay / no ISO modification."

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){
    & $py.Source -3 ".\qa_sub52g_residual_candidate_collection.py"
}else{
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){throw "Python not found"}
    & $py.Source ".\qa_sub52g_residual_candidate_collection.py"
}
if($LASTEXITCODE -ne 0){
    throw "SUB52G collection failed: $LASTEXITCODE"
}
