param([string]$Root='PROJECT_ROOT')
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$Stage='naruto_sub52o_unified_audit'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$Out=Join-Path $Root 'analysis\sub\sub52o_unified_audit'
$Logs=Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $Logs,$Out | Out-Null
$Stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$Transcript=Join-Path $Logs ($Stage+'_'+$Stamp+'.log')
$Success=Join-Path $Logs ($Stage+'_upload.zip')
$Failure=Join-Path $Logs ('fail_'+$Stage+'_upload.zip')
$Okay=$false
$EnvSummary=Join-Path $Out 'ppsspp_environment.txt'
$PPSSPPExe='LOCAL_PATH'

function Snapshot-Environment {
  @(
    '=== SUB52O PPSSPP ENVIRONMENT (READ-ONLY) ===',
    'Timestamp='+[string](Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
    'PPSSPP_ExpectedExe='+$PPSSPPExe,
    'Root='+$Root
  ) | Set-Content -LiteralPath $EnvSummary -Encoding UTF8
  foreach($drive in @('C','D')) {
    try {
      $d=Get-PSDrive -Name $drive -ErrorAction Stop
      "Drive=$drive FreeBytes=$([int64]$d.Free) UsedBytes=$([int64]$d.Used)" | Add-Content $EnvSummary -Encoding UTF8
    } catch { "Drive=$drive unavailable" | Add-Content $EnvSummary -Encoding UTF8 }
  }
  '--- RUNNING PPSSPP INSTANCES ---' | Add-Content $EnvSummary -Encoding UTF8
  try {
    $processes=Get-CimInstance Win32_Process -Filter "Name = 'PPSSPPWindows64.exe'" -ErrorAction Stop
    foreach($p in $processes) {
      "PID=$($p.ProcessId) EXE=$($p.ExecutablePath) COMMANDLINE=$($p.CommandLine)" | Add-Content $EnvSummary -Encoding UTF8
    }
    if(-not $processes){'None found' | Add-Content $EnvSummary -Encoding UTF8}
  } catch { "CIM_FAIL=$($_.Exception.Message)" | Add-Content $EnvSummary -Encoding UTF8 }
  # Known standalone and Windows per-user PPSSPP config locations. Never modify any of them.
  $PpssppParent=Split-Path -Parent $PPSSPPExe
  $bases=@(
    $PpssppParent,
    (Join-Path $PpssppParent 'memstick'),
    (Join-Path $PpssppParent 'ms'),
    (Join-Path $env:USERPROFILE 'Documents\PPSSPP'),
    (Join-Path $env:APPDATA 'PPSSPP'),
    (Join-Path $env:LOCALAPPDATA 'PPSSPP'),
    (Join-Path $Root 'ppsspp')
  ) | Select-Object -Unique
  $lookup=@()
  foreach($base in $bases) {
    if(-not (Test-Path -LiteralPath $base -PathType Container)){continue}
    foreach($rel in @('PSP\SYSTEM\ppsspp.ini','memstick\PSP\SYSTEM\ppsspp.ini','ms\PSP\SYSTEM\ppsspp.ini','ppsspp.ini')) {
      $cfg=Join-Path $base $rel
      if(Test-Path -LiteralPath $cfg -PathType Leaf){$lookup+= $cfg}
    }
  }
  $lookup=$lookup | Select-Object -Unique
  '--- CONFIG FLAGS (select keys only, not the complete file) ---' | Add-Content $EnvSummary -Encoding UTF8
  foreach($cfg in $lookup) {
    "FILE=$cfg" | Add-Content $EnvSummary -Encoding UTF8
    Get-Content -LiteralPath $cfg -ErrorAction SilentlyContinue | Where-Object {
      $_ -match '^(ReplaceTextures|SaveNewTextures|TextureReplacementsEnabled|MemStickDirectory|TextureFiltering|TextureScalingLevel|GameID|EnableCheats|CurrentDirectory|RewindSnapshotInterval|EnableState)\s*='
    } | Add-Content $EnvSummary -Encoding UTF8
  }
  '--- TEXTURE OVERRIDE PACKS: ULKS46086 (non-destructive) ---' | Add-Content $EnvSummary -Encoding UTF8
  $packRoots=@()
  foreach($base in $bases){
    if(-not (Test-Path -LiteralPath $base -PathType Container)){continue}
    foreach($rel in @('PSP\TEXTURES\ULKS46086','memstick\PSP\TEXTURES\ULKS46086','ms\PSP\TEXTURES\ULKS46086')) {
      $folder=Join-Path $base $rel
      if(Test-Path -LiteralPath $folder -PathType Container){$packRoots+=$folder}
    }
  }
  foreach($folder in ($packRoots | Select-Object -Unique)) {
    "FOUND_TEXTURE_PACK=$folder" | Add-Content $EnvSummary -Encoding UTF8
    try {
      $items=Get-ChildItem -LiteralPath $folder -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 200
      foreach($item in $items) {
        "TEXTURE_FILE=$($item.FullName) SIZE=$($item.Length)" | Add-Content $EnvSummary -Encoding UTF8
      }
      $ini=Join-Path $folder 'textures.ini'
      if(Test-Path -LiteralPath $ini -PathType Leaf) {
        Copy-Item -LiteralPath $ini -Destination (Join-Path $Out ('texture_pack_'+(Split-Path $folder -Leaf)+'.ini')) -Force
      }
    } catch { "ERROR_ENUM_TEXTURES=$($_.Exception.Message)" | Add-Content $EnvSummary -Encoding UTF8 }
  }
  if(-not $packRoots){'No ULKS46086 override folder found in known locations' | Add-Content $EnvSummary -Encoding UTF8}
  '--- RECENT ULKS46086 SCREENSHOTS (max 10 copies) ---' | Add-Content $EnvSummary -Encoding UTF8
  $shots=@()
  foreach($base in $bases){
    foreach($rel in @('PSP\SCREENSHOT','memstick\PSP\SCREENSHOT','ms\PSP\SCREENSHOT')) {
      $folder=Join-Path $base $rel
      if(Test-Path -LiteralPath $folder -PathType Container) {
        $shots+= Get-ChildItem -LiteralPath $folder -Filter 'ULKS46086_*.jpg' -File -ErrorAction SilentlyContinue
      }
    }
  }
  $snapDir=Join-Path $Out 'recent_screenshots'
  New-Item -ItemType Directory -Force -Path $snapDir | Out-Null
  $ix=0
  foreach($pic in ($shots | Sort-Object LastWriteTime -Descending | Select-Object -First 10)) {
    $dst=Join-Path $snapDir ($ix.ToString('D2')+'_'+$pic.Name)
    Copy-Item -LiteralPath $pic.FullName -Destination $dst -Force
    "SCREENSHOT=$($pic.FullName)" | Add-Content $EnvSummary -Encoding UTF8
    $ix++
  }
}

Start-Transcript -Path $Transcript -Force | Out-Null
try {
  Write-Host '=== SUB52O UNIFIED STATIC AUDIT ==='
  Write-Host 'Read-only audit. Does NOT launch/exit/control PPSSPP or edit ISO.'
  Snapshot-Environment
  $py=Get-Command py.exe -ErrorAction SilentlyContinue
  if($py) {$exe=$py.Source;$prefix='-3 '} else {
    $py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $py){throw 'Python missing'}
    $exe=$py.Source;$prefix=''
  }
  # Start-Process avoids PowerShell 5.1 turning Python stderr into a terminating error.
  $script=Join-Path $ScriptDir 'sub52o_scan.py'
  $cmdArgs=$prefix+'"'+$script+'" --root "'+$Root+'" --out "'+$Out+'" --max-textures 165'
  $proc=Start-Process -FilePath $exe -ArgumentList $cmdArgs -Wait -PassThru -NoNewWindow `
     -RedirectStandardOutput (Join-Path $Out 'python_stdout.log') -RedirectStandardError (Join-Path $Out 'python_stderr.log')
  Get-Content (Join-Path $Out 'python_stdout.log') | Write-Host
  if($proc.ExitCode -ne 0){throw "Static ISO audit failed with Python exit code $($proc.ExitCode)"}
  $summary=Join-Path $Out 'SUMMARY.json'
  if(-not (Test-Path $summary)){throw 'SUMMARY.json was not written'}
  $Okay=$true
}
catch {
  @('SUB52O FAILURE', (Get-Date -Format o),$_.Exception.Message,($_ | Out-String)) | Set-Content (Join-Path $Out 'FAILURE.txt') -Encoding UTF8
}
finally {
  try {Stop-Transcript | Out-Null} catch {}
  $pack=Join-Path $Out '_upload'
  if(Test-Path $pack){Remove-Item -LiteralPath $pack -Recurse -Force -ErrorAction SilentlyContinue}
  New-Item -ItemType Directory -Force -Path $pack | Out-Null
  Get-ChildItem -LiteralPath $Out -File -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $pack -Force
  }
  foreach($folder in @('focus_textures','recent_screenshots')) {
    $src=Join-Path $Out $folder
    if(Test-Path $src){Copy-Item -LiteralPath $src -Destination $pack -Recurse -Force}
  }
  foreach($fname in @('sub52o_scan.py','sub52l_core.py','run_naruto_sub52o_unified_audit.ps1')) {
    $f=Join-Path $ScriptDir $fname
    if(Test-Path -LiteralPath $f){Copy-Item -LiteralPath $f -Destination $pack -Force}
  }
  if(Test-Path $Transcript){Copy-Item -LiteralPath $Transcript -Destination $pack -Force}
  $zip=if($Okay){$Success}else{$Failure}
  if(Test-Path $zip){Remove-Item -LiteralPath $zip -Force}
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::CreateFromDirectory($pack,$zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
  Remove-Item -LiteralPath $pack -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host "Upload ZIP: $zip"
  if(-not $Okay){exit 1}
}
