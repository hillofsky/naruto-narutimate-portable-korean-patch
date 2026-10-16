# Naruto PSP MOV01 wrapper
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "mov01_frame_matching"
$StageDir   = Join-Path $Root "analysis\mov\$StageName"
$LogsDir    = Join-Path $Root "logs"
$OldRoot    = Join-Path $LogsDir "old"
$FailedRoot = Join-Path $LogsDir "failed"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript = Join-Path $LogsDir "naruto_mov01_frame_matching_$Stamp.log"
$UploadZip  = Join-Path $LogsDir "naruto_mov01_frame_matching_upload.zip"
$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) $StageName

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null

# Rotate old MOV01 transient logs/results; retain fingerprint cache to save time.
$oldLogs = @(Get-ChildItem $LogsDir -File -Filter "naruto_mov01_frame_matching_*.log" -ErrorAction SilentlyContinue)
if ($oldLogs.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach ($f in $oldLogs) { Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force }
}
if (Test-Path $StageDir) {
    $cache = Join-Path $StageDir "fingerprint_cache"
    $toArchive = @(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ne $cache })
    if ($toArchive.Count -gt 0) {
        $oldStage = Join-Path $ArchiveDir "previous_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach ($x in $toArchive) { Move-Item $x.FullName $oldStage -Force }
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

Start-Transcript -Path $Transcript -Force | Out-Null
$Success = $false
try {
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV01 - PMF <-> YouTube coarse frame matching"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Stage   : $StageDir"

    $Py = $null
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $Py = @($pyLauncher.Source,"-3")
    } else {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
        if ($python) { $Py = @($python.Source) }
    }
    if (-not $Py) { throw "Python 3를 찾지 못했습니다." }

    $Script = Join-Path $Root "run_naruto_mov01_frame_matching.py"
    if (-not (Test-Path $Script)) { throw "Python script not found: $Script" }

    Write-Host "Python  : $($Py -join ' ')"
    Write-Host ""

    if ($Py.Count -eq 2) {
        & $Py[0] $Py[1] $Script
    } else {
        & $Py[0] $Script
    }
    $ec = $LASTEXITCODE
    if ($ec -ne 0) { throw "MOV01 Python exited with code $ec" }

    $Success = $true
} catch {
    Write-Host ""
    Write-Host "!!!!!!!! MOV01 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)
} finally {
    try { Stop-Transcript | Out-Null } catch {}

    $Pkg = Join-Path $StageDir "_upload_package"
    if (Test-Path $Pkg) { Remove-Item $Pkg -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach ($name in @(
        "SUMMARY.txt","source_candidates.tsv","selected_sources.txt",
        "pmf_source_mapping_coarse.tsv","pmf_source_mapping_coarse.csv",
        "verification_manifest.tsv","FAILURE.txt","source_override.txt"
    )) {
        $p = Join-Path $StageDir $name
        if (Test-Path $p) { Copy-Item $p $Pkg -Force }
    }
    if (Test-Path $Transcript) { Copy-Item $Transcript $Pkg -Force }

    $Verify = Join-Path $StageDir "verification"
    if (Test-Path $Verify) {
        $dst = Join-Path $Pkg "verification"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Get-ChildItem $Verify -File -Filter "*.jpg" -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName $dst -Force }
    }

    foreach ($s in @(
        (Join-Path $Root "run_naruto_mov01_frame_matching.ps1"),
        (Join-Path $Root "run_naruto_mov01_frame_matching.py")
    )) {
        if (Test-Path $s) { Copy-Item $s $Pkg -Force }
    }

    if ($Success) {
        if (Test-Path $UploadZip) {
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov01_frame_matching_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV01 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    } else {
        $fd = Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Get-ChildItem $Pkg -File -Recurse | ForEach-Object {
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_mov01_frame_matching_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV01 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if (-not $Success) { exit 1 }
exit 0
