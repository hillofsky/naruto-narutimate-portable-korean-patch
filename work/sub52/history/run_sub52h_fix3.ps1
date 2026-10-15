param(
    [string]$Root = 'D:\narutimate portable',
    [string]$Source = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$stage = 'naruto_sub52h_fix3'
$outDir = Join-Path $Root 'analysis\sub\sub52h_fix3'
$logRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $outDir,$logRoot | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$transcript = Join-Path $logRoot ($stage + '_' + $stamp + '.log')
$successZip = Join-Path $logRoot ($stage + '_upload.zip')
$failZip = Join-Path $logRoot ('fail_' + $stage + '_upload.zip')
$ok=$false

Set-Location $Root
Start-Transcript -Path $transcript -Force | Out-Null
try {
    Write-Host '=== SUB52H FIX3 ==='
    Write-Host 'Fixes prior BOOT-offset failure by searching exact NUL-terminated C strings.'
    Write-Host 'No story macro. Exact generated ISO only.'

    $args=@(
        (Join-Path $scriptDir 'build_sub52h_fix3.py'),
        '--root',$Root,
        '--assets',(Join-Path $scriptDir 'sub52h_assets'),
        '--mapping',(Join-Path $scriptDir 'combined_hangul_mapping_sub52d2.tsv'),
        '--boot-patch',(Join-Path $scriptDir 'sub52h_boot_patch.tsv'),
        '--text-patch',(Join-Path $scriptDir 'sub52h_text_patch.tsv')
    )
    if($Source -ne ''){
        $args += @('--source',$Source)
    }

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        & $py.Source -3 @args
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw 'Python not found'}
        & $py.Source @args
    }
    if($LASTEXITCODE -ne 0){throw "SUB52H FIX3 build failed: $LASTEXITCODE"}

    $built=Join-Path $outDir 'Naruto_KR_MOV06E_SUB52H_FIX3.iso'
    if(-not (Test-Path $built)){throw "Built ISO missing: $built"}
    $rootIso=Join-Path $Root 'Naruto_KR_MOV06E_SUB52H_FIX3.iso'
    Copy-Item -LiteralPath $built -Destination $rootIso -Force

    $ok=$true
}
catch {
    @(
      'Naruto SUB52H FIX3 FAILURE',
      ('Timestamp=' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
      $_.Exception.Message,
      ($_ | Out-String)
    ) | Set-Content (Join-Path $outDir 'FAILURE.txt') -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}

    $pack=Join-Path $outDir '_upload'
    if(Test-Path $pack){Remove-Item $pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $pack | Out-Null

    foreach($n in @(
      'SUMMARY.txt','SUB52H_static_verification.json',
      'sub52h_boot_patch.tsv','sub52h_text_patch.tsv','sub52h_texture_patch.tsv',
      'sub52h_primary_rebuild.tsv','sub52h_fsts_rebuild.tsv',
      'sub52h_core_verification.tsv','sub52h_movie_preservation.tsv',
      'FAILURE.txt'
    )){
        $p=Join-Path $outDir $n
        if(Test-Path $p){Copy-Item $p $pack -Force}
    }
    if(Test-Path $transcript){Copy-Item $transcript $pack -Force}

    foreach($n in @(
      'build_sub52h_fix3.py','run_sub52h_fix3.ps1',
      'combined_hangul_mapping_sub52d2.tsv','sub52h_boot_patch.tsv','sub52h_text_patch.tsv'
    )){
        $p=Join-Path $scriptDir $n
        if(Test-Path $p){Copy-Item $p $pack -Force}
    }
    if(Test-Path (Join-Path $scriptDir 'sub52h_assets\asset_manifest.json')){
        Copy-Item (Join-Path $scriptDir 'sub52h_assets\asset_manifest.json') $pack -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=if($ok){$successZip}else{$failZip}
    if(Test-Path $zip){Remove-Item $zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
      $pack,$zip,[System.IO.Compression.CompressionLevel]::Optimal,$false
    )
    Remove-Item $pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Upload ZIP: $zip"

    if($ok){
        $rootIso=Join-Path $Root 'Naruto_KR_MOV06E_SUB52H_FIX3.iso'
        $PPSSPP='C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe'
        if(Test-Path $PPSSPP){
            Write-Host "Launching exact ISO: $rootIso"
            Start-Process -FilePath $PPSSPP -ArgumentList @("`"$rootIso`"") | Out-Null
        } else {
            Write-Warning "PPSSPP not found. Launch manually: $rootIso"
        }
    } else {
        exit 1
    }
}
