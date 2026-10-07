$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51p_fix2_modesel_title_fix\build"
$AssetDir=Join-Path $Root "analysis\sub\sub51p_modesel_title_fix\assets"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51p_fix2_modesel_title_fix_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51p_fix2_modesel_title_fix_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51p_fix2_modesel_title_fix_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$AssetDir | Out-Null
$PackAssets=Join-Path $Root "sub51p_assets"
if(-not (Test-Path $PackAssets)){ throw "Missing package asset folder: $PackAssets" }
Copy-Item (Join-Path $PackAssets "*") $AssetDir -Force

if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$Succeeded=$false

Start-Transcript -Path $Transcript -Force | Out-Null
try{
    Write-Host "=== SUB51P MODESEL/TITLE FIX ==="
    Write-Host "PPSSPP will auto-launch after build. NO story automation/macro."
    $Py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($Py){
        & $Py.Source -3 (Join-Path $Root "build_sub51p_fix2_modesel_title_fix.py") --root $Root --assets $AssetDir
    } else {
        $Py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $Py){throw "Python not found"}
        & $Py.Source (Join-Path $Root "build_sub51p_fix2_modesel_title_fix.py") --root $Root --assets $AssetDir
    }
    if($LASTEXITCODE -ne 0){throw "SUB51P build failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @("Naruto SUB51P FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
      $_.Exception.Message,($_|Out-String)) | Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}
finally{
    try{Stop-Transcript | Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null
    foreach($n in @("SUMMARY.txt","SUB51O_static_verification.json","FAILURE.txt",
      "SUB51O_diagnostic.txt","sub51o_texture_patch.tsv","sub51o_fsts_rebuild.tsv",
      "sub51o_core_verification.tsv","sub51o_movie_preservation.tsv")){
        $s=Join-Path $StageDir $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n) -Force}
    }
    Copy-Item $Transcript (Join-Path $Pkg (Split-Path $Transcript -Leaf)) -Force
    if(Test-Path (Join-Path $AssetDir "SUB51P_asset_preview.png")){
        Copy-Item (Join-Path $AssetDir "SUB51P_asset_preview.png") (Join-Path $Pkg "SUB51P_asset_preview.png") -Force
    }
    foreach($n in @("build_sub51p_fix2_modesel_title_fix.py","run_naruto_sub51p_fix2_modesel_title_fix.ps1")){
        $s=Join-Path $Root $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n) -Force}
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
        $Final=Join-Path $StageDir "Naruto_KR_MOV06E_SUB51P_FIX2_ModeSelTitleFix.iso"
        Copy-Item $Final (Join-Path $Root "Naruto_KR_MOV06E_SUB51P_FIX2_ModeSelTitleFix.iso") -Force
        Write-Host "SUB51P FIX2 SUCCESS"
        Write-Host "ISO: $Root\Naruto_KR_MOV06E_SUB51P_FIX2_ModeSelTitleFix.iso"
        Write-Host "Upload: $SuccessZip"

        # Direct PPSSPP launch only. Do NOT call generated_macros\naruto.bat,
        # because story-line automation is no longer needed.
        $PpssppCandidates=@(
            (Join-Path $Root "tools\ppsspp-stage33-2314\PPSSPPWindows64.exe"),
            (Join-Path $Root "PPSSPPWindows64.exe")
        )
        $Ppsspp=$null
        foreach($c in $PpssppCandidates){
            if(Test-Path $c){ $Ppsspp=$c; break }
        }
        if(-not $Ppsspp){
            $hit=Get-ChildItem (Join-Path $Root "tools") -Filter "PPSSPPWindows64.exe" -File -Recurse -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if($hit){ $Ppsspp=$hit.FullName }
        }

        if($Ppsspp){
            Write-Host "Launching PPSSPP directly (NO story macro)..."
            Start-Process -FilePath $Ppsspp -ArgumentList @($Final) -WorkingDirectory (Split-Path $Ppsspp -Parent)
        } else {
            Write-Warning "PPSSPPWindows64.exe not found. Build succeeded; launch the ISO manually."
        }
    }else{
        Write-Host "Failure ZIP: $FailZip"
        exit 1
    }
}
