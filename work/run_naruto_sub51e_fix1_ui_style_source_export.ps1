# Naruto PSP SUB51E FIX1 - minimal UI style source export
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51e_fix1_ui_style_source_export"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51e_fix1_ui_style_source_export_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51e_fix1_ui_style_source_export_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51e_fix1_ui_style_source_export_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
$Inventory=New-Object System.Collections.Generic.List[object]
[long]$CopiedBytes=0
[long]$MaxTotalBytes=120MB
[long]$MaxSingleBytes=20MB

function Test-PatternMatch {
    param([string]$Name,[string]$FullName,[string[]]$Patterns)
    $n=$Name.ToLowerInvariant()
    $f=$FullName.ToLowerInvariant()
    foreach($p in $Patterns){
        $q=$p.ToLowerInvariant()
        if($n.Contains($q) -or $f.Contains($q)){ return $true }
    }
    return $false
}

function Copy-Candidate {
    param([string]$Group,[System.IO.FileInfo]$File)
    if($File.Length -gt $script:MaxSingleBytes){ return }
    if(($script:CopiedBytes + $File.Length) -gt $script:MaxTotalBytes){ return }

    $destDir=Join-Path $StageDir $Group
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    $hash=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $ext=$File.Extension.ToLowerInvariant()
    $safeBase=($File.BaseName -replace '[^A-Za-z0-9._-]','_')
    if([string]::IsNullOrWhiteSpace($safeBase)){ $safeBase="asset" }
    $destName=("{0}_{1}{2}" -f $safeBase,$hash.Substring(0,12),$ext)
    $dest=Join-Path $destDir $destName

    if(-not (Test-Path $dest)){
        Copy-Item -LiteralPath $File.FullName -Destination $dest -Force
        $script:CopiedBytes += [long]$File.Length
        $Inventory.Add([pscustomobject]@{
            group=$Group
            source_path=$File.FullName
            copied_name=$destName
            bytes=$File.Length
            sha256=$hash
            last_write=$File.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        }) | Out-Null
    }
}

Start-Transcript -Path $Transcript -Force | Out-Null
try {
    $Iso=Join-Path $Root "analysis\sub\sub51d_full_text_apply\Naruto_KR_MOV06E_SUB51D_FullText.iso"
    if(-not (Test-Path $Iso)){throw "SUB51D ISO not found: $Iso"}
    $IsoSha=(Get-FileHash $Iso -Algorithm SHA256).Hash.ToLowerInvariant()
    if($IsoSha -ne "7138f8c35bacaafab85ff50c12daf0620030cb9b44e7b7bf242168c20c91e845"){
        throw "SUB51D ISO SHA mismatch: $IsoSha"
    }

    Write-Host "=== SUB51E FIX1 - MINIMAL UI SOURCE EXPORT ==="
    Write-Host "Base SHA256: $IsoSha"
    Write-Host "Size cap: $([math]::Round($MaxTotalBytes/1MB)) MB"
    Write-Host "No ISO modification / no PPSSPP / no local LLM"

    $SearchRoots=@(
        (Join-Path $Root "analysis"),
        (Join-Path $Root "sub43_assets"),
        (Join-Path $Root "macro_screenshots")
    ) | Where-Object { Test-Path $_ }

    $Groups=@(
        @{Name="modesel1"; Patterns=@("modesel1","tex_mod","mode_sel","modebg","mod_bg")},
        @{Name="option"; Patterns=@("option.ccs","tex_option","s_menu","setting.ccs")},
        @{Name="charsel1"; Patterns=@("charsel1","tex_sel","char_sel")},
        @{Name="mugen"; Patterns=@("mugen.ccs","tex_name","tex_yellow","tex_white","tex_red","tex_prv_")},
        @{Name="network_home"; Patterns=@("network.ccs","tex_network","home.ccs","tex_mhvid","narup")},
        @{Name="gauge"; Patterns=@("gauge.ccs","rpggauge.ccs","tex_rpgmenu")}
    )

    $AllowedExt=@(".png",".jpg",".jpeg",".bmp",".webp",".txt",".tsv",".csv",".json",".md",".py",".ps1")
    $Seen=@{}

    foreach($rootPath in $SearchRoots){
        Write-Host "Scanning: $rootPath"
        $files=@(Get-ChildItem -LiteralPath $rootPath -Recurse -Force -File -ErrorAction SilentlyContinue |
            Where-Object {
                ($AllowedExt -contains $_.Extension.ToLowerInvariant()) -and
                $_.Length -le $MaxSingleBytes
            })
        foreach($f in $files){
            if($Seen.ContainsKey($f.FullName)){continue}
            foreach($g in $Groups){
                if(Test-PatternMatch -Name $f.Name -FullName $f.FullName -Patterns $g.Patterns){
                    Copy-Candidate -Group $g.Name -File $f
                    $Seen[$f.FullName]=$true
                    break
                }
            }
            if($CopiedBytes -ge $MaxTotalBytes){break}
        }
        if($CopiedBytes -ge $MaxTotalBytes){break}
    }

    # Copy only the newest 20 screenshots separately, if not already collected.
    $Macro=Join-Path $Root "macro_screenshots"
    if(Test-Path $Macro){
        $shots=@(Get-ChildItem -LiteralPath $Macro -Recurse -Force -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension.ToLowerInvariant() -in @(".png",".jpg",".jpeg") } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 20)
        foreach($s in $shots){
            if(-not $Seen.ContainsKey($s.FullName)){
                Copy-Candidate -Group "recent_screens" -File $s
                $Seen[$s.FullName]=$true
            }
        }
    }

    $Inv=Join-Path $StageDir "sub51e_fix1_ui_source_inventory.tsv"
    $Inventory | Sort-Object group,source_path |
        Export-Csv -Delimiter "`t" -NoTypeInformation -Encoding UTF8 $Inv

    $counts=@{}
    foreach($x in $Inventory){
        if(-not $counts.ContainsKey($x.group)){$counts[$x.group]=0}
        $counts[$x.group]++
    }

    $summary=@(
        "Naruto SUB51E FIX1 - Minimal UI Style Source Export",
        "",
        "BaseISO=$Iso",
        "BaseISO_SHA256=$IsoSha",
        "CopiedFiles=$($Inventory.Count)",
        "CopiedBytes=$CopiedBytes",
        "CopiedMB=$([math]::Round($CopiedBytes/1MB,2))",
        "MaxTotalMB=$([math]::Round($MaxTotalBytes/1MB,0))",
        "GameDataModified=NO",
        "PPSSPPExecuted=NO",
        "BC250Used=NO",
        "LocalLLMUsed=NO",
        "",
        "Groups:"
    )
    foreach($k in ($counts.Keys | Sort-Object)){ $summary += " - $k=$($counts[$k])" }
    $summary | Set-Content (Join-Path $StageDir "SUMMARY.txt") -Encoding UTF8

    if($Inventory.Count -eq 0){
        throw "No relevant UI source files were found. Upload failure ZIP so the next exporter can extract directly from SUB51D."
    }

    $Succeeded=$true
}
catch {
    @(
        "Naruto SUB51E FIX1 FAILURE",
        "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_ | Out-String)
    ) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
    Write-Host "SUB51E FIX1 FAILED: $($_.Exception.Message)"
}
finally {
    try{Stop-Transcript | Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($n in @("SUMMARY.txt","FAILURE.txt","sub51e_fix1_ui_source_inventory.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    foreach($d in @("modesel1","option","charsel1","mugen","network_home","gauge","recent_screens")){
        $s=Join-Path $StageDir $d
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $d)-Recurse -Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    if(Test-Path $PSCommandPath){Copy-Item $PSCommandPath (Join-Path $Pkg (Split-Path $PSCommandPath -Leaf))-Force}

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
        Write-Host "SUB51E FIX1 SUCCESS"
        Write-Host "Upload: $SuccessZip"
    }else{
        Write-Host "Failure ZIP: $FailZip"
        exit 1
    }
}
