# Naruto PSP translation project - safe storage cleanup
# Keeps authoritative SUB36 baseline, SUB50 final ISO, font mappings and patcher tools.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = "PROJECT_ROOT"
$Analysis = Join-Path $Root "analysis"
$SubRoot = Join-Path $Analysis "sub"
$Logs = Join-Path $Root "logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$CleanupLog = Join-Path $Logs "naruto_storage_cleanup_$Stamp.txt"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$script:Freed = [int64]0
$script:Deleted = New-Object System.Collections.Generic.List[string]

function Get-PathSize([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return [int64]0 }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) { return [int64]$item.Length }
    $sum = [int64]0
    Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
        ForEach-Object { $sum += [int64]$_.Length }
    return $sum
}

function Remove-Tracked([string]$Path, [string]$Reason) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $size = Get-PathSize $Path
    Write-Host ("DELETE {0:N2} GB  {1}" -f ($size / 1GB), $Path)
    Write-Host ("       reason: {0}" -f $Reason)
    Add-Content -LiteralPath $CleanupLog -Value ("DELETE`t{0}`t{1}`t{2}" -f $size,$Path,$Reason)
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    $script:Freed += $size
    $script:Deleted.Add($Path) | Out-Null
}

function Remove-MatchingFiles([string]$Dir, [string[]]$Patterns, [string]$Reason) {
    if (-not (Test-Path -LiteralPath $Dir)) { return }
    foreach ($pat in $Patterns) {
        Get-ChildItem -LiteralPath $Dir -Recurse -Force -File -Filter $pat -ErrorAction SilentlyContinue |
            ForEach-Object {
                Remove-Tracked $_.FullName $Reason
            }
    }
}

Write-Host "============================================================"
Write-Host " Naruto PSP Translation - Safe Storage Cleanup"
Write-Host "============================================================"
Write-Host ""
Write-Host "PRESERVE:"
Write-Host "  - SUB36 final baseline ISO"
Write-Host "  - SUB50 final authoritative ISO"
Write-Host "  - analysis\shared"
Write-Host "  - analysis\sub\sub40_tutorial (17-glyph mapping)"
Write-Host "  - analysis\stage14 / stage15 patchers"
Write-Host "  - tools / generated_macros"
Write-Host ""

Add-Content -LiteralPath $CleanupLog -Value "Naruto storage cleanup $Stamp"
Add-Content -LiteralPath $CleanupLog -Value "ROOT=$Root"

# 1) Collection stages are reproducible and can be very large.
Remove-Tracked (Join-Path $SubRoot "sub51a_full_japanese_sweep") `
    "SUB51A inventory is already uploaded/reviewed and is superseded."
Remove-Tracked (Join-Path $SubRoot "sub51b_exact_source_collection") `
    "Remove partial/failed SUB51B collection so it can be recreated cleanly."

# 2) Remove large build payloads from superseded late stages, but keep reports/scripts/screenshots.
#    SUB40 is excluded because new_glyph_mapping.tsv lives there.
$OldStageDirs = Get-ChildItem -LiteralPath $SubRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        if ($_.Name -match '^sub(\d+)') {
            $n=[int]$Matches[1]
            return ($n -ge 37 -and $n -le 49 -and $n -ne 40)
        }
        return $false
    }

foreach ($d in $OldStageDirs) {
    Remove-MatchingFiles $d.FullName @("*.iso") `
        "Superseded stage ISO; SUB50 is current authority."
    Remove-MatchingFiles $d.FullName @("*.dat","*.idx") `
        "Reproducible intermediate DAT/IDX from superseded stage."
    # Large exact BOOT copies are small, so preserve them for diagnostics.
}

# 3) SUB50: preserve the final ISO and reports, remove only reconstructible host build copies.
$Sub50 = Join-Path $SubRoot "sub50_mugen_atlas_surgical_restore"
if (Test-Path -LiteralPath $Sub50) {
    Get-ChildItem -LiteralPath $Sub50 -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '\.(dat|idx)$' -or
            $_.Name -match '^source_.*\.(dat|idx|bin)$' -or
            $_.Name -match '^donor_.*\.(dat|idx|bin)$' -or
            $_.Name -eq 'BOOT.bin'
        } |
        ForEach-Object {
            Remove-Tracked $_.FullName `
                "SUB50 host-side build copy; final SUB50 ISO is preserved and SUB51B extracts from it."
        }
}

# 4) Old MOV-stage ISO copies are superseded by the verified SUB36 baseline.
$MovRoot = Join-Path $Analysis "mov"
if (Test-Path -LiteralPath $MovRoot) {
    Remove-MatchingFiles $MovRoot @("*.iso") `
        "Old movie-stage ISO; translated PMFs are already carried by SUB36/SUB50."
}

# 5) Remove old late-stage upload ZIPs/logs. Keep SUB50 evidence.
if (Test-Path -LiteralPath $Logs) {
    Get-ChildItem -LiteralPath $Logs -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -match '^(fail_)?naruto_sub4[1-9].*\.(zip|log)$') -or
            ($_.Name -match '^(fail_)?naruto_sub51a.*\.(zip|log)$') -or
            ($_.Name -match '^(fail_)?naruto_sub51b.*\.(zip|log)$')
        } |
        ForEach-Object {
            Remove-Tracked $_.FullName "Superseded/reproducible stage log or upload ZIP."
        }
}

# 6) Remove abandoned upload staging folders.
Get-ChildItem -LiteralPath $SubRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "_upload" } |
    Sort-Object FullName -Descending |
    ForEach-Object {
        Remove-Tracked $_.FullName "Temporary upload staging directory."
    }

# 7) Downloads: remove old helper ZIPs only; keep current SUB51B package.
$Downloads = Join-Path $HOME "Downloads"
if (Test-Path -LiteralPath $Downloads) {
    Get-ChildItem -LiteralPath $Downloads -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "run_naruto_sub4*.zip" -or
            $_.Name -like "run_naruto_sub50*.zip" -or
            $_.Name -like "run_naruto_sub51a*.zip"
        } |
        ForEach-Object {
            Remove-Tracked $_.FullName "Old executable bundle; current project state is already built."
        }
}

# Report protected authoritative files.
$Protected = @(
    (Join-Path $Analysis "integrated\sub36_semantic_qa\output\Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"),
    (Join-Path $Sub50 "Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso"),
    (Join-Path $Analysis "shared\event_font_hangul_mapping.tsv"),
    (Join-Path $SubRoot "sub40_tutorial\new_glyph_mapping.tsv"),
    (Join-Path $Analysis "stage14\naruto_patcher.py"),
    (Join-Path $Analysis "stage15\stage15_iso_patcher.py")
)

Write-Host ""
Write-Host "---------------- PRESERVED CHECK ----------------"
foreach ($p in $Protected) {
    if (Test-Path -LiteralPath $p) {
        Write-Host "[KEEP] $p"
        Add-Content -LiteralPath $CleanupLog -Value ("KEEP`t{0}" -f $p)
    } else {
        Write-Host "[WARN MISSING] $p"
        Add-Content -LiteralPath $CleanupLog -Value ("WARN_MISSING`t{0}" -f $p)
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host ("Cleanup complete. Approx. freed: {0:N2} GB" -f ($script:Freed / 1GB))
Write-Host ("Deleted objects: {0}" -f $script:Deleted.Count)
Write-Host "Log: $CleanupLog"
Write-Host "============================================================"

Add-Content -LiteralPath $CleanupLog -Value ("FREED_BYTES={0}" -f $script:Freed)
Add-Content -LiteralPath $CleanupLog -Value ("FREED_GB={0:N3}" -f ($script:Freed / 1GB))
Add-Content -LiteralPath $CleanupLog -Value ("DELETED_OBJECTS={0}" -f $script:Deleted.Count)
