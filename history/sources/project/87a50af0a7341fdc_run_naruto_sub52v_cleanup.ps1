param(
    [string]$Root = 'PROJECT_ROOT',
    [double]$TargetFreeGiB = 16.0,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Logs = Join-Path $Root 'logs'
$Stage = Join-Path $Root 'analysis\sub\sub52v_cleanup'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Report = Join-Path $Stage ('run_' + $Stamp)
$Transcript = Join-Path $Report 'powershell_transcript.log'
$SuccessZip = Join-Path $Logs 'naruto_sub52v_cleanup_upload.zip'
$FailureZip = Join-Path $Logs 'fail_naruto_sub52v_cleanup_upload.zip'
$Succeeded = $false
$Zip = $FailureZip

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "Project root not found: $Root"
}
New-Item -ItemType Directory -Force -Path $Logs,$Report | Out-Null
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== Naruto SUB52V disk cleanup ==='
    Write-Host 'Protect: SUB52U, SUB52T, SUB52N, SUB52M, SUB52K FIX2, SUB52J, original ISO, scripts, translations and logs.'
    Write-Host ('Target free space: {0:N1} GiB' -f $TargetFreeGiB)
    Write-Host 'No PPSSPP process will be launched, controlled or terminated.'

    # If PPSSPP process inspection is unavailable, ISO deletion is DISABLED.
    # Scratch cleanup may still proceed, limited to completed Stage52 builds.
    $snap = @{
        inspection_success = $false
        command_lines = @()
        note = 'PPSSPP command-line inspection not performed'
    }
    try {
        $running = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'PPSSPPWindows64.exe' OR Name = 'PPSSPPWindows.exe' OR Name = 'PPSSPPWindows64_dev.exe'" -ErrorAction Stop)
        $lines = @()
        foreach ($p in $running) {
            if ([string]::IsNullOrWhiteSpace([string]$p.CommandLine)) {
                throw 'Cannot read a PPSSPP command line; protect all obsolete ISOs'
            }
            $lines += [string]$p.CommandLine
        }
        $snap.inspection_success = $true
        $snap.command_lines = $lines
        $snap.note = ('PPSSPP processes examined: ' + $running.Count)
    }
    catch {
        $snap.note = 'Read-only PPSSPP inspection unavailable: ' + $_.Exception.Message
        Write-Warning $snap.note
    }
    $activeFile = Join-Path $Report 'active_ppsspp_processes.json'
    $snap | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $activeFile -Encoding UTF8

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $python = $py.Source
        $pythonArgs = @('-3')
    } else {
        $py = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $py) { throw 'Python 3.12+ was not found' }
        $python = $py.Source
        $pythonArgs = @()
    }
    $runArgs = @(
        (Join-Path $Here 'cleanup_sub52v.py'),
        '--root', $Root,
        '--report', $Report,
        '--target-free-gib', ([string]$TargetFreeGiB),
        '--active-file', $activeFile
    )
    if ($DryRun) { $runArgs += '--dry-run' }

    # PowerShell 5.1 can treat stderr from native applications as terminating
    # errors under Stop, even when the application handles the error itself.
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $python @pythonArgs @runArgs
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($exitCode -ne 0) { throw "Cleanup analyzer exited with code $exitCode" }
    if (-not (Test-Path -LiteralPath (Join-Path $Report 'SUMMARY.json'))) {
        throw 'SUMMARY.json was not created'
    }
    $Succeeded = $true
    $Zip = $SuccessZip
}
catch {
    @(
        'SUB52V CLEANUP FAILURE',
        ('Timestamp=' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
        ($_ | Out-String)
    ) | Set-Content -LiteralPath (Join-Path $Report 'FAILURE.txt') -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
    Copy-Item -LiteralPath (Join-Path $Here 'cleanup_sub52v.py') -Destination $Report -Force
    Copy-Item -LiteralPath (Join-Path $Here 'run_naruto_sub52v_cleanup.ps1') -Destination $Report -Force
    Copy-Item -LiteralPath (Join-Path $Here 'README_SUB52V.txt') -Destination $Report -Force
    try {
        $oldDir = Join-Path $Logs 'old'
        if (Test-Path -LiteralPath $Zip) {
            New-Item -ItemType Directory -Force -Path $oldDir | Out-Null
            $oldTarget = Join-Path $oldDir ([IO.Path]::GetFileNameWithoutExtension($Zip) + '_' + $Stamp + '.zip')
            Move-Item -LiteralPath $Zip -Destination $oldTarget -Force
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $Report, $Zip, [System.IO.Compression.CompressionLevel]::Optimal, $false
        )
        Write-Host "RESULT_ZIP=$Zip"
        if ($Succeeded) {
            $status = Get-Content -LiteralPath (Join-Path $Report 'SUMMARY.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Host ('DELETED_ITEMS=' + $status.files_and_dirs_deleted)
            Write-Host ('FREED_GIB={0:N2}' -f ($status.free_delta_bytes / 1GB))
            Write-Host ('FREE_NOW_GIB={0:N2}' -f ($status.free_after_bytes / 1GB))
            Write-Host ('TARGET_REACHED=' + $status.target_reached)
        }
    }
    catch {
        Write-Host ('FAILED_TO_CREATE_ZIP: ' + $_.Exception.Message)
        exit 1
    }
    if (-not $Succeeded) { exit 1 }
}
