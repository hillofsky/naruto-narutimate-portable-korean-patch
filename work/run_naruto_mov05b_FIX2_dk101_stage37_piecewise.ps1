# Naruto PSP MOV05B FIX2 wrapper
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageDir=Join-Path $Root "analysis\mov\mov05b_fix2_dk101_stage37_piecewise"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Base="naruto_mov05b_FIX2_dk101_stage37_piecewise"
$Transcript=Join-Path $LogsDir ($Base+"_"+$Stamp+".log")
$FailTranscript=Join-Path $LogsDir ("fail_"+$Base+"_"+$Stamp+".log")
$UploadZip=Join-Path $LogsDir ($Base+"_upload.zip")
$FailZip=Join-Path $LogsDir ("fail_"+$Base+"_upload.zip")
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) "mov05b_FIX2"
$PyScript=Join-Path $Root "run_naruto_mov05b_FIX2_dk101_stage37_piecewise.py"
$FinalIso=Join-Path $StageDir "output\Naruto_KR_MOV05B_FIX2_dk101_stage37_smoketest.iso"

function Find-PPSSPP {
    foreach($pn in @("PPSSPPWindows64","PPSSPPWindows")){
        try{$p=Get-Process -Name $pn -ErrorAction SilentlyContinue|Select-Object -First 1
            if($p -and $p.Path -and(Test-Path $p.Path)){return $p.Path}}catch{}
    }
    foreach($n in @("PPSSPPWindows64.exe","PPSSPPWindows.exe")){
        $c=Get-Command $n -ErrorAction SilentlyContinue
        if($c -and $c.Source -and(Test-Path $c.Source)){return $c.Source}
    }
    try{
        $p=Get-ChildItem -LiteralPath $Root -File -Recurse -ErrorAction SilentlyContinue|
            Where-Object{$_.Name -in @("PPSSPPWindows64.exe","PPSSPPWindows.exe")}|
            Select-Object -First 1
        if($p){return $p.FullName}
    }catch{}
    return $null
}
function Start-PPSSPPIso([string]$Iso){
    $exe=Find-PPSSPP
    if(-not $exe){Write-Warning "PPSSPP not found; ISO remains PASS.";return}
    try{Start-Process -FilePath $exe -ArgumentList @("`"$Iso`"")}
    catch{Write-Warning ("PPSSPP launch failed; ISO remains PASS: "+$_.Exception.Message)}
}

New-Item -ItemType Directory -Force -Path $StageDir,$LogsDir,$OldRoot|Out-Null
foreach($p in @((Join-Path $StageDir "FAILURE.txt"),(Join-Path $StageDir "FAILURE_WRAPPER.txt"))){
    Remove-Item $p -Force -ErrorAction SilentlyContinue
}
Start-Transcript -Path $Transcript -Force|Out-Null
$Success=$false
try{
    Write-Host "================================================================================"
    Write-Host " Naruto PSP MOV05B FIX2 - robust Stage37 dk101 piecewise build"
    Write-Host "================================================================================"

    $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
    if($launcher){& $launcher.Source -3 $PyScript 2>&1|Out-Host;$rc=$LASTEXITCODE}
    else{
        $p=Get-Command python.exe -ErrorAction SilentlyContinue
        if(-not $p){$p=Get-Command python -ErrorAction SilentlyContinue}
        if(-not $p){throw "Python 3 not found."}
        & $p.Source $PyScript 2>&1|Out-Host;$rc=$LASTEXITCODE
    }
    if([int]$rc -ne 0){throw "MOV05B FIX2 Python exited with code $rc"}
    if(-not(Test-Path $FinalIso)){throw "Smoke ISO missing"}
    $Success=$true
}catch{
    Write-Host "";Write-Host "!!!!!!!! MOV05B FIX2 FAILED !!!!!!!!";Write-Host $_.Exception.Message
    @("MOV05B FIX2 FAILED","",$_.Exception.Message,"",($_|Out-String))|
      Set-Content (Join-Path $StageDir "FAILURE_WRAPPER.txt") -Encoding UTF8
}finally{
    try{Stop-Transcript|Out-Null}catch{}
    if(-not $Success -and(Test-Path $Transcript)){Move-Item $Transcript $FailTranscript -Force;$Transcript=$FailTranscript}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
    foreach($n in @("SUMMARY.txt","FAILURE.txt","FAILURE_WRAPPER.txt","robust_audio_anchors.tsv","mov05b_fix2_result.tsv")){
        $p=Join-Path $StageDir $n;if(Test-Path $p){Copy-Item $p $Pkg -Force}
    }
    $od=Join-Path $StageDir "output"
    if(Test-Path $od){
        Get-ChildItem $od -Filter "review_*.jpg" -File -ErrorAction SilentlyContinue|ForEach-Object{Copy-Item $_.FullName $Pkg -Force}
        Get-ChildItem $od -File -ErrorAction SilentlyContinue|
          Select-Object Name,Length,LastWriteTime|Format-Table -AutoSize|Out-String|
          Set-Content (Join-Path $Pkg "LOCAL_OUTPUT_MANIFEST.txt") -Encoding UTF8
    }
    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    foreach($s in @($PyScript,(Join-Path $Root "mov05b_proven_movie_core.py"),
      (Join-Path $Root "invoke_naruto_mov05b_FIX2_raw_mux.ps1"),
      (Join-Path $Root "run_naruto_mov05b_FIX2_dk101_stage37_piecewise.ps1"))){
        if(Test-Path $s){Copy-Item $s $Pkg -Force}
    }

    if($Success){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir ($Base+"_upload.zip")) -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force
        Write-Host "";Write-Host "MOV05B FIX2 SUCCESS"
        Write-Host "Smoke ISO:";Write-Host "  $FinalIso"
        Write-Host "Upload ZIP:";Write-Host "  $UploadZip"
        Start-PPSSPPIso $FinalIso
    }else{
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
        Write-Host "";Write-Host "MOV05B FIX2 FAILED";Write-Host "Failure ZIP:";Write-Host "  $FailZip"
    }
    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Success){exit 1}
exit 0
