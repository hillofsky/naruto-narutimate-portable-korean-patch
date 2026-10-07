# Naruto PSP SUB51M - consolidated final runtime QA capture
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$Iso=Join-Path $Root "analysis\sub\sub51l_fix2_consolidated_ui\Naruto_KR_MOV06E_SUB51L_FIX2_ConsolidatedUI.iso"
$ExpectedSha="d3556573931e102eafda7b2dafcaa5adce230004af0ca825e7b6b7c2aa8f0cf8"
$Macro=Join-Path $Root "generated_macros\naruto.bat"

$StageDir=Join-Path $Root "analysis\sub\sub51m_final_runtime_qa"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51m_final_runtime_qa_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51m_final_runtime_qa_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51m_final_runtime_qa_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$CaptureDir=Join-Path $StageDir "screenshots"
New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null
$Succeeded=$false
$Start=Get-Date

function Copy-NewImages {
    param([string]$SearchRoot,[string]$Tag)
    if(-not (Test-Path $SearchRoot)){return 0}
    $count=0
    $threshold=$script:Start.AddMinutes(-2)
    $files=@(Get-ChildItem -LiteralPath $SearchRoot -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.LastWriteTime -ge $threshold -and
            $_.Extension.ToLowerInvariant() -in @(".png",".jpg",".jpeg",".bmp",".webp")
        } |
        Sort-Object LastWriteTime,FullName)
    foreach($f in $files){
        $safe=($f.Name -replace '[^A-Za-z0-9._-]','_')
        $name=("{0}_{1:D3}_{2}" -f $Tag,$count,$safe)
        Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $CaptureDir $name) -Force
        $count++
    }
    return $count
}

Start-Transcript -Path $Transcript -Force | Out-Null
try{
    Write-Host "=== SUB51M FINAL RUNTIME QA ==="
    Write-Host "ISO: $Iso"

    if(-not (Test-Path $Iso)){throw "SUB51L FIX2 ISO missing: $Iso"}
    $sha=(Get-FileHash -LiteralPath $Iso -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "ISO SHA256: $sha"
    if($sha -ne $ExpectedSha){throw "SUB51L FIX2 ISO SHA mismatch"}

    if(-not (Test-Path $Macro)){throw "Runtime macro missing: $Macro"}

    @(
      "Naruto SUB51M runtime QA",
      "Start=$($Start.ToString('yyyy-MM-dd HH:mm:ss'))",
      "ISO=$Iso",
      "ISO_SHA256=$sha",
      "Macro=$Macro",
      "RuntimeMode=normal boot",
      "BC250Used=NO",
      "LocalLLMUsed=NO"
    ) | Set-Content (Join-Path $StageDir "RUN_INFO.txt") -Encoding UTF8

    Write-Host ""
    Write-Host "Launching the established normal-boot Naruto macro..."
    Write-Host "Do not load an old save-state for visual verification."
    Write-Host ""

    # Established project rule: pass generated ISO path as the first argument.
    & $Macro $Iso
    $MacroExit=$LASTEXITCODE
    Write-Host "naruto.bat exit code: $MacroExit"

    # Give PPSSPP/macro screenshots a moment to flush to disk.
    Start-Sleep -Seconds 5

    $total=0
    $total += Copy-NewImages (Join-Path $Root "macro_screenshots") "macro"
    $total += Copy-NewImages (Join-Path $Root "tools\ppsspp-stage33-2314") "ppsspp"
    $total += Copy-NewImages (Join-Path $Root "generated_macros") "generated"

    # Deduplicate identical captured images by SHA256.
    $seen=@{}
    $manifest=New-Object System.Collections.Generic.List[object]
    foreach($f in @(Get-ChildItem $CaptureDir -File -ErrorAction SilentlyContinue | Sort-Object Name)){
        $h=(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if($seen.ContainsKey($h)){
            Remove-Item -LiteralPath $f.FullName -Force
            continue
        }
        $seen[$h]=$true
        $manifest.Add([pscustomobject]@{
            file=$f.Name
            bytes=$f.Length
            sha256=$h
            modified=$f.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        }) | Out-Null
    }

    $ManifestPath=Join-Path $StageDir "screenshot_manifest.tsv"
    $manifest | Export-Csv -Delimiter "`t" -NoTypeInformation -Encoding UTF8 $ManifestPath

    @(
      "Naruto SUB51M Runtime QA Summary",
      "",
      "ISO_SHA256=$sha",
      "MacroExitCode=$MacroExit",
      "UniqueScreenshots=$($manifest.Count)",
      "NormalBoot=YES",
      "OldSaveStateVisualQA=NO",
      "BC250Used=NO",
      "LocalLLMUsed=NO",
      "",
      "Review focus:",
      " - main mode-select styling / clipping",
      " - option menu normal + selected variants",
      " - home and RPG menu labels",
      " - Mugen status / red / white / mini-game title atlases",
      " - skill names and mini-game result images",
      " - title new/continue menu",
      " - remaining Japanese image text or corrupted shared-atlas regions"
    ) | Set-Content (Join-Path $StageDir "SUMMARY.txt") -Encoding UTF8

    if($MacroExit -ne 0){throw "naruto.bat returned non-zero exit code: $MacroExit"}
    if($manifest.Count -eq 0){throw "No new runtime screenshots were captured"}

    $Succeeded=$true
}
catch{
    @(
      "Naruto SUB51M FAILURE",
      "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally{
    try{Stop-Transcript | Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($n in @("SUMMARY.txt","RUN_INFO.txt","FAILURE.txt","screenshot_manifest.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n)-Force}
    }
    if(Test-Path $CaptureDir){
        Copy-Item $CaptureDir (Join-Path $Pkg "screenshots") -Recurse -Force
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf))-Force
    if(Test-Path $PSCommandPath){
        Copy-Item $PSCommandPath (Join-Path $Pkg "run_naruto_sub51m_final_runtime_qa.ps1") -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force -ErrorAction SilentlyContinue}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
      Write-Host "SUB51M SUCCESS"
      Write-Host "Upload: $SuccessZip"
    }else{
      Write-Host "Failure ZIP: $FailZip"
      exit 1
    }
}
