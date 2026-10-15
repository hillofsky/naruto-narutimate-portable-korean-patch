$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root = 'D:\narutimate portable'
$Stage = 'naruto_sub52k_fix2_compact'
$Out = Join-Path $Root 'analysis\sub\sub52k_fix2_compact'
$Logs = Join-Path $Root 'logs'
$SuccessZip = Join-Path $Logs ($Stage + '_upload.zip')
$FailZip = Join-Path $Logs ('fail_' + $Stage + '_upload.zip')
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript = Join-Path $Logs ($Stage + '_' + $Stamp + '.log')
$Succeeded = $false
$Reason = ''

New-Item -ItemType Directory -Force -Path $Out,$Logs | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== Naruto SUB52K FIX2 - compact ISO under 4GiB ==='
    Write-Host 'Read only: source SUB52J and failed SUB52K.'
    Write-Host 'This is repacking only: no new texture edits, no story macro.'
    $Py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Py) {
        & $Py.Source -3 '.\build_sub52k_fix2_compact.py' --root $Root
    } else {
        $Py = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $Py) { throw 'Python 3 executable not found' }
        & $Py.Source '.\build_sub52k_fix2_compact.py' --root $Root
    }
    if ($LASTEXITCODE -ne 0) { throw ('Python compact build failed, exit=' + $LASTEXITCODE) }
    $ISO = Join-Path $Out 'Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso'
    $Report = Join-Path $Out 'SUB52K_FIX2_verification.json'
    if (-not (Test-Path -LiteralPath $ISO)) { throw 'Compacted ISO not created' }
    if (-not (Test-Path -LiteralPath $Report)) { throw 'Verification report not created' }
    $Json = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
    if ($Json.static_qa -ne 'PASS' -or -not $Json.under_4gib) { throw 'Compact static QA failed' }
    $Succeeded = $true
    Write-Host ('ISO ready: ' + $ISO)
} catch {
    $Reason = $_.Exception.Message
    @('SUB52K FIX2 COMPACT FAILURE',('Timestamp=' + (Get-Date -Format 's')),$Reason,($_ | Out-String)) |
        Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
} finally {
    try { Stop-Transcript | Out-Null } catch {}
    $Pack = Join-Path $Out '_upload_package'
    if (Test-Path $Pack) { Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    foreach ($name in @('SUMMARY.txt','SUB52K_FIX2_verification.json','FAILURE.txt')) {
        $p = Join-Path $Out $name
        if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination $Pack -Force }
    }
    if (Test-Path -LiteralPath $Transcript) { Copy-Item -LiteralPath $Transcript -Destination $Pack -Force }
    foreach ($name in @('build_sub52k_fix2_compact.py','run_naruto_sub52k_fix2_compact.ps1','README_SUB52K_FIX2.txt')) {
        $p = Join-Path $Root $name
        if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination $Pack -Force }
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = if ($Succeeded) { $SuccessZip } else { $FailZip }
    if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item -LiteralPath $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ('Upload ZIP: ' + $Zip)
}

if (-not $Succeeded) {
    Write-Host ('Build stopped: ' + $Reason) -ForegroundColor Red
    exit 1
}

# Launch ONLY the verified compact ISO. Never terminate/control existing PPSSPP instances.
$ISO = Join-Path $Out 'Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso'
$PPSSPP = 'C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe'
if (Test-Path -LiteralPath $PPSSPP) {
    Write-Host ('Launching only compact ISO: ' + $ISO)
    $proc = Start-Process -FilePath $PPSSPP -ArgumentList @(('"' + $ISO + '"')) -PassThru
    Write-Host ('Launched PPSSPP PID=' + $proc.Id)
} else {
    Write-Warning ('PPSSPP not found. Start this ISO manually: ' + $ISO)
}
