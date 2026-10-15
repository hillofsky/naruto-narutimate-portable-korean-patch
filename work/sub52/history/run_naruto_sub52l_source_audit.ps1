$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root = 'D:\narutimate portable'
$Stage = 'naruto_sub52l_runtime_source_audit'
$Out = Join-Path $Root 'analysis\sub\sub52l_runtime_source_audit'
$Logs = Join-Path $Root 'logs'
$SuccessZip = Join-Path $Logs ($Stage + '_upload.zip')
$FailZip = Join-Path $Logs ('fail_' + $Stage + '_upload.zip')
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript = Join-Path $Logs ($Stage + '_' + $Stamp + '.log')
$Succeeded = $false

New-Item -ItemType Directory -Force -Path $Out, $Logs | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== SUB52L STATIC RUNTIME SOURCE AUDIT ==='
    Write-Host 'Read-only: no ISO writes, no PPSSPP launch, no story macro.'
    $Source = Join-Path $Root 'analysis\sub\sub52k_fix2_compact\Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso'
    $Baseline = Join-Path $Root 'analysis\sub\sub52j_safe_atlas\Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso'
    if (-not (Test-Path -LiteralPath $Source)) { throw "Missing working SUB52K FIX2 ISO: $Source" }
    if (-not (Test-Path -LiteralPath $Baseline)) { throw "Missing reference SUB52J ISO: $Baseline" }

    $Py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Py) {
        & $Py.Source -3 (Join-Path $ScriptDir 'sub52l_audit.py') --root $Root
    } else {
        $Py = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $Py) { throw 'Python not found' }
        & $Py.Source (Join-Path $ScriptDir 'sub52l_audit.py') --root $Root
    }
    if ($LASTEXITCODE -ne 0) { throw "SUB52L static audit Python exit code: $LASTEXITCODE" }
    if (-not (Test-Path (Join-Path $Out 'SUMMARY.json'))) { throw 'Missing SUMMARY.json' }
    $Succeeded = $true
}
catch {
    @(
      'SUB52L FAILED',
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content -Path (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    $Pack = Join-Path $Out '_upload_bundle'
    if (Test-Path $Pack) { Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null

    Get-ChildItem -Path $Out -File -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Pack -Force
    }
    foreach ($sub in @('current_FIX2','baseline_SUB52J')) {
        $src = Join-Path $Out $sub
        if (Test-Path $src) { Copy-Item -LiteralPath $src -Destination (Join-Path $Pack $sub) -Recurse -Force }
    }
    if (Test-Path $Transcript) { Copy-Item -LiteralPath $Transcript -Destination $Pack -Force }
    Copy-Item -LiteralPath (Join-Path $ScriptDir 'sub52l_audit.py') -Destination $Pack -Force
    Copy-Item -LiteralPath (Join-Path $ScriptDir 'run_naruto_sub52l_source_audit.ps1') -Destination $Pack -Force

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $TargetZip = if ($Succeeded) { $SuccessZip } else { $FailZip }
    if (Test-Path $TargetZip) { Remove-Item $TargetZip -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
       $Pack, $TargetZip, [System.IO.Compression.CompressionLevel]::Optimal, $false
    )
    Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Upload ZIP: $TargetZip"
    if (-not $Succeeded) { exit 1 }
}
