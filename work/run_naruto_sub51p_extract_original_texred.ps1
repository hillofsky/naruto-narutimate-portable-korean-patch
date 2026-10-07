$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root

Write-Host "=== SUB51P TEX_red ORIGINAL EXTRACT ==="
Write-Host "No PPSSPP. No story automation. No ISO modification."

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){
    & $py.Source -3 ".\qa_sub51p_extract_original_texred.py"
}else{
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){ throw "Python not found" }
    & $py.Source ".\qa_sub51p_extract_original_texred.py"
}
if($LASTEXITCODE -ne 0){
    throw "SUB51P TEX_red extraction failed: $LASTEXITCODE"
}
