$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Root='PROJECT_ROOT'
$Out=Join-Path $Root 'analysis\sub\sub52t_gauge_hud_compact'
$Logs=Join-Path $Root 'logs'
$Here=Split-Path -Parent $MyInvocation.MyCommand.Path
$Result=Join-Path $Out 'Naruto_KR_MOV06E_SUB52T_GaugeHUD_Compact.iso'
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $Logs ("naruto_sub52t_gauge_hud_"+$Stamp+'.log')
$Success=Join-Path $Logs 'naruto_sub52t_gauge_hud_upload.zip'
$Failure=Join-Path $Logs 'fail_naruto_sub52t_gauge_hud_upload.zip'
$Pass=$false

New-Item -ItemType Directory -Force -Path $Out,$Logs | Out-Null
Set-Location $Root
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== Naruto SUB52T gauge HUD / winner patch ==='
    Write-Host 'Uses only the already verified SUB52N reward ISO.'
    $drive=(Get-Item $Root).PSDrive
    $before=(Get-PSDrive -Name $drive.Name).Free
    Write-Host "Free bytes before: $before"

    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){$python=$py.Source;$pyArgs=@('-3')}
    else{
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py){throw 'Python not found'}
        $python=$py.Source;$pyArgs=@()
    }

    # Windows PowerShell 5.1 native stderr can be a terminating error under Stop.
    $saved=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
        & $python @pyArgs (Join-Path $Here 'build_sub52t_gauge_hud_compact.py') --root $Root
        $code=$LASTEXITCODE
    }
    finally {$ErrorActionPreference=$saved}
    if($code -ne 0){throw "Python build failed (exit $code)"}
    if(-not (Test-Path -LiteralPath $Result)){throw "Verified ISO missing: $Result"}

    $report=Join-Path $Out 'SUMMARY.json'
    if(-not (Test-Path -LiteralPath $report)){throw 'Verification JSON not found'}
    $status=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
    if($status.static_qa -ne 'PASS'){throw 'Static QA did not pass'}

    $after=(Get-PSDrive -Name $drive.Name).Free
    @(
        'SUB52T space and cleanup report',
        "free_before_bytes=$before",
        "free_after_bytes=$after",
        'deleted_intermediate=analysis\sub\sub52t_gauge_hud_compact\_work',
        'deleted_failed_partial=analysis\sub\sub52t_gauge_hud_compact\*.partial',
        'baseline_iso_deleted=False',
        'generated_iso_count=1'
    ) | Set-Content -LiteralPath (Join-Path $Out 'cleanup_report.txt') -Encoding UTF8
    $Pass=$true
}
catch {
    @('SUB52T FAILURE',($_ | Out-String),'Timestamp='+(Get-Date)) |
        Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    $Pack=Join-Path $Out '_upload'
    if(Test-Path $Pack){Remove-Item -LiteralPath $Pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    foreach($f in @('SUMMARY.json','SUMMARY.txt','sub52t_texture_report.tsv','sub52t_fsts_report.tsv','cleanup_report.txt','FAILURE.txt')){
        $src=Join-Path $Out $f
        if(Test-Path $src){Copy-Item $src (Join-Path $Pack $f) -Force}
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Pack -Force}
    foreach($f in @('build_sub52t_gauge_hud_compact.py','run_naruto_sub52t_gauge_hud.ps1','README_SUB52T.txt')){
        $src=Join-Path $Here $f
        if(Test-Path $src){Copy-Item $src $Pack -Force}
    }
    foreach($f in @('gauge__TEX_xgauge5__KO.png','gauge__TEX_vs__KO.png')){
        $src=Join-Path $Here ('assets\'+$f)
        if(Test-Path $src){Copy-Item $src $Pack -Force}
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=if($Pass){$Success}else{$Failure}
    if(Test-Path $zip){Remove-Item $zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Upload ZIP: $zip"
    if(-not $Pass){exit 1}
}

$PPSSPP='LOCAL_PATH'
if(Test-Path -LiteralPath $PPSSPP){
    Write-Host "Starting PPSSPP with EXACT ISO: $Result"
    $pr=Start-Process -FilePath $PPSSPP -ArgumentList @('"'+$Result+'"') -PassThru
    Write-Host "PPSSPP PID=$($pr.Id). No other PPSSPP instances were controlled."
}else{
    Write-Warning "Build succeeded. PPSSPP not found; launch exact ISO manually: $Result"
}
