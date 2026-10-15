$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root='D:\narutimate portable'
$Out=Join-Path $Root 'analysis\sub\sub52i_p0_rollback_fix1'
$Logs=Join-Path $Root 'logs'
$Stage='naruto_sub52i_p0_rollback_fix1'
$SuccessZip=Join-Path $Logs ($Stage+'_upload.zip')
$FailZip=Join-Path $Logs ('fail_'+$Stage+'_upload.zip')
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $Logs ($Stage+'_'+$Stamp+'.log')
$Succeeded=$false
$Reason=''
New-Item -ItemType Directory -Force -Path $Out,$Logs | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== NARUTO SUB52I FIX1 - P0 SAFE ROLLBACK ==='
    Write-Host 'Use EXACT SHA-verified FIX3 and SUB52G FIX1 ISOs.'
    Write-Host 'Restore exactly two atlas payloads + two Mugen UV rows; no other text modification.'
    Write-Host 'Other PPSSPP processes are untouched; story macro is NOT used.'

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 '.\build_sub52i_p0rollback_fix1.py' --root $Root
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw 'Python 3 not found'}
        & $py.Source '.\build_sub52i_p0rollback_fix1.py' --root $Root
    }
    if($LASTEXITCODE -ne 0){throw "SUB52I Python build failed with exit code $LASTEXITCODE"}
    $Built=Join-Path $Out 'Naruto_KR_MOV06E_SUB52I_P0_Rollback_FIX1.iso'
    if(-not (Test-Path -LiteralPath $Built)){throw 'Generated ISO missing: '+$Built}
    $Report=Join-Path $Out 'SUMMARY.json'
    if(-not (Test-Path -LiteralPath $Report)){throw 'Static verification summary missing'}
    $Summary=Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
    if($Summary.static_qa -ne 'PASS'){throw 'Static QA is not PASS'}
    Write-Host 'Verified generated ISO: ' $Built
    $Succeeded=$true
}
catch {
    $Reason=$_.Exception.Message
    @('SUB52I FAILED',('Timestamp='+[DateTime]::Now.ToString('s')),$Reason,($_ | Out-String)) |
        Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
}
finally {
    try{Stop-Transcript | Out-Null}catch{}
    $Pack=Join-Path $Out '_log_package'
    if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    foreach($n in @('SUMMARY.json','SUMMARY.txt','texture_rollback.tsv','uv_rollback.tsv',
                     'target_texture_evidence.tsv','resource_rebuild.tsv',
                     'core_verification.tsv','movie_preservation.tsv','FAILURE.txt')) {
        $p=Join-Path $Out $n
        if(Test-Path $p){Copy-Item -LiteralPath $p -Destination $Pack -Force}
    }
    $Comparison=Join-Path $Out 'comparisons'
    if(Test-Path $Comparison){Copy-Item -LiteralPath $Comparison -Destination (Join-Path $Pack 'comparisons') -Recurse -Force}
    if(Test-Path $Transcript){Copy-Item -LiteralPath $Transcript -Destination $Pack -Force}
    foreach($n in @('build_sub52i_p0rollback_fix1.py','run_naruto_sub52i_p0rollback_fix1.ps1','README_SUB52I_FIX1.txt')){
        $src=Join-Path $Root $n
        if(Test-Path $src){Copy-Item -LiteralPath $src -Destination $Pack -Force}
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $ZipPath=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $ZipPath){Remove-Item $ZipPath -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$ZipPath,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ('Upload ZIP: '+$ZipPath)
}
if(-not $Succeeded){
    Write-Host ('Failed: '+$Reason) -ForegroundColor Red
    exit 1
}

# QA launch: no port/websocket interaction, no killing another PPSSPP instance.
# The only argument is the exact generated ISO path, not a batch/story macro.
$Iso=Join-Path $Out 'Naruto_KR_MOV06E_SUB52I_P0_Rollback_FIX1.iso'
$PPSSPP='C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe'
if(Test-Path -LiteralPath $PPSSPP){
    Write-Host ('Launching for MANUAL visual QA: '+$Iso)
    $proc=Start-Process -FilePath $PPSSPP -ArgumentList @(('"'+$Iso+'"')) -PassThru
    Write-Host ('Launched PPSSPP PID='+$proc.Id)
}else{
    Write-Warning ('PPSSPP not found; ISO is still ready: '+$Iso)
}
