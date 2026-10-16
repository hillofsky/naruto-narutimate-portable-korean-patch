$ErrorActionPreference = "Stop"

$base  = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage25"
$logs  = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage25_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
}

function Fail {
    param([string]$Reason)

    $failDir = Join-Path $failedRoot $stamp
    New-Item -ItemType Directory -Force -Path $failDir | Out-Null

    if (Test-Path -LiteralPath $runLog) {
        Copy-Item -LiteralPath $runLog -Destination $failDir -Force
    }

    Set-Content `
        -LiteralPath (Join-Path $failDir "FAILURE.txt") `
        -Value $Reason `
        -Encoding UTF8

    Write-Host ""
    Write-Host "STAGE 25 FAILED"
    Write-Host $Reason
    Write-Host "로그:"
    Write-Host $runLog
}

function RunPy {
    param(
        [string]$Label,
        [string[]]$PythonArgs
    )

    Log ""
    Log "===== $Label ====="

    $oldPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    & python @PythonArgs 2>&1 |
        ForEach-Object { Log "$_" }

    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPref
    return $code
}

try {
    Log "Naruto PSP Stage 25"
    Log "File-backed .data cave Hangul hook"
    Log "Started: $(Get-Date)"
    Log ""

    $srcHook = Join-Path $base "analysis\stage24\stage24_hangul_hook.py"
    $srcIso  = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"
    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"

    foreach ($p in @($srcHook,$srcIso,$patcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage25_driver.py"

    $driverCode = @'
from pathlib import Path
import csv
import importlib.util
import struct
import sys

BASE = Path(r"PROJECT_ROOT")
STAGE = BASE / "analysis" / "stage25"
SRC = BASE / "analysis" / "stage24" / "stage24_hangul_hook.py"

STAGE.mkdir(parents=True, exist_ok=True)

def load_stage24():
    spec = importlib.util.spec_from_file_location("stage24hook", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def write_tsv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, delimiter="\t", fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})

def find_data_code_cave(mod, elf, minimum=0xA0):
    data_sec = elf.section(".data")
    if data_sec is None:
        raise RuntimeError(".data section 없음")

    raw = elf.data
    data_start = data_sec["offset"]
    data_end = data_sec["offset"] + data_sec["size"]

    # .rel.data에 등장하는 실제 VA는 사용 중으로 간주.
    reloc_addrs = set()
    rel = elf.section(".rel.data")
    if rel is not None:
        p = rel["offset"]
        end = rel["offset"] + rel["size"]
        while p + 8 <= end:
            reloc_addrs.add(mod.u32(raw, p))
            p += 8

    # .data 안의 32-bit 값이 해당 영역을 가리키면 사용 중으로 간주.
    ptr_targets = set()
    p = data_start
    while p + 4 <= data_end:
        value = mod.u32(raw, p)
        if data_sec["addr"] <= value < data_sec["addr"] + data_sec["size"]:
            ptr_targets.add(value)
        p += 4

    # 실행 코드에서 lui + addiu/ori/load/store로 구성되는 절대주소도 수집.
    refs = set()

    def s16(v):
        return v - 0x10000 if v & 0x8000 else v

    mem_ops = {0x20,0x21,0x23,0x24,0x25,0x28,0x29,0x2B}

    for sec in elf.sections:
        if not (sec["flags"] & 0x4):
            continue

        inst = []
        p = sec["offset"]
        end = sec["offset"] + sec["size"]

        while p + 4 <= end:
            pc = sec["addr"] + p - sec["offset"]
            inst.append((p, pc, mod.u32(raw, p)))
            p += 4

        for i, (off, pc, word) in enumerate(inst):
            if ((word >> 26) & 0x3F) != 0x0F:
                continue

            reg = (word >> 16) & 31
            high = (word & 0xFFFF) << 16

            for j in range(i + 1, min(i + 9, len(inst))):
                _, _, w2 = inst[j]
                op2 = (w2 >> 26) & 0x3F
                rs2 = (w2 >> 21) & 31
                rt2 = (w2 >> 16) & 31
                imm2 = w2 & 0xFFFF

                if op2 == 0x0F and rt2 == reg:
                    break

                addr = None

                if op2 == 0x09 and rs2 == reg and rt2 == reg:
                    addr = (high + s16(imm2)) & 0xFFFFFFFF
                elif op2 == 0x0D and rs2 == reg and rt2 == reg:
                    addr = (high | imm2) & 0xFFFFFFFF
                elif op2 in mem_ops and rs2 == reg:
                    addr = (high + s16(imm2)) & 0xFFFFFFFF

                if addr is not None and data_sec["addr"] <= addr < data_sec["addr"] + data_sec["size"]:
                    refs.add(addr)

    rows = []
    p = data_start

    while p < data_end:
        if raw[p] != 0:
            p += 1
            continue

        run_start = p
        while p < data_end and raw[p] == 0:
            p += 1
        run_end = p

        start = (run_start + 15) & ~15
        end = run_end & ~15
        available = end - start

        if available < minimum:
            continue

        va = data_sec["addr"] + start - data_sec["offset"]
        va_end = va + minimum

        reloc_hits = sum(1 for x in reloc_addrs if va <= x < va_end)
        ptr_hits = sum(1 for x in ptr_targets if va <= x < va_end)
        ref_hits = sum(1 for x in refs if va <= x < va_end)

        safe = reloc_hits == 0 and ptr_hits == 0 and ref_hits == 0

        rows.append({
            "file_offset": start,
            "file_offset_hex": f"0x{start:X}",
            "va": va,
            "va_hex": f"0x{va:08X}",
            "available": available,
            "relocations": reloc_hits,
            "data_pointers": ptr_hits,
            "code_xrefs": ref_hits,
            "safe": safe,
            "distance_to_data_end": data_end - run_end,
        })

    write_tsv(
        STAGE / "stage25_code_caves.tsv",
        rows,
        [
            "file_offset","file_offset_hex","va","va_hex","available",
            "relocations","data_pointers","code_xrefs","safe",
            "distance_to_data_end",
        ],
    )

    safe = [r for r in rows if r["safe"]]
    if not safe:
        raise RuntimeError(
            "file-backed .data에서 안전한 0xA0-byte zero cave를 찾지 못했습니다."
        )

    # .data 끝에 가까운 padding을 우선.
    safe.sort(key=lambda r: (r["distance_to_data_end"], r["available"]))
    chosen = safe[0]

    # Stage24 main이 기대하는 키.
    p0 = elf.programs[0]
    chosen.update({
        "branch_targets": chosen["code_xrefs"],
        "preceded_by_control": False,
        "requires_zero": True,
        "extend_load": False,
        "program_index": 0,
        "phdr_offset": elf.e_phoff,
        "old_filesz": p0["filesz"],
        "new_filesz": p0["filesz"],
        "old_memsz": p0["memsz"],
        "file_gap": 0,
        "memory_slack": p0["memsz"] - p0["filesz"],
        "next_file_offset": chosen["file_offset"] + chosen["available"],
    })

    print(
        "[DATA CAVE]",
        chosen["va_hex"],
        chosen["file_offset_hex"],
        "available=", chosen["available"],
    )

    if chosen["va"] == 0x0049B590:
        raise RuntimeError("BSS 시작 주소가 다시 선택됨")

    return chosen

def main():
    mod = load_stage24()

    # Stage25 output paths.
    mod.OUT = STAGE
    mod.PATCHED_BOOT = STAGE / "BOOT_stage25_hangul_hook.BIN"
    mod.PATCHED_TBL = STAGE / "event000_stage25.tbl"

    # Stage24 main()이 호출하는 cave finder만 교체.
    mod.find_loader_gap_cave = lambda elf, minimum=0xA0: find_data_code_cave(
        mod, elf, minimum
    )

    mod.main()

    # Stage24 이름으로 생성된 보고서를 Stage25 이름으로 정리.
    for p in list(STAGE.glob("stage24_*")):
        target = p.with_name(p.name.replace("stage24_", "stage25_", 1))
        if target.exists():
            target.unlink()
        p.rename(target)

    print("=" * 72)
    print("STAGE25 DRIVER COMPLETE")
    print("=" * 72)
    print(mod.PATCHED_BOOT)
    print(mod.PATCHED_TBL)

if __name__ == "__main__":
    main()
'@

    Set-Content -LiteralPath $driver -Value $driverCode -Encoding UTF8

    $code = RunPy "driver syntax" @("-m","py_compile",$driver)
    if ($code -ne 0) { throw "Stage25 driver 문법 오류" }

    $code = RunPy "[1/3] .data cave Hangul hook" @($driver)
    if ($code -ne 0) { throw "Stage25 hook 생성 실패" }

    $probeTbl = Join-Path $stage "event000_stage25.tbl"
    $patchedBoot = Join-Path $stage "BOOT_stage25_hangul_hook.BIN"

    if (-not (Test-Path -LiteralPath $probeTbl)) {
        throw "event000_stage25.tbl 없음"
    }

    if (-not (Test-Path -LiteralPath $patchedBoot)) {
        throw "BOOT_stage25_hangul_hook.BIN 없음"
    }

    $patchOut = Join-Path $stage "patch"
    Remove-Item -LiteralPath $patchOut -Recurse -Force -ErrorAction SilentlyContinue

    $replaceArg = "event000.tbl=$probeTbl"

    $code = RunPy "[2/3] DAT/IDX patch" @(
        $patcher,
        "--root",$base,
        "--output",$patchOut,
        "--replace",$replaceArg,
        "--force"
    )
    if ($code -ne 0) { throw "DAT/IDX patch 실패" }

    $dat = Join-Path $patchOut "naruto.dat"
    $idx = Join-Path $patchOut "naruto.idx"

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    $outIso = Join-Path `
        $base `
        "Naruto - Stage25 Hangul Data Cave Test.iso"

    Remove-Item -LiteralPath $outIso -Force -ErrorAction SilentlyContinue

    # Stage24 ISO patcher는 CLI 범용이므로 그대로 재사용.
    $code = RunPy "[3/3] ISO patch" @(
        $srcIso,
        "--source-iso",$sourceIso,
        "--dat",$dat,
        "--idx",$idx,
        "--boot",$patchedBoot,
        "--output-iso",$outIso,
        "--report-dir",$stage
    )
    if ($code -ne 0) { throw "Stage25 ISO patch 실패" }

    if (-not (Test-Path -LiteralPath $outIso)) {
        throw "Stage25 ISO 생성 안 됨"
    }

    # 성공한 경우에만 이전 top-level logs 아카이브.
    $archive = Join-Path $oldRoot (Get-Date -Format "yyyyMMdd_HHmmss")
    New-Item -ItemType Directory -Force -Path $archive | Out-Null

    Get-ChildItem -LiteralPath $logs -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $archive -Force
        }

    Get-ChildItem -LiteralPath $stage -File |
        Where-Object {
            $_.Extension -eq ".txt" -or $_.Extension -eq ".tsv"
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $logs -Force
        }

    if (Test-Path -LiteralPath $patchOut) {
        Get-ChildItem -LiteralPath $patchOut -File |
            Where-Object {
                $_.Extension -eq ".txt" -or $_.Extension -eq ".tsv"
            } |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (Join-Path $logs ("patcher_" + $_.Name)) `
                    -Force
            }
    }

    Copy-Item -LiteralPath $runLog -Destination $logs -Force

    $readme = Join-Path $logs "README_UPLOAD.txt"
    @(
        "Naruto PSP Stage 25"
        "생성: $(Get-Date)"
        ""
        "Hook 위치를 BSS가 아닌 file-backed .data zero cave로 이동."
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage25_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content -LiteralPath $readme -Encoding UTF8

    $zip = Join-Path $logs "naruto_stage25_upload.zip"
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem -LiteralPath $logs -File |
        Where-Object { $_.Name -ne "naruto_stage25_upload.zip" } |
        Select-Object -ExpandProperty FullName

    Compress-Archive `
        -Path $zipInputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 25 SUCCESS"
    Log "=========================================="
    Log "ISO: $outIso"
    Log "ZIP: $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}
