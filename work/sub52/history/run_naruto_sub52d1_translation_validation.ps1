$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
Set-Location $Root
Write-Host "=== SUB52D1 TRANSLATION VALIDATION ==="
Write-Host "No PPSSPP. No gameplay. No ISO modification."

$src=Join-Path $Root "sub52d1_residual_text_translated.tsv"
if(-not (Test-Path $src)){
    throw "Bundled translation TSV was not extracted to root."
}

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if($py){ & $py.Source -3 ".\qa_sub52d1_translation_validation.py" }
else{
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){throw "Python not found"}
    & $py.Source ".\qa_sub52d1_translation_validation.py"
}
if($LASTEXITCODE -ne 0){throw "SUB52D1 validation failed: $LASTEXITCODE"}
