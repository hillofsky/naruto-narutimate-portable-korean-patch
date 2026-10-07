$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX4 CONTACT COLLECTION ==="
Write-Host "PPSSPP will NOT launch. Read-only collection only."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix4_collect_contacts.py" }
else { & python ".\qa_sub51o_fix4_collect_contacts.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX4 failed: $LASTEXITCODE" }
