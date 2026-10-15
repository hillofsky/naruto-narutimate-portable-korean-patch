$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root='D:\narutimate portable'
$Logs=Join-Path $Root 'logs'
$Out=Join-Path $Root 'analysis\sub\sub52k_black_screen_diagnostic'
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $Logs ('naruto_sub52k_black_screen_diagnostic_'+$Stamp+'.log')
$Success=Join-Path $Logs 'naruto_sub52k_black_screen_diagnostic_upload.zip'
$Failure=Join-Path $Logs 'fail_naruto_sub52k_black_screen_diagnostic_upload.zip'
$Succeeded=$false
New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
Start-Transcript -LiteralPath $Transcript -Force | Out-Null
try {
    Write-Host '=== SUB52K BLACK SCREEN: READ-ONLY DIAGNOSTIC ==='
    Write-Host 'ISO and PPSSPP processes will not be changed or terminated.'
    $ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $Exe=$py.Source
        $Args=@('-3', (Join-Path $ScriptDir 'diagnose_sub52k_black_screen.py'), '--root',$Root,'--out',$Out)
    } else {
        $py=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $py) { throw 'Python 3 was not found' }
        $Exe=$py.Source
        $Args=@((Join-Path $ScriptDir 'diagnose_sub52k_black_screen.py'),'--root',$Root,'--out',$Out)
    }
    Write-Host '[1/3] Analyze base SUB52J vs black-screen SUB52K ISO...'
    $OldEAP=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
        & $Exe @Args 2>&1 | ForEach-Object { $_.ToString() | Tee-Object -FilePath (Join-Path $Out 'python_console.log') -Append }
        $Code=$LASTEXITCODE
    } finally { $ErrorActionPreference=$OldEAP }
    if($Code -ne 0) { throw ('Static diagnostic failed with exit code '+$Code) }

    $Succeeded=$true
} catch {
    @('SUB52K READ-ONLY DIAGNOSTIC FAILED',($_.Exception.Message),($_ | Out-String)) |
       Set-Content -LiteralPath (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
} finally {
    try {
        Write-Host '[2/3] Snapshot PPSSPP process command lines (no control)...'
        Get-CimInstance Win32_Process -ErrorAction Stop |
          Where-Object { $_.Name -match '^PPSSPP.*\.exe$' } |
          Select-Object ProcessId,Name,ExecutablePath,CommandLine |
          ConvertTo-Json -Depth 3 |
          Set-Content -LiteralPath (Join-Path $Out 'ppsspp_process_snapshot.json') -Encoding UTF8
    } catch {
        ('Cannot read PPSSPP process list: '+$_.Exception.Message) |
          Set-Content -LiteralPath (Join-Path $Out 'process_snapshot_error.txt') -Encoding UTF8
    }
    try {
        $Prior=Join-Path $Logs 'naruto_sub52k_face_names_upload.zip'
        if(Test-Path -LiteralPath $Prior) {
            Copy-Item -LiteralPath $Prior -Destination (Join-Path $Out 'previous_sub52k_build_log.zip') -Force
        }
        $Stage=Join-Path $Root 'analysis\sub\sub52k_face_names'
        foreach($Name in @('SUB52K_static_verification.json','SUMMARY.txt','sub52k_texture_patch.tsv','sub52k_primary_rebuild.tsv','sub52k_fsts_rebuild.tsv','sub52k_core_verification.tsv')) {
            $p=Join-Path $Stage $Name
            if(Test-Path -LiteralPath $p) {Copy-Item -LiteralPath $p -Destination $Out -Force}
        }
        # Only known PPSSPP log locations, with a per-file size limit.
        $PPSSPP='C:\Users\admin\Documents\Codex\2026-09-18\c-users-admin-downloads\work\ppsspp'
        $Dirs=@((Join-Path $env:APPDATA 'PPSSPP'), (Join-Path $env:LOCALAPPDATA 'PPSSPP'),$PPSSPP)
        foreach($Dir in $Dirs) {
            foreach($Rel in @('PPSSPP.log','ppsspp.log','memstick\PSP\SYSTEM\PPSSPP.log','memstick\PSP\SYSTEM\ppsspp.log','PSP\SYSTEM\ppsspp.log')) {
                $F=Join-Path $Dir $Rel
                if(Test-Path -LiteralPath $F -PathType Leaf) {
                    $Info=Get-Item -LiteralPath $F
                    if($Info.Length -le 2097152) {
                        $dst=Join-Path $Out ('ppsspp_'+([IO.Path]::GetFileName($Dir))+'_'+([IO.Path]::GetFileName($F)))
                        Copy-Item -LiteralPath $F -Destination $dst -Force
                    }
                }
            }
        }
    } catch {
        ('Optional log collection warning: '+$_.Exception.Message) |
          Set-Content -LiteralPath (Join-Path $Out 'optional_logs_warning.txt') -Encoding UTF8
    }
    try {Stop-Transcript | Out-Null} catch {}
    Write-Host '[3/3] Package diagnostic files...'
    $Pack=Join-Path $Out '_upload'
    if(Test-Path $Pack){Remove-Item $Pack -Recurse -Force -ErrorAction SilentlyContinue}
    New-Item -ItemType Directory -Force -Path $Pack | Out-Null
    Get-ChildItem -LiteralPath $Out -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Pack -Force
    }
    if(Test-Path -LiteralPath $Transcript){Copy-Item -LiteralPath $Transcript -Destination $Pack -Force}
    $ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
    Copy-Item -LiteralPath (Join-Path $ScriptDir 'diagnose_sub52k_black_screen.py') -Destination $Pack -Force
    Copy-Item -LiteralPath $MyInvocation.MyCommand.Path -Destination $Pack -Force
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip=if($Succeeded){$Success}else{$Failure}
    if(Test-Path -LiteralPath $Zip){Remove-Item -LiteralPath $Zip -Force}
    [System.IO.Compression.ZipFile]::CreateFromDirectory($Pack,$Zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
    Remove-Item -LiteralPath $Pack -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ('UPLOAD_ZIP='+$Zip)
    if(-not $Succeeded){exit 1}
}
