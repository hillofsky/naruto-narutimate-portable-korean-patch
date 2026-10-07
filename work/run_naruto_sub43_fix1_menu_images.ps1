# Naruto PSP SUB43 - menu image translation build from exact SUB42
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "D:\narutimate portable"
$StageName  = "sub43_menu_images"
$StageDir   = Join-Path $Root "analysis\sub\$StageName"
$LogsDir    = Join-Path $Root "logs"
$OldRoot    = Join-Path $LogsDir "old"
$FailedRoot = Join-Path $LogsDir "failed"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript = Join-Path $LogsDir "naruto_sub43_fix1_menu_images_$Stamp.log"
$SuccessZip = Join-Path $LogsDir "naruto_sub43_fix1_menu_images_upload.zip"
$FailZip    = Join-Path $LogsDir "fail_naruto_sub43_fix1_menu_images_upload.zip"
$FinalIso   = Join-Path $StageDir "Naruto_KR_MOV06E_SUB43_MenuImages.iso"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null

# SUB43 is a reproducible stage. Remove only a prior SUB43 working/output directory,
# never SUB42 or any earlier authority stage.
if (Test-Path $StageDir) {
    $OldSmall = Join-Path (Join-Path $OldRoot $Stamp) $StageName
    New-Item -ItemType Directory -Force -Path $OldSmall | Out-Null
    Get-ChildItem $StageDir -File -ErrorAction SilentlyContinue | Where-Object {
        $_.Extension -notin @('.iso','.dat')
    } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $OldSmall $_.Name) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded = $false
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "Naruto SUB43 FIX1 - Menu Image Translation"
    Write-Host "Base: exact SUB42 ISO"
    Write-Host "Targets: modesel1 / option / charsel1 / mugen white+red / gauge white+red / setting"

    $ScriptDir = Split-Path -Parent $PSCommandPath
    $PyScript  = Join-Path $ScriptDir "build_sub43_menu_images.py"
    $Assets    = Join-Path $ScriptDir "sub43_assets"

    if (-not (Test-Path $PyScript)) { throw "SUB43 Python builder missing: $PyScript" }
    if (-not (Test-Path $Assets))   { throw "SUB43 assets folder missing: $Assets" }

    $Py = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $Py) { $Py = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $Py) { throw "Python not found." }

    & $Py.Source $PyScript --root $Root --assets $Assets
    if ($LASTEXITCODE -ne 0) { throw "SUB43 build failed. ExitCode=$LASTEXITCODE" }
    if (-not (Test-Path $FinalIso)) { throw "SUB43 final ISO missing: $FinalIso" }

    $Report = Join-Path $StageDir "SUB43_static_verification.json"
    if (-not (Test-Path $Report)) { throw "SUB43 verification report missing." }
    $J = Get-Content $Report -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($J.static_qa -ne "PASS") { throw "SUB43 static QA is not PASS." }
    if ([int]$J.patched_textures -ne 14) { throw "Expected 14 patched textures." }
    if ([int]$J.preserved_pmf_movies -ne 24) { throw "Expected 24 preserved PMFs." }

    $Succeeded = $true
    Write-Host ""
    Write-Host "SUB43 STATIC BUILD SUCCESS"
    Write-Host "Final ISO:"
    Write-Host "  $FinalIso"
    Write-Host "SHA256:"
    Write-Host "  $($J.final_iso_sha256)"
}
catch {
    Write-Host "!!!!!!!! SUB43 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
        "Naruto SUB43 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}

    $Pkg = Join-Path $StageDir "_upload_package"
    if (Test-Path $Pkg) { Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    function Copy-Diag {
        param([string]$Source,[string]$Dest)
        try {
            if (Test-Path $Source -PathType Leaf) {
                $Dst = Join-Path $Pkg $Dest
                $Parent = Split-Path $Dst -Parent
                if ($Parent) { New-Item -ItemType Directory -Force -Path $Parent | Out-Null }
                Copy-Item $Source $Dst -Force
            }
        } catch {}
    }

    foreach ($Name in @(
        "SUMMARY.txt",
        "SUB43_static_verification.json",
        "sub43_texture_patch.tsv",
        "sub43_resource_patch.tsv",
        "sub43_iso_core_verification.tsv",
        "sub43_movie_preservation.tsv",
        "replacement_manifest.json",
        "SUB43_targets.md",
        "SUB43_menu_preview.png",
        "SUB43_run.cmd",
        "FAILURE.txt"
    )) {
        Copy-Diag (Join-Path $StageDir $Name) $Name
    }

    Copy-Diag $Transcript ("logs\" + (Split-Path $Transcript -Leaf))
    if ($PSCommandPath) { Copy-Diag $PSCommandPath ("scripts\" + (Split-Path $PSCommandPath -Leaf)) }
    $SD = Split-Path -Parent $PSCommandPath
    Copy-Diag (Join-Path $SD "build_sub43_menu_images.py") "scripts\build_sub43_menu_images.py"

    $Zip = if ($Succeeded) { $SuccessZip } else { $FailZip }
    if (Test-Path $Zip) { Remove-Item $Zip -Force -ErrorAction SilentlyContinue }
    Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $Zip -Force
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if ($Succeeded) {
        Write-Host "Upload ZIP:"
        Write-Host "  $SuccessZip"

        # Open the final ISO for manual visual QA. The build does not claim runtime
        # verification until the user has inspected the affected menu screens.
        $PPSSPP = Join-Path $Root "tools\ppsspp-stage33-2314\PPSSPPWindows64.exe"
        if (Test-Path $PPSSPP) {
            Write-Host "Launching PPSSPP for menu visual QA..."
            Start-Process -FilePath $PPSSPP -ArgumentList @($FinalIso)
        } else {
            Write-Host "PPSSPP executable not found; use SUB43_run.cmd manually."
        }
    } else {
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }
}

if (-not $Succeeded) { exit 1 }
exit 0
