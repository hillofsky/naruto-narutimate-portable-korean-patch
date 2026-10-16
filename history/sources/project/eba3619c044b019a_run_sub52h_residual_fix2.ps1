param(
    [string]$Root = 'PROJECT_ROOT',
    [string]$Source = ''
)
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$stageName = 'naruto_sub52h_residual_fix2'
$outDir = Join-Path $Root 'analysis\sub\sub52h_residual_fix2'
$logRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$time = Get-Date -Format 'yyyyMMdd_HHmmss'
$runDir = Join-Path $outDir ("run_" + $time)
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$stdoutLog = Join-Path $runDir 'stdout.log'
$stderrLog = Join-Path $runDir 'stderr.log'
$summaryPath = Join-Path $runDir 'RUN_SUMMARY.txt'

function New-UploadZip([string]$Prefix, [string]$BaseName) {
    $zipName = "$Prefix$BaseName.zip"
    $zipPath = Join-Path $logRoot $zipName
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $runDir '*') -DestinationPath $zipPath -Force
    return $zipPath
}

try {
    Copy-Item (Join-Path $scriptDir 'build_sub52h_residual_fix2.py') $runDir -Force
    Copy-Item (Join-Path $scriptDir 'combined_hangul_mapping_sub52d2.tsv') $runDir -Force
    Copy-Item (Join-Path $scriptDir 'sub52h_boot_patch.tsv') $runDir -Force
    Copy-Item (Join-Path $scriptDir 'sub52h_text_patch.tsv') $runDir -Force
    Copy-Item (Join-Path $scriptDir 'sub52h_assets') (Join-Path $runDir 'sub52h_assets') -Recurse -Force

    $pyArgs = @(
        (Join-Path $scriptDir 'build_sub52h_residual_fix2.py'),
        '--root', $Root,
        '--assets', (Join-Path $scriptDir 'sub52h_assets'),
        '--mapping', (Join-Path $scriptDir 'combined_hangul_mapping_sub52d2.tsv'),
        '--boot-patch', (Join-Path $scriptDir 'sub52h_boot_patch.tsv'),
        '--text-patch', (Join-Path $scriptDir 'sub52h_text_patch.tsv')
    )
    if ($Source -ne '') {
        $pyArgs += @('--source', $Source)
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'python'
    $psi.Arguments = ($pyArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $psi.WorkingDirectory = $scriptDir
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardOutput.ReadToEnd() | Set-Content -Encoding UTF8 $stdoutLog
    $proc.StandardError.ReadToEnd() | Set-Content -Encoding UTF8 $stderrLog
    $proc.WaitForExit()

    if ($proc.ExitCode -ne 0) {
        throw "Python build failed with exit code $($proc.ExitCode)"
    }

    $finalSummary = Join-Path $outDir 'SUMMARY.txt'
    if (Test-Path $finalSummary) {
        Copy-Item $finalSummary $summaryPath -Force
    } else {
        "Build completed, but SUMMARY.txt missing." | Set-Content -Encoding UTF8 $summaryPath
    }

    $zipPath = New-UploadZip '' ($stageName + '_upload')
    Write-Host "SUCCESS_ZIP=$zipPath"
    exit 0
}
catch {
    $_ | Out-String | Set-Content -Encoding UTF8 (Join-Path $runDir 'FAILURE.txt')
    $zipPath = New-UploadZip 'fail_' ($stageName + '_upload')
    Write-Host "FAIL_ZIP=$zipPath"
    throw
}
