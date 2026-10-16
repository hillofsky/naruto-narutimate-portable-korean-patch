$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage32"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage32_$stamp.log"

function Log {
    param([string]$Text)
    Write-Host $Text
    Add-Content -LiteralPath $runLog -Value $Text -Encoding UTF8
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
    Write-Host "STAGE 32 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "로그:"
    Write-Host $runLog
}

try {
    Log "Naruto PSP Stage 32"
    Log "Executable-load / renderer-path split diagnostic"
    Log "Started: $(Get-Date)"

    $stage24 = Join-Path $base "analysis\stage24\stage24_hangul_hook.py"
    $isoPatcher = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"

    foreach ($p in @($stage24,$isoPatcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage32_split_diagnostic.py"

    $driverCode = @'
from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage32"
OUT.mkdir(parents=True, exist_ok=True)

STAGE24 = (
    BASE / "analysis" / "stage24"
    / "stage24_hangul_hook.py"
)

BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

BOOT_A = OUT / "BOOT_stage32A_entry_trap.BIN"
BOOT_B = OUT / "BOOT_stage32B_renderer_blank.BIN"

RENDER_PATCH_VA = 0x002AC2F4
EXPECTED_RENDER_WORD = 0xAFA00040
NEW_RENDER_WORD = 0xA7A000D0  # sh zero,0xD0(sp)


def load_stage24():
    spec = importlib.util.spec_from_file_location(
        "stage24hook",
        STAGE24
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_tsv(path, rows, fields):
    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields
        )
        w.writeheader()
        for row in rows:
            w.writerow({
                k: row.get(k, "")
                for k in fields
            })


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    print("=" * 72)
    print("Naruto PSP Stage 32")
    print("Executable-load / renderer-path split diagnostic")
    print("=" * 72)

    h = load_stage24()
    s17 = h.load_stage17()
    elf = s17.ELF32(BOOT)

    original = bytearray(
        elf.data
    )

    relocs = h.relocation_sites(
        elf
    )

    # ========================================================
    # A. ELF entry-point trap
    # ========================================================

    if original[0:4] != b"\x7fELF":
        raise RuntimeError(
            "BOOT.BIN is not raw ELF"
        )

    entry_va = struct.unpack_from(
        "<I",
        original,
        0x18
    )[0]

    entry_off = elf.va_to_offset(
        entry_va
    )

    if entry_off is None:
        raise RuntimeError(
            f"ELF e_entry mapping failed: "
            f"0x{entry_va:08X}"
        )

    entry_old0 = h.u32(
        original,
        entry_off
    )

    entry_old1 = h.u32(
        original,
        entry_off + 4
    )

    entry_relocs = []

    for va in (
        entry_va,
        entry_va + 4,
    ):
        if va in relocs:
            entry_relocs.append({
                "va": va,
                "infos": relocs[va],
            })

    if entry_relocs:
        raise RuntimeError(
            "ELF entry first two instructions "
            "contain relocations; trap aborted"
        )

    patched_a = bytearray(
        original
    )

    # beq zero,zero,-1 -> loop forever at the same instruction.
    h.p32(
        patched_a,
        entry_off,
        0x1000FFFF
    )

    h.p32(
        patched_a,
        entry_off + 4,
        0x00000000
    )

    BOOT_A.write_bytes(
        patched_a
    )

    # ========================================================
    # B. Known Stage18 renderer path:
    # after converter call, force UTF16 buffer[0] = 0.
    #
    # This instruction is not a JAL and has no relocation.
    # If 0x002AC2A4 actually renders event dialogue,
    # body text must become blank.
    # ========================================================

    render_off = elf.va_to_offset(
        RENDER_PATCH_VA
    )

    if render_off is None:
        raise RuntimeError(
            "Renderer test VA mapping failed"
        )

    render_old = h.u32(
        original,
        render_off
    )

    if render_old != EXPECTED_RENDER_WORD:
        raise RuntimeError(
            f"Renderer patch word mismatch: "
            f"0x{render_old:08X} != "
            f"0x{EXPECTED_RENDER_WORD:08X}"
        )

    if RENDER_PATCH_VA in relocs:
        raise RuntimeError(
            "Renderer test instruction unexpectedly "
            "has a relocation"
        )

    patched_b = bytearray(
        original
    )

    h.p32(
        patched_b,
        render_off,
        NEW_RENDER_WORD
    )

    BOOT_B.write_bytes(
        patched_b
    )

    rows = [
        {
            "test":
                "A_ENTRY_TRAP",
            "va":
                f"0x{entry_va:08X}",
            "file_offset":
                f"0x{entry_off:X}",
            "old_word_0":
                f"0x{entry_old0:08X}",
            "old_word_1":
                f"0x{entry_old1:08X}",
            "new_word_0":
                "0x1000FFFF",
            "new_word_1":
                "0x00000000",
            "relocation_hits":
                0,
            "expected_runtime":
                "Game must hang/fail before normal boot "
                "if patched executable is actually loaded.",
        },
        {
            "test":
                "B_RENDERER_BLANK",
            "va":
                f"0x{RENDER_PATCH_VA:08X}",
            "file_offset":
                f"0x{render_off:X}",
            "old_word_0":
                f"0x{render_old:08X}",
            "old_word_1":
                "",
            "new_word_0":
                f"0x{NEW_RENDER_WORD:08X}",
            "new_word_1":
                "",
            "relocation_hits":
                0,
            "expected_runtime":
                "If 0x002AC2A4 is the event-dialogue renderer, "
                "dialogue body must become blank.",
        },
    ]

    write_tsv(
        OUT / "stage32_patch_map.tsv",
        rows,
        [
            "test",
            "va",
            "file_offset",
            "old_word_0",
            "old_word_1",
            "new_word_0",
            "new_word_1",
            "relocation_hits",
            "expected_runtime",
        ]
    )

    (OUT / "stage32_summary.txt").write_text(
        "\n".join([
            "Naruto PSP Stage 32",
            "=" * 72,
            "",
            "This stage does NOT attempt Hangul rendering.",
            "It isolates two unknowns from Stages 23-31.",
            "",
            "A_ENTRY_TRAP:",
            f"  ELF e_entry VA: 0x{entry_va:08X}",
            f"  file offset: 0x{entry_off:X}",
            f"  old words: "
            f"0x{entry_old0:08X} "
            f"0x{entry_old1:08X}",
            "  new: infinite self-loop + nop",
            "  relocation hits: 0",
            "",
            "B_RENDERER_BLANK:",
            f"  VA: 0x{RENDER_PATCH_VA:08X}",
            f"  file offset: 0x{render_off:X}",
            f"  old: 0x{render_old:08X}",
            f"  new: 0x{NEW_RENDER_WORD:08X}",
            "  meaning: force stack UTF16 buffer first code unit to NUL",
            "  relocation hits: 0",
            "",
            f"Original SHA256: {sha256(original)}",
            f"A BOOT SHA256:   {sha256(patched_a)}",
            f"B BOOT SHA256:   {sha256(patched_b)}",
            "",
            "Interpretation:",
            "  A boots normally:",
            "    Our replacement BOOT/EBOOT is not the executable "
            "PPSSPP is actually running (or e_entry is unused).",
            "",
            "  A hangs/fails before normal boot:",
            "    Executable patching is active.",
            "",
            "  B dialogue body blank:",
            "    0x002AC2A4 path is active for event dialogue.",
            "",
            "  B dialogue unchanged:",
            "    0x002AC2A4 is NOT the event-dialogue renderer; "
            "find the real rendering/conversion path.",
        ]),
        encoding="utf-8"
    )

    print()
    print("A entry trap:")
    print(
        f"  e_entry=0x{entry_va:08X} "
        f"file=0x{entry_off:X}"
    )
    print()
    print("B renderer blank:")
    print(
        f"  VA=0x{RENDER_PATCH_VA:08X} "
        f"file=0x{render_off:X}"
    )
    print()
    print(BOOT_A)
    print(BOOT_B)

    print()
    print("=" * 72)
    print("STAGE32 PATCHES READY")
    print("=" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
'@

    Set-Content `
        -LiteralPath $driver `
        -Value $driverCode `
        -Encoding UTF8

    $code = RunPy `
        "driver syntax" `
        @(
            "-m",
            "py_compile",
            $driver
        )

    if ($code -ne 0) {
        throw "Stage32 Python 문법 오류"
    }

    $code = RunPy `
        "[1/3] create split diagnostic BOOTs" `
        @($driver)

    if ($code -ne 0) {
        throw "Stage32 BOOT 생성 실패"
    }

    $bootA = Join-Path `
        $stage `
        "BOOT_stage32A_entry_trap.BIN"

    $bootB = Join-Path `
        $stage `
        "BOOT_stage32B_renderer_blank.BIN"

    if (-not (Test-Path -LiteralPath $bootA)) {
        throw "Stage32A BOOT 없음"
    }

    if (-not (Test-Path -LiteralPath $bootB)) {
        throw "Stage32B BOOT 없음"
    }

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    $dat = Join-Path `
        $base `
        "kr_extracted\PSP_GAME\USRDIR\naruto.dat"

    $idx = Join-Path `
        $base `
        "kr_extracted\PSP_GAME\USRDIR\naruto.idx"

    foreach ($p in @(
        $sourceIso,
        $dat,
        $idx
    )) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 원본 파일 없음: $p"
        }
    }

    $isoA = Join-Path `
        $base `
        "Naruto - Stage32A Executable Load Trap.iso"

    $isoB = Join-Path `
        $base `
        "Naruto - Stage32B Renderer Path Trap.iso"

    Remove-Item `
        -LiteralPath $isoA,$isoB `
        -Force `
        -ErrorAction SilentlyContinue

    $reportA = Join-Path $stage "isoA"
    $reportB = Join-Path $stage "isoB"

    Remove-Item `
        -LiteralPath $reportA,$reportB `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    $code = RunPy `
        "[2/3] build Stage32A entry-trap ISO" `
        @(
            $isoPatcher,
            "--source-iso",
            $sourceIso,
            "--dat",
            $dat,
            "--idx",
            $idx,
            "--boot",
            $bootA,
            "--output-iso",
            $isoA,
            "--report-dir",
            $reportA
        )

    if ($code -ne 0) {
        throw "Stage32A ISO 생성 실패"
    }

    $code = RunPy `
        "[3/3] build Stage32B renderer-trap ISO" `
        @(
            $isoPatcher,
            "--source-iso",
            $sourceIso,
            "--dat",
            $dat,
            "--idx",
            $idx,
            "--boot",
            $bootB,
            "--output-iso",
            $isoB,
            "--report-dir",
            $reportB
        )

    if ($code -ne 0) {
        throw "Stage32B ISO 생성 실패"
    }

    if (-not (Test-Path -LiteralPath $isoA)) {
        throw "Stage32A ISO 없음"
    }

    if (-not (Test-Path -LiteralPath $isoB)) {
        throw "Stage32B ISO 없음"
    }

    $runtime = Join-Path `
        $stage `
        "stage32_runtime_test.txt"

    @(
        "Naruto PSP Stage32"
        "=============================================="
        ""
        "이번 단계는 한글 테스트가 아닙니다."
        "두 가지 핵심 전제를 분리 검증합니다."
        ""
        "A:"
        " $isoA"
        ""
        " A는 ELF entry에 무한루프를 넣었습니다."
        " 정상적으로 게임이 실행/부팅되면 이상합니다."
        " 부팅 전에 멈추거나 검은 화면이면 executable patch가 실제 실행된다는 뜻입니다."
        ""
        "B:"
        " $isoB"
        ""
        " B는 0x002AC2A4 renderer의 converter 직후"
        " UTF16 buffer[0]을 강제로 NUL로 만듭니다."
        ""
        " 첫 이벤트 대사에서:"
        "  - 대사 본문이 사라짐/빈칸 -> 이 renderer 경로가 실제 사용됨"
        "  - 원래 일본어 대사가 정상 -> 이 renderer는 이벤트 대사 경로가 아님"
        ""
        "테스트 순서:"
        " 1. Stage32A 실행 후 부팅 여부만 확인"
        " 2. 종료"
        " 3. Stage32B 실행 후 첫 이벤트 대사 확인"
    ) | Set-Content `
        -LiteralPath $runtime `
        -Encoding UTF8

    # Success-only archive.
    $archive = Join-Path `
        $oldRoot `
        (Get-Date -Format "yyyyMMdd_HHmmss")

    New-Item `
        -ItemType Directory `
        -Force `
        -Path $archive |
        Out-Null

    Get-ChildItem `
        -LiteralPath $logs `
        -Force |
        Where-Object {
            $_.Name -ne "old" -and
            $_.Name -ne "failed"
        } |
        ForEach-Object {
            Move-Item `
                -LiteralPath $_.FullName `
                -Destination $archive `
                -Force
        }

    Get-ChildItem `
        -LiteralPath $stage `
        -File |
        Where-Object {
            $_.Extension -eq ".txt" -or
            $_.Extension -eq ".tsv" -or
            $_.Name -eq "stage32_split_diagnostic.py"
        } |
        ForEach-Object {
            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }

    foreach ($dir in @($reportA,$reportB)) {
        if (Test-Path -LiteralPath $dir) {
            Get-ChildItem `
                -LiteralPath $dir `
                -File |
                ForEach-Object {
                    $prefix = (
                        Split-Path `
                            $dir `
                            -Leaf
                    )

                    Copy-Item `
                        -LiteralPath $_.FullName `
                        -Destination (
                            Join-Path `
                                $logs `
                                ($prefix + "_" + $_.Name)
                        ) `
                        -Force
                }
        }
    }

    Copy-Item `
        -LiteralPath $runLog `
        -Destination $logs `
        -Force

    $readme = Join-Path `
        $logs `
        "README_UPLOAD.txt"

    @(
        "Naruto PSP Stage 32"
        "생성: $(Get-Date)"
        ""
        "A: executable load trap"
        " $isoA"
        ""
        "B: event renderer path trap"
        " $isoB"
        ""
        "ChatGPT 업로드:"
        " naruto_stage32_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage32_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage32_upload.zip"
        } |
        Select-Object `
            -ExpandProperty FullName

    Compress-Archive `
        -Path $zipInputs `
        -DestinationPath $zip `
        -CompressionLevel Optimal `
        -Force

    Log ""
    Log "=========================================="
    Log " STAGE 32 SUCCESS"
    Log "=========================================="
    Log "ISO A: $isoA"
    Log "ISO B: $isoB"
    Log "ZIP:   $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}
