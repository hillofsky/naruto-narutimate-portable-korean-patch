$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX5 EXACT TARGET COLLECTION ==="
Write-Host "Confirmed target: gauge.ccs / TEX_xpanel"
Write-Host "PPSSPP will NOT launch. No ISO modification."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix5_collect_exact_targets.py" }
else { & python ".\qa_sub51o_fix5_collect_exact_targets.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX5 failed: $LASTEXITCODE" }
