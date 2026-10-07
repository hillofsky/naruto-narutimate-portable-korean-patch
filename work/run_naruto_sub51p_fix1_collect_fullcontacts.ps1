$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51P FIX1 FULL CONTACT COLLECTION ==="
Write-Host "No PPSSPP. No story automation. No ISO modification."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51p_fix1_collect_fullcontacts.py" }
else { & python ".\qa_sub51p_fix1_collect_fullcontacts.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51P FIX1 failed: $LASTEXITCODE" }
