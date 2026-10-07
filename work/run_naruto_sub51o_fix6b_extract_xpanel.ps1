$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51O FIX6B EXACT TEX_xpanel EXTRACT ==="
Write-Host "No NumPy. No Pillow. Standard-library-only PNG writer."
Write-Host "PPSSPP will NOT launch. Source ISO is READ ONLY."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51o_fix6b_extract_xpanel.py" }
else { & python ".\qa_sub51o_fix6b_extract_xpanel.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51O FIX6B failed: $LASTEXITCODE" }
