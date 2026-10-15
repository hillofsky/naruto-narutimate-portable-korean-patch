$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = 'D:\narutimate portable'
$Logs = Join-Path $Root 'logs'
$Out = Join-Path $Root 'analysis\sub\sub52p_historical_source'
$Success = Join-Path $Logs 'naruto_sub52p_historical_source_upload.zip'
$Failure = Join-Path $Logs 'fail_naruto_sub52p_historical_source_upload.zip'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript = Join-Path $Logs ("naruto_sub52p_historical_source_$RunStamp.log")
$ok = $false
New-Item -ItemType Directory -Force -Path $Logs, $Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== SUB52P SOURCE MAP: READ ONLY ==='
    Write-Host 'Inputs: verified SUB52J and SUB52N. No ISO writes or emulator operations.'
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    $oldEAP=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
        if($py) {
            & $py.Source -3 (Join-Path $ScriptRoot 'sub52p_history_probe.py') --root $Root --out $Out
        } else {
            $py = Get-Command python.exe -ErrorAction SilentlyContinue
            if(-not $py) { throw 'Python not found' }
            & $py.Source (Join-Path $ScriptRoot 'sub52p_history_probe.py') --root $Root --out $Out
        }
        $code=$LASTEXITCODE
    } finally { $ErrorActionPreference=$oldEAP }
    if($code -ne 0) { throw "SUB52P Python probe failed, exit=$code" }
    if(-not (Test-Path (Join-Path $Out 'SUMMARY.json'))) { throw 'SUMMARY.json missing' }
    $ok=$true
} catch {
    @('SUB52P failure', "time=$(Get-Date -Format s)", $_.Exception.ToString()) |
        Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
} finally {
    try { Stop-Transcript | Out-Null } catch {}
    $pack=Join-Path $Out '_logpack'
    if(Test-Path $pack) { Remove-Item -LiteralPath $pack -Recurse -Force }
    New-Item -ItemType Directory -Path $pack -Force | Out-Null
    Get-ChildItem -LiteralPath $Out -File -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $pack -Force
    }
    $cmp=Join-Path $Out 'comparison_png'
    if(Test-Path $cmp) {
        Copy-Item -LiteralPath $cmp -Destination $pack -Recurse -Force
    }
    if(Test-Path $Transcript) { Copy-Item -LiteralPath $Transcript -Destination $pack -Force }
    Copy-Item -LiteralPath (Join-Path $ScriptRoot 'sub52p_history_probe.py') -Destination $pack -Force
    Copy-Item -LiteralPath (Join-Path $ScriptRoot 'sub52l_core.py') -Destination $pack -Force
    $zip=if($ok){$Success}else{$Failure}
    try {
        if(Test-Path $zip){Remove-Item -LiteralPath $zip -Force}
        Compress-Archive -Path (Join-Path $pack '*') -DestinationPath $zip -CompressionLevel Optimal -Force
        Write-Host "UPLOAD_ZIP=$zip"
    } finally {
        Remove-Item -LiteralPath $pack -Recurse -Force -ErrorAction SilentlyContinue
    }
    if(-not $ok){exit 1}
}
