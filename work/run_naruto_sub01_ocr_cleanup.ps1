# Naruto PSP SUB01 - OCR cleanup / triage
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "D:\narutimate portable"
$StageName  = "sub01_ocr_cleanup"
$StageDir   = Join-Path $Root "analysis\sub\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_sub01_ocr_cleanup_$Stamp.log"
$UploadZip  = Join-Path $LogsDir "naruto_sub01_ocr_cleanup_upload.zip"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$FailedRoot,$OldRoot | Out-Null

$ArchiveDir = Join-Path (Join-Path $OldRoot $Stamp) "sub01_ocr_cleanup"

# Rotate previous SUB01 transient log and results, preserving prior work.
$oldLogs = @(Get-ChildItem $LogsDir -File -Filter "naruto_sub01_ocr_cleanup_*.log" -ErrorAction SilentlyContinue)
if ($oldLogs.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach ($f in $oldLogs) {
        Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force
    }
}
if (Test-Path $StageDir) {
    $oldItems = @(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if ($oldItems.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage = Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach ($item in $oldItems) {
            Move-Item $item.FullName $oldStage -Force
        }
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host (" " + $Text)
    Write-Host ("=" * 80)
}

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto SUB01 - OCR cleanup / triage"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    $Py = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $Py) { $Py = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $Py) { throw "Python을 찾지 못했습니다." }

    $ScriptDir = Split-Path -Parent $PSCommandPath
    $PyScript  = Join-Path $ScriptDir "naruto_sub01_ocr_cleanup.py"
    if (-not (Test-Path $PyScript)) {
        throw "naruto_sub01_ocr_cleanup.py를 찾지 못했습니다: $PyScript"
    }

    $InputCsv = Join-Path $Root "analysis\stage38e_full_ocr\ocr_2086_results.csv"
    if (-not (Test-Path $InputCsv)) {
        throw "Stage38E 결과를 찾지 못했습니다: $InputCsv"
    }

    Write-Host "Python : $($Py.Source)"
    Write-Host "Input  : $InputCsv"
    Write-Host "Output : $StageDir"

    Write-Section "1/3 - Build cleaned OCR + review queues"

    & $Py.Source $PyScript --root $Root --stage-dir $StageDir
    $exitCode=$LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "SUB01 Python cleanup failed. ExitCode=$exitCode"
    }

    Write-Section "2/3 - Collect review images"

    $ReviewTsv = Join-Path $StageDir "sub01_review_queue.tsv"
    $ReviewImageDir = Join-Path $StageDir "review_images"
    New-Item -ItemType Directory -Force -Path $ReviewImageDir | Out-Null

    $review = @(Import-Csv $ReviewTsv -Delimiter "`t")
    $copied=0
    $bytes=0L
    $maxFiles=100
    $maxBytes=20MB

    foreach ($r in $review) {
        if ($copied -ge $maxFiles -or $bytes -ge $maxBytes) { break }
        $src=[string]$r.source_path
        if (-not $src -or -not (Test-Path $src)) { continue }
        $fi=Get-Item $src
        if (($bytes + $fi.Length) -gt $maxBytes) { continue }

        $name=("g{0:D4}_{1}" -f [int]$r.global_index,$fi.Name)
        Copy-Item $fi.FullName (Join-Path $ReviewImageDir $name) -Force
        $copied++
        $bytes += $fi.Length
    }

    Write-Host "Review rows  : $($review.Count)"
    Write-Host "Images copied: $copied"
    Write-Host ("Image bytes  : {0:N2} MiB" -f ($bytes/1MB))

    Write-Section "3/3 - Package"

    $Succeeded=$true

} catch {
    $Succeeded=$false
    Write-Host ""
    Write-Host "!!!!!!!! SUB01 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_ | Out-String)

    @(
        "Naruto SUB01 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        $_.Exception.Message,
        "",
        ($_ | Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

} finally {
    try { Stop-Transcript | Out-Null } catch {}

    $PackageDir=Join-Path $StageDir "_upload_package"
    if (Test-Path $PackageDir) { Remove-Item $PackageDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

    foreach ($f in @(
        "SUMMARY.txt",
        "sub01_cleaned_2086.tsv",
        "sub01_cleaned_2086.csv",
        "sub01_review_queue.tsv",
        "sub01_japanese_rows.tsv",
        "speaker_frequency.tsv",
        "speaker_alias_report.tsv",
        "prelim_char_frequency.tsv",
        "prelim_unique_hangul.txt",
        "FAILURE.txt"
    )) {
        $src=Join-Path $StageDir $f
        if (Test-Path $src) { Copy-Item $src $PackageDir -Force }
    }

    if (Test-Path $Transcript) { Copy-Item $Transcript $PackageDir -Force }

    if ($PSCommandPath -and (Test-Path $PSCommandPath)) {
        Copy-Item $PSCommandPath $PackageDir -Force
    }
    $ScriptDir = Split-Path -Parent $PSCommandPath
    $PyScript = Join-Path $ScriptDir "naruto_sub01_ocr_cleanup.py"
    if (Test-Path $PyScript) { Copy-Item $PyScript $PackageDir -Force }

    $ReviewImageDir=Join-Path $StageDir "review_images"
    if (Test-Path $ReviewImageDir) {
        $imgs=@(Get-ChildItem $ReviewImageDir -File -ErrorAction SilentlyContinue)
        if ($imgs.Count -gt 0) {
            $dst=Join-Path $PackageDir "review_images"
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            foreach ($img in $imgs) { Copy-Item $img.FullName $dst -Force }
        }
    }

    if ($Succeeded) {
        if (Test-Path $UploadZip) {
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub01_ocr_cleanup_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB01 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    } else {
        $failedDir=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $failedDir | Out-Null
        Get-ChildItem $PackageDir -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $rel=$_.FullName.Substring($PackageDir.Length).TrimStart('\')
            $dst=Join-Path $failedDir $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $failedZip=Join-Path $failedDir "naruto_sub01_ocr_cleanup_failed_upload.zip"
        Compress-Archive -Path (Join-Path $failedDir "*") -DestinationPath $failedZip -Force
        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $failedZip"
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Succeeded) { exit 1 }
exit 0
