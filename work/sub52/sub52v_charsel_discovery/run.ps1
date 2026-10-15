#requires -Version 5.1
[CmdletBinding()]
param(
    [int]$MaxAssetCopies = 24,
    [int]$MaxArchiveMiB = 28
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = 'D:\narutimate portable'
$SubRoot = Join-Path $Root 'analysis\sub'
$LogRoot = Join-Path $Root 'logs'
$TPath = Join-Path $SubRoot 'sub52t_gauge_hud_compact\Naruto_KR_MOV06E_SUB52T_GaugeHUD_Compact.iso'
$UPath = Join-Path $SubRoot 'sub52u_hud_remaining\Naruto_KR_MOV06E_SUB52U_HUDRemaining_Compact.iso'
$ExpectedTSize = 4288798720L
$TimeTag = Get-Date -Format 'yyyyMMdd_HHmmss'
$SessionName = 'naruto_sub52v_charsel_discovery_' + $TimeTag
$Session = Join-Path $LogRoot $SessionName
$FinalOK = Join-Path $LogRoot 'naruto_sub52v_charsel_discovery_upload.zip'
$FinalFAIL = Join-Path $LogRoot 'fail_naruto_sub52v_charsel_discovery_upload.zip'
$TranscriptOn = $false
$Fatal = $null
$FilesSeen = 0
$TotalAssets = 0L
$AssetCopies = 0
$BinaryCount = 0
$RefCount = 0
$ImagesCount = 0
$CCSCount = 0
$MaxBytes = [long]$MaxArchiveMiB * 1048576L
$Inventory = New-Object 'System.Collections.Generic.List[object]'
$Refs = New-Object 'System.Collections.Generic.List[object]'
$Exports = New-Object 'System.Collections.Generic.List[object]'
$Warnings = New-Object 'System.Collections.Generic.List[string]'
$Selected = New-Object 'System.Collections.Generic.List[object]'
$ScannedDirectories = New-Object 'System.Collections.Generic.List[string]'

function Write-TextUtf8([string]$Path,[string]$Content) {
    [System.IO.File]::WriteAllText($Path,$Content,(New-Object System.Text.UTF8Encoding($true)))
}
function Add-Inventory([System.IO.FileInfo]$File,[string]$Category) {
    $sha = ''
    if ($File.Length -le 33554432L) {
        try { $sha = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() }
        catch { $Warnings.Add('HASH_ERROR '+$File.FullName+' '+$_.Exception.Message) }
    }
    $Inventory.Add([pscustomobject]@{
        category=$Category; path=$File.FullName; bytes=[long]$File.Length;
        modified_utc=$File.LastWriteTimeUtc.ToString('o'); sha256=$sha
    })
}
function Export-SmallFile([System.IO.FileInfo]$File,[string]$Kind,[long]$PerFileCap) {
    if ($AssetCopies -ge $MaxAssetCopies) { return }
    if ($File.Length -gt $PerFileCap) { return }
    if (($TotalAssets + $File.Length) -gt $MaxBytes) { return }
    if (($File.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
    $destName = ('asset_{0:D3}{1}' -f ($AssetCopies+1),$File.Extension.ToLowerInvariant())
    $destPath = Join-Path (Join-Path $Session 'assets') $destName
    try {
        Copy-Item -LiteralPath $File.FullName -Destination $destPath -ErrorAction Stop
        $script:AssetCopies++
        $script:TotalAssets += [long]$File.Length
        $Exports.Add([pscustomobject]@{ path=$File.FullName; zip_name=('assets/'+$destName); kind=$Kind; bytes=$File.Length })
    } catch { $Warnings.Add('EXPORT_ERROR '+$File.FullName+' '+$_.Exception.Message) }
}
function Scan-TextReference([System.IO.FileInfo]$File) {
    if ($File.Length -gt 2097152L -or $File.Length -eq 0L) { return }
    if ($RefCount -ge 700) { return }
    try {
        $lines = [System.IO.File]::ReadAllLines($File.FullName)
        $matchCount = 0
        for ($i=0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '(?i)(charsel[0-9]?\.ccs|TEX[_-]?sel\b|character.?select|mode.?select|select.?atlas|select.?name|SUB52U|SUB52T)') {
                $lo = [Math]::Max(0,$i-2)
                $hi = [Math]::Min($lines.Count-1,$i+2)
                $context = (($lines[$lo..$hi] | ForEach-Object { $_.Trim() }) -join ' / ')
                if ($context.Length -gt 1100) { $context=$context.Substring(0,1100) }
                $Refs.Add([pscustomobject]@{path=$File.FullName; line=$i+1; context=$context})
                $script:RefCount++
                $matchCount++
                if ($matchCount -ge 16 -or $RefCount -ge 700) { break }
            }
        }
    } catch {
        $Warnings.Add('TEXT_SCAN_ERROR '+$File.FullName+' '+$_.Exception.Message)
    }
}
function Scan-CCSHeader([System.IO.FileInfo]$File) {
    $script:BinaryCount++
    $outname = 'CCS_' + ('{0:D3}' -f $BinaryCount) + '_sample.bin'
    $outpath = Join-Path $Session $outname
    $want = [int][Math]::Min(65536L,$File.Length)
    try {
        $fs=[System.IO.File]::Open($File.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
        try {
            $buf=New-Object byte[] $want
            $read=$fs.Read($buf,0,$want)
            if ($read -lt $want) { $buf=$buf[0..([Math]::Max(0,$read-1))] }
            [System.IO.File]::WriteAllBytes($outpath,$buf)
        } finally { $fs.Dispose() }
        $Exports.Add([pscustomobject]@{path=$File.FullName; zip_name=$outname; kind='CCS_FIRST_64K'; bytes=$want})
    } catch { $Warnings.Add('CCS_HEADER_READ_ERROR '+$File.FullName+' '+$_.Exception.Message) }
}
function Handle-File([System.IO.FileInfo]$File) {
    $script:FilesSeen++
    if (($File.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return }
    $name=$File.Name
    $ext=$File.Extension.ToLowerInvariant()
    $target = ($name -match '(?i)(charsel|TEX[_-]?sel|mode.?sel|character.?select|select.?name|name.?overlap|xgauge|face_.*\.png)')
    if ($target -and $ext -in @('.ccs','.png','.bmp','.dds','.ktx','.bin','.json','.csv','.txt','.py','.ps1','.zip')) {
        $kind='TARGET_FILE'
        if ($ext -eq '.ccs') { $kind='CHARSEL_CCS'; $script:CCSCount++ }
        if ($ext -in @('.png','.bmp','.dds','.ktx')) { $kind='TARGET_IMAGE'; $script:ImagesCount++ }
        Add-Inventory $File $kind
        if ($kind -eq 'CHARSEL_CCS') {
            if ($BinaryCount -lt 6) { Scan-CCSHeader $File }
            Export-SmallFile $File 'CCS_COPY' 10485760L
        } elseif ($kind -eq 'TARGET_IMAGE') {
            Export-SmallFile $File 'IMAGE' 4194304L
        } elseif ($ext -in @('.json','.csv','.txt','.py','.ps1')) {
            Export-SmallFile $File 'TEXT_REFERENCE' 262144L
        }
    }
    if ($ext -in @('.ps1','.py','.json','.md','.txt','.csv') -and $File.Length -le 2097152L) {
        Scan-TextReference $File
    }
    # Select named snapshots, not a broad scan or upload of personal screenshots.
    if (($ext -eq '.png' -or $ext -eq '.jpg') -and $name -match '(?i)(charsel|character_select|select_screen|name_overlap|mode_select)') {
        if (-not $target) { Add-Inventory $File 'SCREENSHOT' }
        Export-SmallFile $File 'SCREENSHOT' 4194304L
    }
}

try {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { throw 'PROJECT_ROOT_MISSING: D:\narutimate portable' }
    New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $Session | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Session 'assets') | Out-Null
    try { Start-Transcript -Path (Join-Path $Session 'console_transcript.txt') -Force | Out-Null; $TranscriptOn=$true }
    catch { $Warnings.Add('TRANSCRIPT_FAILED '+$_.Exception.Message) }

    Write-Host '==== NARUTO SUB52V CHARACTER SELECTION DISCOVERY (READ ONLY) ===='
    Write-Host 'No ISO or texture will be edited. No PPSSPP instance will be controlled.'
    foreach ($checkpoint in @($TPath,$UPath)) {
        if (-not (Test-Path -LiteralPath $checkpoint -PathType Leaf)) { throw 'CHECKPOINT_MISSING: '+$checkpoint }
        $item=Get-Item -LiteralPath $checkpoint
        if ($item.Length -lt 4000000000L) { throw 'CHECKPOINT_TOO_SMALL: '+$checkpoint }
        Add-Inventory $item 'PROTECTED_CHECKPOINT_ISO'
        Write-Host ('Protected: '+$checkpoint+' ('+[Math]::Round($item.Length/1GB,2)+' GiB)')
    }
    if ((Get-Item -LiteralPath $TPath).Length -ne $ExpectedTSize) { throw 'SUB52T_BASELINE_SIZE_MISMATCH' }
    $emu=@()
    try { $emu=@(Get-CimInstance Win32_Process -Filter "Name LIKE 'PPSSPP%'" -ErrorAction Stop) }
    catch { $Warnings.Add('PPSSPP_PROCESS_QUERY_ERROR '+$_.Exception.Message) }
    $emu | Select-Object ProcessId,Name,CommandLine | Export-Csv -LiteralPath (Join-Path $Session 'PPSSPP_PROCESS_STATE.csv') -NoTypeInformation -Encoding UTF8

    # Focus on stages likely to contain charsel1.ccs and texture rebuild tools. Skip arbitrary game ISOs.
    $dirNames = @('sub52u_hud_remaining','sub52t_gauge_hud_compact','sub52v_cleanup','sub52n_reward_safe_fix1','sub52n_reward_safe',
                  'sub51p_fix13_full_atlas','sub51p_fix10_stable_ui','sub51n_titlehomepolish','sub51g_modesel1_style_rebuild')
    $scanDirs=New-Object 'System.Collections.Generic.List[string]'
    foreach ($n in $dirNames) {
        $p=Join-Path $SubRoot $n
        if (Test-Path -LiteralPath $p -PathType Container) { $scanDirs.Add($p) }
    }
    foreach ($relative in @('extracted','assets','resources','tools','generated_macros','analysis\graphics','analysis\textures')) {
        $p=Join-Path $Root $relative
        if (Test-Path -LiteralPath $p -PathType Container) { $scanDirs.Add($p) }
    }
    # Also inspect the first level of sub52* stages for likely code/artifacts, excluding whole ISO scanning.
    if (Test-Path -LiteralPath $SubRoot -PathType Container) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $SubRoot -Directory -ErrorAction Stop)) {
            if ($dir.Name -match '(?i)^sub52' -and $dir.FullName -notin $scanDirs) { $scanDirs.Add($dir.FullName) }
        }
    }
    foreach ($dir in $scanDirs) {
        try {
            Write-Host ('Scanning: '+$dir)
            $ScannedDirectories.Add($dir)
            foreach ($f in (Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction Stop)) {
                if ($FilesSeen -gt 150000) { $Warnings.Add('FILE_SCAN_LIMIT_150000_REACHED'); break }
                if ($f.Length -ge 268435456L -and $f.Extension.ToLowerInvariant() -ne '.ccs') { continue }
                Handle-File $f
            }
            if ($FilesSeen -gt 150000) { break }
        } catch { $Warnings.Add('SCAN_DIR_ERROR '+$dir+' '+$_.Exception.Message) }
    }
    if ($CCSCount -eq 0) { $Warnings.Add('CHARSEL_CCS_NOT_FOUND: may be packed inside FSTS/ISO; find source via script reference or next stage extractor') }
    if ($ImagesCount -eq 0) { $Warnings.Add('TARGET_IMAGE_NOT_FOUND: collect PNG dump / screenshot before texture edits') }
    Write-Host ('Seen files: '+$FilesSeen+' / target CCS: '+$CCSCount+' / target images: '+$ImagesCount+' / text refs: '+$RefCount)
} catch {
    $Fatal = $_.Exception.Message
    $Warnings.Add('FATAL: '+$Fatal)
    Write-Warning ('COLLECTION_FAILED: '+$Fatal)
} finally {
    # Always create a forensic upload ZIP, including on failure.
    if (-not (Test-Path -LiteralPath $Session -PathType Container)) {
        try { New-Item -ItemType Directory -Force -Path $Session | Out-Null } catch {
            $LogRoot=Join-Path $env:TEMP 'naruto_logs_fallback'
            New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
            $Session=Join-Path $LogRoot $SessionName
            New-Item -ItemType Directory -Force -Path $Session | Out-Null
            $FinalFAIL=Join-Path $LogRoot 'fail_naruto_sub52v_charsel_discovery_upload.zip'
            $FinalOK=Join-Path $LogRoot 'naruto_sub52v_charsel_discovery_upload.zip'
        }
    }
    $status='PASS'
    if ($null -ne $Fatal) { $status='FAIL' }
    elseif ($CCSCount -eq 0 -and $RefCount -eq 0) { $status='NEEDS_SOURCE_DISCOVERY' }
    try {
        $Inventory | Export-Csv -LiteralPath (Join-Path $Session 'INVENTORY.csv') -NoTypeInformation -Encoding UTF8
        $Refs | Export-Csv -LiteralPath (Join-Path $Session 'SOURCE_REFERENCES.csv') -NoTypeInformation -Encoding UTF8
        $Exports | Export-Csv -LiteralPath (Join-Path $Session 'EXPORTED_ASSETS.csv') -NoTypeInformation -Encoding UTF8
        $ScannedDirectories | Set-Content -LiteralPath (Join-Path $Session 'SCANNED_DIRS.txt') -Encoding UTF8
        $Warnings | Set-Content -LiteralPath (Join-Path $Session 'WARNINGS.txt') -Encoding UTF8
        $summary=[ordered]@{
            stage='SUB52V'; purpose='char selection name atlas mapping'; status=$status;
            timestamp=(Get-Date).ToString('o'); fatal=$Fatal; filesSeen=$FilesSeen;
            charselCCS=$CCSCount; targetImages=$ImagesCount; sourceReferences=$RefCount;
            copiedFiles=$AssetCopies; copiedBytes=$TotalAssets; warnings=$Warnings.Count;
            isoModified=$false; emulatorControlled=$false; previousStage='SUB52U';
            next='Locate exact charsel1.ccs/TEX_sel texture+UI masks; design no-overlap atlas patch'
        }
        Write-TextUtf8 (Join-Path $Session 'RESULT.json') ($summary | ConvertTo-Json -Depth 6)
        $report=@(
            'NARUTO SUB52V CHARACTER SELECTION DIAGNOSTIC',
            'Result: '+$status,
            'SUB52T known-good ISO: '+$TPath,
            'SUB52U current ISO: '+$UPath,
            'Files scanned: '+$FilesSeen,
            'Charsel CCS candidates: '+$CCSCount,
            'Image candidates: '+$ImagesCount,
            'Source references: '+$RefCount,
            'Exported assets: '+$AssetCopies+' / bytes: '+$TotalAssets,
            'No game ISO or original files were changed.',
            'No PPSSPP instance was started/controlled/killed.',
            'NEXT: Upload this ZIP to ChatGPT, then proceed with atlas bounding box analysis.'
        ) -join [Environment]::NewLine
        Write-TextUtf8 (Join-Path $Session 'SUMMARY.txt') $report
        if ($status -eq 'FAIL') { Write-TextUtf8 (Join-Path $Session 'FAILURE.txt') ('Reason: '+$Fatal) }
        Copy-Item -LiteralPath $MyInvocation.MyCommand.Path -Destination (Join-Path $Session 'run.ps1') -Force -ErrorAction SilentlyContinue
    } catch { Write-Warning ('LOG_WRITE_ERROR: '+$_.Exception.Message) }
    if ($TranscriptOn) { try { Stop-Transcript | Out-Null } catch {} }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $destination= if ($status -eq 'FAIL') { $FinalFAIL } else { $FinalOK }
        # Save old same-name upload ZIP in logs\old with a timestamp; never delete prior logs.
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $old=Join-Path $LogRoot 'old'; New-Item -ItemType Directory -Force -Path $old | Out-Null
            $oldName=('{0}_{1}.zip' -f ([IO.Path]::GetFileNameWithoutExtension($destination)), $TimeTag)
            Move-Item -LiteralPath $destination -Destination (Join-Path $old $oldName) -ErrorAction Stop
        }
        [System.IO.Compression.ZipFile]::CreateFromDirectory($Session,$destination,[System.IO.Compression.CompressionLevel]::Optimal,$false)
        Write-Host ('UPLOAD ZIP: '+$destination)
        Write-Host ('RESULT: '+$status)
    } catch {
        Write-Warning ('ZIP_CREATION_ERROR: '+$_.Exception.Message)
        try { Write-TextUtf8 (Join-Path $Session 'ZIP_CREATION_ERROR.txt') $_.Exception.ToString() } catch {}
    }
}
