$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Root='D:\narutimate portable'
$Stage='naruto_sub52k_face_names'
$Out=Join-Path $Root 'analysis\sub\sub52k_face_names'
$Logs=Join-Path $Root 'logs'
$ZipSuccess=Join-Path $Logs ($Stage+'_upload.zip')
$ZipFailure=Join-Path $Logs ('fail_'+$Stage+'_upload.zip')
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $Logs ($Stage+'_'+$Stamp+'.log')
$Succeeded=$false
$Reason=''
New-Item -ItemType Directory -Force -Path $Out,$Logs | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== NARUTO SUB52K - FACE NAME KOREAN ASSETS ==='
    Write-Host 'Only 46 TEX_n_* name textures in 23 face_*.ccs resources.'
    Write-Host 'Source ISO hash verified. SUB52J scroll and tree-climb improvements remain preserved.'
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 '.\build_sub52k_face_names.py' --root $Root --assets (Join-Path $Root 'sub52k_assets')
    }else{
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw 'Python 3 not found'}
        & $py.Source '.\build_sub52k_face_names.py' --root $Root --assets (Join-Path $Root 'sub52k_assets')
    }
    if($LASTEXITCODE -ne 0){throw ('SUB52K Python build failed, exit='+$LASTEXITCODE)}
    $Iso=Join-Path $Out 'Naruto_KR_MOV06E_SUB52K_FaceNames.iso'
    if(-not (Test-Path -LiteralPath $Iso)){throw ('Generated ISO is missing: '+$Iso)}
    $ReportPath=Join-Path $Out 'SUB52K_static_verification.json'
    if(-not (Test-Path -LiteralPath $ReportPath)){throw 'Static verification JSON missing'}
    $Report=Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
    if($Report.static_qa -ne 'PASS'){throw 'Static QA did not pass'}
    if($Report.textures_changed -ne 46){throw 'Incorrect number of modified name textures'}
    if($Report.resources_changed -ne 23){throw 'Incorrect number of modified character face resources'}
    $Succeeded=$true
    Write-Host ('ISO: '+$Iso)
} catch {
    $Reason=$_.Exception.Message
    @('SUB52K FAILURE',('Timestamp='+[DateTime]::Now.ToString('s')),$Reason,($_ | Out-String)) |
        Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
} finally {
    try {Stop-Transcript | Out-Null} catch {}
    $Pack=Join-Path $Out '_log_package'
    if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    foreach($n in @('SUMMARY.txt','SUB52K_static_verification.json',
        'sub52k_texture_patch.tsv','sub52k_primary_rebuild.tsv',
        'sub52k_fsts_rebuild.tsv','sub52k_core_verification.tsv',
        'sub52k_movie_preservation.tsv','FAILURE.txt')){
        $p=Join-Path $Out $n
        if(Test-Path $p){Copy-Item -LiteralPath $p -Destination $Pack -Force}
    }
    if(Test-Path $Transcript){Copy-Item -LiteralPath $Transcript -Destination $Pack -Force}
    foreach($n in @('build_sub52k_face_names.py','run_naruto_sub52k_face_names.ps1','README_SUB52K.txt','face_name_jp_ko_preview.jpg','TRANSLATIONS.tsv')){
        $p=Join-Path $Root $n
        if(Test-Path $p){Copy-Item -LiteralPath $p -Destination $Pack -Force}
    }
    $AssetsPath=Join-Path $Root 'sub52k_assets'
    if(Test-Path $AssetsPath){Copy-Item -LiteralPath $AssetsPath -Destination $Pack -Recurse -Force}
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$ZipSuccess}else{$ZipFailure}
    if(Test-Path $Zip){Remove-Item $Zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item -LiteralPath $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ('Upload ZIP: '+$Zip)
}
if(-not $Succeeded){
    Write-Host ('Failed: '+$Reason) -ForegroundColor Red
    exit 1
}
$Iso=Join-Path $Out 'Naruto_KR_MOV06E_SUB52K_FaceNames.iso'
$PPSSPP='C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe'
if(Test-Path -LiteralPath $PPSSPP){
    Write-Host ('Launching exact SUB52K ISO for manual QA: '+$Iso)
    $proc=Start-Process -FilePath $PPSSPP -ArgumentList @(('"'+$Iso+'"')) -PassThru
    Write-Host ('PPSSPP PID='+$proc.Id)
}else{
    Write-Warning ('PPSSPP not found; launch this ISO manually: '+$Iso)
}
