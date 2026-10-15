$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = "D:\narutimate portable"
$Stage = "naruto_sub52m_safe_boot_patch"
$Out = Join-Path $Root "analysis\sub\sub52m_safe_boot_patch"
$Logs = Join-Path $Root "logs"
$SuccessZip = Join-Path $Logs ($Stage + "_upload.zip")
$FailZip = Join-Path $Logs ("fail_" + $Stage + "_upload.zip")
$Now = Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript = Join-Path $Logs ($Stage + "_" + $Now + ".log")
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Successful = $false

New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== SUB52M SAFE BOOT STRING PATCH ==="
    Write-Host "Source SHA256 is strictly checked; no ISO image/atlas edits."
    Write-Host "Only one fixed-length C-string in BOOT/EBOOT is patched."

    $PyCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyCmd) {
        & $PyCmd.Source -3 -u (Join-Path $Bundle "sub52m_safe_boot_patch.py") --root $Root --bundle $Bundle
    }
    else {
        $PyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $PyCmd) { throw "Python 3 not found" }
        & $PyCmd.Source -u (Join-Path $Bundle "sub52m_safe_boot_patch.py") --root $Root --bundle $Bundle
    }
    if ($LASTEXITCODE -ne 0) { throw "SUB52M Python build failed (exit $LASTEXITCODE)" }

    $OutputISO = Join-Path $Out "Naruto_KR_MOV06E_SUB52M_SafeBoot.iso"
    if (-not (Test-Path -LiteralPath $OutputISO)) { throw "Expected output ISO missing: $OutputISO" }
    $Summary = Join-Path $Out "SUMMARY.json"
    if (-not (Test-Path -LiteralPath $Summary)) { throw "Static report missing" }
    $Report = Get-Content -Raw -LiteralPath $Summary | ConvertFrom-Json
    if ($Report.status -ne "STATIC_PASS_RUNTIME_UNVERIFIED") {
        throw "Static verification not PASS: $($Report.status)"
    }
    Write-Host "Generated ISO: $OutputISO"
    $Successful = $true
}
catch {
    @(
        "Naruto SUB52M build failed",
        "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Reason: $($_.Exception.Message)",
        ($_ | Out-String)
    ) | Set-Content -Path (Join-Path $Out "RUNNER_FAILURE.txt") -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    $Pack = Join-Path $Out "_upload"
    if (Test-Path $Pack) { Remove-Item -Recurse -Force $Pack }
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null

    foreach ($n in @("SUMMARY.txt","SUMMARY.json","FAILURE.txt","RUNNER_FAILURE.txt",
                     "exact_boot_patch_plan.tsv","reward_cstring_evidence.tsv")) {
        $file = Join-Path $Out $n
        if (Test-Path $file) { Copy-Item $file $Pack -Force }
    }
    if (Test-Path $Transcript) { Copy-Item $Transcript $Pack -Force }
    foreach ($n in @("sub52m_safe_boot_patch.py","run_naruto_sub52m_safe_boot_patch.ps1","combined_hangul_mapping_sub52d2.tsv","README_SUB52M.txt")) {
        $file = Join-Path $Bundle $n
        if (Test-Path $file) { Copy-Item $file $Pack -Force }
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = if ($Successful) { $SuccessZip } else { $FailZip }
    if (Test-Path $Zip) { Remove-Item -Force $Zip }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Pack,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false
    )
    Remove-Item -Recurse -Force $Pack
    Write-Host "UPLOAD_ZIP=$Zip"
}

if (-not $Successful) { exit 1 }

# Launch only the newly generated ISO. Do not control or terminate any existing PPSSPP process.
$OutputISO = Join-Path $Out "Naruto_KR_MOV06E_SUB52M_SafeBoot.iso"
$Candidates = @(
    "C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe",
    "D:\narutimate portable\PPSSPPWindows64.exe",
    "D:\narutimate portable\ppsspp\PPSSPPWindows64.exe"
)
$Emulator = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Emulator) {
    try {
        Write-Host "Launching exact ISO in PPSSPP: $OutputISO"
        $p=Start-Process -FilePath $Emulator -ArgumentList @("`"$OutputISO`"") -PassThru
        Write-Host "New PPSSPP PID=$($p.Id)"
    }
    catch {
        Write-Warning "Build succeeded; PPSSPP launch failed: $($_.Exception.Message)"
        Write-Host "Launch manually: $OutputISO"
    }
}
else {
    Write-Warning "PPSSPP executable not located; build still succeeded."
    Write-Host "Launch manually: $OutputISO"
}
