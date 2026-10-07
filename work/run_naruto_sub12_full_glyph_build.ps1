# Naruto PSP SUB12 - Build 694 Hangul glyphs / patched BOOT
$ErrorActionPreference="Stop"
Set-StrictMode -Version 2.0

$Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding=$Utf8NoBom
[Console]::OutputEncoding=$Utf8NoBom
$OutputEncoding=$Utf8NoBom
try { & chcp.com 65001 | Out-Null } catch {}

$Root="D:\narutimate portable"
$StageName="sub12_full_glyph_build"
$StageDir=Join-Path $Root "analysis\sub\$StageName"
$LogsDir=Join-Path $Root "logs"
$OldRoot=Join-Path $LogsDir "old"
$FailedRoot=Join-Path $LogsDir "failed"
$Stamp=Get-Date -Format "yyyyMMdd_HHmmss"
$Transcript=Join-Path $LogsDir "naruto_sub12_full_glyph_build_$Stamp.log"
$UploadZip=Join-Path $LogsDir "naruto_sub12_full_glyph_build_upload.zip"
$FailureTxt=Join-Path $StageDir "FAILURE.txt"

New-Item -ItemType Directory -Force -Path $LogsDir,$OldRoot,$FailedRoot | Out-Null
$ArchiveDir=Join-Path (Join-Path $OldRoot $Stamp) $StageName

$oldLogs=@(Get-ChildItem $LogsDir -File -Filter "naruto_sub12_full_glyph_build_*.log" -ErrorAction SilentlyContinue)
if($oldLogs.Count -gt 0){
    New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
    foreach($f in $oldLogs){
        Move-Item $f.FullName (Join-Path $ArchiveDir $f.Name) -Force
    }
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
    Write-Host " Naruto SUB12 - Build all 694 Hangul glyphs"
    Write-Host "========================================================================"

    $Map=Join-Path $Root "analysis\shared\event_font_hangul_mapping.tsv"
    $Boot=Join-Path $Root "kr_extracted\PSP_GAME\SYSDIR\BOOT.BIN"
    $S36=Join-Path $Root "analysis\stage36r\stage36r_mapping.tsv"

    foreach($p in @($Map,$Boot,$S36)){
        if(-not(Test-Path $p)){throw "필수 입력을 찾지 못했습니다: $p"}
    }

    $Font="C:\Windows\Fonts\malgunbd.ttf"
    if(-not(Test-Path $Font)){throw "Stage34에서 사용한 malgunbd.ttf를 찾지 못했습니다: $Font"}

    $Py=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $Py){$Py=Get-Command python -ErrorAction SilentlyContinue}
    if(-not $Py){throw "Python을 찾지 못했습니다."}

    $ScriptDir=Split-Path -Parent $PSCommandPath
    $PyScript=Join-Path $ScriptDir "naruto_sub12_full_glyph_build.py"
    if(-not(Test-Path $PyScript)){
        throw "SUB12 Python 스크립트를 찾지 못했습니다: $PyScript"
    }

    Write-Host "Mapping : $Map"
    Write-Host "BOOT    : $Boot"
    Write-Host "Stage36R: $S36"
    Write-Host "Font    : $Font"
    Write-Host "Output  : $StageDir"
    Write-Host ""

    & $Py.Source $PyScript --root $Root --out $StageDir
    if($LASTEXITCODE -ne 0){
        throw "SUB12 Python failed. ExitCode=$LASTEXITCODE"
    }

    $Succeeded=$true

}catch{
    Write-Host ""
    Write-Host "!!!!!!!! SUB12 FAILED !!!!!!!!"
    Write-Host $_.Exception.Message
    ($_|Out-String)|Write-Host

    @(
        "Naruto SUB12 FAILURE",
        "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        $_.Exception.Message,
        ($_|Out-String)
    )|Set-Content $FailureTxt -Encoding UTF8

}finally{
    try{Stop-Transcript|Out-Null}catch{}

    $Pkg=Join-Path $StageDir "_upload_package"
    if(Test-Path $Pkg){Remove-Item $Pkg -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

    # Intentionally exclude BOOT_sub12_full_hangul.bin from ChatGPT upload ZIP.
    foreach($f in @(
        "SUMMARY.txt",
        "sub12_build_report.json",
        "sub12_glyph_manifest.tsv",
        "sub12_fixed10_hash_verification.tsv",
        "sub12_original_donor_blocks.bin",
        "sub12_generated_glyph_blocks.bin",
        "sub12_all_694_preview.png",
        "sub12_fixed10_preview.png",
        "FAILURE.txt"
    )){
        $src=Join-Path $StageDir $f
        if(Test-Path $src){Copy-Item $src $Pkg -Force}
    }

    if(Test-Path $Transcript){Copy-Item $Transcript $Pkg -Force}
    if($PSCommandPath -and (Test-Path $PSCommandPath)){
        Copy-Item $PSCommandPath $Pkg -Force
    }

    $PyScript=Join-Path (Split-Path -Parent $PSCommandPath) "naruto_sub12_full_glyph_build.py"
    if(Test-Path $PyScript){Copy-Item $PyScript $Pkg -Force}

    if($Succeeded){
        if(Test-Path $UploadZip){
            New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null
            Copy-Item $UploadZip (Join-Path $ArchiveDir "naruto_sub12_full_glyph_build_upload.zip") -Force
        }

        Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $UploadZip -Force

        Write-Host ""
        Write-Host "SUB12 SUCCESS"
        Write-Host "Patched BOOT (local only):"
        Write-Host "  $(Join-Path $StageDir 'BOOT_sub12_full_hangul.bin')"
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

        $fz=Join-Path $fd "naruto_sub12_full_glyph_build_failed_upload.zip"
        Compress-Archive -Path (Join-Path $fd "*") -DestinationPath $fz -Force

        Write-Host ""
        Write-Host "Failure ZIP:"
        Write-Host "  $fz"
    }

    Remove-Item $Pkg -Recurse -Force -ErrorAction SilentlyContinue
}

if(-not $Succeeded){exit 1}
exit 0
