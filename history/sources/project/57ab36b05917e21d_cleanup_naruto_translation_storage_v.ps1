# Naruto PSP translation storage cleanup v2
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="PROJECT_ROOT"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Report=Join-Path $Logs "naruto_storage_cleanup_v2_$Stamp.txt"
$Transcript=Join-Path $Logs "naruto_storage_cleanup_v2_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

# Critical artifacts that MUST survive.
$KeepExact = @(
    (Join-Path $Root "analysis\integrated\sub36_semantic_qa\output\Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"),
    (Join-Path $Root "analysis\sub\sub51d_full_text_apply\Naruto_KR_MOV06E_SUB51D_FullText.iso")
)

$KeepDirs = @(
    (Join-Path $Root "analysis\shared"),
    (Join-Path $Root "analysis\sub\sub40_tutorial"),
    (Join-Path $Root "analysis\stage14"),
    (Join-Path $Root "analysis\stage15"),
    (Join-Path $Root "tools")
)

function Is-UnderKeepDir([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path).TrimEnd("\")
    foreach($d in $KeepDirs){
        if(Test-Path $d){
            $kd=[IO.Path]::GetFullPath($d).TrimEnd("\")
            if($full.Equals($kd,[StringComparison]::OrdinalIgnoreCase) -or
               $full.StartsWith($kd+"\",[StringComparison]::OrdinalIgnoreCase)){
                return $true
            }
        }
    }
    return $false
}

function Is-KeepExact([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path)
    foreach($p in $KeepExact){
        if($full.Equals([IO.Path]::GetFullPath($p),[StringComparison]::OrdinalIgnoreCase)){
            return $true
        }
    }
    return $false
}

$Deleted = New-Object System.Collections.Generic.List[object]
$Skipped = New-Object System.Collections.Generic.List[object]
$Freed=[int64]0

function Remove-FileSafe([string]$Path,[string]$Reason){
    if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){ return }
    if(Is-KeepExact $Path -or Is-UnderKeepDir $Path){
        $Skipped.Add([pscustomobject]@{Path=$Path;Reason="PROTECTED"}) | Out-Null
        return
    }
    $f=Get-Item -LiteralPath $Path -Force
    $size=[int64]$f.Length
    Remove-Item -LiteralPath $Path -Force
    $script:Freed += $size
    $Deleted.Add([pscustomobject]@{Path=$Path;Bytes=$size;Reason=$Reason}) | Out-Null
}

function Remove-DirSafe([string]$Path,[string]$Reason){
    if(-not (Test-Path -LiteralPath $Path -PathType Container)){ return }
    if(Is-UnderKeepDir $Path){
        $Skipped.Add([pscustomobject]@{Path=$Path;Reason="PROTECTED_DIR"}) | Out-Null
        return
    }
    $files=Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue
    [int64]$size=0
    foreach($f in $files){ $size += [int64]$f.Length }
    Remove-Item -LiteralPath $Path -Recurse -Force
    $script:Freed += $size
    $Deleted.Add([pscustomobject]@{Path=$Path;Bytes=$size;Reason=$Reason}) | Out-Null
}

Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host "=== Naruto translation storage cleanup v2 ==="
    Write-Host "Critical final ISOs preserved:"
    foreach($p in $KeepExact){ Write-Host " KEEP $p" }

    # 1. Delete every superseded ISO under analysis, except SUB36 and SUB51D.
    $Analysis=Join-Path $Root "analysis"
    if(Test-Path $Analysis){
        Get-ChildItem -LiteralPath $Analysis -Recurse -Force -File -Filter *.iso -ErrorAction SilentlyContinue |
            ForEach-Object {
                if(-not (Is-KeepExact $_.FullName)){
                    Remove-FileSafe $_.FullName "superseded_analysis_iso"
                }
            }
    }

    # 2. Reconstructible DAT/IDX copies inside analysis.
    if(Test-Path $Analysis){
        Get-ChildItem -LiteralPath $Analysis -Recurse -Force -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @(".dat",".idx") } |
            ForEach-Object {
                if(-not (Is-UnderKeepDir $_.FullName)){
                    Remove-FileSafe $_.FullName "reconstructible_dat_idx"
                }
            }
    }

    # 3. Old SUB51 discovery/candidate collections are fully consumed into SUB51D.
    foreach($d in @(
        "analysis\sub\sub51a_full_japanese_sweep",
        "analysis\sub\sub51b_exact_source_collection",
        "analysis\sub\sub51c_fix1_chatgpt_candidates",
        "analysis\sub\sub51c_chatgpt_translation_validation",
        "analysis\sub\sub51e_ui_style_source_export"
    )){
        Remove-DirSafe (Join-Path $Root $d) "consumed_or_failed_stage"
    }

    # 4. Any abandoned _work/_upload directories under SUB stages.
    $SubRoot=Join-Path $Root "analysis\sub"
    if(Test-Path $SubRoot){
        Get-ChildItem -LiteralPath $SubRoot -Recurse -Force -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("_work","_upload","temp","tmp","cache") } |
            Sort-Object FullName -Descending |
            ForEach-Object { Remove-DirSafe $_.FullName "temporary_stage_dir" }
    }

    # 5. Large old SUB collection ZIPs/log bundles in logs.
    if(Test-Path $Logs){
        Get-ChildItem -LiteralPath $Logs -Force -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^((fail_)?naruto_sub(3[7-9]|4[0-9]|50|51[abc]?|51c_fix1|51c_chatgpt).*\.zip)$' -or
                $_.Name -eq 'naruto_sub51b_exact_source_collection_upload.zip'
            } |
            ForEach-Object { Remove-FileSafe $_.FullName "old_sub_upload_bundle" }
    }

    # 6. Old MOV-stage ISO copies are redundant because all 24 PMFs are carried in SUB51D.
    $Mov=Join-Path $Root "analysis\mov"
    if(Test-Path $Mov){
        Get-ChildItem -LiteralPath $Mov -Recurse -Force -File -Filter *.iso -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-FileSafe $_.FullName "superseded_mov_iso" }
    }

    # 7. Keep PMFs themselves, but remove common huge transcoding leftovers.
    if(Test-Path $Mov){
        Get-ChildItem -LiteralPath $Mov -Recurse -Force -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -in @(".avi",".mkv",".mov",".wav",".yuv",".raw") -or
                $_.Name -match '\.(h264|264|pcm)$'
            } |
            ForEach-Object { Remove-FileSafe $_.FullName "reconstructible_movie_intermediate" }
    }

    # 8. Old macro screenshots: retain 3 newest top-level sessions only.
    $Macro=Join-Path $Root "macro_screenshots"
    if(Test-Path $Macro){
        $dirs=@(Get-ChildItem -LiteralPath $Macro -Force -Directory -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending)
        if($dirs.Count -gt 3){
            $dirs | Select-Object -Skip 3 |
                ForEach-Object { Remove-DirSafe $_.FullName "old_macro_screenshot_session" }
        }
    }

    # 9. Old logs archive.
    Remove-DirSafe (Join-Path $Logs "old") "old_log_archive"

    # 10. Failed SUB51E extracted runner is obsolete.
    foreach($f in @(
        "run_naruto_sub51e_ui_style_source_export.ps1"
    )){
        Remove-FileSafe (Join-Path $Root $f) "obsolete_failed_runner"
    }

    # Build report.
    $freeNow=(Get-PSDrive -Name D).Free
    $gb=[math]::Round($Freed/1GB,2)
    $freeGb=[math]::Round($freeNow/1GB,2)

    $lines=New-Object System.Collections.Generic.List[string]
    $lines.Add("Naruto storage cleanup v2")
    $lines.Add("Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $lines.Add("FreedBytes=$Freed")
    $lines.Add("FreedGB=$gb")
    $lines.Add("DFreeGB_After=$freeGb")
    $lines.Add("")
    $lines.Add("PRESERVED:")
    foreach($p in $KeepExact){$lines.Add("  $p")}
    foreach($p in $KeepDirs){$lines.Add("  $p")}
    $lines.Add("")
    $lines.Add("DELETED:")
    foreach($x in $Deleted){
        $mb=[math]::Round(([int64]$x.Bytes)/1MB,1)
        $lines.Add(("  {0} MB | {1} | {2}" -f $mb,$x.Reason,$x.Path))
    }
    $lines | Set-Content $Report -Encoding UTF8

    Write-Host ""
    Write-Host ("Cleanup complete. Freed: {0} GB" -f $gb)
    Write-Host ("D: free after cleanup: {0} GB" -f $freeGb)
    Write-Host "Report: $Report"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
