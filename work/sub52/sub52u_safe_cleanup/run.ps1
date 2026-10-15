#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Apply','Preview')]
    [string]$Mode = 'Apply',
    [int]$MinAgeHours = 8
)

$ErrorActionPreference = 'Stop'
$Root = 'D:\narutimate portable'
$SubRoot = Join-Path $Root 'analysis\sub'
$LogsRoot = Join-Path $Root 'logs'
$TName = 'Naruto_KR_MOV06E_SUB52T_GaugeHUD_Compact.iso'
$UName = 'Naruto_KR_MOV06E_SUB52U_HUDRemaining_Compact.iso'
$TPath = Join-Path $SubRoot ("sub52t_gauge_hud_compact\" + $TName)
$UPath = Join-Path $SubRoot ("sub52u_hud_remaining\" + $UName)
$ExpectedTSize = 4288798720L
$ExpectedTSHA = 'c702a4545cd7fae73f7545f1892fc99b164de2ee884a9c2b30286f11291bf21d'
$TimeTag = Get-Date -Format 'yyyyMMdd_HHmmss'
$Session = Join-Path $LogsRoot ("naruto_sub52u_safe_cleanup_" + $TimeTag)
$ZipSuccess = Join-Path $LogsRoot ('naruto_sub52u_safe_cleanup_upload.zip')
$ZipFailure = Join-Path $LogsRoot ('fail_naruto_sub52u_safe_cleanup_upload.zip')
$ScriptSelf = $MyInvocation.MyCommand.Path
$Actions = New-Object 'System.Collections.Generic.List[object]'
$Protected = New-Object 'System.Collections.Generic.List[object]'
$Problems = New-Object 'System.Collections.Generic.List[string]'
$Warns = New-Object 'System.Collections.Generic.List[string]'
$bytesRemoved = 0L
$removedCount = 0
$candidates = 0
$initialFree = 0L
$finalFree = 0L
$transcriptRunning = $false
$fatal = $null
$isoCleanupAllowed = $false

function Record([string]$Action,[string]$Path,[long]$Bytes,[string]$Reason) {
    $script:Actions.Add([pscustomobject]@{
        Action = $Action; Bytes = $Bytes; Reason = $Reason; Path = $Path
    })
}
function Protect([string]$Path,[string]$Reason) {
    $script:Protected.Add([pscustomobject]@{ Path = $Path; Reason = $Reason })
}
function Is-Reparse([System.IO.FileSystemInfo]$Item) {
    return (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}
function Get-FreeBytes {
    $drv = New-Object System.IO.DriveInfo('D:\')
    return [long]$drv.AvailableFreeSpace
}
function Delete-FileSafe([System.IO.FileInfo]$File,[string]$Reason) {
    $script:candidates++
    if (-not $File.Exists) { Record 'SKIP' $File.FullName 0 'file disappeared'; return }
    if (Is-Reparse $File) { Record 'SKIP' $File.FullName $File.Length 'reparse point'; return }
    if ($File.FullName -ieq $script:TPath -or $File.FullName -ieq $script:UPath) {
        Record 'KEEP' $File.FullName $File.Length 'protected tested checkpoint'; return
    }
    if ($Mode -eq 'Preview') {
        Record 'PREVIEW' $File.FullName $File.Length $Reason
        return
    }
    try {
        $sz=[long]$File.Length
        Remove-Item -LiteralPath $File.FullName -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $File.FullName -PathType Leaf) {
            throw 'File remained after Remove-Item'
        }
        $script:bytesRemoved += $sz
        $script:removedCount++
        Record 'DELETED' $File.FullName $sz $Reason
        Write-Host ("Deleted {0:N2} GiB  {1}" -f ($sz/1GB), $File.FullName)
    } catch {
        $msg = 'DELETE_FAILED: ' + $File.FullName + ' :: ' + $_.Exception.Message
        $script:Problems.Add($msg)
        Record 'ERROR' $File.FullName $File.Length $_.Exception.Message
        Write-Warning $msg
    }
}
function Get-SafeFiles([string]$Folder,[string]$NameFilter) {
    # Do not traverse junctions or symbolic-link directories.
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($Folder)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($f in @(Get-ChildItem -LiteralPath $current -File -Force -Filter $NameFilter -ErrorAction Stop)) {
            if (-not (Is-Reparse $f)) { Write-Output $f }
        }
        foreach ($d in @(Get-ChildItem -LiteralPath $current -Directory -Force -ErrorAction Stop)) {
            if (-not (Is-Reparse $d)) { $pending.Push($d.FullName) }
        }
    }
}
function Get-StageKey([string]$FolderName) {
    $m = [regex]::Match($FolderName,'(?i)^sub(?<n>\d{1,3})(?<s>[a-z])(?:_|$)')
    if (-not $m.Success) { return $null }
    return [pscustomobject]@{
        N = [int]$m.Groups['n'].Value
        S = $m.Groups['s'].Value.ToUpperInvariant()
    }
}
function Is-ProtectedStage($Stage) {
    if ($Stage.N -ge 53) { return $true }
    if ($Stage.N -eq 52 -and ($Stage.S -in @('N','T','U','V','W','X','Y','Z'))) { return $true }
    return $false
}
function Safe-OldISO([System.IO.FileInfo]$File, $Stage) {
    # Only generated Korean patch builds inside an old, stage-qualified subfolder.
    $m = [regex]::Match($File.Name,'(?i)^Naruto_KR_.*_SUB(?<n>\d{1,3})(?<s>[a-z])(?:_.*)?\.iso$')
    if (-not $m.Success) { return $false }
    if (([int]$m.Groups['n'].Value) -ne $Stage.N) { return $false }
    if ($m.Groups['s'].Value.ToUpperInvariant() -ne $Stage.S) { return $false }
    return $true
}
function Is-Aged([System.IO.FileSystemInfo]$Item,[int]$Hours) {
    return ($Item.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddHours(-$Hours))
}

try {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Naruto project root missing: $Root"
    }
    if (-not (Test-Path -LiteralPath $SubRoot -PathType Container)) {
        throw "Sub analysis folder missing: $SubRoot"
    }
    New-Item -ItemType Directory -Path $LogsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $Session -Force | Out-Null
    try { Start-Transcript -Path (Join-Path $Session 'console_transcript.txt') -Force | Out-Null; $transcriptRunning=$true } catch {
        $Warns.Add('Transcript could not start: ' + $_.Exception.Message)
    }
    Write-Host "==== NARUTO SUB52U SAFE CLEANUP ===="
    Write-Host "Root: $Root"
    Write-Host "Mode: $Mode; MinAgeHours: $MinAgeHours"
    $initialFree=Get-FreeBytes
    Write-Host ("Initial D: free {0:N2} GiB" -f ($initialFree/1GB))

    # Fail closed unless both checkpoint ISO files are present.
    foreach ($path in @($TPath, $UPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Protected ISO not found, refusing cleanup: $path"
        }
        $f=Get-Item -LiteralPath $path
        if (Is-Reparse $f) { throw "Protected ISO is a reparse point: $path" }
        if ($f.Length -lt 4000000000L) { throw "Protected ISO unexpectedly small, refusing cleanup: $path" }
        Protect $path 'Keep: SUB52T stable baseline / SUB52U latest work'
    }
    $tSize=(Get-Item -LiteralPath $TPath).Length
    if ($tSize -ne $ExpectedTSize) {
        throw "SUB52T size mismatch: expected $ExpectedTSize actual $tSize; no cleanup"
    }
    Write-Host 'Checking SUB52T known-good SHA256 (read only)...'
    $tHash=(Get-FileHash -LiteralPath $TPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($tHash -cne $ExpectedTSHA) {
        throw "SUB52T hash mismatch: $tHash; no cleanup"
    }
    Write-Host 'SUB52T SHA256 PASS'
    Protect (Join-Path $SubRoot 'sub52n*') 'Keep: SUB52N RewardSafe source/fallback'
    Protect (Join-Path $Root 'logs') 'Keep ALL cumulative logs, archives, scripts and project records'
    Protect $Root 'Keep original ISO, saves, MOV/PMF, assets and source files'

    # Respect multiple independently running emulators. Do not stop/control any instance.
    $ppsspp=@()
    try {
        $ppsspp=@(Get-CimInstance Win32_Process -Filter "Name LIKE 'PPSSPP%'" -ErrorAction Stop)
    } catch {
        $Warns.Add('PPSSPP process enumeration failed. ISO cleanup disabled: ' + $_.Exception.Message)
        $ppsspp=@('UNKNOWN')
    }
    if ($ppsspp.Count -gt 0) {
        $Warns.Add("PPSSPP instance(s) active/unknown ($($ppsspp.Count)). All ISO deletions disabled to protect active games.")
        $isoCleanupAllowed=$false
    } else {
        $isoCleanupAllowed=$true
    }

    $stageDirs = @(Get-ChildItem -LiteralPath $SubRoot -Directory -Force -ErrorAction Stop | Where-Object { -not (Is-Reparse $_) })
    foreach ($dir in $stageDirs) {
        $stage=Get-StageKey $dir.Name
        if ($null -eq $stage) { continue }
        if (Is-ProtectedStage $stage) {
            Protect $dir.FullName 'Keep current checkpoint stage or newer stage'
            continue
        }
        $list=@()
        try {
            # Enumerate stage output ISOs only; do not alter resources, DAT/IDX/BOOT, PMF, or saves.
            $list=@(Get-SafeFiles $dir.FullName '*.iso')
        } catch {
            $Problems.Add("ENUM_ISO_FAILED: $($dir.FullName) :: $($_.Exception.Message)")
            continue
        }
        foreach ($iso in $list) {
            if (Is-Reparse $iso) { Record 'KEEP' $iso.FullName $iso.Length 'reparse file'; continue }
            if (-not (Safe-OldISO $iso $stage)) {
                Record 'KEEP' $iso.FullName $iso.Length 'not a recognized generated stage ISO'; continue
            }
            if (-not (Is-Aged $iso $MinAgeHours)) {
                Record 'KEEP' $iso.FullName $iso.Length "less than $MinAgeHours hours old"; continue
            }
            if (-not $isoCleanupAllowed) {
                Record 'KEEP' $iso.FullName $iso.Length 'PPSSPP running or process scan unavailable'; continue
            }
            Delete-FileSafe $iso 'obsolete translated stage ISO; original and 52N/T/U protected'
        }
    }

    # Rebuildable temporary output files only; excludes arbitrary .tmp files and all non-stage folders.
    foreach ($dir in $stageDirs) {
        $stage=Get-StageKey $dir.Name
        if ($null -eq $stage -or (Is-ProtectedStage $stage)) { continue }
        $tempfiles=@()
        try {
            $tempfiles=@(Get-SafeFiles $dir.FullName '*' |
                Where-Object { $_.Name -match '(?i)(\.iso\.(?:tmp|part|partial|download)$|\.(?:partial|incomplete|building)\.iso$)' })
        } catch {
            $Problems.Add("ENUM_TEMP_FAILED: $($dir.FullName) :: $($_.Exception.Message)")
            continue
        }
        foreach ($f in $tempfiles) {
            if (Is-Aged $f ([Math]::Max(36,$MinAgeHours))) {
                Delete-FileSafe $f 'stale incomplete ISO build fragment'
            } else {
                Record 'KEEP' $f.FullName $f.Length 'incomplete ISO fragment too recent'
            }
        }
    }
    # Note: No general directory removal, no snapshots/texture dump cleanup,
    # no zip/log/save/PMF/CCS/DAT/IDX/BOOT/PNG/JPG cleanup.
}
catch {
    $fatal=$_.Exception.ToString()
    $Problems.Add('FATAL: ' + $fatal)
    Write-Host ("FATAL: " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    if (Test-Path -LiteralPath $Session -PathType Container) {
        try { $finalFree=Get-FreeBytes } catch { $Warns.Add('Final disk free check failed.') }
        $failed=($Problems.Count -gt 0)
        $summary = @(
            'NARUTO PSP SUB52U CLEANUP',
            'Timestamp: ' + (Get-Date -Format 'o'),
            'Mode: ' + $Mode,
            'Protected SUB52T: ' + $TPath,
            'Protected SUB52U: ' + $UPath,
            'Protected SUB52N: all sub52n* folders',
            'All original ISO/save/PMF/assets/code/logs retained',
            ('Running/unknown PPSSPP detected: ' + [string](-not $isoCleanupAllowed)),
            ('Candidates: ' + $candidates),
            ('Removed files: ' + $removedCount),
            ('Removed file bytes: ' + $bytesRemoved),
            ('Removed GiB: {0:N3}' -f ($bytesRemoved/1GB)),
            ('Free before GiB: {0:N3}' -f ($initialFree/1GB)),
            ('Free after GiB: {0:N3}' -f ($finalFree/1GB)),
            ('Free space delta GiB: {0:N3}' -f (($finalFree-$initialFree)/1GB)),
            ('Error count: ' + $Problems.Count),
            ('Warning count: ' + $Warns.Count),
            ('Result: ' + $(if ($failed) { 'FAIL' } else { 'PASS' })),
            '',
            'Rule: only recognized, stale older-stage Korean patch ISO files and incomplete ISO fragments can be removed.',
            'Rule: protected checkpoints, original games, state, saves, logs, code and assets are never deleted.',
            'Rule: when any PPSSPP instance is running or cannot be enumerated, ISO deletion is skipped.',
            'NEXT: attach the generated result ZIP to ChatGPT.'
        )
        try {
            $summary | Set-Content -LiteralPath (Join-Path $Session 'SUMMARY.txt') -Encoding UTF8
            @($Actions.ToArray()) | Export-Csv -LiteralPath (Join-Path $Session 'ACTIONS.csv') -NoTypeInformation -Encoding UTF8
            @($Protected.ToArray()) | Export-Csv -LiteralPath (Join-Path $Session 'PROTECTED.csv') -NoTypeInformation -Encoding UTF8
            @($Problems.ToArray()) | Set-Content -LiteralPath (Join-Path $Session 'ERRORS.txt') -Encoding UTF8
            @($Warns.ToArray()) | Set-Content -LiteralPath (Join-Path $Session 'WARNINGS.txt') -Encoding UTF8
            $meta=[pscustomobject]@{
                mode=$Mode; startFree=$initialFree; endFree=$finalFree
                candidateCount=$candidates; deletedCount=$removedCount
                deletedBytes=$bytesRemoved; errors=@($Problems.ToArray())
                warnings=@($Warns.ToArray()); baselineSHA256=$ExpectedTSHA
                protectedIsos=@($TPath,$UPath); fatal=$fatal
            }
            $meta | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $Session 'RESULT.json') -Encoding UTF8
            if (Test-Path -LiteralPath $ScriptSelf -PathType Leaf) {
                Copy-Item -LiteralPath $ScriptSelf -Destination (Join-Path $Session 'run.ps1') -Force
            }
        } catch {
            Write-Warning ('Unable to write some session logs: ' + $_.Exception.Message)
        }
        if ($transcriptRunning) { try { Stop-Transcript | Out-Null } catch { } }
        try {
            $outZip=if ($failed) { $ZipFailure } else { $ZipSuccess }
            if (Test-Path -LiteralPath $outZip) { Remove-Item -LiteralPath $outZip -Force }
            Compress-Archive -Path (Join-Path $Session '*') -DestinationPath $outZip -CompressionLevel Optimal -Force -ErrorAction Stop
            Write-Host ("RESULT ZIP: " + $outZip)
            Write-Host ("RESULT: " + $(if ($failed) { 'FAIL' } else { 'PASS' }))
            Write-Host ("REMOVED: {0} file(s), {1:N3} GiB" -f $removedCount,($bytesRemoved/1GB))
        } catch {
            Write-Warning ('RESULT ZIP CREATION FAILED: ' + $_.Exception.Message)
        }
    }
}
if ($Problems.Count -gt 0) { exit 1 } else { exit 0 }
