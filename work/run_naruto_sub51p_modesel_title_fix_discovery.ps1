$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB51P MODESEL/TITLE FIX DISCOVERY ==="
Write-Host "PPSSPP will NOT launch. No story automation. Read-only collection."
$py=Get-Command py -ErrorAction SilentlyContinue
if($py){ & py -3 ".\qa_sub51p_modesel_title_fix_discovery.py" }
else { & python ".\qa_sub51p_modesel_title_fix_discovery.py" }
if($LASTEXITCODE -ne 0){ throw "SUB51P discovery failed: $LASTEXITCODE" }
