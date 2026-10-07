# Naruto PSP SUB51N FIX1 - patch missing shutil import, then rerun pressed runtime QA
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = "D:\narutimate portable"
$Logs = Join-Path $Root "logs"
$QaPy = Join-Path $Root "qa_sub51n_pressed_runtime.py"
$Runner = Join-Path $Root "run_naruto_sub51n_pressed_runtime_qa.ps1"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$PatchLog = Join-Path $Logs "naruto_sub51n_fix1_import_patch_$Stamp.log"
$FailZip = Join-Path $Logs "fail_naruto_sub51n_fix1_pressed_runtime_qa_upload.zip"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Write-Log([string]$s) {
    Write-Host $s
    Add-Content -LiteralPath $PatchLog -Value $s -Encoding UTF8
}

try {
    Write-Log "=== SUB51N FIX1 - MISSING SHUTIL IMPORT ==="
    Write-Log "No game assets or ISO are modified by this fix."
    Write-Log "Target: $QaPy"
    Write-Log "Runner: $Runner"

    if (-not (Test-Path -LiteralPath $QaPy)) {
        throw "QA Python script not found: $QaPy"
    }
    if (-not (Test-Path -LiteralPath $Runner)) {
        throw "QA runner not found: $Runner"
    }

    $Py = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $Py) { $Py = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $Py) { throw "Python not found." }

    $Backup = "$QaPy.pre_sub51n_fix1.bak"
    if (-not (Test-Path -LiteralPath $Backup)) {
        Copy-Item -LiteralPath $QaPy -Destination $Backup -Force
        Write-Log "Backup created: $Backup"
    } else {
        Write-Log "Backup already exists: $Backup"
    }

    $Text = [IO.File]::ReadAllText($QaPy, [Text.Encoding]::UTF8)

    # Match either "import shutil" or a comma-separated import containing shutil.
    $HasShutil = [regex]::IsMatch(
        $Text,
        '(?m)^\s*import\s+[^\r\n#]*\bshutil\b|^\s*from\s+shutil\s+import\s+'
    )

    if (-not $HasShutil) {
        # Insert after __future__ import when present; otherwise at file start.
        $Future = [regex]::Match($Text, '(?m)^from\s+__future__\s+import[^\r\n]*(?:\r?\n)')
        if ($Future.Success) {
            $Pos = $Future.Index + $Future.Length
            $Text = $Text.Insert($Pos, "import shutil`r`n")
        } else {
            $Text = "import shutil`r`n" + $Text
        }
        [IO.File]::WriteAllText($QaPy, $Text, (New-Object Text.UTF8Encoding($false)))
        Write-Log "Inserted: import shutil"
    } else {
        Write-Log "import shutil already present; no source edit needed."
    }

    # Syntax/import preflight.
    & $Py.Source -m py_compile $QaPy
    if ($LASTEXITCODE -ne 0) {
        throw "py_compile failed after FIX1."
    }
    Write-Log "py_compile: PASS"

    # Verify the source really imports shutil.
    & $Py.Source -c "import ast,sys; p=sys.argv[1]; t=ast.parse(open(p,encoding='utf-8-sig').read()); ok=any((isinstance(n,ast.Import) and any(a.name=='shutil' for a in n.names)) or (isinstance(n,ast.ImportFrom) and n.module=='shutil') for n in ast.walk(t)); print('shutil import AST check:', 'PASS' if ok else 'FAIL'); raise SystemExit(0 if ok else 1)" $QaPy
    if ($LASTEXITCODE -ne 0) {
        throw "AST check says shutil is still not imported."
    }

    Write-Log "Starting existing SUB51N pressed-runtime QA runner..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner
    $Code = $LASTEXITCODE
    Write-Log "Existing runner exit code: $Code"

    if ($Code -ne 0) {
        throw "Pressed runtime QA still failed after shutil FIX1. ExitCode=$Code"
    }

    Write-Log "SUB51N FIX1 wrapper SUCCESS"
}
catch {
    Write-Log ("SUB51N FIX1 wrapper FAILED: " + $_.Exception.Message)

    $Tmp = Join-Path $Logs "_sub51n_fix1_fail_upload"
    if (Test-Path $Tmp) { Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

    @(
        "Naruto SUB51N FIX1 FAILURE",
        "Timestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Error=$($_.Exception.Message)",
        "",
        ($_ | Out-String)
    ) | Set-Content (Join-Path $Tmp "FAILURE.txt") -Encoding UTF8

    foreach ($p in @($PatchLog,$QaPy,$Runner,"$QaPy.pre_sub51n_fix1.bak")) {
        if (Test-Path -LiteralPath $p) {
            Copy-Item -LiteralPath $p -Destination (Join-Path $Tmp (Split-Path $p -Leaf)) -Force
        }
    }

    # Include the original QA failure package if the existing runner produced it.
    $OldFail = Join-Path $Logs "fail_naruto_sub51n_pressed_runtime_qa_upload.zip"
    if (Test-Path -LiteralPath $OldFail) {
        Copy-Item -LiteralPath $OldFail -Destination (Join-Path $Tmp (Split-Path $OldFail -Leaf)) -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $FailZip) { Remove-Item $FailZip -Force -ErrorAction SilentlyContinue }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Tmp, $FailZip, [System.IO.Compression.CompressionLevel]::Optimal, $false
    )
    Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "FIX1 failure ZIP: $FailZip"
    exit 1
}
