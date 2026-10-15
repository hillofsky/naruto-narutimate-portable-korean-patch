$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = 'D:\narutimate portable'
$Name = 'naruto_sub52w_charsel_structural_upload.zip'
$FailName = 'fail_naruto_sub52w_charsel_structural_upload.zip'
$LogRoot = Join-Path $Root 'logs'
$RunId = Get-Date -Format 'yyyyMMdd_HHmmss'
$Out = Join-Path $Root ('analysis\sub\sub52w_charsel_structural\run_' + $RunId)
$Success = $false
try {
  if (!(Test-Path -LiteralPath $Root -PathType Container)) { throw "Project root missing: $Root" }
  New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
  New-Item -ItemType Directory -Path $Out -Force | Out-Null
  $Transcript = Join-Path $Out 'console_transcript.txt'
  try { Start-Transcript -Path $Transcript -Force | Out-Null } catch {}
  Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $Out 'run.ps1') -Force
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'diagnose.py') -Destination (Join-Path $Out 'diagnose.py') -Force
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README_KO.txt') -Destination (Join-Path $Out 'README_KO.txt') -Force
  Write-Host '=== NARUTO SUB52W CHARACTER SELECT STRUCTURAL AUDIT ==='
  Write-Host 'READ ONLY: source ISO, original files, PPSSPP instances untouched.'
  # Isolate to this script's own process. Never address a running emulator.
  $PyCmd = $null
  $PyArgs = @()
  if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $PyCmd = 'py.exe'; $PyArgs = @('-3')
  } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    $PyCmd = 'python.exe'
  } else { throw 'Python 3 not found (py.exe or python.exe). Install Python 3 and retry.' }
  $Script = Join-Path $PSScriptRoot 'diagnose.py'
  $Arguments = @() + $PyArgs + @($Script, '--root', $Root, '--out', $Out)
  & $PyCmd @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $Out 'python_console.txt')
  if ($LASTEXITCODE -ne 0) { throw "Python diagnostic failed, exit=$LASTEXITCODE" }
  $Data = Get-Content -LiteralPath (Join-Path $Out 'RESULT.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($Data.status -eq 'FAIL') { throw 'RESULT.json reports FAIL' }
  $Success = $true
} catch {
  $ErrText = ($_ | Out-String)
  Write-Host ('FAILED: ' + $ErrText) -ForegroundColor Red
  try { New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null } catch { $LogRoot = $env:TEMP }
  if (!(Test-Path -LiteralPath $Out)) {
    $Out = Join-Path $env:TEMP ('naruto_sub52w_failure_' + $RunId)
    New-Item -ItemType Directory -Path $Out -Force | Out-Null
  }
  Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Value $ErrText -Encoding UTF8
  foreach ($File in @('run.ps1','diagnose.py','README_KO.txt')) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot $File)) {
      Copy-Item -LiteralPath (Join-Path $PSScriptRoot $File) -Destination (Join-Path $Out $File) -Force -ErrorAction SilentlyContinue
    }
  }
} finally {
  try { Stop-Transcript | Out-Null } catch {}
  $ArchiveName = if ($Success) { $Name } else { $FailName }
  $Archive = Join-Path $LogRoot $ArchiveName
  try {
    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
    $Items = @(Get-ChildItem -LiteralPath $Out -Force)
    if (!$Items -or $Items.Count -eq 0) { throw 'No output files to archive' }
    Compress-Archive -LiteralPath ($Items | ForEach-Object { $_.FullName }) -DestinationPath $Archive -CompressionLevel Optimal -Force
    Write-Host ('UPLOAD ZIP: ' + $Archive)
  } catch {
    Write-Host ('ZIP failure: ' + ($_ | Out-String)) -ForegroundColor Red
    # Emergency plain ZIP with minimal failure trace, even if work dir missing.
    try {
      $Emergency = Join-Path $env:TEMP ('naruto_sub52w_emergency_' + $RunId)
      New-Item -ItemType Directory -Path $Emergency -Force | Out-Null
      Set-Content -LiteralPath (Join-Path $Emergency 'FAILURE.txt') -Value (($_ | Out-String) + "`nOUT=$Out") -Encoding UTF8
      Compress-Archive -LiteralPath (Join-Path $Emergency 'FAILURE.txt') -DestinationPath (Join-Path $LogRoot $FailName) -Force
      Write-Host ('UPLOAD FAILURE ZIP: ' + (Join-Path $LogRoot $FailName))
    } catch { Write-Host 'Emergency ZIP could not be created.' }
    $Success = $false
  }
}
if (!$Success) { exit 1 }
