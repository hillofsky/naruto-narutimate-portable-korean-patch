# Naruto PSP MOV03D wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="mov03d_all_tbl_link"
$StageDir=Join-Path $Root "analysis\mov\$StageName"
$LogsDir=Join-Path $Root "logs"
$FailedRoot=Join-Path $LogsDir "failed"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03d_all_tbl_link_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03d_all_tbl_link_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName
$PyScript=Join-Path $Root "run_naruto_mov03d_all_tbl_link.py"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$FailedRoot,$OldRoot|Out-Null

# Archive previous stage outputs except extraction cache will be rebuilt anyway.
$existing=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
if($existing.Count -gt 0){
    $dst=Join-Path $ArchiveDir "previous_results"
    New-Item -ItemType Directory -Force -Path $dst|Out-Null
    foreach($x in $existing){Move-Item $x.FullName $dst -Force}
}

Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false

try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03D - All TBL movie / voice linkage scan"
    Write-Host "========================================================================"

    if(-not(Test-Path $PyScript)){throw "Python script not found: $PyScript"}

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){
        & $launcher.Source -3 $PyScript
    }else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript
    }

    if($LASTEXITCODE -ne 0){throw "MOV03D Python exited with code $LASTEXITCODE"}
    $Success=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03D FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    @(
        "Naruto PSP MOV03D FAILED",
        "",
        $_.Exception.Message,
        "",
        ($_|Out-String)
    )|Set-Content (Join-Path $StageDir "FAILURE.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($n in @(
        "SUMMARY.txt","FAILURE.txt","quickbms_all_tbl.log",
        "tbl_inventory.tsv","decode_failures.tsv",
        "movie_commands.tsv","bare_movie_tokens.tsv","movie_summary.tsv",
        "voice_refs.tsv","movie_nearby_voice_refs.tsv","directive_counts.tsv"
    )){
        $p=Join-Path $StageDir $n
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }

    $ctx=Join-Path $StageDir "contexts"
    if(Test-Path $ctx){Copy-Item $ctx (Join-Path $Pkg "contexts") -Recurse -Force}

    # Decoded TBL text is useful and generally compact; include only up to 15 MiB total.
    $dec=Join-Path $StageDir "decoded_tbl"
    if(Test-Path $dec){
        $files=@(Get-ChildItem $dec -File -Recurse -ErrorAction SilentlyContinue)
        $bytes=($files|Measure-Object Length -Sum).Sum
        if($bytes -le 15728640){
            Copy-Item $dec (Join-Path $Pkg "decoded_tbl") -Recurse -Force
        }else{
            @("decoded_files=$($files.Count)","decoded_bytes=$bytes","omitted_over_15MiB=YES") |
                Set-Content (Join-Path $Pkg "DECODED_STATUS.txt") -Encoding UTF8
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @(
        (Join-Path $Root "run_naruto_mov03d_all_tbl_link.ps1"),
        (Join-Path $Root "run_naruto_mov03d_all_tbl_link.py")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03d_all_tbl_link_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "MOV03D SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Copy-Item (Join-Path $Pkg "*") $fd -Recurse -Force -ErrorAction SilentlyContinue
        $fz=Join-Path $fd "naruto_mov03d_all_tbl_link_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "MOV03D FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Success){exit 1}
exit 0
