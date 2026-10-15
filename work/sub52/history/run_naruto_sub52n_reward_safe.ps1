$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$Root='D:\narutimate portable'
$Stage='naruto_sub52n_reward_safe'
$PackRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$Logs=Join-Path $Root 'logs'
$Out=Join-Path $Root 'analysis\sub\sub52n_reward_safe'
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
$Transcript=Join-Path $Logs ($Stage+'_'+$Stamp+'.log')
$Success=Join-Path $Logs ($Stage+'_upload.zip')
$Fail=Join-Path $Logs ('fail_'+$Stage+'_upload.zip')
$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null
try {
    Write-Host '=== SUB52N: FIXED-LENGTH REWARD TEXT PATCH ==='
    Write-Host 'Keeps SUB52M gameplay/UI, changes only two reward C-strings in BOOT/EBOOT.'
    $Py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($Py){
        & $Py.Source -3 (Join-Path $PackRoot 'build_sub52n_reward_safe.py') --root $Root --bundle $PackRoot
    } else {
        $Py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $Py){throw 'Python not installed'}
        & $Py.Source (Join-Path $PackRoot 'build_sub52n_reward_safe.py') --root $Root --bundle $PackRoot
    }
    if($LASTEXITCODE -ne 0){throw 'SUB52N build did not complete'}
    $Result=Join-Path $Out 'Naruto_KR_MOV06E_SUB52N_RewardSafe.iso'
    if(-not (Test-Path -LiteralPath $Result)){throw 'Built ISO missing'}
    $Succeeded=$true
} catch {
    @('SUB52N FAILURE',($_ | Out-String)) | Set-Content -Encoding UTF8 (Join-Path $Out 'FAILURE.txt')
} finally {
    try{Stop-Transcript | Out-Null}catch{}
    $Upload=Join-Path $Out '_upload'
    if(Test-Path $Upload){Remove-Item -Recurse -Force $Upload}
    New-Item -ItemType Directory -Force -Path $Upload | Out-Null
    foreach($N in @('SUMMARY.json','SUMMARY.txt','reward_translation_plan.tsv','exact_reward_patch_offsets.tsv','FAILURE.txt')){
        $P=Join-Path $Out $N
        if(Test-Path $P){Copy-Item $P $Upload -Force}
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Upload -Force}
    foreach($N in @('build_sub52n_reward_safe.py','sub52m_iso_helpers.py','run_naruto_sub52n_reward_safe.ps1')){
        $P=Join-Path $PackRoot $N
        if(Test-Path $P){Copy-Item $P $Upload -Force}
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Dest=if($Succeeded){$Success}else{$Fail}
    if(Test-Path $Dest){Remove-Item $Dest -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Upload,$Dest,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item $Upload -Recurse -Force
    Write-Host "UPLOAD_ZIP=$Dest"
    if($Succeeded){
        # Launch exact new ISO only. Never control, stop or reuse other emulator sessions.
        $Iso=Join-Path $Out 'Naruto_KR_MOV06E_SUB52N_RewardSafe.iso'
        $PPSSPP='C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp\PPSSPPWindows64.exe'
        if(Test-Path $PPSSPP){
            Write-Host "Launching this ISO in new PPSSPP process: $Iso"
            $NewPPSSPP=Start-Process -FilePath $PPSSPP -ArgumentList @("`"$Iso`"") -PassThru
            Write-Host "New PPSSPP PID: $($NewPPSSPP.Id)"
        } else {
            Write-Warning "PPSSPP executable not found at expected path; manually launch: $Iso"
        }
    } else { exit 1 }
}
