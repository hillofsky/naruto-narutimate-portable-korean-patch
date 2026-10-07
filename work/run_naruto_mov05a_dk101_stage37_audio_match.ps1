# Naruto PSP MOV05A wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov05a_dk101_stage37_audio_match"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"

$Base="naruto_mov05a_dk101_stage37_audio_match"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov05a"

$PyScript=Join-Path $Root "run_naruto_mov05a_dk101_stage37_audio_match.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot | Out-Null
Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false

try {
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV05A - dk101 Stage37 local-video audio match"
    Write-Host "================================================================================"
    Write-Host "No YouTube download; reusing source_video.mp4 / part2.mp4."

    if(-not(Test-Path $PyScript)){throw "Missing script: $PyScript"}

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){
        & $launcher.Source -3 $PyScript | Out-Host
        $rc=$LASTEXITCODE
    } else {
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript | Out-Host
        $rc=$LASTEXITCODE
    }

    if([int]$rc -ne 0){throw "MOV05A Python exited with code $rc"}
    $Success=$true
} catch {
    Write-Host ""
    Write-Host "!!!!!!!! MOV05A FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @("MOV05A FAILED","",$_.Exception.Message,"",($_|Out-String)) |
      Set-Content (Join-Path $StageDir "FAILURE_WRAPPER.txt") -Encoding UTF8
} finally {
    try { Stop-Transcript | Out-Null } catch {}

    if(-not $Success -and (Test-Path $Transcript)){
        Move-Item $Transcript $FailTranscript -Force
        $Transcript=$FailTranscript
    }

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt","FAILURE_WRAPPER.txt",
        "audio_match_candidates.tsv","source_summary.tsv","review_frames.tsv",
        "stage37_existing_analysis_inventory.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $Rep=Join-Path $StageDir "representatives"
    if(Test-Path $Rep){Copy-Item $Rep (Join-Path $Pkg "representatives") -Recurse -Force}

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}
    $Self=Join-Path $Root "run_naruto_mov05a_dk101_stage37_audio_match.ps1"
    if(Test-Path $Self){Copy-Item $Self $Pkg -Force}

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir ($Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV05A SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    } else {
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host ""
        Write-Host "MOV05A FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $FailZip"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
