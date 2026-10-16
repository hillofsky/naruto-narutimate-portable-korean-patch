$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"

$runner = Join-Path `
    $base `
    "run_stage28_immediate_unicode_diag.ps1"

$driver = Join-Path `
    $base `
    "analysis\stage28\stage28_immediate_unicode_diag.py"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Stage28 runner 없음: $runner"
}

$old = "mod.ORIGINAL_UTF8_DECODER"
$new = "0x002AC8AC"

Write-Host ""
Write-Host "=========================================="
Write-Host " Stage28 decoder constant fix"
Write-Host "=========================================="
Write-Host ""

# ------------------------------------------------------------
# 1. Patch the runner source so future regenerations are fixed.
# ------------------------------------------------------------

$runnerText = Get-Content `
    -LiteralPath $runner `
    -Raw

if ($runnerText.Contains($old)) {

    $runnerText = $runnerText.Replace(
        $old,
        $new
    )

    Set-Content `
        -LiteralPath $runner `
        -Value $runnerText `
        -Encoding UTF8

    Write-Host "Runner 수정 완료:"
    Write-Host $runner
}
elseif ($runnerText.Contains($new)) {

    Write-Host "Runner는 이미 수정되어 있습니다."
}
else {

    throw "Runner에서 수정 대상 문자열을 찾지 못했습니다."
}


# ------------------------------------------------------------
# 2. Also patch the already-generated driver if present.
# ------------------------------------------------------------

if (Test-Path -LiteralPath $driver) {

    $driverText = Get-Content `
        -LiteralPath $driver `
        -Raw

    if ($driverText.Contains($old)) {

        $driverText = $driverText.Replace(
            $old,
            $new
        )

        Set-Content `
            -LiteralPath $driver `
            -Value $driverText `
            -Encoding UTF8

        Write-Host ""
        Write-Host "기존 driver도 수정 완료:"
        Write-Host $driver
    }
}


# ------------------------------------------------------------
# 3. PowerShell syntax validation
# ------------------------------------------------------------

$tokens = $null
$errors = $null

[System.Management.Automation.Language.Parser]::ParseFile(
    $runner,
    [ref]$tokens,
    [ref]$errors
) | Out-Null

if ($errors.Count -gt 0) {

    $errors | Format-List

    throw "수정 후 Stage28 runner PowerShell 문법 오류"
}


# ------------------------------------------------------------
# 4. If driver exists, Python syntax validation too.
# ------------------------------------------------------------

if (Test-Path -LiteralPath $driver) {

    & python -m py_compile $driver

    if ($LASTEXITCODE -ne 0) {
        throw "수정 후 Stage28 driver Python 문법 오류"
    }
}


Write-Host ""
Write-Host "수정 내용:"
Write-Host "  mod.ORIGINAL_UTF8_DECODER"
Write-Host "        ->"
Write-Host "  0x002AC8AC"
Write-Host ""
Write-Host "Stage28 재실행"
Write-Host ""


Set-ExecutionPolicy `
    -Scope Process `
    -ExecutionPolicy Bypass `
    -Force

& $runner
