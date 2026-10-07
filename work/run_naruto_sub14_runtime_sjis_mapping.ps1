# Naruto PSP SUB14 - Recover actual runtime SJIS -> glyph conversion
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub14_runtime_sjis_mapping"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub14_runtime_sjis_mapping_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub14_runtime_sjis_mapping_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub14_runtime_sjis_mapping_*.log" -ErrorAction SilentlyContinue)
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
    Write-Host " Naruto SUB14 - Recover actual event SJIS -> glyph mapping"
    Write-Host "========================================================================"

    $Boot=Join-Path $Root "kr_extracted\PSP_GAME\SYSDIR\BOOT.BIN"
    if(-not(Test-Path $Boot)){throw "KR BOOT을 찾지 못했습니다: $Boot"}

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub14_runtime_sjis_mapping.py"
    if(-not(Test-Path $PyScript)){throw "SUB14 Python 스크립트를 찾지 못했습니다."}

    Write-Host "BOOT  : $Boot"
    Write-Host "Output: $StageDir"
    Write-Host ""
    Write-Host "Extracting actual runtime functions:"
    Write-Host "  0x088D5640  SJIS byte classifier"
    Write-Host "  0x088D56EC  SJIS -> glyph converter"
    Write-Host "  plus renderer/caller context"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){throw "SUB14 Python failed. ExitCode=$LASTEXITCODE"}

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB14 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB14 FAILURE",
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
        "SUMMARY.txt",
        "sub14_report.json",
        "sub14_elf_program_headers.tsv",
        "sub14_runtime_address_map.tsv",
        "sub14_disassembly.tsv",
        "sub14_stage_evidence.tsv",
        "sub14_previous_mapping_theory.tsv",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    foreach($dirName in @("function_raw","stage_evidence")){
        $srcDir=Join-Path $StageDir $dirName
        if(Test-Path $srcDir){
            $files=@(Get-ChildItem $srcDir -File -Recurse -ErrorAction SilentlyContinue)
            if($files.Count -gt 0){
                $dstDir=Join-Path $Pkg $dirName
                New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
                foreach($f in $files){
                    if($f.Length -gt 5MB){continue}
                    $rel=$f.FullName.Substring($srcDir.Length).TrimStart('\')
                    $dst=Join-Path $dstDir $rel
                    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
                    Copy-Item $f.FullName $dst -Force
                }
            }
        }
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){Copy-Item $PSCommandPath $Pkg -Force}
    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub14_runtime_sjis_mapping.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub14_runtime_sjis_mapping_upload.zip") -Force
        }
        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB14 SUCCESS"
        Write-Host "Upload ZIP:"
        Write-Host "  $UploadZip"
    }else{
        $fd=Join-Path $FailedRoot $Stamp
        New-Item -ItemType Directory -Force -Path $fd | Out-Null
        Get-ChildItem $Pkg -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $rel=$_.FullName.Substring($Pkg.Length).TrimStart('\')
            $dst=Join-Path $fd $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            Copy-Item $_.FullName $dst -Force
        }

        $fz=Join-Path $fd "naruto_sub14_runtime_sjis_mapping_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force
        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
