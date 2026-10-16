# Naruto PSP Stage 38C - Persistent30 EXACT workload
# RTX 3070 comparison against the uploaded BC250 persistent30 benchmark.
#
# Ground truth copied from naruto_persistent30_bc250_upload(3).zip:
# - 30 samples, exact original_sample indices and order
# - exact OCR prompt
# - one llama-server process / one model load / 30 sequential requests
# - BC250: n_threads=8, n_slots=4, n_ctx_slot=4096, image prompt_n=660
# - BC250 warm(2-30): mean 1.848191s, median 1.827353s, p95 2.001356s
#
# NOTE: BC250 llama.cpp build = commit fb4b273.
# RTX runtime currently uses a different Windows llama.cpp build.
# This script matches the workload/configuration observable from the BC250 ZIP;
# software build/backend remain different and are reported explicitly.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "stage38c_persistent30_exact"
$StageDir   = Join-Path $Root "analysis\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_stage38c_persistent30_exact_$Stamp.log"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$CsvPath    = Join-Path $StageDir "persistent30_rtx3070_results.csv"
$CompareCsv = Join-Path $StageDir "persistent30_bc250_vs_rtx3070.csv"
$Manifest   = Join-Path $StageDir "persistent30_exact_manifest.csv"
$ServerLog  = Join-Path $StageDir "llama_server_$Stamp.log"
$ServerErr  = Join-Path $StageDir "llama_server_$Stamp.err.log"
$VersionTxt = Join-Path $StageDir "llama_server_version.txt"
$EnvTxt     = Join-Path $StageDir "ENVIRONMENT.txt"
$CmdTxt     = Join-Path $StageDir "SERVER_COMMAND.txt"
$GpuBefore  = Join-Path $StageDir "NVIDIA_BEFORE.txt"
$GpuAfter   = Join-Path $StageDir "NVIDIA_AFTER.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38c_persistent30_exact_upload.zip"

$Port = 8092
$BaseUrl = "httLOCAL_PATH"

# Exact BC250 benchmark values from uploaded persistent30_summary.json
$BC250First  = 1.4406653159999792
$BC250WarmMean = 1.848191054206897
$BC250WarmMedian = 1.8273534369999993
$BC250WarmP95 = 2.001355785599992
$BC250AllMean = 1.8346068629333332
$BC250Build = "0.5.0-dev build 1 commit fb4b273"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host (" " + $Text)
    Write-Host ("=" * 78)
}

function Find-FirstFile {
    param([string[]]$Roots,[string]$Filter,[scriptblock]$Predicate=$null)
    foreach ($r in $Roots) {
        if (-not (Test-Path $r)) { continue }
        $items = Get-ChildItem $r -Filter $Filter -File -Recurse -ErrorAction SilentlyContinue
        if ($Predicate) { $items = $items | Where-Object $Predicate }
        $hit = $items | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Get-Percentile {
    param([double[]]$Values,[double]$P)
    $s = @($Values | Sort-Object)
    if ($s.Count -eq 0) { return [double]::NaN }
    if ($s.Count -eq 1) { return [double]$s[0] }
    $rank = ($P / 100.0) * ($s.Count - 1)
    $lo = [int][Math]::Floor($rank)
    $hi = [int][Math]::Ceiling($rank)
    if ($lo -eq $hi) { return [double]$s[$lo] }
    $w = $rank - $lo
    return ([double]$s[$lo]*(1-$w)) + ([double]$s[$hi]*$w)
}

function Save-NvidiaSmi([string]$Path) {
    if (Test-Path $Path) { Remove-Item $Path -Force }
    $nvsmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvsmi) { $nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue }
    if (-not $nvsmi) {
        "nvidia-smi not found" | Set-Content $Path -Encoding UTF8
        return
    }
    $cmd = '"' + $nvsmi.Source + '" 2>&1'
    & $env:ComSpec /d /s /c $cmd | ForEach-Object {
        $line=[string]$_
        Write-Host $line
        $line | Out-File $Path -Append -Encoding utf8
    }
}

function Normalize-Ocr([string]$Text) {
    if ($null -eq $Text) { return "" }
    $x = $Text -replace "`r`n","`n" -replace "`r","`n"
    return $x.Trim()
}

function Get-TimingValue($Obj,[string]$Name) {
    if ($null -eq $Obj) { return $null }
    $p = $Obj.PSObject.Properties[$Name]
    if ($p) { return $p.Value }
    return $null
}

# Exact manifest + BC250 OCR result from the uploaded ZIP.
$ExactRows = @'
[
  {
    "persistent_index": 1,
    "original_sample": 1,
    "video_part": "part1",
    "part_index": 1,
    "global_index": 1,
    "timestamp_seconds": 4.4044,
    "timestamp": "00:00:04.404",
    "bc250_image_file": "images/01_part1_orig1.jpg",
    "bc250_wall_seconds": 1.4407,
    "bc250_prompt_ms": 1238.993,
    "bc250_predicted_ms": 135.488,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 19,
    "bc250_ocr_text": "원작 - 키시모토 마사시"
  },
  {
    "persistent_index": 2,
    "original_sample": 5,
    "video_part": "part1",
    "part_index": 102,
    "global_index": 102,
    "timestamp_seconds": 512.1116,
    "timestamp": "00:08:32.112",
    "bc250_image_file": "images/02_part1_orig5.jpg",
    "bc250_wall_seconds": 1.7817,
    "bc250_prompt_ms": 1068.598,
    "bc250_predicted_ms": 79.356,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 10,
    "bc250_ocr_text": "규칙"
  },
  {
    "persistent_index": 3,
    "original_sample": 9,
    "video_part": "part1",
    "part_index": 204,
    "global_index": 204,
    "timestamp_seconds": 993.3924000000001,
    "timestamp": "00:16:33.392",
    "bc250_image_file": "images/03_part1_orig9.jpg",
    "bc250_wall_seconds": 1.8387,
    "bc250_prompt_ms": 1069.455,
    "bc250_predicted_ms": 158.783,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 22,
    "bc250_ocr_text": "시카마우\n뭔가 상태가 좀 이상한데…?"
  },
  {
    "persistent_index": 4,
    "original_sample": 14,
    "video_part": "part1",
    "part_index": 331,
    "global_index": 331,
    "timestamp_seconds": 1574.6731,
    "timestamp": "00:26:14.673",
    "bc250_image_file": "images/04_part1_orig14.jpg",
    "bc250_wall_seconds": 1.7799,
    "bc250_prompt_ms": 1069.393,
    "bc250_predicted_ms": 107.648,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 14,
    "bc250_ocr_text": "사쿠라\n…!?"
  },
  {
    "persistent_index": 5,
    "original_sample": 18,
    "video_part": "part1",
    "part_index": 432,
    "global_index": 432,
    "timestamp_seconds": 2061.2592,
    "timestamp": "00:34:21.259",
    "bc250_image_file": "images/05_part1_orig18.jpg",
    "bc250_wall_seconds": 1.8005,
    "bc250_prompt_ms": 1069.797,
    "bc250_predicted_ms": 102.553,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 13,
    "bc250_ocr_text": "나두토\n…!"
  },
  {
    "persistent_index": 6,
    "original_sample": 22,
    "video_part": "part1",
    "part_index": 534,
    "global_index": 534,
    "timestamp_seconds": 2614.7121,
    "timestamp": "00:43:34.712",
    "bc250_image_file": "images/06_part1_orig22.jpg",
    "bc250_wall_seconds": 2.0199,
    "bc250_prompt_ms": 1071.376,
    "bc250_predicted_ms": 350.527,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 44,
    "bc250_ocr_text": "카카시\n아마도… 성이 봉인될 때 잔존사람으로 남은 사람들의 기억도 봉인된 거겠지."
  },
  {
    "persistent_index": 7,
    "original_sample": 26,
    "video_part": "part1",
    "part_index": 635,
    "global_index": 635,
    "timestamp_seconds": 3067.3643,
    "timestamp": "00:51:07.364",
    "bc250_image_file": "images/07_part1_orig26.jpg",
    "bc250_wall_seconds": 1.8494,
    "bc250_prompt_ms": 1071.576,
    "bc250_predicted_ms": 120.352,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 15,
    "bc250_ocr_text": "나두토\n젠장…!!"
  },
  {
    "persistent_index": 8,
    "original_sample": 31,
    "video_part": "part1",
    "part_index": 762,
    "global_index": 762,
    "timestamp_seconds": 3694.2906000000003,
    "timestamp": "01:01:34.291",
    "bc250_image_file": "images/08_part1_orig31.jpg",
    "bc250_wall_seconds": 1.8274,
    "bc250_prompt_ms": 1071.036,
    "bc250_predicted_ms": 151.807,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 21,
    "bc250_ocr_text": "사쿠라\n아… 야! 기다려…!"
  },
  {
    "persistent_index": 9,
    "original_sample": 35,
    "video_part": "part1",
    "part_index": 864,
    "global_index": 864,
    "timestamp_seconds": 4148.5444,
    "timestamp": "01:09:08.544",
    "bc250_image_file": "images/09_part1_orig35.jpg",
    "bc250_wall_seconds": 1.8311,
    "bc250_prompt_ms": 1072.695,
    "bc250_predicted_ms": 123.019,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 16,
    "bc250_ocr_text": "나두토\n뭐지…!!?"
  },
  {
    "persistent_index": 10,
    "original_sample": 39,
    "video_part": "part1",
    "part_index": 965,
    "global_index": 965,
    "timestamp_seconds": 4597.7932,
    "timestamp": "01:16:37.793",
    "bc250_image_file": "images/10_part1_orig39.jpg",
    "bc250_wall_seconds": 1.7631,
    "bc250_prompt_ms": 1071.312,
    "bc250_predicted_ms": 78.243,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 10,
    "bc250_ocr_text": "규칙"
  },
  {
    "persistent_index": 11,
    "original_sample": 43,
    "video_part": "part1",
    "part_index": 1067,
    "global_index": 1067,
    "timestamp_seconds": 5127.122,
    "timestamp": "01:25:27.122",
    "bc250_image_file": "images/11_part1_orig43.jpg",
    "bc250_wall_seconds": 1.9013,
    "bc250_prompt_ms": 1068.052,
    "bc250_predicted_ms": 217.425,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 29,
    "bc250_ocr_text": "카부토\n빨리 없애버리도록… 알겠지, 카스미?"
  },
  {
    "persistent_index": 12,
    "original_sample": 47,
    "video_part": "part1",
    "part_index": 1168,
    "global_index": 1168,
    "timestamp_seconds": 5644.7391,
    "timestamp": "01:34:04.739",
    "bc250_image_file": "images/12_part1_orig47.jpg",
    "bc250_wall_seconds": 1.762,
    "bc250_prompt_ms": 1067.702,
    "bc250_predicted_ms": 88.618,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 11,
    "bc250_ocr_text": "카부토"
  },
  {
    "persistent_index": 13,
    "original_sample": 52,
    "video_part": "part1",
    "part_index": 1295,
    "global_index": 1295,
    "timestamp_seconds": 6272.1659,
    "timestamp": "01:44:32.166",
    "bc250_image_file": "images/13_part1_orig52.jpg",
    "bc250_wall_seconds": 1.8811,
    "bc250_prompt_ms": 1070.556,
    "bc250_predicted_ms": 181.082,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 25,
    "bc250_ocr_text": "카스미\n그래… 저걸 부수면… 성은 사라져…"
  },
  {
    "persistent_index": 14,
    "original_sample": 56,
    "video_part": "part1",
    "part_index": 1397,
    "global_index": 1397,
    "timestamp_seconds": 6808.9021,
    "timestamp": "01:53:28.902",
    "bc250_image_file": "images/14_part1_orig56.jpg",
    "bc250_wall_seconds": 1.805,
    "bc250_prompt_ms": 1071.159,
    "bc250_predicted_ms": 101.694,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 13,
    "bc250_ocr_text": "카스미\n....."
  },
  {
    "persistent_index": 15,
    "original_sample": 60,
    "video_part": "part1",
    "part_index": 1498,
    "global_index": 1498,
    "timestamp_seconds": 7327.7204,
    "timestamp": "02:02:07.720",
    "bc250_image_file": "images/15_part1_orig60.jpg",
    "bc250_wall_seconds": 1.785,
    "bc250_prompt_ms": 1067.691,
    "bc250_predicted_ms": 113.677,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 15,
    "bc250_ocr_text": "(그치?… 누나!)"
  },
  {
    "persistent_index": 16,
    "original_sample": 61,
    "video_part": "part2",
    "part_index": 1,
    "global_index": 1499,
    "timestamp_seconds": 4.0040000000000004,
    "timestamp": "00:00:04.004",
    "bc250_image_file": "images/16_part2_orig61.jpg",
    "bc250_wall_seconds": 1.8112,
    "bc250_prompt_ms": 1067.103,
    "bc250_predicted_ms": 142.141,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 19,
    "bc250_ocr_text": "원작 - 키시모토 마사시"
  },
  {
    "persistent_index": 17,
    "original_sample": 65,
    "video_part": "part2",
    "part_index": 41,
    "global_index": 1539,
    "timestamp_seconds": 189.2891,
    "timestamp": "00:03:09.289",
    "bc250_image_file": "images/17_part2_orig65.jpg",
    "bc250_wall_seconds": 2.0179,
    "bc250_prompt_ms": 1067.131,
    "bc250_predicted_ms": 312.222,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 42,
    "bc250_ocr_text": "지라이야\n미안하지만 나 말고 3명 정도 담자를 데려가고 싶은데…\n누구 없나?"
  },
  {
    "persistent_index": 18,
    "original_sample": 69,
    "video_part": "part2",
    "part_index": 81,
    "global_index": 1579,
    "timestamp_seconds": 356.6563,
    "timestamp": "00:05:56.656",
    "bc250_image_file": "images/18_part2_orig69.jpg",
    "bc250_wall_seconds": 1.7995,
    "bc250_prompt_ms": 1067.722,
    "bc250_predicted_ms": 110.953,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 14,
    "bc250_ocr_text": "지라이야\n....."
  },
  {
    "persistent_index": 19,
    "original_sample": 74,
    "video_part": "part2",
    "part_index": 130,
    "global_index": 1628,
    "timestamp_seconds": 583.3828,
    "timestamp": "00:09:43.383",
    "bc250_image_file": "images/19_part2_orig74.jpg",
    "bc250_wall_seconds": 1.8176,
    "bc250_prompt_ms": 1068.481,
    "bc250_predicted_ms": 115.702,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 15,
    "bc250_ocr_text": "지라이야\n…!?"
  },
  {
    "persistent_index": 20,
    "original_sample": 78,
    "video_part": "part2",
    "part_index": 170,
    "global_index": 1668,
    "timestamp_seconds": 767.0663000000001,
    "timestamp": "00:12:47.066",
    "bc250_image_file": "images/20_part2_orig78.jpg",
    "bc250_wall_seconds": 1.899,
    "bc250_prompt_ms": 1070.883,
    "bc250_predicted_ms": 213.228,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 29,
    "bc250_ocr_text": "지라이야\n그거 말인데…. 잠깐 좀 도와줬으면 하는 일이 있어서…"
  },
  {
    "persistent_index": 21,
    "original_sample": 82,
    "video_part": "part2",
    "part_index": 210,
    "global_index": 1708,
    "timestamp_seconds": 944.6437,
    "timestamp": "00:15:44.644",
    "bc250_image_file": "images/21_part2_orig82.jpg",
    "bc250_wall_seconds": 1.9156,
    "bc250_prompt_ms": 1066.668,
    "bc250_predicted_ms": 220.687,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 30,
    "bc250_ocr_text": "카스미\n어라? 아름다운 눈동자의 행상인이 아니었나요?"
  },
  {
    "persistent_index": 22,
    "original_sample": 86,
    "video_part": "part2",
    "part_index": 250,
    "global_index": 1748,
    "timestamp_seconds": 1132.4313,
    "timestamp": "00:18:52.431",
    "bc250_image_file": "images/22_part2_orig86.jpg",
    "bc250_wall_seconds": 1.8593,
    "bc250_prompt_ms": 1066.964,
    "bc250_predicted_ms": 187.018,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 24,
    "bc250_ocr_text": "즈나데\n그건 그렇고 카스미 공주라…"
  },
  {
    "persistent_index": 23,
    "original_sample": 91,
    "video_part": "part2",
    "part_index": 299,
    "global_index": 1797,
    "timestamp_seconds": 1369.2679,
    "timestamp": "00:22:49.268",
    "bc250_image_file": "images/23_part2_orig91.jpg",
    "bc250_wall_seconds": 1.8037,
    "bc250_prompt_ms": 1068.57,
    "bc250_predicted_ms": 101.075,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 13,
    "bc250_ocr_text": "즈나데\n그래!"
  },
  {
    "persistent_index": 24,
    "original_sample": 95,
    "video_part": "part2",
    "part_index": 339,
    "global_index": 1837,
    "timestamp_seconds": 1626.7251,
    "timestamp": "00:27:06.725",
    "bc250_image_file": "images/24_part2_orig95.jpg",
    "bc250_wall_seconds": 1.9766,
    "bc250_prompt_ms": 1073.56,
    "bc250_predicted_ms": 282.594,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 37,
    "bc250_ocr_text": "카부토\n해에… 대단하군요. 설마 그의 환영을 쓰러뜨리다니…"
  },
  {
    "persistent_index": 25,
    "original_sample": 99,
    "video_part": "part2",
    "part_index": 379,
    "global_index": 1877,
    "timestamp_seconds": 1865.864,
    "timestamp": "00:31:05.864",
    "bc250_image_file": "images/25_part2_orig99.jpg",
    "bc250_wall_seconds": 1.8379,
    "bc250_prompt_ms": 1070.317,
    "bc250_predicted_ms": 135.345,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 17,
    "bc250_ocr_text": "오로치마두\n자, 그럼…"
  },
  {
    "persistent_index": 26,
    "original_sample": 103,
    "video_part": "part2",
    "part_index": 419,
    "global_index": 1917,
    "timestamp_seconds": 2088.0860000000002,
    "timestamp": "00:34:48.086",
    "bc250_image_file": "images/26_part2_orig103.jpg",
    "bc250_wall_seconds": 1.8051,
    "bc250_prompt_ms": 1070.386,
    "bc250_predicted_ms": 114.854,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 15,
    "bc250_ocr_text": "즈나데\n아… 그래…"
  },
  {
    "persistent_index": 27,
    "original_sample": 107,
    "video_part": "part2",
    "part_index": 459,
    "global_index": 1957,
    "timestamp_seconds": 2340.2379,
    "timestamp": "00:39:00.238",
    "bc250_image_file": "images/27_part2_orig107.jpg",
    "bc250_wall_seconds": 1.8213,
    "bc250_prompt_ms": 1067.761,
    "bc250_predicted_ms": 123.291,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 16,
    "bc250_ocr_text": "시즈네\n으아악…!"
  },
  {
    "persistent_index": 28,
    "original_sample": 112,
    "video_part": "part2",
    "part_index": 508,
    "global_index": 2006,
    "timestamp_seconds": 2560.7582,
    "timestamp": "00:42:40.758",
    "bc250_image_file": "images/28_part2_orig112.jpg",
    "bc250_wall_seconds": 1.9618,
    "bc250_prompt_ms": 1067.774,
    "bc250_predicted_ms": 258.102,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 34,
    "bc250_ocr_text": "지라이야\n흥… 우리들이 쓰러지면 나못잎 마을을… 구할 수 없잖아…"
  },
  {
    "persistent_index": 29,
    "original_sample": 116,
    "video_part": "part2",
    "part_index": 548,
    "global_index": 2046,
    "timestamp_seconds": 2755.0523,
    "timestamp": "00:45:55.052",
    "bc250_image_file": "images/29_part2_orig116.jpg",
    "bc250_wall_seconds": 1.86,
    "bc250_prompt_ms": 1072.375,
    "bc250_predicted_ms": 157.862,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 20,
    "bc250_ocr_text": "오로치마속\n하아… 하아 …."
  },
  {
    "persistent_index": 30,
    "original_sample": 120,
    "video_part": "part2",
    "part_index": 588,
    "global_index": 2086,
    "timestamp_seconds": 2971.6687,
    "timestamp": "00:49:31.669",
    "bc250_image_file": "images/30_part2_orig120.jpg",
    "bc250_wall_seconds": 1.7853,
    "bc250_prompt_ms": 1071.12,
    "bc250_predicted_ms": 101.073,
    "bc250_prompt_n": 660,
    "bc250_predicted_n": 13,
    "bc250_ocr_text": "(3대…!)"
  }
]
'@ | ConvertFrom-Json

# Exact BC250 OCR prompt from persistent30_summary.json
$Prompt = @'
이 이미지는 게임 영상에서 잘라낸 자막/대사 영역이다.
화면에 실제로 보이는 글자만 정확히 전사하라.

규칙:
- 한국어, 일본어, 영어, 숫자, 문장부호를 보이는 그대로 적는다.
- 번역, 의역, 요약, 추측, 설명을 하지 않는다.
- 줄바꿈은 화면에 보이는 대로 최대한 유지한다.
- 글자가 전혀 없으면 [EMPTY]라고 적는다.
- 판독할 수 없는 글자만 [불명]으로 표시한다.
- 이미지에 없는 문장을 만들어내지 않는다.

반드시 아래 형식만 출력한다.
<OCR>
화면의 실제 텍스트
</OCR>
'@

$Succeeded = $false
$ServerProc = $null
$Caught = $null
$Results = @()
$Samples = @()

Start-Transcript -Path $Transcript -Force | Out-Null

try {
    Write-Section "Naruto Stage38C - exact BC250 persistent30 workload on RTX 3070"
    Write-Host "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "BC250 warm mean : $([Math]::Round($BC250WarmMean,3)) sec/image"
    Write-Host "BC250 all mean  : $([Math]::Round($BC250AllMean,3)) sec/image"
    Write-Host "Exact order      : Part1 15, then Part2 15"

    Write-Section "1/8 - Runtime/model/mmproj"

    $runtimeRoots=@(
        (Join-Path $Root "analysis\stage38a_cuda\cuda_runtime"),
        (Join-Path $Root "analysis\stage38a_cuda"),
        (Join-Path $Root "analysis")
    )
    $ServerExe = Find-FirstFile $runtimeRoots "llama-server.exe"
    if (-not $ServerExe) { throw "llama-server.exe를 찾지 못했습니다." }

    $modelRoots=@(
        (Join-Path $Root "analysis\stage38a_cuda\models"),
        (Join-Path $Root "models"),
        (Join-Path $Root "analysis\stage38a_cuda")
    )
    $Model = Find-FirstFile $modelRoots "*Qwen3*VL*2B*Q8_0*.gguf" { $_.Name -notmatch '^mmproj' }
    $Mmproj = Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*Q8_0*.gguf"
    if (-not $Mmproj) { $Mmproj = Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*.gguf" }

    if (-not $Model) { throw "Qwen3-VL-2B-Instruct-Q8_0.gguf를 찾지 못했습니다." }
    if (-not $Mmproj) { throw "Qwen3-VL-2B mmproj를 찾지 못했습니다." }

    Write-Host "server : $ServerExe"
    Write-Host "model  : $Model"
    Write-Host "mmproj : $Mmproj"

    # Capture RTX llama.cpp build.
    $verCmd = '"' + $ServerExe + '" --version 2>&1'
    & $env:ComSpec /d /s /c $verCmd | Set-Content $VersionTxt -Encoding UTF8
    Get-Content $VersionTxt | ForEach-Object { Write-Host $_ }

    Write-Section "2/8 - Resolve the EXACT 30 source images"

    $payloadCandidates=@(
        (Join-Path $Root "analysis\stage38a\naruto_stage38a_payload\images"),
        (Join-Path $Root "analysis\stage38a\images"),
        (Join-Path $Root "analysis\stage38\images")
    )
    $PayloadDir=$null
    foreach($d in $payloadCandidates) {
        if(Test-Path $d){ $PayloadDir=$d; break }
    }
    if(-not $PayloadDir){ throw "Stage38A 120장 이미지 폴더를 찾지 못했습니다." }

    $AllImages=@(Get-ChildItem $PayloadDir -File | Where-Object {
        $_.Extension -match '^\.(jpg|jpeg|png|webp)$'
    } | Sort-Object Name)

    if($AllImages.Count -lt 120){
        throw "원본 Stage38A 샘플이 120장 이상 필요합니다. 발견=$($AllImages.Count)"
    }

    foreach($r in $ExactRows) {
        $ordinal=[int]$r.original_sample
        $src=$AllImages[$ordinal-1]
        if(-not $src){ throw "original_sample=$ordinal 이미지를 찾지 못했습니다." }

        $Samples += [PSCustomObject]@{
            persistent_index=[int]$r.persistent_index
            original_sample=$ordinal
            video_part=[string]$r.video_part
            part_index=[int]$r.part_index
            global_index=[int]$r.global_index
            timestamp=[string]$r.timestamp
            source_file=$src
            bc250_image_file=[string]$r.bc250_image_file
            bc250_wall_seconds=[double]$r.bc250_wall_seconds
            bc250_prompt_ms=[double]$r.bc250_prompt_ms
            bc250_predicted_ms=[double]$r.bc250_predicted_ms
            bc250_prompt_n=[int]$r.bc250_prompt_n
            bc250_predicted_n=[int]$r.bc250_predicted_n
            bc250_ocr_text=[string]$r.bc250_ocr_text
        }
    }

    if($Samples.Count -ne 30){ throw "정확히 30장이 선택되지 않았습니다." }

    # Sanity check known first sample from previous Stage38A work.
    Write-Host "Payload dir: $PayloadDir"
    Write-Host "Total source images: $($AllImages.Count)"
    Write-Host ""
    foreach($s in $Samples){
        Write-Host ("[{0,2}] orig={1,3} {2} -> {3}" -f `
            $s.persistent_index,$s.original_sample,$s.video_part,$s.source_file.Name)
    }

    $Samples | Select-Object persistent_index,original_sample,video_part,part_index,global_index,timestamp,
        @{n="source_filename";e={$_.source_file.Name}},
        bc250_image_file,bc250_wall_seconds,bc250_prompt_n,bc250_predicted_n |
        Export-Csv $Manifest -NoTypeInformation -Encoding UTF8

    Write-Section "3/8 - GPU/environment"

    @(
        "Timestamp=$Stamp",
        "Computer=$env:COMPUTERNAME",
        "PowerShell=$($PSVersionTable.PSVersion)",
        "SERVER=$ServerExe",
        "MODEL=$Model",
        "MMPROJ=$Mmproj",
        "PAYLOAD=$PayloadDir",
        "BC250_BUILD=$BC250Build",
        "BC250_WARM_MEAN=$BC250WarmMean",
        "BC250_WARM_MEDIAN=$BC250WarmMedian",
        "BC250_WARM_P95=$BC250WarmP95",
        "BC250_ALL_MEAN=$BC250AllMean"
    ) | Set-Content $EnvTxt -Encoding UTF8

    Save-NvidiaSmi $GpuBefore

    Write-Section "4/8 - Start one persistent llama-server"

    # Values observable in BC250 llama_server_bc250.log:
    # n_threads=8, n_slots=4, n_ctx_slot=4096.
    # Thus total ctx is set to 16384 with 4 parallel slots.
    # prompt_n=660 is reproduced with image_max_tokens=512.
    # -ngl 99 ensures full GPU offload on the RTX backend.
    #
    # Batch/ubatch were NOT recorded in the BC250 upload, so they are left at
    # this llama.cpp build's defaults rather than inventing values.
    $ServerArgs=@(
        "-m",$Model,
        "--mmproj",$Mmproj,
        "--host","127.0.0.1",
        "--port","$Port",
        "-t","8",
        "-np","4",
        "-c","16384",
        "-ngl","99",
        "--image-max-tokens","512"
    )

    function Quote-ProcArg([string]$Value) {
        if($null -eq $Value){ return '""' }
        return '"' + $Value.Replace('"','\"') + '"'
    }
    $ArgLine=(($ServerArgs | ForEach-Object { Quote-ProcArg ([string]$_) }) -join " ")
    ('"' + $ServerExe + '" ' + $ArgLine) | Set-Content $CmdTxt -Encoding UTF8
    Get-Content $CmdTxt | ForEach-Object { Write-Host $_ }

    if(Test-Path $ServerLog){Remove-Item $ServerLog -Force}
    if(Test-Path $ServerErr){Remove-Item $ServerErr -Force}

    # Ensure the comparison port is not already occupied.
    try {
        $occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if($occupied){ throw "TCP $Port 포트가 이미 사용 중입니다. 기존 서버를 종료한 뒤 다시 실행하세요." }
    } catch [System.Management.Automation.CommandNotFoundException] {}

    $startup=[Diagnostics.Stopwatch]::StartNew()
    $ServerProc=Start-Process `
        -FilePath $ServerExe `
        -ArgumentList $ArgLine `
        -RedirectStandardOutput $ServerLog `
        -RedirectStandardError $ServerErr `
        -PassThru `
        -WindowStyle Hidden

    Write-Host "PID: $($ServerProc.Id)"
    Write-Host "Waiting for /health ..."

    $ready=$false
    $deadline=(Get-Date).AddMinutes(3)
    while((Get-Date)-lt $deadline){
        if($ServerProc.HasExited){
            try{$ServerProc.WaitForExit()}catch{}
            try{$ServerProc.Refresh()}catch{}
            Write-Host ""
            Write-Host "----- stderr tail -----"
            if(Test-Path $ServerErr){Get-Content $ServerErr -Tail 100 | ForEach-Object{Write-Host $_}}
            Write-Host "----- stdout tail -----"
            if(Test-Path $ServerLog){Get-Content $ServerLog -Tail 50 | ForEach-Object{Write-Host $_}}
            $ec="unknown"; try{$ec=[string]$ServerProc.ExitCode}catch{}
            throw "llama-server exited before ready. ExitCode=$ec"
        }
        try {
            $null=Invoke-RestMethod "$BaseUrl/health" -Method Get -TimeoutSec 3
            $ready=$true; break
        } catch { Start-Sleep -Milliseconds 250 }
    }
    $startup.Stop()
    if(-not $ready){throw "llama-server가 3분 내 준비되지 않았습니다."}

    Write-Host ("Server ready: {0:N3}s" -f $startup.Elapsed.TotalSeconds)

    Write-Section "5/8 - 30 exact persistent requests"

    $runWall=[Diagnostics.Stopwatch]::StartNew()

    foreach($s in $Samples){
        $bytes=[IO.File]::ReadAllBytes($s.source_file.FullName)
        $b64=[Convert]::ToBase64String($bytes)
        $mime=switch($s.source_file.Extension.ToLowerInvariant()){
            ".png" {"image/png"}
            ".webp" {"image/webp"}
            default {"image/jpeg"}
        }
        $dataUri="data:$mime;base64,$b64"

        # Same prompt. Short OCR output, deterministic decoding.
        $body=@{
            model="qwen3-vl"
            temperature=0
            max_tokens=128
            messages=@(
                @{
                    role="user"
                    content=@(
                        @{type="text";text=$Prompt},
                        @{type="image_url";image_url=@{url=$dataUri}}
                    )
                }
            )
        } | ConvertTo-Json -Depth 12 -Compress

        Write-Host ""
        Write-Host ("[{0:D2}/30] {1} {2} {3}" -f `
            $s.persistent_index,$s.video_part,$s.timestamp,$s.source_file.Name)

        $sw=[Diagnostics.Stopwatch]::StartNew()
        $status="OK"; $ocr=""; $err=""
        $promptMs=$null; $predMs=$null; $promptN=$null; $predN=$null

        try{
            $resp=Invoke-RestMethod `
                -Uri "$BaseUrl/v1/chat/completions" `
                -Method Post `
                -ContentType "application/json; charset=utf-8" `
                -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
                -TimeoutSec 180

            $raw=[string]$resp.choices[0].message.content
            $m=[regex]::Match($raw,'(?s)<OCR>\s*(.*?)\s*</OCR>')
            if($m.Success){$ocr=$m.Groups[1].Value}else{$ocr=$raw}
            $ocr=Normalize-Ocr $ocr

            if($resp.PSObject.Properties["timings"]){
                $promptMs=Get-TimingValue $resp.timings "prompt_ms"
                $predMs=Get-TimingValue $resp.timings "predicted_ms"
                $promptN=Get-TimingValue $resp.timings "prompt_n"
                $predN=Get-TimingValue $resp.timings "predicted_n"
            }
        }catch{
            $status="ERROR"
            $err=$_.Exception.Message
        }

        $sw.Stop()
        $sec=[Math]::Round($sw.Elapsed.TotalSeconds,4)
        $same=((Normalize-Ocr $ocr) -ceq (Normalize-Ocr $s.bc250_ocr_text))

        if($status -eq "OK"){
            $preview=$ocr -replace "`n"," / "
            if($preview.Length -gt 150){$preview=$preview.Substring(0,150)+"..."}
            Write-Host ("  RTX {0:N4}s | BC250 {1:N4}s | sameOCR={2}" -f `
                $sec,$s.bc250_wall_seconds,$same)
            Write-Host ("  {0}" -f $preview)
        }else{
            Write-Host ("  ERROR {0:N4}s | {1}" -f $sec,$err)
        }

        $Results += [PSCustomObject]@{
            persistent_index=$s.persistent_index
            original_sample=$s.original_sample
            video_part=$s.video_part
            part_index=$s.part_index
            global_index=$s.global_index
            timestamp=$s.timestamp
            source_filename=$s.source_file.Name
            status=$status
            rtx_wall_seconds=$sec
            rtx_prompt_ms=$promptMs
            rtx_predicted_ms=$predMs
            rtx_prompt_n=$promptN
            rtx_predicted_n=$predN
            rtx_ocr_text=$ocr
            bc250_wall_seconds=$s.bc250_wall_seconds
            bc250_prompt_ms=$s.bc250_prompt_ms
            bc250_predicted_ms=$s.bc250_predicted_ms
            bc250_prompt_n=$s.bc250_prompt_n
            bc250_predicted_n=$s.bc250_predicted_n
            bc250_ocr_text=$s.bc250_ocr_text
            same_ocr_as_bc250=$same
            error=$err
        }
    }

    $runWall.Stop()
    $Results | Export-Csv $CsvPath -NoTypeInformation -Encoding UTF8
    $Results | Export-Csv $CompareCsv -NoTypeInformation -Encoding UTF8

    Write-Section "6/8 - Statistics"

    $ok=@($Results|Where-Object status -eq "OK")
    $fail=@($Results|Where-Object status -ne "OK")
    if($ok.Count -eq 0){throw "성공한 OCR 요청이 없습니다."}

    $allTimes=[double[]]@($ok|ForEach-Object{[double]$_.rtx_wall_seconds})
    $warmRows=@($ok|Where-Object{[int]$_.persistent_index -ge 2})
    $warmTimes=[double[]]@($warmRows|ForEach-Object{[double]$_.rtx_wall_seconds})

    $allMean=($allTimes|Measure-Object -Average).Average
    $first=[double]($ok|Where-Object persistent_index -eq 1|Select-Object -First 1).rtx_wall_seconds
    $warmMean=($warmTimes|Measure-Object -Average).Average
    $warmMedian=Get-Percentile $warmTimes 50
    $warmP95=Get-Percentile $warmTimes 95
    $sameCount=@($ok|Where-Object same_ocr_as_bc250 -eq $true).Count

    $speedRatio=$BC250WarmMean/$warmMean

    Write-Host ("Success             : {0}/30" -f $ok.Count)
    Write-Host ("RTX first           : {0:N4}s" -f $first)
    Write-Host ("RTX all mean        : {0:N4}s/image" -f $allMean)
    Write-Host ("RTX warm mean 2-30  : {0:N4}s/image" -f $warmMean)
    Write-Host ("RTX warm median     : {0:N4}s" -f $warmMedian)
    Write-Host ("RTX warm p95        : {0:N4}s" -f $warmP95)
    Write-Host ("BC250 warm mean     : {0:N4}s/image" -f $BC250WarmMean)
    Write-Host ("BC250 / RTX speed   : {0:N3}x" -f $speedRatio)
    Write-Host ("Identical OCR text  : {0}/30" -f $sameCount)
    Write-Host ("30 request wall     : {0:N3}s" -f $runWall.Elapsed.TotalSeconds)

    Write-Section "7/8 - Summary + GPU after"

    $rtxVer=(Get-Content $VersionTxt -Raw -ErrorAction SilentlyContinue).Trim()
    @(
        "Naruto Stage38C Persistent30 Exact Workload",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: $(if($fail.Count -eq 0){'SUCCESS'}else{'PARTIAL'})",
        "",
        "Source benchmark:",
        "naruto_persistent30_bc250_upload(3).zip",
        "BC250 build: $BC250Build",
        "RTX build: $rtxVer",
        "",
        "Matched workload:",
        "same 30 original_sample indices and order",
        "same exact OCR prompt",
        "one model load / 30 sequential requests",
        "threads=8",
        "parallel slots=4",
        "ctx total=16384 -> 4096 per slot",
        "image_max_tokens=512",
        "full GPU offload requested (-ngl 99)",
        "",
        "Important limitation:",
        "BC250 upload did not record batch/ubatch or the full original server CLI.",
        "Those are left at llama.cpp defaults. Backend and llama.cpp commit differ.",
        "",
        "BC250:",
        ("first={0:N4}s" -f $BC250First),
        ("all_mean={0:N4}s" -f $BC250AllMean),
        ("warm_mean={0:N4}s" -f $BC250WarmMean),
        ("warm_median={0:N4}s" -f $BC250WarmMedian),
        ("warm_p95={0:N4}s" -f $BC250WarmP95),
        "",
        "RTX3070:",
        ("success={0}/30" -f $ok.Count),
        ("first={0:N4}s" -f $first),
        ("all_mean={0:N4}s" -f $allMean),
        ("warm_mean={0:N4}s" -f $warmMean),
        ("warm_median={0:N4}s" -f $warmMedian),
        ("warm_p95={0:N4}s" -f $warmP95),
        ("same_ocr_as_bc250={0}/30" -f $sameCount),
        ("request_wall={0:N3}s" -f $runWall.Elapsed.TotalSeconds),
        "",
        ("BC250_warm_mean / RTX_warm_mean = {0:N3}x" -f $speedRatio)
    ) | Set-Content $Summary -Encoding UTF8

    Save-NvidiaSmi $GpuAfter

    if($fail.Count -gt 0){throw "일부 요청 실패: $($fail.Count)/30"}
    $Succeeded=$true

}catch{
    $Caught=$_
    $Succeeded=$false
    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38C FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_|Out-String)
    @(
        "Naruto Stage38C FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        "Message:",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    ) | Set-Content $FailureTxt -Encoding UTF8

}finally{
    Write-Section "8/8 - Stop server / package"

    if($ServerProc){
        try{
            if(-not $ServerProc.HasExited){
                Stop-Process -Id $ServerProc.Id -Force -ErrorAction SilentlyContinue
                $ServerProc.WaitForExit(5000)|Out-Null
            }
        }catch{}
    }

    try{Stop-Transcript|Out-Null}catch{}

    $PackageDir=Join-Path $StageDir "_upload_package"
    if(Test-Path $PackageDir){Remove-Item $PackageDir -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $PackageDir|Out-Null

    @($Summary,$CsvPath,$CompareCsv,$Manifest,$ServerLog,$ServerErr,$VersionTxt,
      $EnvTxt,$CmdTxt,$GpuBefore,$GpuAfter,$Transcript,$FailureTxt) |
      ForEach-Object {
        if($_ -and (Test-Path $_)){Copy-Item $_ $PackageDir -Force}
      }

    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-Item $PSCommandPath $PackageDir -Force
    }

    if($Samples.Count -gt 0){
        $imgDir=Join-Path $PackageDir "selected_images"
        New-Item -ItemType Directory -Force -Path $imgDir|Out-Null
        foreach($s in $Samples){
            if(Test-Path $s.source_file.FullName){
                $dst=Join-Path $imgDir ("{0:D2}_orig{1}_{2}" -f `
                    $s.persistent_index,$s.original_sample,$s.source_file.Name)
                Copy-Item $s.source_file.FullName $dst -Force
            }
        }
    }

    if($Succeeded){
        if(Test-Path $UploadZip){
            $old=Join-Path $OldRoot $Stamp
            New-Item -ItemType Directory -Force -Path $old|Out-Null
            Copy-Item $UploadZip (Join-Path $old "naruto_stage38c_persistent30_exact_upload.zip") -Force
        }
        Compress-Archive (Join-Path $PackageDir "*") $UploadZip -Force
        Write-Host ""
        Write-Host "STAGE 38C SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Get-ChildItem $PackageDir -File -Recurse | ForEach-Object {
            $rel=$_.FullName.Substring($PackageDir.Length).TrimStart('\')
            $dest=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent)|Out-Null
            Copy-Item $_.FullName $dest -Force
        }
        $fz=Join-Path $fd "naruto_stage38c_persistent30_exact_failed_upload.zip"
        Compress-Archive (Join-Path $fd "*") $fz -Force
        Write-Host ""
        Write-Host "STAGE 38C FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
