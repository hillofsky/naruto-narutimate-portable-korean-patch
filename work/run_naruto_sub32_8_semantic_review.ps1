# Naruto PSP SUB32-8 - Semantic review rows 1401-1600
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0
$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}
$Root="D:\narutimate portable";$StageName="sub32_8_semantic_review_1401_1600"
$StageDir=Join-Path $Root "analysis\sub\$StageName";$LogsDir=Join-Path $Root "logs";$OldRoot=Join-Path $LogsDir "old";$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss";$Transcript=Join-Path $LogsDir "naruto_sub32_8_semantic_review_$Stamp.log"
$SuccessZip=Join-Path $LogsDir "naruto_sub32_8_semantic_review_upload.zip";$FailZip=Join-Path $LogsDir "fail_naruto_sub32_8_semantic_review_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt";$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName
New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot|Out-Null
if(Test-Path $StageDir){$items=@(Get-ChildItem $StageDir -Force -ErrorAction SilentlyContinue);if($items.Count -gt 0){New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null;foreach($x in $items){Move-Item $x.FullName $ArchiveDir -Force}}}
New-Item -ItemType Directory -Force -Path $StageDir|Out-Null
$Succeeded=$false;Start-Transcript -Path $Transcript -Force|Out-Null
try{
 Write-Host "Naruto SUB32-8 - Semantic review 1401-1600"
 $Py=Get-Command python.exe -ErrorAction SilentlyContinue;if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue};if(-not $Py){throw "Python not found."}
 $SD=Split-Path -Parent $PSCommandPath;$P=Join-Path $SD "naruto_sub32_8_semantic_review.py";$R=Join-Path $SD "sub32_8_revisions_1401_1600.json"
 if(-not(Test-Path $P)){throw "SUB32-8 Python script missing."};if(-not(Test-Path $R)){throw "SUB32-8 revision JSON missing."}
 & $Py.Source $P --root $Root --out $StageDir;if($LASTEXITCODE -ne 0){throw "SUB32-8 Python failed. ExitCode=$LASTEXITCODE"};$Succeeded=$true
}catch{
 Write-Host "!!!!!!!! SUB32-8 FAILED !!!!!!!!";Write-Host $_.Exception.Message
 @("Naruto SUB32-8 FAILURE","Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",$_.Exception.Message,($_|Out-String))|Set-Content $FailureTxt -Encoding UTF8
}finally{
 try{Stop-Transcript|Out-Null}catch{}
 $Pkg=Join-Path $StageDir "_upload_package";if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue};New-Item -ItemType Directory -Force -Path $Pkg|Out-Null
 function Copy-Diag{param([string]$Source,[string]$Dest)try{if(Test-Path $Source){$dst=Join-Path $Pkg $Dest;$parent=Split-Path $dst -Parent;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null};Copy-Item $Source $dst -Force}}catch{}}
 foreach($f in @("SUMMARY.txt","sub32_8_report.json","sub32_8_review_1401_1600_completed.tsv","sub32_8_changed_rows.tsv","FAILURE.txt")){Copy-Diag (Join-Path $StageDir $f) $f}
 Copy-Diag $Transcript ("logs\"+(Split-Path $Transcript -Leaf));if($PSCommandPath){Copy-Diag $PSCommandPath ("scripts\"+(Split-Path $PSCommandPath -Leaf))}
 $SD=Split-Path -Parent $PSCommandPath;Copy-Diag (Join-Path $SD "naruto_sub32_8_semantic_review.py") "scripts\naruto_sub32_8_semantic_review.py";Copy-Diag (Join-Path $SD "sub32_8_revisions_1401_1600.json") "scripts\sub32_8_revisions_1401_1600.json"
 Copy-Diag (Join-Path $Root "analysis\sub\sub31_full_semantic_review\sub31_review_1401_1600.tsv") "evidence\sub31_review_1401_1600.tsv";Copy-Diag (Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv") "evidence\event_font_hangul_mapping.tsv"
 if($Succeeded){
  if(Test-Path $SuccessZip){New-Item -ItemType Directory -Force -Path $ArchiveDir|Out-Null;Copy-Item $SuccessZip (Join-Path $ArchiveDir (Split-Path $SuccessZip -Leaf)) -Force}
  if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue};Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $SuccessZip -Force
  Write-Host "SUB32-8 SUCCESS";Write-Host "Upload ZIP:";Write-Host "  $SuccessZip"
 }else{
  if(Test-Path $FailZip){Remove-Item $FailZip -Force -ErrorAction SilentlyContinue};Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $FailZip -Force
  $fd=Join-Path $FailedRoot $Stamp;New-Item -ItemType Directory -Force -Path $fd|Out-Null;Copy-Item $FailZip (Join-Path $fd (Split-Path $FailZip -Leaf)) -Force
  Write-Host "Failure ZIP:";Write-Host "  $FailZip"
 }
 Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}
if(-not $Succeeded){exit 1}
exit 0
