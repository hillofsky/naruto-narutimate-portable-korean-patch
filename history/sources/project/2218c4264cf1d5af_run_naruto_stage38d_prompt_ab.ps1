# Naruto PSP Stage 38D FIX1
# RTX 3070 OCR correction A/B test on the 8 Stage38C mismatch frames.
#
# A = exact Stage38C prompt/layout (baseline)
# B = corrected layout:
#     - OCR role moved to system message
#     - image placed before user instruction
#     - avoids the literal heading "규칙", which leaked on empty/"규칙" frames
#     - explicitly asks for speaker-name plate + dialogue text
#     - shorter instruction to reduce prompt echo
#
# One persistent llama-server, same RTX runtime/model/mmproj as Stage38C.
# 8 frames x 2 prompt variants = 16 requests.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root       = "PROJECT_ROOT"
$StageName  = "stage38d_prompt_ab"
$StageDir   = Join-Path $Root "analysis\$StageName"
$LogsDir    = Join-Path $Root "logs"
$FailedRoot = Join-Path $LogsDir "failed"
$OldRoot    = Join-Path $LogsDir "old"
$Stamp      = Get-Date -Format "yyyyMMdd_HHmmss"

$Transcript = Join-Path $LogsDir "naruto_stage38d_prompt_ab_$Stamp.log"
$Summary    = Join-Path $StageDir "SUMMARY.txt"
$CsvPath    = Join-Path $StageDir "stage38d_ab_results.csv"
$Manifest   = Join-Path $StageDir "stage38d_mismatch8_manifest.csv"
$ServerLog  = Join-Path $StageDir "llama_server_$Stamp.log"
$ServerErr  = Join-Path $StageDir "llama_server_$Stamp.err.log"
$VersionTxt = Join-Path $StageDir "llama_server_version.txt"
$CmdTxt     = Join-Path $StageDir "SERVER_COMMAND.txt"
$GpuBefore  = Join-Path $StageDir "NVIDIA_BEFORE.txt"
$GpuAfter   = Join-Path $StageDir "NVIDIA_AFTER.txt"
$FailureTxt = Join-Path $StageDir "FAILURE.txt"
$UploadZip  = Join-Path $LogsDir "naruto_stage38d_prompt_ab_upload.zip"

$Port = 8094
$BaseUrl = "httLOCAL_PATH"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot | Out-Null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host (" " + $Text)
    Write-Host ("=" * 78)
}

function Find-FirstFile {
    param([string[]]$Roots,[string]$Filter,[scriptblock]$Predicate=$null)
    foreach ($r in $Roots){
        if (-not(Test-Path $r)){continue}
        $items=Get-ChildItem $r -Filter $Filter -File -Recurse -ErrorAction SilentlyContinue
        if ($Predicate){$items=$items|Where-Object $Predicate}
        $hit=$items|Select-Object -First 1
        if ($hit){return $hit.FullName}
    }
    return $null
}

function Normalize-Ocr([string]$Text) {
    if ($null -eq $Text){return ""}
    $x=$Text -replace "`r`n","`n" -replace "`r","`n"
    return $x.Trim()
}

function Save-NvidiaSmi([string]$Path) {
    if (Test-Path $Path){Remove-Item $Path -Force}
    $nvsmi=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not$nvsmi){$nvsmi=Get-Command nvidia-smi -ErrorAction SilentlyContinue}
    if (-not$nvsmi){"nvidia-smi not found"|Set-Content $Path -Encoding UTF8;return}
    $cmd='"'+$nvsmi.Source+'" 2>&1'
    & $env:ComSpec /d /s /c $cmd | ForEach-Object {
        $line=[string]$_
        Write-Host $line
        $line|Out-File $Path -Append -Encoding utf8
    }
}

function Extract-Ocr([string]$Raw) {
    if ($null -eq $Raw){return ""}
    $m=[regex]::Match($Raw,'(?s)<OCR>\s*(.*?)\s*</OCR>')
    if ($m.Success){return (Normalize-Ocr $m.Groups[1].Value)}
    return (Normalize-Ocr $Raw)
}

function Is-Suspicious([string]$Text) {
    if ($null -eq $Text){return $true}
    $x=Normalize-Ocr $Text
    if ($x.Length -gt 220){return $true}
    $bad=@(
        "한국어, 일본어, 영어",
        "번역, 의역",
        "판독할 수 없는",
        "이미지에 없는 문장",
        "반드시 아래 형식",
        "화면에 실제로 보이는 글자만"
    )
    foreach ($b in $bad){
        if ($x.Contains($b)){return $true}
    }
    return $false
}

# Exact 8 mismatch rows from the successful Stage38C ZIP.
$Cases = @'
[
  {
    "persistent_index": 2,
    "original_sample": 5,
    "video_part": "part1",
    "part_index": 102,
    "global_index": 102,
    "timestamp": "00:08:32.112",
    "source_filename": "005_part1_p102_g102.jpg",
    "stage38c_rtx_ocr": "<OCR>\n규칙:\n- 한국어, 일본어, 영어, 숫자, 문장부호를 보이는 그대로 적는다.\n- 번역, 의역, 요약, 추측, 설명을 하지 않는다.\n- 줄바꿈은 화면에 보이는 대로 최대한 유지한다.\n- 글자가 전혀 없으면 [EMPTY]라고 적는다.\n- 판독할 수 없는 글자만 [불명]으로 표시한다.\n- 이미지에 없는 문장을 만들어내지 않는다.\n\n반드시 아래 형식만 출력한다.\n<OCR>",
    "bc250_ocr": "규칙",
    "stage38c_rtx_seconds": 1.0763,
    "bc250_seconds": 1.7817
  },
  {
    "persistent_index": 5,
    "original_sample": 18,
    "video_part": "part1",
    "part_index": 432,
    "global_index": 432,
    "timestamp": "00:34:21.259",
    "source_filename": "018_part1_p432_g432.jpg",
    "stage38c_rtx_ocr": "나두토\n…\n!",
    "bc250_ocr": "나두토\n…!",
    "stage38c_rtx_seconds": 0.3107,
    "bc250_seconds": 1.8005
  },
  {
    "persistent_index": 7,
    "original_sample": 26,
    "video_part": "part1",
    "part_index": 635,
    "global_index": 635,
    "timestamp": "00:51:07.364",
    "source_filename": "026_part1_p635_g635.jpg",
    "stage38c_rtx_ocr": "나우토\n젠장…!!",
    "bc250_ocr": "나두토\n젠장…!!",
    "stage38c_rtx_seconds": 0.3271,
    "bc250_seconds": 1.8494
  },
  {
    "persistent_index": 10,
    "original_sample": 39,
    "video_part": "part1",
    "part_index": 965,
    "global_index": 965,
    "timestamp": "01:16:37.793",
    "source_filename": "039_part1_p965_g965.jpg",
    "stage38c_rtx_ocr": "[EMPTY]",
    "bc250_ocr": "규칙",
    "stage38c_rtx_seconds": 0.2939,
    "bc250_seconds": 1.7631
  },
  {
    "persistent_index": 17,
    "original_sample": 65,
    "video_part": "part2",
    "part_index": 41,
    "global_index": 1539,
    "timestamp": "00:03:09.289",
    "source_filename": "065_part2_p41_g1539.jpg",
    "stage38c_rtx_ocr": "지라이야\n미안하지만 나 말고 3명 정도 니자를 데려가고 싶은데…\n누구 없나?",
    "bc250_ocr": "지라이야\n미안하지만 나 말고 3명 정도 담자를 데려가고 싶은데…\n누구 없나?",
    "stage38c_rtx_seconds": 0.5083,
    "bc250_seconds": 2.0179
  },
  {
    "persistent_index": 20,
    "original_sample": 78,
    "video_part": "part2",
    "part_index": 170,
    "global_index": 1668,
    "timestamp": "00:12:47.066",
    "source_filename": "078_part2_p170_g1668.jpg",
    "stage38c_rtx_ocr": "지라이야\n그거 말인데… 잠깐 좀 도와줬으면 하는 일이 있어서…",
    "bc250_ocr": "지라이야\n그거 말인데…. 잠깐 좀 도와줬으면 하는 일이 있어서…",
    "stage38c_rtx_seconds": 0.4117,
    "bc250_seconds": 1.899
  },
  {
    "persistent_index": 25,
    "original_sample": 99,
    "video_part": "part2",
    "part_index": 379,
    "global_index": 1877,
    "timestamp": "00:31:05.864",
    "source_filename": "099_part2_p379_g1877.jpg",
    "stage38c_rtx_ocr": "오로치마루\n자, 그럼…",
    "bc250_ocr": "오로치마두\n자, 그럼…",
    "stage38c_rtx_seconds": 0.3477,
    "bc250_seconds": 1.8379
  },
  {
    "persistent_index": 29,
    "original_sample": 116,
    "video_part": "part2",
    "part_index": 548,
    "global_index": 2046,
    "timestamp": "00:45:55.052",
    "source_filename": "116_part2_p548_g2046.jpg",
    "stage38c_rtx_ocr": "오로치마속\n하아… 하아 … .",
    "bc250_ocr": "오로치마속\n하아… 하아 ….",
    "stage38c_rtx_seconds": 0.3619,
    "bc250_seconds": 1.86
  }
]
'@ | ConvertFrom-Json

# A: exact Stage38C prompt.
$PromptA = @'
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

# B: correction prompt.
# Deliberately does not contain the literal Korean word used as the old heading.
$SystemB = @'
너는 게임 화면 OCR 엔진이다.
이미지 안에서 실제로 읽을 수 있는 문자만 복사한다.
배경, 인물, 지식, 문맥으로 보이지 않는 글자를 만들어내지 않는다.
고유명사를 알고 있더라도 이미지에서 읽힌 형태를 우선한다.
설명이나 번역은 출력하지 않는다.
'@

$UserB = @'
이름표가 보이면 이름표부터 읽고, 대사창의 글자를 그 아래에 화면 줄바꿈대로 적어라.
문자가 하나도 보이지 않으면 [EMPTY]만 출력한다.
읽을 수 없는 한 글자만 [불명]으로 적는다.
출력은 <OCR>와 </OCR> 사이에 전사문만 넣어라.
'@

$Succeeded=$false
$ServerProc=$null
$Caught=$null
$Results=@()
$Resolved=@()

Start-Transcript $Transcript -Force | Out-Null

try {
    Write-Section "Naruto Stage38D FIX1 - 8 mismatch frames, prompt A/B correction test"
    Write-Host "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Requests: 8 frames x 2 variants = 16"

    Write-Section "1/7 - Runtime/model/mmproj"

    $runtimeRoots=@(
        (Join-Path $Root "analysis\stage38a_cuda\cuda_runtime"),
        (Join-Path $Root "analysis\stage38a_cuda"),
        (Join-Path $Root "analysis")
    )
    $ServerExe=Find-FirstFile $runtimeRoots "llama-server.exe"
    if (-not$ServerExe){throw "llama-server.exe를 찾지 못했습니다."}

    $modelRoots=@(
        (Join-Path $Root "analysis\stage38a_cuda\models"),
        (Join-Path $Root "models")
    )
    $Model=Find-FirstFile $modelRoots "*Qwen3*VL*2B*Q8_0*.gguf" { $_.Name -notmatch '^mmproj' }
    $Mmproj=Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*Q8_0*.gguf"
    if (-not$Mmproj){$Mmproj=Find-FirstFile $modelRoots "mmproj*Qwen3*VL*2B*.gguf"}
    if (-not$Model){throw "Qwen3-VL-2B Q8_0 모델을 찾지 못했습니다."}
    if (-not$Mmproj){throw "mmproj를 찾지 못했습니다."}

    $verCmd='"'+$ServerExe+'" --version 2>&1'
    & $env:ComSpec /d /s /c $verCmd | Set-Content $VersionTxt -Encoding UTF8
    Get-Content $VersionTxt | ForEach-Object {Write-Host $_}

    Write-Section "2/7 - Resolve exact 8 source frames"

    $payloadCandidates=@(
        (Join-Path $Root "analysis\stage38a\naruto_stage38a_payload\images"),
        (Join-Path $Root "analysis\stage38a\images")
    )
    $PayloadDir=$null
    foreach ($d in $payloadCandidates){if (Test-Path $d){$PayloadDir=$d;break}}
    if (-not$PayloadDir){throw "Stage38A 이미지 폴더를 찾지 못했습니다."}

    $all=@(Get-ChildItem $PayloadDir -File | Where-Object {
        $_.Extension -match '^\.(jpg|jpeg|png|webp)$'
    } | Sort-Object Name)
    if ($all.Count -lt 120){throw "120장 원본 샘플이 필요합니다. 발견=$($all.Count)"}

    foreach ($c in $Cases){
        $src=$all[[int]$c.original_sample-1]
        if (-not$src){throw "original_sample=$($c.original_sample) 이미지를 찾지 못했습니다."}
        $Resolved += [PSCustomObject]@{
            persistent_index=[int]$c.persistent_index
            original_sample=[int]$c.original_sample
            video_part=[string]$c.video_part
            timestamp=[string]$c.timestamp
            source_file=$src
            stage38c_rtx_ocr=[string]$c.stage38c_rtx_ocr
            bc250_ocr=[string]$c.bc250_ocr
            stage38c_rtx_seconds=[double]$c.stage38c_rtx_seconds
            bc250_seconds=[double]$c.bc250_seconds
        }
    }

    foreach ($r in $Resolved){
        Write-Host ("idx={0,2} orig={1,3} {2}" -f $r.persistent_index,$r.original_sample,$r.source_file.Name)
    }

    $Resolved | Select-Object persistent_index,original_sample,video_part,timestamp,
        @{n="source_filename";e={$_.source_file.Name}},
        stage38c_rtx_ocr,bc250_ocr,stage38c_rtx_seconds,bc250_seconds |
        Export-Csv $Manifest -NoTypeInformation -Encoding UTF8

    Write-Section "3/7 - GPU before / start persistent server"
    Save-NvidiaSmi $GpuBefore

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
        if ($null -eq $Value){return '""'}
        return '"'+$Value.Replace('"','\"')+'"'
    }
    $ArgLine=(($ServerArgs|ForEach-Object{Quote-ProcArg([string]$_)})-join " ")
    ('"'+$ServerExe+'" '+$ArgLine)|Set-Content $CmdTxt -Encoding UTF8
    Get-Content $CmdTxt | ForEach-Object {Write-Host $_}

    if (Test-Path $ServerLog){Remove-Item $ServerLog -Force}
    if (Test-Path $ServerErr){Remove-Item $ServerErr -Force}

    $ServerProc=Start-Process -FilePath $ServerExe -ArgumentList $ArgLine `
        -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErr `
        -PassThru -WindowStyle Hidden

    Write-Host "PID: $($ServerProc.Id)"
    $ready=$false
    $deadline=(Get-Date).AddMinutes(3)
    while ((Get-Date)-lt$deadline){
        if ($ServerProc.HasExited){
            try {$ServerProc.WaitForExit()}catch {}
            try {$ServerProc.Refresh()}catch {}
            Write-Host "----- stderr -----"
            if (Test-Path $ServerErr){Get-Content $ServerErr -Tail 100|ForEach-Object{Write-Host $_}}
            $ec="unknown";try {$ec=[string]$ServerProc.ExitCode}catch {}
            throw "llama-server exited before ready. ExitCode=$ec"
        }
        try {
            $null=Invoke-RestMethod "$BaseUrl/health" -Method Get -TimeoutSec 3
            $ready=$true;break
        }catch {Start-Sleep -Milliseconds 250}
    }
    if (-not$ready){throw "llama-server가 준비되지 않았습니다."}
    Write-Host "Server ready."

    Write-Section "4/7 - A/B OCR requests"

    foreach ($r in $Resolved){
        $bytes=[IO.File]::ReadAllBytes($r.source_file.FullName)
        $b64=[Convert]::ToBase64String($bytes)
        $mime=switch($r.source_file.Extension.ToLowerInvariant()){
            ".png"{"image/png"};".webp"{"image/webp"};default{"image/jpeg"}
        }
        $uri="data:$mime;base64,$b64"

        foreach ($variant in @("A","B")){
            if ($variant -eq "A"){
                $messages=@(
                    @{
                        role="user"
                        content=@(
                            @{type="text";text=$PromptA},
                            @{type="image_url";image_url=@{url=$uri}}
                        )
                    }
                )
            }else{
                $messages=@(
                    @{role="system";content=$SystemB},
                    @{
                        role="user"
                        content=@(
                            @{type="image_url";image_url=@{url=$uri}},
                            @{type="text";text=$UserB}
                        )
                    }
                )
            }

            $body=@{
                model="qwen3-vl"
                temperature=0
                max_tokens=96
                messages=$messages
            } | ConvertTo-Json -Depth 14 -Compress

            Write-Host ""
            Write-Host ("[idx {0:D2}] variant {1} | {2}" -f $r.persistent_index,$variant,$r.source_file.Name)

            $sw=[Diagnostics.Stopwatch]::StartNew()
            $status="OK";$raw="";$ocr="";$err=""
            try {
                $resp=Invoke-RestMethod "$BaseUrl/v1/chat/completions" -Method Post `
                    -ContentType "application/json; charset=utf-8" `
                    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 180
                $raw=[string]$resp.choices[0].message.content
                $ocr=Extract-Ocr $raw
            }catch {
                $status="ERROR";$err=$_.Exception.Message
            }
            $sw.Stop()
            $sec=[Math]::Round($sw.Elapsed.TotalSeconds,4)
            $suspicious=Is-Suspicious $ocr

            Write-Host ("  {0:N4}s suspicious={1}" -f $sec,$suspicious)
            if ($status -eq "OK"){Write-Host ($ocr -replace "`n"," / ")}
            else{Write-Host "  ERROR: $err"}

            $Results += [PSCustomObject]@{
                persistent_index=$r.persistent_index
                original_sample=$r.original_sample
                video_part=$r.video_part
                timestamp=$r.timestamp
                source_filename=$r.source_file.Name
                variant=$variant
                status=$status
                seconds=$sec
                suspicious=$suspicious
                ocr_text=$ocr
                raw_model_output=$raw
                prior_stage38c_rtx_ocr=$r.stage38c_rtx_ocr
                bc250_ocr=$r.bc250_ocr
                error=$err
            }
        }
    }

    $Results|Export-Csv $CsvPath -NoTypeInformation -Encoding UTF8

    Write-Section "5/7 - A/B summary"

    $a=@($Results|Where-Object{$_.variant -eq "A" -and $_.status -eq "OK"})
    $b=@($Results|Where-Object{$_.variant -eq "B" -and $_.status -eq "OK"})
    $aSusp=@($a|Where-Object suspicious -eq $true).Count
    $bSusp=@($b|Where-Object suspicious -eq $true).Count
    $aMean=($a|Measure-Object seconds -Average).Average
    $bMean=($b|Measure-Object seconds -Average).Average

    Write-Host ("A success/suspicious : {0}/8, {1}" -f $a.Count,$aSusp)
    Write-Host ("B success/suspicious : {0}/8, {1}" -f $b.Count,$bSusp)
    Write-Host ("A mean                : {0:N4}s" -f $aMean)
    Write-Host ("B mean                : {0:N4}s" -f $bMean)

    Write-Host ""
    Write-Host "Per-frame A -> B:"
    foreach ($r in $Resolved){
        $ra=$Results|Where-Object{$_.persistent_index -eq $r.persistent_index -and $_.variant -eq "A"}|Select-Object -First 1
        $rb=$Results|Where-Object{$_.persistent_index -eq $r.persistent_index -and $_.variant -eq "B"}|Select-Object -First 1
        Write-Host ""
        Write-Host ("idx {0:D2}" -f $r.persistent_index)
        Write-Host ("  A: "+(($ra.ocr_text) -replace "`n"," / "))
        Write-Host ("  B: "+(($rb.ocr_text) -replace "`n"," / "))
        Write-Host ("  BC250: "+(($r.bc250_ocr) -replace "`n"," / "))
    }

    Write-Section "6/7 - Save summary / GPU after"

    @(
        "Naruto Stage38D Prompt A/B",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Result: SUCCESS",
        "",
        "Scope: Stage38C mismatch frames only",
        "Indices: 2,5,7,10,17,20,25,29",
        "Requests: 16 total",
        "",
        "Variant A:",
        "Exact Stage38C prompt/layout",
        ("success={0}/8" -f $a.Count),
        ("suspicious={0}/8" -f $aSusp),
        ("mean_sec={0:N4}" -f $aMean),
        "",
        "Variant B:",
        "System OCR role + image-first + short user instruction",
        "Old heading word removed to reduce prompt echo",
        "Speaker-name plate explicitly included",
        ("success={0}/8" -f $b.Count),
        ("suspicious={0}/8" -f $bSusp),
        ("mean_sec={0:N4}" -f $bMean),
        "",
        "Review stage38d_ab_results.csv and selected_images before choosing production prompt."
    ) | Set-Content $Summary -Encoding UTF8

    Save-NvidiaSmi $GpuAfter

    if ($a.Count -ne 8 -or $b.Count -ne 8){
        throw "A/B 요청 중 실패가 있습니다."
    }

    $Succeeded=$true

}catch {
    $Caught=$_
    $Succeeded=$false
    Write-Host ""
    Write-Host "!!!!!!!! STAGE 38D FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_|Out-String)
    @(
        "Naruto Stage38D FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8

}finally{
    Write-Section "7/7 - Stop server / package"

    if ($ServerProc){
        try {
            if (-not$ServerProc.HasExited){
                Stop-Process -Id $ServerProc.Id -Force -ErrorAction SilentlyContinue
                $ServerProc.WaitForExit(5000)|Out-Null
            }
        }catch {}
    }

    try {Stop-Transcript|Out-Null}catch {}

    $pkg=Join-Path $StageDir "_upload_package"
    if (Test-Path $pkg){Remove-Item $pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $pkg|Out-Null

    @($Summary,$CsvPath,$Manifest,$ServerLog,$ServerErr,$VersionTxt,$CmdTxt,
      $GpuBefore,$GpuAfter,$Transcript,$FailureTxt) |
      ForEach-Object {if ($_ -and(Test-Path $_)){Copy-Item $_ $pkg -Force}}

    if ($PSCommandPath -and(Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $pkg -Force}

    if ($Resolved.Count -gt 0){
        $id=Join-Path $pkg "selected_images"
        New-Item -ItemType Directory -Force -Path $id|Out-Null
        foreach ($r in $Resolved){
            $dst=Join-Path $id ("{0:D2}_orig{1}_{2}" -f $r.persistent_index,$r.original_sample,$r.source_file.Name)
            Copy-Item $r.source_file.FullName $dst -Force
        }
    }

    if ($Succeeded){
        if (Test-Path $UploadZip){
            $old=Join-Path $OldRoot $Stamp
            New-Item -ItemType Directory -Force -Path $old|Out-Null
            Copy-Item $UploadZip (Join-Path $old "naruto_stage38d_prompt_ab_upload.zip") -Force
        }
        Compress-Archive (Join-Path $pkg "*") $UploadZip -Force
        Write-Host ""
        Write-Host "STAGE 38D SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Get-ChildItem $pkg -File -Recurse|ForEach-Object{
            $rel=$_.FullName.Substring($pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path(Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_stage38d_prompt_ab_failed_upload.zip"
        Compress-Archive (Join-Path $fd "*") $fz -Force
        Write-Host ""
        Write-Host "STAGE 38D FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not$Succeeded){exit 1}
exit 0
