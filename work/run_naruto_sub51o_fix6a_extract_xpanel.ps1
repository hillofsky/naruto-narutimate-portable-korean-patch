$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX6A EXACT TEX_xpanel EXTRACT ==="
Write-Host "No NumPy required."
Write-Host "PPSSPP will NOT launch. Source ISO is READ ONLY."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix6a_extract_xpanel.py" }
else { & python ".\qa_sub51o_fix6a_extract_xpanel.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX6A failed: $LASTEXITCODE" }
