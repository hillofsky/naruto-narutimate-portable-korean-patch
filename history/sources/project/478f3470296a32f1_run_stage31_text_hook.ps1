$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage31"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage31_$stamp.log"

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
    Write-Host "STAGE 31 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "로그:"
    Write-Host $runLog
}

try {
    Log "Naruto PSP Stage 31"
    Log "Executable .text hook proof"
    Log "Started: $(Get-Date)"

    $stage26 = Join-Path $base "analysis\stage26\stage26_final_unicode_hook.py"
    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"
    $isoPatcher = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"

    foreach ($p in @($stage26,$patcher,$isoPatcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage31_text_hook.py"

    $driverCode = @'
from pathlib import Path
import csv
import hashlib
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage31"
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

PATCHED_BOOT = OUT / "BOOT_stage31_text_hook.BIN"
PATCHED_TBL = OUT / "event000_stage31.tbl"


# Unused arithmetic/validation helper area in executable .text.
# Stage19 showed no direct JAL callers to these helper entries.
HOOK_VA = 0x002AD2C8

# Keep the diagnostic hook entirely before 0x002AD44C.
HOOK_LIMIT_VA = 0x002AD44C

# Renderer -> source text to 16-bit converter.
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


def collect_direct_targets(h, elf):
    text = elf.section(".text")
    start = text["offset"]
    end = text["offset"] + text["size"]

    rows = []

    p = start
    while p + 4 <= end:
        word = h.u32(
            elf.data,
            p
        )

        pc = (
            text["addr"]
            + p
            - text["offset"]
        )

        op = (
            word >> 26
        ) & 0x3F

        target = None
        kind = None

        if op in (2, 3):
            target = (
                ((pc + 4) & 0xF0000000)
                |
                ((word & 0x03FFFFFF) << 2)
            )
            kind = (
                "JAL"
                if op == 3
                else "J"
            )

        elif op in (
            1, 4, 5, 6, 7,
            0x14, 0x15, 0x16, 0x17
        ):
            imm = word & 0xFFFF

            if imm & 0x8000:
                imm -= 0x10000

            target = (
                pc
                + 4
                + imm * 4
            )
            kind = "BRANCH"

        if target is not None:
            rows.append({
                "source_va": pc,
                "target_va": target,
                "kind": kind,
            })

        p += 4

    return rows


def validate_hook_region(h, elf, hook_size):
    hook_end = HOOK_VA + hook_size

    if hook_end > HOOK_LIMIT_VA:
        raise RuntimeError(
            f"hook too large for reserved .text range: "
            f"0x{hook_end:08X} > "
            f"0x{HOOK_LIMIT_VA:08X}"
        )

    # --------------------------------------------------------
    # Existing .rel.text entries inside our overwritten bytes
    # would mutate the new hook during PRX relocation.
    # Therefore require exactly zero.
    # --------------------------------------------------------

    relocs = h.relocation_sites(
        elf
    )

    relocation_hits = []

    for va, infos in relocs.items():
        if HOOK_VA <= va < hook_end:
            relocation_hits.append(
                (
                    va,
                    infos,
                )
            )

    # --------------------------------------------------------
    # Direct J/JAL/branch entries from OUTSIDE the overwritten
    # range into it must also be zero.
    # --------------------------------------------------------

    incoming = []

    for row in collect_direct_targets(
        h,
        elf
    ):
        src = row["source_va"]
        dst = row["target_va"]

        if (
            HOOK_VA <= dst < hook_end
            and not (
                HOOK_VA <= src < hook_end
            )
        ):
            incoming.append(
                row
            )

    # --------------------------------------------------------
    # Scan raw .data words for direct address references.
    # --------------------------------------------------------

    data_sec = elf.section(
        ".data"
    )

    data_refs = []

    if data_sec is not None:
        p = data_sec["offset"]
        end = (
            data_sec["offset"]
            + data_sec["size"]
        )

        while p + 4 <= end:
            value = h.u32(
                elf.data,
                p
            )

            if HOOK_VA <= value < hook_end:
                data_refs.append({
                    "file_offset": p,
                    "value": value,
                })

            p += 4

    write_tsv(
        OUT / "stage31_text_region_validation.tsv",
        [
            {
                "hook_va":
                    f"0x{HOOK_VA:08X}",
                "hook_end":
                    f"0x{hook_end:08X}",
                "hook_size":
                    hook_size,
                "relocation_hits":
                    len(relocation_hits),
                "external_direct_incoming":
                    len(incoming),
                "raw_data_refs":
                    len(data_refs),
            }
        ],
        [
            "hook_va",
            "hook_end",
            "hook_size",
            "relocation_hits",
            "external_direct_incoming",
            "raw_data_refs",
        ]
    )

    if relocation_hits:
        text = ", ".join(
            f"0x{va:08X}"
            for va, _
            in relocation_hits
        )

        raise RuntimeError(
            "Chosen .text hook range contains "
            f"relocations: {text}"
        )

    if incoming:
        text = ", ".join(
            f"{x['kind']} "
            f"0x{x['source_va']:08X}->"
            f"0x{x['target_va']:08X}"
            for x in incoming
        )

        raise RuntimeError(
            "Chosen .text hook range has "
            f"external direct xrefs: {text}"
        )

    if data_refs:
        text = ", ".join(
            f"file=0x{x['file_offset']:X} "
            f"value=0x{x['value']:08X}"
            for x in data_refs
        )

        raise RuntimeError(
            "Chosen .text hook range has "
            f"raw .data refs: {text}"
        )

    return hook_end


def build_hook(mod):
    h = mod.load_stage24()

    ZERO = 0
    V0 = 2
    A0 = 4

    T0 = 8
    T1 = 9
    T2 = 10
    T3 = 11
    T9 = 25

    SP = 29
    RA = 31

    words = []
    labels = {}
    fixups = []

    def emit(word):
        words.append(word)

    def label(name):
        labels[name] = len(words)

    def branch(op, rs, rt, target):
        index = len(words)
        words.append(0)
        fixups.append(
            (
                index,
                op,
                rs,
                rt,
                target,
            )
        )

    # --------------------------------------------------------
    # Save caller and output pointer.
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

    # Runtime PC in RA.
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
        HOOK_VA
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

    # Preserve converter return.
    emit(
        h.I(
            0x2B,
            SP,
            V0,
            12
        )
    )

    # Output buffer pointer.
    emit(
        h.I(
            0x23,
            SP,
            T0,
            16
        )
    )

    # --------------------------------------------------------
    # Walk the produced 16-bit stream.
    #
    # U+03B1..03B5 -> ASCII 1..5
    # U+03B6..03BA -> U+AC00 ("가")
    # --------------------------------------------------------

    label("loop")

    emit(
        h.I(
            0x25,
            T0,
            T1,
            0
        )
    )

    branch(
        0x04,
        T1,
        ZERO,
        "done"
    )
    emit(0)

    emit(
        h.I(
            0x09,
            T1,
            T2,
            -0x03B1
        )
    )

    emit(
        h.I(
            0x0B,
            T2,
            T3,
            10
        )
    )

    branch(
        0x04,
        T3,
        ZERO,
        "next"
    )
    emit(0)

    emit(
        h.I(
            0x0B,
            T2,
            T3,
            5
        )
    )

    branch(
        0x04,
        T3,
        ZERO,
        "hangul"
    )
    emit(0)

    # α..ε => '1'..'5'
    emit(
        h.I(
            0x09,
            T2,
            T1,
            0x31
        )
    )

    branch(
        0x04,
        ZERO,
        ZERO,
        "store"
    )
    emit(0)

    # ζ..κ => Hangul '가'
    label("hangul")

    emit(
        h.I(
            0x0D,
            ZERO,
            T1,
            0xAC00
        )
    )

    label("store")

    emit(
        h.I(
            0x29,
            T0,
            T1,
            0
        )
    )

    label("next")

    emit(
        h.I(
            0x09,
            T0,
            T0,
            2
        )
    )

    branch(
        0x04,
        ZERO,
        ZERO,
        "loop"
    )
    emit(0)

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

    def va(index):
        return (
            HOOK_VA
            + index * 4
        )

    for (
        index,
        op,
        rs,
        rt,
        target
    ) in fixups:

        if target not in labels:
            raise RuntimeError(
                f"Missing label: {target}"
            )

        words[index] = h.branch(
            op,
            rs,
            rt,
            va(index),
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

    probes = [
        (
            "TEXT_HOOK_ASCII",
            "AMAP:12345",
            b"AMAP:"
            + b"".join(
                GREEK[0:5]
            ),
        ),
        (
            "TEXT_HOOK_HANGUL",
            "KMAP:가가가가가",
            b"KMAP:"
            + b"".join(
                GREEK[5:10]
            ),
        ),
        (
            "TEXT_HOOK_MIX",
            "MIX:1가2가",
            b"MIX:"
            + GREEK[0]
            + GREEK[5]
            + GREEK[1]
            + GREEK[6],
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
        / "stage31_probe_map.tsv",
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
    print("Naruto PSP Stage 31")
    print("Executable .text hook proof")
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

    hook_off = elf.va_to_offset(
        HOOK_VA
    )

    if hook_off is None:
        raise RuntimeError(
            "HOOK_VA file offset 변환 실패"
        )

    blob, words, labels = (
        build_hook(
            mod
        )
    )

    hook_end = validate_hook_region(
        h,
        elf,
        len(blob)
    )

    call_off = elf.va_to_offset(
        CALL_SITE
    )

    if call_off is None:
        raise RuntimeError(
            "CALL_SITE file offset 변환 실패"
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

    call_relocs = h.relocation_sites(
        elf
    ).get(
        CALL_SITE,
        []
    )

    if 4 not in call_relocs:
        raise RuntimeError(
            "Renderer callsite에 "
            "R_MIPS_26 relocation 없음"
        )

    patched = bytearray(
        original
    )

    patched[
        hook_off:
        hook_off + len(blob)
    ] = blob

    new_word = h.JAL(
        HOOK_VA
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

    hook_rows = []

    for i, word in enumerate(
        words
    ):
        hook_rows.append({
            "index":
                i,
            "va":
                f"0x{HOOK_VA + i*4:08X}",
            "word":
                f"0x{word:08X}",
        })

    write_tsv(
        OUT
        / "stage31_hook_words.tsv",
        hook_rows,
        [
            "index",
            "va",
            "word",
        ]
    )

    label_rows = [
        {
            "label":
                name,
            "instruction_index":
                idx,
            "va":
                f"0x{HOOK_VA + idx*4:08X}",
        }
        for (
            name,
            idx
        ) in labels.items()
    ]

    write_tsv(
        OUT
        / "stage31_labels.tsv",
        label_rows,
        [
            "label",
            "instruction_index",
            "va",
        ]
    )

    write_tsv(
        OUT
        / "stage31_patch.tsv",
        [
            {
                "kind":
                    "RENDERER_JAL",
                "va":
                    f"0x{CALL_SITE:08X}",
                "file_offset":
                    f"0x{call_off:X}",
                "old":
                    f"0x{old_word:08X}",
                "new":
                    f"0x{new_word:08X}",
            },
            {
                "kind":
                    "TEXT_HOOK",
                "va":
                    f"0x{HOOK_VA:08X}",
                "file_offset":
                    f"0x{hook_off:X}",
                "old":
                    f"{len(blob)} original text bytes",
                "new":
                    f"{len(blob)} byte hook",
            },
        ],
        [
            "kind",
            "va",
            "file_offset",
            "old",
            "new",
        ]
    )

    (OUT / "stage31_summary.txt").write_text(
        "\n".join([
            "Naruto PSP Stage31",
            "=" * 72,
            "",
            "Purpose:",
            "  Prove whether previous failures were caused by",
            "  executing injected code from .data.",
            "",
            f"Renderer callsite: "
            f"0x{CALL_SITE:08X}",
            f"Original converter: "
            f"0x{ORIGINAL_CONVERTER:08X}",
            f"Hook .text VA: "
            f"0x{HOOK_VA:08X}",
            f"Hook .text end: "
            f"0x{hook_end:08X}",
            f"Hook file offset: "
            f"0x{hook_off:X}",
            f"Hook size: "
            f"{len(blob)} bytes",
            "",
            "Expected:",
            "  AMAP:12345",
            "  KMAP:가가가가가",
            "  MIX:1가2가",
            "  JP:日本語確認",
            "  ASCII:OK",
            "",
            "If AMAP becomes 12345, the .text hook executed.",
        ]),
        encoding="utf-8"
    )

    print()
    print(
        ".text hook:",
        f"0x{HOOK_VA:08X}",
        f"file=0x{hook_off:X}",
        f"size={len(blob)}"
    )

    print(
        "Expected:"
    )
    print(
        "  AMAP:12345"
    )
    print(
        "  KMAP:가가가가가"
    )
    print(
        "  MIX:1가2가"
    )

    print()
    print("=" * 72)
    print("STAGE31 HOOK READY")
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
        throw "Stage31 Python 문법 오류"
    }

    $code = RunPy `
        "[1/3] executable text hook" `
        @($driver)

    if ($code -ne 0) {
        throw "Stage31 hook 생성 실패"
    }

    $probeTbl = Join-Path `
        $stage `
        "event000_stage31.tbl"

    $patchedBoot = Join-Path `
        $stage `
        "BOOT_stage31_text_hook.BIN"

    if (-not (
        Test-Path `
            -LiteralPath $probeTbl
    )) {
        throw "event000_stage31.tbl 없음"
    }

    if (-not (
        Test-Path `
            -LiteralPath $patchedBoot
    )) {
        throw "BOOT_stage31_text_hook.BIN 없음"
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
        throw "Stage31 DAT/IDX patch 실패"
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
        "Naruto - Stage31 Executable Text Hook Test.iso"

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
        throw "Stage31 ISO patch 실패"
    }

    if (-not (
        Test-Path `
            -LiteralPath $outIso
    )) {
        throw "Stage31 ISO 생성 안 됨"
    }

    $runtime = Join-Path `
        $stage `
        "stage31_runtime_test.txt"

    @(
        "Naruto PSP Stage31"
        "=============================================="
        ""
        "ISO:"
        " $outIso"
        ""
        "This hook is in executable .text,"
        "NOT in .data."
        ""
        "Expected:"
        " 1. AMAP:12345"
        " 2. KMAP:가가가가가"
        " 3. MIX:1가2가"
        " 4. JP:日本語確認"
        " 5. ASCII:OK"
        ""
        "판정:"
        " AMAP=12345 -> hook 실행 확정"
        " AMAP가 Greek/깨진 글자 -> callsite/hook가 실행되지 않음"
        " AMAP 정상 + KMAP 깨짐 -> Korean font path 문제"
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
            $_.Name -eq "stage31_text_hook.py"
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
        "Naruto PSP Stage 31"
        "생성: $(Get-Date)"
        ""
        "핵심:"
        " .data code cave 사용 중단."
        " unused executable .text 영역에 hook 삽입."
        ""
        "Expected:"
        " AMAP:12345"
        " KMAP:가가가가가"
        " MIX:1가2가"
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage31_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage31_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage31_upload.zip"
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
    Log " STAGE 31 SUCCESS"
    Log "=========================================="
    Log "ISO: $outIso"
    Log "ZIP: $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}
