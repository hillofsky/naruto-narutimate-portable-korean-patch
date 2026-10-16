$ErrorActionPreference = 'Stop'
$Root = 'PROJECT_ROOT'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Set-Location $Root
$PyCmd=Get-Command py.exe -ErrorAction SilentlyContinue
if ($PyCmd) {
    $Exe = $PyCmd.Source
    $PyArgs = @('-3')
} else {
    $PyCmd=Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $PyCmd) { throw 'Python not found' }
    $Exe = $PyCmd.Source
    $PyArgs = @()
}
$Stage='naruto_sub52r_exact_glyph_audit'
$Stdout = Join-Path $env:TEMP ($Stage+'_stdout.txt')
$Stderr = Join-Path $env:TEMP ($Stage+'_stderr.txt')
try {
    & $Exe @PyArgs (Join-Path $ScriptDir 'qa_sub52r_exact_glyph_audit.py') --root $Root 1> $Stdout 2> $Stderr
    $ExitCode=$LASTEXITCODE
    Get-Content $Stdout -ErrorAction SilentlyContinue | Write-Host
    if (Test-Path $Stderr) { Get-Content $Stderr | Write-Host }
    if ($ExitCode -ne 0) { throw ('SUB52R Python exited '+$ExitCode) }
    Write-Host ('Upload: '+(Join-Path $LogRoot ($Stage+'_upload.zip')))
} catch {
    $FailZip=Join-Path $LogRoot ('fail_'+$Stage+'_upload.zip')
    if (-not (Test-Path $FailZip)) {
        $TmpDir=Join-Path $env:TEMP ($Stage+'_fallback')
        New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null
        $_ | Out-String | Set-Content (Join-Path $TmpDir 'FAILURE.txt') -Encoding UTF8
        if(Test-Path $Stdout){Copy-Item $Stdout $TmpDir -Force}
        if(Test-Path $Stderr){Copy-Item $Stderr $TmpDir -Force}
        Compress-Archive -Path (Join-Path $TmpDir '*') -DestinationPath $FailZip -Force
    }
    Write-Host ('Upload failure ZIP: '+$FailZip)
    exit 1
}
