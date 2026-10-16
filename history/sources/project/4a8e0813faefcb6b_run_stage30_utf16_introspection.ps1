$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage30"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage30_$stamp.log"

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
    Write-Host "STAGE 30 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "로그:"
    Write-Host $runLog
}

try {
    Log "Naruto PSP Stage 30"
    Log "UTF16 buffer introspection / direct-write diagnostic"
    Log "Started: $(Get-Date)"

    $stage26 = Join-Path $base "analysis\stage26\stage26_final_unicode_hook.py"
    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"
    $isoPatcher = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"

    foreach ($p in @($stage26,$patcher,$isoPatcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage30_utf16_introspection.py"

    $driverCode = @'
from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage30"
OUT.mkdir(parents=True, exist_ok=True)

STAGE26 = (
    BASE / "analysis" / "stage26"
    / "stage26_final_unicode_hook.py"
)

BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = OUT / "BOOT_stage30_utf16_diag.BIN"
PATCHED_TBL = OUT / "event000_stage30.tbl"


# Larger file-backed .data zero cave, verified safe in Stage25.
CAVE_VA = 0x003A439C
CAVE_OFF = 0x3A43F0
CAVE_AVAILABLE = 2464

CALL_SITE = 0x002AC2EC
ORIGINAL_CONVERTER = 0x002ACCF4

GREEK = [
    b"\x83\xBF",  # α
    b"\x83\xC0",  # β
    b"\x83\xC1",  # γ
    b"\x83\xC2",  # δ
    b"\x83\xC3",  # ε
    b"\x83\xC4",  # ζ
    b"\x83\xC5",  # η
    b"\x83\xC6",  # θ
    b"\x83\xC7",  # ι
    b"\x83\xC8",  # κ
]


def load_stage26():
    spec = importlib.util.spec_from_file_location(
        "stage26hook",
        STAGE26
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


def build_wrapper(mod, cave_va):
    h = mod.load_stage24()

    ZERO = 0
    V0 = 2

    A0 = 4

    T0 = 8
    T1 = 9
    T2 = 10
    T3 = 11
    T4 = 12
    T5 = 13
    T9 = 25

    SP = 29
    RA = 31

    words = []
    labels = {}
    fixups = []

    def emit(word):
        words.append(word)
        return len(words) - 1

    def label(name):
        labels[name] = len(words)

    def branch(op, rs, rt, target):
        idx = emit(0)
        fixups.append(
            (
                idx,
                op,
                rs,
                rt,
                target,
            )
        )
        return idx

    def bal(target):
        idx = emit(0)
        fixups.append(
            (
                idx,
                0x01,
                ZERO,
                0x11,  # bgezal
                target,
            )
        )
        return idx

    # --------------------------------------------------------
    # Wrapper prologue + original converter
    # --------------------------------------------------------

    emit(
        h.I(
            0x09,
            SP,
            SP,
            -32
        )
    )

    emit(
        h.I(
            0x2B,
            SP,
            RA,
            28
        )
    )

    emit(
        h.I(
            0x2B,
            SP,
            A0,
            16
        )
    )

    # RA = runtime address of instruction 5.
    emit(
        h.I(
            0x01,
            ZERO,
            0x11,
            1
        )
    )
    emit(0)

    self_ref = (
        cave_va
        + 5 * 4
    )

    delta = (
        ORIGINAL_CONVERTER
        - self_ref
    ) & 0xFFFFFFFF

    hi, lo = h.split_u32(
        delta
    )

    emit(
        h.I(
            0x0F,
            ZERO,
            T9,
            hi
        )
    )

    emit(
        h.I(
            0x0D,
            T9,
            T9,
            lo
        )
    )

    emit(
        h.R(
            T9,
            RA,
            T9,
            0,
            0x21
        )
    )

    emit(
        h.R(
            T9,
            ZERO,
            RA,
            0,
            0x09
        )
    )

    emit(0)

    # Preserve converter return value.
    emit(
        h.I(
            0x2B,
            SP,
            V0,
            12
        )
    )

    # t0 = actual UTF16 output buffer.
    emit(
        h.I(
            0x23,
            SP,
            T0,
            16
        )
    )

    # --------------------------------------------------------
    # Dispatch by first ASCII character:
    #
    # JHEX:
    # KHEX:
    # AMUT:
    # PJPN:
    # HKOR:
    # --------------------------------------------------------

    emit(
        h.I(
            0x25,
            T0,
            T1,
            0
        )
    )

    for ch, target in [
        (ord("J"), "hex"),
        (ord("K"), "hex"),
        (ord("A"), "amut"),
        (ord("P"), "pjpn"),
        (ord("H"), "hkor"),
    ]:
        emit(
            h.I(
                0x09,
                T1,
                T2,
                -ch
            )
        )
        branch(
            0x04,
            T2,
            ZERO,
            target
        )
        emit(0)

    branch(
        0x04,
        ZERO,
        ZERO,
        "done"
    )
    emit(0)

    # --------------------------------------------------------
    # JHEX / KHEX:
    # show the first raw UTF16 code unit as Hxxxx.
    # --------------------------------------------------------

    label("hex")

    # Prefix is always five characters -> target starts +10.
    emit(
        h.I(
            0x09,
            T0,
            T0,
            10
        )
    )

    emit(
        h.I(
            0x25,
            T0,
            T1,
            0
        )
    )

    # 'H'
    emit(
        h.I(
            0x09,
            ZERO,
            T2,
            ord("H")
        )
    )
    emit(
        h.I(
            0x29,
            T0,
            T2,
            0
        )
    )

    # Four hexadecimal nibbles.
    for shift, offset in [
        (12, 2),
        (8, 4),
        (4, 6),
    ]:
        emit(
            h.R(
                ZERO,
                T1,
                T2,
                shift,
                0x00
            )
        )
        emit(
            h.I(
                0x0C,
                T2,
                T2,
                0x000F
            )
        )
        bal("nibble_ascii")
        emit(0)
        emit(
            h.I(
                0x29,
                T0,
                T2,
                offset
            )
        )

    # low nibble
    emit(
        h.I(
            0x0C,
            T1,
            T2,
            0x000F
        )
    )
    bal("nibble_ascii")
    emit(0)
    emit(
        h.I(
            0x29,
            T0,
            T2,
            8
        )
    )

    branch(
        0x04,
        ZERO,
        ZERO,
        "done"
    )
    emit(0)

    # --------------------------------------------------------
    # AMUT: direct ASCII buffer write.
    # Expected: AMUT:12345
    # --------------------------------------------------------

    label("amut")

    emit(
        h.I(
            0x09,
            T0,
            T0,
            10
        )
    )

    emit(
        h.I(
            0x09,
            ZERO,
            T1,
            ord("1")
        )
    )

    emit(
        h.I(
            0x09,
            ZERO,
            T2,
            5
        )
    )

    label("amut_loop")

    emit(
        h.I(
            0x29,
            T0,
            T1,
            0
        )
    )

    emit(
        h.I(
            0x09,
            T1,
            T1,
            1
        )
    )

    emit(
        h.I(
            0x09,
            T0,
            T0,
            2
        )
    )

    emit(
        h.I(
            0x09,
            T2,
            T2,
            -1
        )
    )

    branch(
        0x05,
        T2,
        ZERO,
        "amut_loop"
    )
    emit(0)

    branch(
        0x04,
        ZERO,
        ZERO,
        "done"
    )
    emit(0)

    # --------------------------------------------------------
    # PJPN: direct known-good Japanese Unicode.
    # Expected: PJPN:あいうえお
    # --------------------------------------------------------

    label("pjpn")

    emit(
        h.I(
            0x09,
            T0,
            T0,
            10
        )
    )

    emit(
        h.I(
            0x09,
            ZERO,
            T1,
            0x3042
        )
    )

    emit(
        h.I(
            0x09,
            ZERO,
            T2,
            5
        )
    )

    label("pjpn_loop")

    emit(
        h.I(
            0x29,
            T0,
            T1,
            0
        )
    )

    emit(
        h.I(
            0x09,
            T1,
            T1,
            2
        )
    )

    emit(
        h.I(
            0x09,
            T0,
            T0,
            2
        )
    )

    emit(
        h.I(
            0x09,
            T2,
            T2,
            -1
        )
    )

    branch(
        0x05,
        T2,
        ZERO,
        "pjpn_loop"
    )
    emit(0)

    branch(
        0x04,
        ZERO,
        ZERO,
        "done"
    )
    emit(0)

    # --------------------------------------------------------
    # HKOR: direct Korean Unicode.
    # Expected: HKOR:가가가가가
    # --------------------------------------------------------

    label("hkor")

    emit(
        h.I(
            0x09,
            T0,
            T0,
            10
        )
    )

    emit(
        h.I(
            0x0D,
            ZERO,
            T1,
            0xAC00
        )
    )

    emit(
        h.I(
            0x09,
            ZERO,
            T2,
            5
        )
    )

    label("hkor_loop")

    emit(
        h.I(
            0x29,
            T0,
            T1,
            0
        )
    )

    emit(
        h.I(
            0x09,
            T0,
            T0,
            2
        )
    )

    emit(
        h.I(
            0x09,
            T2,
            T2,
            -1
        )
    )

    branch(
        0x05,
        T2,
        ZERO,
        "hkor_loop"
    )
    emit(0)

    branch(
        0x04,
        ZERO,
        ZERO,
        "done"
    )
    emit(0)

    # --------------------------------------------------------
    # Helper: t2 nibble 0..15 -> ASCII hex in t2.
    # --------------------------------------------------------

    label("nibble_ascii")

    emit(
        h.I(
            0x0B,
            T2,
            T3,
            10
        )
    )

    branch(
        0x05,
        T3,
        ZERO,
        "nibble_digit"
    )
    emit(0)

    emit(
        h.I(
            0x09,
            T2,
            T2,
            0x37
        )
    )

    emit(
        h.R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )
    emit(0)

    label("nibble_digit")

    emit(
        h.I(
            0x09,
            T2,
            T2,
            0x30
        )
    )

    emit(
        h.R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )
    emit(0)

    # --------------------------------------------------------
    # Return to original renderer.
    # --------------------------------------------------------

    label("done")

    emit(
        h.I(
            0x23,
            SP,
            V0,
            12
        )
    )

    emit(
        h.I(
            0x23,
            SP,
            RA,
            28
        )
    )

    emit(
        h.I(
            0x09,
            SP,
            SP,
            32
        )
    )

    emit(
        h.R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )

    emit(0)

    # --------------------------------------------------------
    # Resolve all branches.
    # --------------------------------------------------------

    def va(index):
        return (
            cave_va
            + index * 4
        )

    for (
        idx,
        op,
        rs,
        rt,
        target
    ) in fixups:

        if target not in labels:
            raise RuntimeError(
                f"Missing label: "
                f"{target}"
            )

        words[idx] = h.branch(
            op,
            rs,
            rt,
            va(idx),
            va(
                labels[target]
            )
        )

    blob = b"".join(
        struct.pack(
            "<I",
            word
        )
        for word in words
    )

    if len(blob) > CAVE_AVAILABLE:
        raise RuntimeError(
            f"Stage30 hook too large: "
            f"{len(blob)} > "
            f"{CAVE_AVAILABLE}"
        )

    return (
        blob,
        words,
        labels,
    )


def make_probe_tbl():
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: "
            f"{SOURCE_TBL}"
        )

    A = GREEK[0:5]
    Z = GREEK[5:10]

    probes = [
        (
            "HEX_ALPHA",
            "JHEX:Hxxxx",
            b"JHEX:"
            + b"".join(A),
        ),
        (
            "HEX_ZETA",
            "KHEX:Hxxxx",
            b"KHEX:"
            + b"".join(Z),
        ),
        (
            "ASCII_DIRECT_WRITE",
            "AMUT:12345",
            b"AMUT:"
            + b"".join(A),
        ),
        (
            "JAPANESE_DIRECT_WRITE",
            "PJPN:あいうえお",
            b"PJPN:"
            + b"".join(A),
        ),
        (
            "KOREAN_DIRECT_WRITE",
            "HKOR:가가가가가",
            b"HKOR:"
            + b"".join(A),
        ),
        (
            "JP_CONTROL",
            "JP:日本語確認",
            b"JP:"
            + "日本語確認".encode(
                "cp932"
            ),
        ),
        (
            "ASCII_CONTROL",
            "ASCII:OK",
            b"ASCII:OK",
        ),
    ]

    raw = SOURCE_TBL.read_bytes()
    lines = raw.splitlines(
        keepends=True
    )

    out = []
    report = []
    index = 0

    for line_no, line in enumerate(
        lines,
        1
    ):
        body = line.rstrip(
            b"\r\n"
        )

        newline = line[
            len(body):
        ]

        if (
            index < len(probes)
            and body.startswith(
                b"MSG ="
            )
        ):
            parts = body.split(
                b",",
                2
            )

            if len(parts) == 3:
                (
                    name,
                    expected,
                    payload,
                ) = probes[
                    index
                ]

                out.append(
                    parts[0]
                    + b","
                    + parts[1]
                    + b","
                    + payload
                    + newline
                )

                report.append({
                    "probe":
                        index + 1,
                    "probe_name":
                        name,
                    "line":
                        line_no,
                    "msg_id":
                        parts[1].decode(
                            "ascii",
                            errors="replace"
                        ),
                    "expected":
                        expected,
                    "encoded_hex":
                        payload.hex(" "),
                })

                index += 1
                continue

        out.append(line)

    if index != len(probes):
        raise RuntimeError(
            f"MSG rows 부족: "
            f"{index}/{len(probes)}"
        )

    PATCHED_TBL.write_bytes(
        b"".join(out)
    )

    write_tsv(
        OUT
        / "stage30_probe_map.tsv",
        report,
        [
            "probe",
            "probe_name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ]
    )


def main():
    print("=" * 72)
    print("Naruto PSP Stage 30")
    print("UTF16 introspection / direct write")
    print("=" * 72)

    mod = load_stage26()
    h = mod.load_stage24()
    s17 = h.load_stage17()

    elf = s17.ELF32(
        BOOT
    )

    original = bytearray(
        elf.data
    )

    actual_cave_off = (
        elf.va_to_offset(
            CAVE_VA
        )
    )

    if actual_cave_off != CAVE_OFF:
        raise RuntimeError(
            f"Cave VA/file mismatch: "
            f"{actual_cave_off} != "
            f"{CAVE_OFF}"
        )

    if any(
        original[
            CAVE_OFF:
            CAVE_OFF
            + CAVE_AVAILABLE
        ]
    ):
        raise RuntimeError(
            "Stage30 selected cave "
            "is not zero in original BOOT"
        )

    call_off = elf.va_to_offset(
        CALL_SITE
    )

    if call_off is None:
        raise RuntimeError(
            "Renderer converter callsite "
            "VA 변환 실패"
        )

    old_word = h.u32(
        original,
        call_off
    )

    expected_word = h.JAL(
        ORIGINAL_CONVERTER
    )

    if old_word != expected_word:
        raise RuntimeError(
            f"Callsite mismatch: "
            f"0x{old_word:08X} != "
            f"0x{expected_word:08X}"
        )

    relocs = h.relocation_sites(
        elf
    )

    if 4 not in relocs.get(
        CALL_SITE,
        []
    ):
        raise RuntimeError(
            "Callsite R_MIPS_26 relocation 없음"
        )

    (
        blob,
        words,
        labels,
    ) = build_wrapper(
        mod,
        CAVE_VA
    )

    patched = bytearray(
        original
    )

    patched[
        CAVE_OFF:
        CAVE_OFF
        + len(blob)
    ] = blob

    new_word = h.JAL(
        CAVE_VA
    )

    h.p32(
        patched,
        call_off,
        new_word
    )

    PATCHED_BOOT.write_bytes(
        patched
    )

    make_probe_tbl()

    rows = []

    for i, word in enumerate(
        words
    ):
        rows.append({
            "index":
                i,
            "va":
                f"0x{CAVE_VA + i*4:08X}",
            "word":
                f"0x{word:08X}",
        })

    write_tsv(
        OUT
        / "stage30_hook_words.tsv",
        rows,
        [
            "index",
            "va",
            "word",
        ]
    )

    label_rows = [
        {
            "label": name,
            "instruction_index": idx,
            "va":
                f"0x{CAVE_VA + idx*4:08X}",
        }
        for name, idx
        in labels.items()
    ]

    write_tsv(
        OUT
        / "stage30_labels.tsv",
        label_rows,
        [
            "label",
            "instruction_index",
            "va",
        ]
    )

    (OUT / "stage30_summary.txt").write_text(
        "\n".join([
            "Naruto PSP Stage30",
            "=" * 72,
            "",
            f"Callsite: 0x{CALL_SITE:08X}",
            f"Original converter: "
            f"0x{ORIGINAL_CONVERTER:08X}",
            f"Code cave: "
            f"0x{CAVE_VA:08X}",
            f"Code cave file: "
            f"0x{CAVE_OFF:X}",
            f"Hook size: "
            f"{len(blob)}",
            "",
            "Runtime probes:",
            "  JHEX: first converted UTF16 "
            "code unit -> Hxxxx",
            "  KHEX: first converted UTF16 "
            "code unit -> Hxxxx",
            "  AMUT: force UTF16 ASCII 12345",
            "  PJPN: force UTF16 あいうえお",
            "  HKOR: force UTF16 가가가가가",
            "",
            "Interpretation:",
            "  AMUT:12345 proves the actual renderer buffer is patched.",
            "  PJPN verifies direct Japanese Unicode rendering.",
            "  HKOR verifies direct Korean Unicode + Korean font rendering.",
        ]),
        encoding="utf-8"
    )

    print()
    print(
        "Code cave:",
        f"0x{CAVE_VA:08X}",
        f"file=0x{CAVE_OFF:X}"
    )
    print(
        "Hook size:",
        len(blob)
    )
    print(
        "Expected key lines:"
    )
    print(
        "  JHEX:Hxxxx"
    )
    print(
        "  KHEX:Hxxxx"
    )
    print(
        "  AMUT:12345"
    )
    print(
        "  PJPN:あいうえお"
    )
    print(
        "  HKOR:가가가가가"
    )

    print()
    print("=" * 72)
    print("STAGE30 HOOK READY")
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
        throw "Stage30 Python 문법 오류"
    }

    $code = RunPy `
        "[1/3] UTF16 diagnostic hook" `
        @($driver)

    if ($code -ne 0) {
        throw "Stage30 hook 생성 실패"
    }

    $probeTbl = Join-Path `
        $stage `
        "event000_stage30.tbl"

    $patchedBoot = Join-Path `
        $stage `
        "BOOT_stage30_utf16_diag.BIN"

    if (-not (
        Test-Path `
            -LiteralPath $probeTbl
    )) {
        throw "event000_stage30.tbl 없음"
    }

    if (-not (
        Test-Path `
            -LiteralPath $patchedBoot
    )) {
        throw "BOOT_stage30_utf16_diag.BIN 없음"
    }

    $patchOut = Join-Path `
        $stage `
        "patch"

    Remove-Item `
        -LiteralPath $patchOut `
        -Recurse `
        -Force `
        -ErrorAction SilentlyContinue

    $replaceArg = "event000.tbl=$probeTbl"

    $code = RunPy `
        "[2/3] DAT/IDX patch" `
        @(
            $patcher,
            "--root",
            $base,
            "--output",
            $patchOut,
            "--replace",
            $replaceArg,
            "--force"
        )

    if ($code -ne 0) {
        throw "Stage30 DAT/IDX patch 실패"
    }

    $dat = Join-Path `
        $patchOut `
        "naruto.dat"

    $idx = Join-Path `
        $patchOut `
        "naruto.idx"

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    $outIso = Join-Path `
        $base `
        "Naruto - Stage30 UTF16 Introspection.iso"

    Remove-Item `
        -LiteralPath $outIso `
        -Force `
        -ErrorAction SilentlyContinue

    $code = RunPy `
        "[3/3] ISO patch" `
        @(
            $isoPatcher,
            "--source-iso",
            $sourceIso,
            "--dat",
            $dat,
            "--idx",
            $idx,
            "--boot",
            $patchedBoot,
            "--output-iso",
            $outIso,
            "--report-dir",
            $stage
        )

    if ($code -ne 0) {
        throw "Stage30 ISO patch 실패"
    }

    if (-not (
        Test-Path `
            -LiteralPath $outIso
    )) {
        throw "Stage30 ISO 생성 안 됨"
    }

    $runtime = Join-Path `
        $stage `
        "stage30_runtime_test.txt"

    @(
        "Naruto PSP Stage30"
        "=============================================="
        ""
        "ISO:"
        " $outIso"
        ""
        "Expected / diagnostic:"
        " 1. JHEX:Hxxxx"
        "    - xxxx = first actual UTF16 value"
        " 2. KHEX:Hxxxx"
        "    - xxxx = first actual UTF16 value"
        " 3. AMUT:12345"
        "    - proves UTF16 output buffer writes"
        " 4. PJPN:あいうえお"
        "    - tests direct Japanese Unicode rendering"
        " 5. HKOR:가가가가가"
        "    - tests direct Korean Unicode rendering"
        " 6. JP:日本語確認"
        " 7. ASCII:OK"
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
            $_.Name -eq "stage30_utf16_introspection.py"
        } |
        ForEach-Object {
            Copy-Item `
                -LiteralPath $_.FullName `
                -Destination $logs `
                -Force
        }

    if (Test-Path -LiteralPath $patchOut) {
        Get-ChildItem `
            -LiteralPath $patchOut `
            -File |
            Where-Object {
                $_.Extension -eq ".txt" -or
                $_.Extension -eq ".tsv"
            } |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination (
                        Join-Path `
                            $logs `
                            ("patcher_" + $_.Name)
                    ) `
                    -Force
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
        "Naruto PSP Stage 30"
        "생성: $(Get-Date)"
        ""
        "목적:"
        " 실제 UTF16 buffer 첫 문자값을 화면에 HEX로 출력."
        " 같은 buffer에 ASCII/Japanese/Korean Unicode를"
        " 각각 직접 써서 어느 단계가 실패하는지 확정."
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage30_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage30_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage30_upload.zip"
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
    Log " STAGE 30 SUCCESS"
    Log "=========================================="
    Log "ISO: $outIso"
    Log "ZIP: $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}
