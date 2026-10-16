$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_cuda"
$diag = Join-Path $stage "smoke_diag"
$cli = Join-Path $stage "llama_cuda\llama-cli.exe"
$model = Join-Path $stage "models\Qwen3-VL-2B-Instruct-Q8_0.gguf"
$mmproj = Join-Path $stage "models\mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf"
$image = Join-Path $base "analysis\stage38a\naruto_stage38a_payload\images\001_part1_p1_g1.jpg"

New-Item -ItemType Directory -Force -Path $diag | Out-Null

foreach ($p in @($cli,$model,$mmproj,$image)) {
    if (-not (Test-Path -LiteralPath $p)) {
        throw "필수 파일 없음: $p"
    }
}

$prompt = @'
이 이미지는 게임 영상에서 잘라낸 자막/대사 영역이다.
화면에 실제로 보이는 글자만 정확히 전사하라.
번역, 의역, 요약, 추측, 설명을 하지 마라.
글자가 전혀 없으면 [EMPTY]라고 적는다.
반드시 아래 형식만 출력한다.
<OCR>
화면의 실제 텍스트
</OCR>
'@

function Q([string]$s) {
    '"' + $s.Replace('"','\"') + '"'
}

function Run-Test {
    param(
        [string]$Name,
        [string[]]$ExtraArgs
    )

    $stdout = Join-Path $diag ($Name + "_stdout.txt")
    $stderr = Join-Path $diag ($Name + "_stderr.txt")
    $meta   = Join-Path $diag ($Name + "_meta.txt")

    Remove-Item -LiteralPath $stdout,$stderr,$meta -Force -ErrorAction SilentlyContinue

    $parts = @(
        "-m", (Q $model),
        "--mmproj", (Q $mmproj),
        "--image", (Q $image),
        "-p", (Q $prompt),
        "-ngl", "99",
        "-c", "4096",
        "--temp", "0",
        "--top-k", "1",
        "--top-p", "1",
        "-n", "160",
        "--log-colors", "off"
    ) + $ExtraArgs

    $argString = $parts -join " "

    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Name
    Write-Host "============================================================"
    Write-Host $argString
    Write-Host ""

    $sw = [Diagnostics.Stopwatch]::StartNew()

    $proc = Start-Process `
        -FilePath $cli `
        -ArgumentList $argString `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    $finished = $proc.WaitForExit(120000)

    if (-not $finished) {
        try { $proc.Kill() } catch {}
        $sw.Stop()

        @(
            "name=$Name"
            "status=TIMEOUT"
            "elapsed_seconds=$([math]::Round($sw.Elapsed.TotalSeconds,3))"
        ) | Set-Content -LiteralPath $meta -Encoding UTF8

        Write-Host "TIMEOUT (120초)"
        return [pscustomobject]@{
            name = $Name
            status = "TIMEOUT"
            exit_code = ""
            elapsed_seconds = [math]::Round($sw.Elapsed.TotalSeconds,3)
        }
    }

    $proc.Refresh()
    $sw.Stop()
    $exit = $proc.ExitCode

    $status = if ($exit -eq 0) { "PASS" } else { "FAIL" }

    # Convert common unsigned Windows NTSTATUS to hex for readability.
    $u = [uint32]$exit
    $hex = ('0x{0:X8}' -f $u)

    @(
        "name=$Name"
        "status=$status"
        "exit_code=$exit"
        "exit_hex=$hex"
        "elapsed_seconds=$([math]::Round($sw.Elapsed.TotalSeconds,3))"
        "args=$argString"
    ) | Set-Content -LiteralPath $meta -Encoding UTF8

    Write-Host "status=$status  exit=$exit ($hex)  elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,2))s"

    if (Test-Path -LiteralPath $stderr) {
        Write-Host ""
        Write-Host "--- stderr tail ---"
        Get-Content -LiteralPath $stderr -Tail 25 -ErrorAction SilentlyContinue
    }

    if (Test-Path -LiteralPath $stdout) {
        Write-Host ""
        Write-Host "--- stdout tail ---"
        Get-Content -LiteralPath $stdout -Tail 15 -ErrorAction SilentlyContinue
    }

    return [pscustomobject]@{
        name = $Name
        status = $status
        exit_code = $exit
        exit_hex = $hex
        elapsed_seconds = [math]::Round($sw.Elapsed.TotalSeconds,3)
    }
}

Write-Host "RTX 3070 Qwen3-VL smoke matrix"
Write-Host "CLI: $cli"
Write-Host "Image: $image"
Write-Host ""
Write-Host "현재 VRAM:"
& nvidia-smi.exe --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader

$rows = @()

# A: Original failing condition.
$rows += Run-Test "A_baseline_full_cuda" @()

# B: Known Qwen3-VL high image-token/non-causal-attention workaround candidate.
$rows += Run-Test "B_large_ubatch" @(
    "-b","2048",
    "-ub","2048"
)

# C: Bound dynamic image token count and keep sufficient ubatch.
$rows += Run-Test "C_limit_image_tokens" @(
    "-b","1024",
    "-ub","1024",
    "--image-max-tokens","512"
)

# D: Keep main LLM on RTX 3070 but run vision projector on CPU.
$rows += Run-Test "D_cpu_mmproj" @(
    "--no-mmproj-offload",
    "-b","1024",
    "-ub","1024",
    "--image-max-tokens","512"
)

$csv = Join-Path $diag "smoke_matrix.csv"
$rows | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "============================================================"
Write-Host "SUMMARY"
Write-Host "============================================================"
$rows | Format-Table -AutoSize

Write-Host ""
Write-Host "진단 결과:"
Write-Host $diag
Write-Host ""
Write-Host "smoke_matrix.csv와 FAIL한 테스트의 stderr 마지막 부분을 올려주세요."
Write-Host "이 창은 자동으로 닫히지 않습니다."
