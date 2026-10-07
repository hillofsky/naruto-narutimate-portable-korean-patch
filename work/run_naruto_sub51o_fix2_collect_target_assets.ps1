$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX2 TARGET ASSET COLLECTION ==="
Write-Host "PPSSPP will NOT launch. Read-only collection of 12 exact candidate PNGs."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix2_collect_target_assets.py" }
else { & python ".\qa_sub51o_fix2_collect_target_assets.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX2 collection failed: $LASTEXITCODE" }
