$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root = 'D:\narutimate portable'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $LogRoot ("naruto_sub52q_fix2_existing_dumps_"+$Stamp+".log")
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host 'SUB52Q FIX2: Read-only existing texture scan. No game will launch.'
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 (Join-Path $Here 'qa_sub52q_fix2_existing_dump_scan.py') --root $Root
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){ throw 'Python not found' }
        & $py.Source (Join-Path $Here 'qa_sub52q_fix2_existing_dump_scan.py') --root $Root
    }
    if($LASTEXITCODE -ne 0){throw 'SUB52Q FIX2 scan failed. Upload fail_ ZIP in logs folder.'}
    Write-Host 'RESULT: D:\narutimate portable\logs\naruto_sub52q_fix2_existing_dumps_upload.zip'
} finally {
    try{Stop-Transcript | Out-Null}catch{}
}
