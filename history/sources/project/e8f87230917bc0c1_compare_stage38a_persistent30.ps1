$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage38a_persistent30"

$a = Join-Path $stage "results_3070\persistent30_summary.json"
$b = Join-Path $stage "results_bc250\persistent30_summary.json"

if (-not (Test-Path $a)) {
    throw "RTX 3070 summary 없음: $a"
}
if (-not (Test-Path $b)) {
    throw "BC250 summary 없음: $b"
}

$j3070 = Get-Content $a -Raw | ConvertFrom-Json
$jbc = Get-Content $b -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "============================================================"
Write-Host " Persistent-30 comparison"
Write-Host "============================================================"
Write-Host ""

"{0,-16} {1,12} {2,12} {3,12} {4,12}" -f `
    "Device","Startup(s)","First(s)","WarmMean(s)","img/s"

"{0,-16} {1,12:N3} {2,12:N3} {3,12:N3} {4,12:N3}" -f `
    "RTX 3070", `
    [double]$j3070.server_startup_seconds, `
    [double]$j3070.first_request_seconds, `
    [double]$j3070.warm_mean_seconds, `
    [double]$j3070.warm_images_per_second

"{0,-16} {1,12:N3} {2,12:N3} {3,12:N3} {4,12:N3}" -f `
    "BC250", `
    [double]$jbc.server_startup_seconds, `
    [double]$jbc.first_request_seconds, `
    [double]$jbc.warm_mean_seconds, `
    [double]$jbc.warm_images_per_second

Write-Host ""

$ratio = [double]$jbc.warm_mean_seconds / [double]$j3070.warm_mean_seconds
Write-Host ("BC250 warm mean / RTX3070 warm mean = {0:N2}x" -f $ratio)
Write-Host ""
