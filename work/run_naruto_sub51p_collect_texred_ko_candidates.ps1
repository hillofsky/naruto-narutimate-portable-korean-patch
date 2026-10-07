$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root

Write-Host "=== SUB51P TEX_red KO CANDIDATE COLLECTION ==="
Write-Host "Read-only. No PPSSPP. No story automation. No ISO modification."

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){
    & $py.Source -3 ".\qa_sub51p_collect_texred_ko_candidates.py"
}else{
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){throw "Python not found"}
    & $py.Source ".\qa_sub51p_collect_texred_ko_candidates.py"
}
if($LASTEXITCODE -ne 0){throw "Collection failed: $LASTEXITCODE"}
