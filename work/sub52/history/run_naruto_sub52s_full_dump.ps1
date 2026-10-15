$ErrorActionPreference = 'Stop'
$Root = 'D:\narutimate portable'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
Write-Host 'SUB52S read-only export: copying existing Naruto texture PNGs into one small ZIP.'
Write-Host 'No PPSSPP launch, ISO writing, file deletion or dependency installation.'
$PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($PyLauncher) {
    & $PyLauncher.Source -3 (Join-Path $ScriptDir 'sub52s_collect_full_existing_dump.py') --root $Root
} else {
    $Python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $Python) { throw 'Python 3 not found in PATH.' }
    & $Python.Source (Join-Path $ScriptDir 'sub52s_collect_full_existing_dump.py') --root $Root
}
if ($LASTEXITCODE -ne 0) {
    throw 'SUB52S export failed; upload the fail_naruto_sub52s_full_existing_dump_upload.zip from D:\narutimate portable\logs.'
}
Write-Host 'SUB52S export completed. Upload naruto_sub52s_full_existing_dump_upload.zip from D:\narutimate portable\logs.'
