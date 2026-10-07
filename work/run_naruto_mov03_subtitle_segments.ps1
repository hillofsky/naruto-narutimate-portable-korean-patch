# Naruto PSP MOV03 FIX2 wrapper - exact 40px subtitle segmentation
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov03_subtitle_segments"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov03_subtitle_segments_FIX2_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov03_subtitle_segments_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov03_subtitle_segments"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot,$FailedRoot|Out-Null

# Archive old MOV03 result set.
$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_mov03_subtitle_segments_*.log" -ErrorAction SilentlyContinue)
if($oldLogs.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
    foreach($f in $oldLogs){Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force}
}
if(Test-Path $StageDir){
    $old=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue)
    if($old.Count -gt 0){
        $dst=Join-Path $ArchiveDir "previous_results"
        New-Item -ItemType Directory -Force -Path $dst|Out-Null
        foreach($x in $old){Move-Item $x.FullName $dst -Force}
    }
}
New-Item -ItemType Directory -Force -Path $StageDir|Out-Null

Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false
try{
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV03 FIX2 - Exact 40px Japanese subtitle segmentation"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){$Py=@($launcher.Source,"-3")}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3를 찾지 못했습니다."}
        $Py=@($p.Source)
    }

    $Script=Join-Path $Root "run_naruto_mov03_subtitle_segments.py"
    if(-not(Test-Path $Script)){throw "Python script not found: $Script"}

    if($Py.Count -eq 2){& $Py[0] $Py[1] $Script}else{& $Py[0] $Script}
    $ec=$LASTEXITCODE
    if($ec -ne 0){throw "MOV03 Python exited with code $ec"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV03 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_|Out-String)
}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null

    foreach($name in @("SUMMARY.txt","FAILURE.txt","subtitle_segments.tsv","subtitle_segments.csv","movie_summary.tsv")){
        $p=Join-Path $StageDir $name
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    # Include subtitle crop images, but not the large per-frame metric tables.
    $Crops=Join-Path $StageDir "crops"
    if(Test-Path $Crops){
        $D=Join-Path $Pkg "crops"
        New-Item -ItemType Directory -Force -Path $D|Out-Null
        Get-ChildItem $Crops -File -Recurse -Filter "*.jpg" -ErrorAction SilentlyContinue|ForEach-Object{
            $rel=$_.FullName.Substring($Crops.Length).TrimStart('\')
            $dst=Join-Path $D $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
    }

    foreach($s in @(
        (Join-Path $Root "run_naruto_mov03_subtitle_segments.ps1"),
        (Join-Path $Root "run_naruto_mov03_subtitle_segments.py")
    )){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov03_subtitle_segments_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV03 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd|Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue|ForEach-Object{
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent)|Out-Null
            Copy-Item $_.FullName $dst -Force
        }
        $fz=Join-Path $fd "naruto_mov03_subtitle_segments_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV03 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Success){exit 1}
exit 0
