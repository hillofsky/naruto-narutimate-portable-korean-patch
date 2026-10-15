$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root='D:\narutimate portable'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot=Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$Transcript=Join-Path $LogRoot ('naruto_sub52q_live_texture_probe_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'.log')
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== SUB52Q isolated runtime texture provenance ==='
    Write-Host 'No ISO modifications, no commands sent to any existing PPSSPP instances.'
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 (Join-Path $ScriptDir 'sub52q_live_texture_probe.py') --root $Root
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw 'Python missing'}
        & $py.Source (Join-Path $ScriptDir 'sub52q_live_texture_probe.py') --root $Root
    }
    if($LASTEXITCODE -ne 0){ throw "SUB52Q failed with exit code $LASTEXITCODE. Upload fail_ zip from D:\narutimate portable\logs." }
    Write-Host 'Success ZIP: D:\narutimate portable\logs\naruto_sub52q_live_texture_probe_upload.zip'
} finally {
    try{Stop-Transcript|Out-Null}catch{}
}
