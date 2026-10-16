$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$runner = Join-Path $base "run_stage38a_cuda_compare_fix.ps1"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "수정 대상 runner가 없습니다: $runner"
}

$backup = "$runner.bak_" + (Get-Date -Format "yyyyMMdd_HHmmss")
Copy-Item -LiteralPath $runner -Destination $backup -Force

$text = Get-Content -LiteralPath $runner -Raw

$oldBinary = '$_\.name -match "bin-win-cuda-12\\\.4-x64\\\.zip\$"'
$oldCuda   = '$_\.name -match "\^cudart-\.\*bin-win-cuda-12\\\.4-x64\\\.zip\$"'

# Replace the overly broad binary selector.
# The old selector also matched:
#   cudart-llama-bin-win-cuda-12.4-x64.zip
# which caused both $binAsset and $cudaAsset to point at the same DLL-only archive.
$newText = [regex]::Replace(
    $text,
    $oldBinary,
    '$_.name -match "^llama-.*-bin-win-cuda-12\.4-x64\.zip$"'
)

# Keep / normalize the cudart selector.
$newText = [regex]::Replace(
    $newText,
    $oldCuda,
    '$_.name -match "^cudart-llama-bin-win-cuda-12\.4-x64\.zip$"'
)

if ($newText -eq $text) {
    # Fallback for exact text emitted by the previous package.
    $newText = $text.Replace(
        '$_.name -match "bin-win-cuda-12\.4-x64\.zip$"',
        '$_.name -match "^llama-.*-bin-win-cuda-12\.4-x64\.zip$"'
    )

    $newText = $newText.Replace(
        '$_.name -match "^cudart-.*bin-win-cuda-12\.4-x64\.zip$"',
        '$_.name -match "^cudart-llama-bin-win-cuda-12\.4-x64\.zip$"'
    )
}

if ($newText -eq $text) {
    throw @"
자동 수정할 asset 선택 코드를 찾지 못했습니다.
수정 대상:
$runner
백업:
$backup
"@
}

Set-Content `
    -LiteralPath $runner `
    -Value $newText `
    -Encoding UTF8

Write-Host ""
Write-Host "Stage38A-CUDA asset selector 수정 완료"
Write-Host "Backup:"
Write-Host $backup
Write-Host ""
Write-Host "수정 내용:"
Write-Host '  Binary: ^llama-.*-bin-win-cuda-12\.4-x64\.zip$'
Write-Host '  DLL:    ^cudart-llama-bin-win-cuda-12\.4-x64\.zip$'
Write-Host ""

# Remove only the incorrectly extracted runtime folder.
# Keep downloaded archives, model cache, and prior failure logs.
$runtime = Join-Path $base "analysis\stage38a_cuda\llama_cuda"

if (Test-Path -LiteralPath $runtime) {
    Remove-Item `
        -LiteralPath $runtime `
        -Recurse `
        -Force
}

Write-Host "Stage38A-CUDA 다시 실행합니다..."
Write-Host ""

powershell.exe `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $runner

exit $LASTEXITCODE
