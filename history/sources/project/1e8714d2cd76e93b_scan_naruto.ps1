$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"

$krIsoDir = Join-Path $base "kr"
$usIsoDir = Join-Path $base "us"

$krExtract = Join-Path $base "kr_extracted"
$usExtract = Join-Path $base "us_extracted"

$logDir = Join-Path $base "logs"
$resultDir = Join-Path $base "analysis"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

$logFile = Join-Path $logDir "naruto_analysis_$stamp.log"

$krManifestFile = Join-Path $resultDir "kr_manifest.csv"
$usManifestFile = Join-Path $resultDir "us_manifest.csv"
$compareFile = Join-Path $resultDir "kr_us_compare.csv"

Start-Transcript -Path $logFile -Force

try {

    Write-Host ""
    Write-Host "=========================================="
    Write-Host " Naruto PSP KR/US 분석"
    Write-Host "=========================================="
    Write-Host "시작 시간: $(Get-Date)"
    Write-Host "기준 경로: $base"
    Write-Host ""

    # ISO 검색
    $krIso = Get-ChildItem $krIsoDir -Filter *.iso -File |
        Select-Object -First 1

    $usIso = Get-ChildItem $usIsoDir -Filter *.iso -File |
        Select-Object -First 1

    if (-not $krIso) {
        throw "KR ISO를 찾을 수 없습니다: $krIsoDir"
    }

    if (-not $usIso) {
        throw "US ISO를 찾을 수 없습니다: $usIsoDir"
    }

    Write-Host "[KR ISO]"
    Write-Host "Path : $($krIso.FullName)"
    Write-Host "Size : $($krIso.Length)"
    Write-Host ""

    Write-Host "[US ISO]"
    Write-Host "Path : $($usIso.FullName)"
    Write-Host "Size : $($usIso.Length)"
    Write-Host ""

    # ISO 해시
    Write-Host "ISO SHA256 계산 중..."

    $krHash = Get-FileHash $krIso.FullName -Algorithm SHA256
    $usHash = Get-FileHash $usIso.FullName -Algorithm SHA256

    Write-Host ""
    Write-Host "[ISO HASH]"
    Write-Host "KR SHA256: $($krHash.Hash)"
    Write-Host "US SHA256: $($usHash.Hash)"
    Write-Host ""

    # 7-Zip 검색
    $sevenZipCandidates = @(
        "LOCAL_PATH Files\7-Zip\7z.exe",
        "LOCAL_PATH Files (x86)\7-Zip\7z.exe"
    )

    $sevenZip = $sevenZipCandidates |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1

    if (-not $sevenZip) {
        throw "7-Zip을 찾지 못했습니다."
    }

    Write-Host "7-Zip: $sevenZip"
    Write-Host ""

    # ISO 추출
    if (-not (Test-Path "$krExtract\PSP_GAME")) {

        Write-Host "KR ISO 추출 시작"

        & $sevenZip x $krIso.FullName "-o$krExtract" -y

        if ($LASTEXITCODE -ne 0) {
            throw "KR ISO 추출 실패. 7-Zip exit code: $LASTEXITCODE"
        }

        Write-Host "KR ISO 추출 완료"
        Write-Host ""

    } else {

        Write-Host "KR 추출 폴더가 이미 존재하여 추출을 생략합니다."
        Write-Host "$krExtract"
        Write-Host ""
    }

    if (-not (Test-Path "$usExtract\PSP_GAME")) {

        Write-Host "US ISO 추출 시작"

        & $sevenZip x $usIso.FullName "-o$usExtract" -y

        if ($LASTEXITCODE -ne 0) {
            throw "US ISO 추출 실패. 7-Zip exit code: $LASTEXITCODE"
        }

        Write-Host "US ISO 추출 완료"
        Write-Host ""

    } else {

        Write-Host "US 추출 폴더가 이미 존재하여 추출을 생략합니다."
        Write-Host "$usExtract"
        Write-Host ""
    }

    function Make-Manifest {

        param(
            [string]$Root,
            [string]$Output
        )

        Write-Host "Manifest 생성: $Root"

        $manifest = @(
            Get-ChildItem $Root -Recurse -File |
                ForEach-Object {

                    $relative = $_.FullName.Substring($Root.Length).TrimStart("\")

                    [PSCustomObject]@{
                        Path      = $relative
                        Size      = $_.Length
                        SHA1      = (Get-FileHash $_.FullName -Algorithm SHA1).Hash
                        Extension = $_.Extension
                    }
                }
        )

        $manifest |
            Sort-Object Path |
            Export-Csv $Output -NoTypeInformation -Encoding UTF8

        return $manifest
    }

    # Manifest 생성
    $krManifest = Make-Manifest `
        -Root $krExtract `
        -Output $krManifestFile

    Write-Host "KR files: $($krManifest.Count)"

    $usManifest = Make-Manifest `
        -Root $usExtract `
        -Output $usManifestFile

    Write-Host "US files: $($usManifest.Count)"
    Write-Host ""

    # 경로별 테이블
    $krTable = @{}

    foreach ($f in $krManifest) {
        $krTable[$f.Path.ToLowerInvariant()] = $f
    }

    $usTable = @{}

    foreach ($f in $usManifest) {
        $usTable[$f.Path.ToLowerInvariant()] = $f
    }

    $allPaths = @(
        $krTable.Keys
        $usTable.Keys
    ) | Sort-Object -Unique

    # KR/US 비교
    $comparison = @(
        foreach ($path in $allPaths) {

            $kr = $krTable[$path]
            $us = $usTable[$path]

            if ($kr -and $us) {

                if ($kr.SHA1 -eq $us.SHA1) {
                    $status = "IDENTICAL"
                }
                elseif ($kr.Size -eq $us.Size) {
                    $status = "DIFFERENT_SAME_SIZE"
                }
                else {
                    $status = "DIFFERENT_SIZE"
                }

            }
            elseif ($kr) {

                $status = "KR_ONLY"

            }
            else {

                $status = "US_ONLY"
            }

            [PSCustomObject]@{
                Path     = $path
                KR_Size  = if ($kr) { $kr.Size } else { "" }
                US_Size  = if ($us) { $us.Size } else { "" }
                KR_SHA1  = if ($kr) { $kr.SHA1 } else { "" }
                US_SHA1  = if ($us) { $us.SHA1 } else { "" }
                Status   = $status
            }
        }
    )

    $comparison |
        Export-Csv $compareFile -NoTypeInformation -Encoding UTF8

    # 요약
    Write-Host ""
    Write-Host "=========================================="
    Write-Host " 파일 비교 요약"
    Write-Host "=========================================="

    $comparison |
        Group-Object Status |
        Sort-Object Name |
        ForEach-Object {
            Write-Host "$($_.Name): $($_.Count)"
        }

    Write-Host ""
    Write-Host "=========================================="
    Write-Host " KR / US 서로 다른 파일"
    Write-Host "=========================================="

    $comparison |
        Where-Object { $_.Status -ne "IDENTICAL" } |
        Sort-Object Path |
        Format-Table Path, KR_Size, US_Size, Status -AutoSize |
        Out-String -Width 300 |
        Write-Host

    # 분석 후보
    Write-Host ""
    Write-Host "=========================================="
    Write-Host " BIN / DAT / CCS / EBOOT 분석 후보"
    Write-Host "=========================================="

    $comparison |
        Where-Object {
            $_.Path -match '\.(bin|dat|ccs)$' -or
            $_.Path -match 'EBOOT\.BIN$'
        } |
        Sort-Object Path |
        Format-Table Path, KR_Size, US_Size, Status -AutoSize |
        Out-String -Width 300 |
        Write-Host

    Write-Host ""
    Write-Host "=========================================="
    Write-Host " 완료"
    Write-Host "=========================================="

    Write-Host "로그:"
    Write-Host $logFile
    Write-Host ""

    Write-Host "KR manifest:"
    Write-Host $krManifestFile
    Write-Host ""

    Write-Host "US manifest:"
    Write-Host $usManifestFile
    Write-Host ""

    Write-Host "KR/US 비교:"
    Write-Host $compareFile
}
catch {

    Write-Host ""
    Write-Host "!!!!!!!! ERROR !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host $_.ScriptStackTrace
}
finally {

    Write-Host ""
    Write-Host "종료 시간: $(Get-Date)"

    Stop-Transcript
}
