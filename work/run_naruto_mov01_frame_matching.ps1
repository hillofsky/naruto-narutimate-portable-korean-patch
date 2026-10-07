# Naruto PSP MOV01 FIX4 wrapper - Stage37 dialogue-anchor recovery
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov01_frame_matching"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_mov01_frame_matching_FIX4_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_mov01_frame_matching_FIX4_upload.zip"
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov01_frame_matching"

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot,$FailedRoot | Out-Null

# Only rotate old FIX4 transient logs.  FIX3 mapping/cache/results remain in place
# because FIX4 intentionally consumes them.
$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_mov01_frame_matching_FIX4_*.log" -ErrorAction SilentlyContinue)
if ($oldLogs.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach($f in $oldLogs){Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force}
}

Start-Transcript -Path $Transcript -Force | Out-Null
$Success=$false
try {
    Write-Host "========================================================================"
    Write-Host " Naruto PSP MOV01 FIX4 - Stage37 dialogue-anchor recovery"
    Write-Host "========================================================================"
    Write-Host "Started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host ""

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){$Py=@($launcher.Source,"-3")}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3를 찾지 못했습니다."}
        $Py=@($p.Source)
    }
    $Script=Join-Path $Root "run_naruto_mov01_frame_matching.py"
    if(-not(Test-Path $Script)){throw "Python script not found: $Script"}

    if($Py.Count -eq 2){& $Py[0] $Py[1] $Script}else{& $Py[0] $Script}
    $ec=$LASTEXITCODE
    if($ec -ne 0){throw "MOV01 FIX4 Python exited with code $ec"}
    $Success=$true
}catch{
    Write-Host ""
    Write-Host "!!!!!!!! MOV01 FIX4 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    Write-Host ($_|Out-String)
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    $Pkg=Join-Path $StageDir "_upload_package_fix4"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    foreach($name in @(
        "SUMMARY_FIX4.txt","FAILURE_FIX4.txt","anchor_discovery_FIX4.txt","anchor_filename_samples_FIX4.txt",
        "dm_anchor_recovery_fix4.tsv","dm_anchor_candidates_fix4.tsv",
        "pmf_source_mapping_fix4.tsv","pmf_source_mapping_fix4.csv","verification_fix4_manifest.tsv",
        "pmf_source_mapping_fix3.csv","SUMMARY_FIX3.txt"
    )){
        $p=Join-Path $StageDir $name
        if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}

    $V=Join-Path $StageDir "verification_fix4"
    if(Test-Path $V){
        $D=Join-Path $Pkg "verification_fix4"
        New-Item -ItemType Directory -Force -Path $D|Out-Null
        Get-ChildItem $V -File -Filter "*.jpg" -ErrorAction SilentlyContinue|ForEach-Object{Copy-Item $_.FullName $D -Force}
    }
    foreach($s in @((Join-Path $Root "run_naruto_mov01_frame_matching.ps1"),(Join-Path $Root "run_naruto_mov01_frame_matching.py"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_mov01_frame_matching_FIX4_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host ""
        Write-Host "MOV01 FIX4 SUCCESS"
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
        $fz=Join-Path $fd "naruto_mov01_frame_matching_FIX4_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "MOV01 FIX4 FAILED"
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Success){exit 1}
exit 0
