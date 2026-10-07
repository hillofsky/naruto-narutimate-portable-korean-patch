# Naruto PSP SUB04 - Rare/suspicious Hangul visual-review collector
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub04_rare_ocr_review"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub04_rare_ocr_review_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub04_rare_ocr_review_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub04_rare_ocr_review_*.log" -ErrorAction SilentlyContinue)
if($oldLogs.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach($f in $oldLogs){Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force}
}
if(Test-Path $StageDir){
    $items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($items.Count -gt 0){
        New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
        $oldStage=Join-Path $ArchiveDir "previous_stage_results"
        New-Item -ItemType Directory -Force -Path $oldStage | Out-Null
        foreach($x in $items){Move-Item $x.FullName $oldStage -Force}
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

$Succeeded=$false
Start-Transcript -Path $Transcript -Force | Out-Null
try{
    Write-Host "========================================================================"
    Write-Host " Naruto SUB04 - Rare/suspicious Hangul OCR visual review"
    Write-Host "========================================================================"

    $Input=Join-Path $Root "analysis\sub\sub03_sequence_timeline\sub03_dialogue_sequence.tsv"
    if(-not(Test-Path $Input)){throw "SUB03 결과를 찾지 못했습니다: $Input"}

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub04_rare_ocr_review.py"
    if(-not(Test-Path $PyScript)){throw "SUB04 Python 스크립트를 찾지 못했습니다."}

    Write-Host "Input : $Input"
    Write-Host "Output: $StageDir"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB04 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB04 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host
    @(
        "Naruto SUB04 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($f in @(
        "SUMMARY.txt","sub04_review_queue.tsv","review_image_manifest.tsv",
        "rare_char_le3.tsv","missing_review_images.tsv","FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    $ImgDir=Join-Path $StageDir "review_images"
    if(Test-Path $ImgDir){
        $imgs=@(Get-ChildItem $ImgDir -File -ErrorAction SilentlyContinue)
        if($imgs.Count -gt 0){
            $dst=Join-Path $Pkg "review_images"
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            foreach($i in $imgs){Copy-Item $i.FullName $dst -Force}
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $Pkg -Force}
    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub04_rare_ocr_review.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub04_rare_ocr_review_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "SUB04 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue|ForEach-Object{
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_sub04_rare_ocr_review_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
