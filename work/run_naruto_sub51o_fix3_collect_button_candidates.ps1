$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX3 BUTTON CANDIDATE COLLECTION ==="
Write-Host "PPSSPP will NOT launch. No ISO modification."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix3_collect_button_candidates.py" }
else { & python ".\qa_sub51o_fix3_collect_button_candidates.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX3 failed: $LASTEXITCODE" }
