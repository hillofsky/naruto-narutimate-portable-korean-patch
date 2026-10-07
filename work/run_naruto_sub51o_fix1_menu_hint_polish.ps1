$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\sub\sub51o_menu_hint_polish\build"
$AssetDir=Join-Path $Root "analysis\sub\sub51o_menu_hint_polish\assets"
$Logs=Join-Path $Root "logs"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $Logs "naruto_sub51o_fix1_menu_hint_polish_$Stamp.log"
$SuccessZip=Join-Path $Logs "naruto_sub51o_fix1_menu_hint_polish_upload.zip"
$FailZip=Join-Path $Logs "fail_naruto_sub51o_fix1_menu_hint_polish_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs,$AssetDir | Out-Null

# Package assets are installed beside this script under sub51o_assets.
$PackAssets=Join-Path $Root "sub51o_assets"
if(-not (Test-Path $PackAssets)){ throw "Missing package asset folder: $PackAssets" }
Copy-Item (Join-Path $PackAssets "*") $AssetDir -Force

if(Test-Path $StageDir){Remove-Item $StageDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
$Succeeded=$false

Start-Transcript -Path $Transcript -Force | Out-Null
try{
    $Py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($Py){
        $PyCmd=$Py.Source
        & $PyCmd -3 (Join-Path $Root "build_sub51o_fix1_menu_hint_polish.py") --root $Root --assets $AssetDir
    } else {
        $Py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $Py){throw "Python not found"}
        & $Py.Source (Join-Path $Root "build_sub51o_fix1_menu_hint_polish.py") --root $Root --assets $AssetDir
    }
    if($LASTEXITCODE -ne 0){throw "SUB51O build failed. ExitCode=$LASTEXITCODE"}
    $Succeeded=$true
}
catch{
    @("Naruto SUB51O FAILURE","Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
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
    Copy-Item (Join-Path $AssetDir "SUB51O_asset_preview.png") (Join-Path $Pkg "SUB51O_asset_preview.png") -Force
    foreach($n in @("build_sub51o_fix1_menu_hint_polish.py","run_naruto_sub51o_fix1_menu_hint_polish.ps1")){
        $s=Join-Path $Root $n
        if(Test-Path $s){Copy-Item $s (Join-Path $Pkg $n) -Force}
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$SuccessZip}else{$FailZip}
    if(Test-Path $Zip){Remove-Item $Zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pkg,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue

    if($Succeeded){
        $Final=Join-Path $StageDir "Naruto_KR_MOV06E_SUB51O_MenuHintPolish.iso"
        Copy-Item $Final (Join-Path $Root "Naruto_KR_MOV06E_SUB51O_MenuHintPolish.iso") -Force
        Write-Host "SUB51O FIX1 SUCCESS"
        Write-Host "ISO: $Root\Naruto_KR_MOV06E_SUB51O_MenuHintPolish.iso"
        Write-Host "Upload: $SuccessZip"
        $Macro=Join-Path $Root "generated_macros\naruto.bat"
        if(Test-Path $Macro){
            Write-Host "Launching PPSSPP via naruto.bat for visual QA..."
            & $Macro $Final
        }
    }else{
        Write-Host "Failure ZIP: $FailZip"
        exit 1
    }
}
