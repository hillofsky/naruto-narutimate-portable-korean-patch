$ErrorActionPreference="Stop"
$Root="D:\narutimate portable"
$LogDir=Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogDir ("naruto_sub51o_menu_hint_discovery_"+$Stamp+".log")
Start-Transcript -Path $Transcript -Force
try {
    Set-Location $Root
    Write-Host "=== SUB51O MENU/HINT DISCOVERY ==="
    Write-Host "Read-only discovery. No ISO/game asset modification."
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 ".\qa_sub51o_menu_hint_discovery.py"
    } else {
        & python ".\qa_sub51o_menu_hint_discovery.py"
    }
    if ($LASTEXITCODE -ne 0) { throw "Python discovery failed: exit $LASTEXITCODE" }
}
finally {
    Stop-Transcript
}
