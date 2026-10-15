$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB52C STATIC PATCH SOURCE COLLECTION ==="
Write-Host "No PPSSPP. No gameplay. No story automation. No ISO modification."
$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){& $py.Source -3 ".\qa_sub52c_collect_static_patch_sources.py"}
else{
  $py=Get-Command python.exe -ErrorAction SilentlyContinue
  if(-not $py){throw "Python not found"}
  & $py.Source ".\qa_sub52c_collect_static_patch_sources.py"
}
if($LASTEXITCODE -ne 0){throw "SUB52C collection failed: $LASTEXITCODE"}
