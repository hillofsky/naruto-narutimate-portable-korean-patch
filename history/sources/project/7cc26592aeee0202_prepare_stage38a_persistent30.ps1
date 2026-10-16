$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$sourcePayload = Join-Path $base "analysis\stage38a\naruto_stage38a_payload"
$sourceManifest = Join-Path $sourcePayload "stage38a_manifest.tsv"

$outRoot = Join-Path $base "analysis\stage38a_persistent30\payload"
$outImages = Join-Path $outRoot "images"
$outManifest = Join-Path $outRoot "stage38a_persistent30_manifest.tsv"

if (-not (Test-Path -LiteralPath $sourceManifest)) {
    throw "Stage38A manifest 없음: $sourceManifest"
}

Remove-Item -LiteralPath $outRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $outImages | Out-Null

$rows = @(Import-Csv -LiteralPath $sourceManifest -Delimiter "`t")

$selected = New-Object System.Collections.Generic.List[object]
$persistentIndex = 0

foreach ($part in @("part1","part2")) {
    $group = @(
        $rows |
            Where-Object { $_.video_part -eq $part } |
            Sort-Object { [int]$_.sample_index }
    )

    if ($group.Count -lt 15) {
        throw "$part 샘플이 15개 미만입니다: $($group.Count)"
    }

    $used = @{}

    for ($i = 0; $i -lt 15; $i++) {
        $idx = [int][math]::Round($i * ($group.Count - 1) / 14.0)

        while ($used.ContainsKey($idx) -and $idx + 1 -lt $group.Count) {
            $idx++
        }

        if ($used.ContainsKey($idx)) {
            $idx = 0
            while ($used.ContainsKey($idx) -and $idx -lt $group.Count) {
                $idx++
            }
        }

        if ($idx -ge $group.Count) {
            throw "$part 샘플 인덱스 계산 실패"
        }

        $used[$idx] = $true
        $row = $group[$idx]
        $persistentIndex++

        $rel = $row.image_file -replace "/", "\"
        $src = Join-Path $sourcePayload $rel

        if (-not (Test-Path -LiteralPath $src)) {
            throw "이미지 없음: $src"
        }

        $ext = [IO.Path]::GetExtension($src)
        $dstName = "{0:D2}_{1}_orig{2}{3}" -f `
            $persistentIndex, `
            $part, `
            ([int]$row.sample_index), `
            $ext.ToLower()

        Copy-Item `
            -LiteralPath $src `
            -Destination (Join-Path $outImages $dstName) `
            -Force

        $selected.Add([pscustomobject]@{
            persistent_index    = $persistentIndex
            original_sample     = [int]$row.sample_index
            video_part          = $row.video_part
            part_index          = $row.part_index
            global_index        = $row.global_index
            timestamp_seconds   = $row.timestamp_seconds
            timestamp           = $row.timestamp
            image_file          = "images/$dstName"
        })
    }
}

if ($selected.Count -ne 30) {
    throw "30개 선택 실패: $($selected.Count)"
}

$selected |
    Export-Csv `
        -LiteralPath $outManifest `
        -Delimiter "`t" `
        -NoTypeInformation `
        -Encoding UTF8

@(
    "Naruto Stage38A Persistent-30 payload"
    "Part1: 15"
    "Part2: 15"
    "Total: 30"
    ""
    "Stage38A의 기존 120장 benchmark payload에서 각 파트를 균등 간격으로 15장씩 선택."
    "BC250와 RTX 3070 모두 이 동일한 30장을 사용."
) | Set-Content `
    -LiteralPath (Join-Path $outRoot "README.txt") `
    -Encoding UTF8

Write-Host ""
Write-Host "Persistent-30 payload 준비 완료"
Write-Host $outRoot
Write-Host ""
$selected | Format-Table persistent_index,video_part,timestamp,image_file -AutoSize
