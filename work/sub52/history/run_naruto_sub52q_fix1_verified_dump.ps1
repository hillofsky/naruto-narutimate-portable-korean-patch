$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root = 'D:\narutimate portable'
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $LogRoot ('naruto_sub52q_fix1_verified_dump_'+$stamp+'.log')
Start-Transcript -Path $log -Force | Out-Null
try {
  Write-Host '=== SUB52Q FIX1 dump preflight ==='
  Write-Host '출력 PNG를 먼저 확인하므로 덤프 설정이 안 켜진 상태에서는 전투를 진행하지 않아.'
  $py = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($py) {
    & $py.Source -3 (Join-Path $Dir 'sub52q_fix1_verified_dump.py') --root $Root
  } else {
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $py) { throw 'Python missing' }
    & $py.Source (Join-Path $Dir 'sub52q_fix1_verified_dump.py') --root $Root
  }
  if ($LASTEXITCODE -ne 0) {
    throw "SUB52Q FIX1 diagnostic failed, exit=$LASTEXITCODE. Upload fail_ ZIP from D:\narutimate portable\logs."
  }
  Write-Host 'Result: D:\narutimate portable\logs\naruto_sub52q_fix1_verified_dump_upload.zip'
} finally {
  try {Stop-Transcript | Out-Null} catch {}
}
