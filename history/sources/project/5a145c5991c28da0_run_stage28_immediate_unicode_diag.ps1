$ErrorActionPreference = "Stop"

$base = "PROJECT_ROOT"
$stage = Join-Path $base "analysis\stage28"
$logs = Join-Path $base "logs"
$oldRoot = Join-Path $logs "old"
$failedRoot = Join-Path $logs "failed"

New-Item -ItemType Directory -Force -Path $stage,$logs,$oldRoot,$failedRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runLog = Join-Path $stage "naruto_stage28_$stamp.log"

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
    Write-Host "STAGE 28 FAILED"
    Write-Host $Reason
    Write-Host ""
    Write-Host "로그:"
    Write-Host $runLog
}

try {
    Log "Naruto PSP Stage 28"
    Log "Immediate Unicode remap diagnostic (no table)"
    Log "Started: $(Get-Date)"

    $stage26 = Join-Path $base "analysis\stage26\stage26_final_unicode_hook.py"
    $patcher = Join-Path $base "analysis\stage14\naruto_patcher.py"
    $isoPatcher = Join-Path $base "analysis\stage24\stage24_iso_multi_patch.py"

    foreach ($p in @($stage26,$patcher,$isoPatcher)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "필수 파일 없음: $p"
        }
    }

    $driver = Join-Path $stage "stage28_immediate_unicode_diag.py"

    $driverCode = @'
from pathlib import Path
import csv
import importlib.util
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT = BASE / "analysis" / "stage28"
OUT.mkdir(parents=True, exist_ok=True)

SOURCE = (
    BASE / "analysis" / "stage26"
    / "stage26_final_unicode_hook.py"
)

SOURCE_TBL = (
    BASE / "analysis" / "stage14"
    / "test_patch" / "event000_original.tbl"
)

PATCHED_BOOT = OUT / "BOOT_stage28_immediate_hook.BIN"
PATCHED_TBL = OUT / "event000_stage28.tbl"


# Valid CP932 Greek placeholders.
# The hook contains NO replacement table in .data.
# It computes target Unicode entirely with MIPS immediates.
PLACEHOLDERS = [
    ("α", b"\x83\xBF", 0x03B1, "ぁ", 0x3041),
    ("β", b"\x83\xC0", 0x03B2, "あ", 0x3042),
    ("γ", b"\x83\xC1", 0x03B3, "ぃ", 0x3043),
    ("δ", b"\x83\xC2", 0x03B4, "い", 0x3044),
    ("ε", b"\x83\xC3", 0x03B5, "ぅ", 0x3045),

    ("ζ", b"\x83\xC4", 0x03B6, "ㄱ", 0x3131),
    ("η", b"\x83\xC5", 0x03B7, "ㄲ", 0x3132),
    ("θ", b"\x83\xC6", 0x03B8, "ㄳ", 0x3133),
    ("ι", b"\x83\xC7", 0x03B9, "ㄴ", 0x3134),
    ("κ", b"\x83\xC8", 0x03BA, "ㄵ", 0x3135),
]


def load_source():
    spec = importlib.util.spec_from_file_location(
        "stage26hook",
        SOURCE
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


def build_immediate_hook(mod, cave_va):
    # bgezal at cave+8 sets RA = cave+16.
    self_ref = cave_va + 0x10

    parser_delta = (
        0x002AC8AC
        - self_ref
    ) & 0xFFFFFFFF

    p_hi, p_lo = mod.split_u32(
        parser_delta
    )

    ZERO = 0
    V0 = 2
    T0 = 8
    T1 = 9
    T9 = 25
    SP = 29
    RA = 31

    words = []

    # 0..1: stack + caller RA
    words.append(
        mod.I(
            0x09,
            SP,
            SP,
            -16
        )
    )
    words.append(
        mod.I(
            0x2B,
            SP,
            RA,
            12
        )
    )

    # 2..3: get runtime PC in RA
    words.append(
        mod.I(
            0x01,
            ZERO,
            0x11,
            1
        )
    )
    words.append(0)

    # 4..8: call original UTF-8 decoder
    words.append(
        mod.I(
            0x0F,
            ZERO,
            T9,
            p_hi
        )
    )
    words.append(
        mod.I(
            0x0D,
            T9,
            T9,
            p_lo
        )
    )
    words.append(
        mod.R(
            T9,
            RA,
            T9,
            0,
            0x21
        )
    )
    words.append(
        mod.R(
            T9,
            ZERO,
            RA,
            0,
            0x09
        )
    )
    words.append(0)

    # 9: index = decoded codepoint - U+03B1
    words.append(
        mod.I(
            0x09,
            V0,
            T0,
            -0x03B1
        )
    )

    # 10: in custom 10-char range?
    words.append(
        mod.I(
            0x0B,
            T0,
            T1,
            10
        )
    )

    # 11: if not, return original decoder result
    # done is instruction 20.
    words.append(
        mod.branch(
            0x04,
            T1,
            ZERO,
            cave_va + 11 * 4,
            cave_va + 20 * 4
        )
    )
    words.append(0)

    # 13: first five?
    words.append(
        mod.I(
            0x0B,
            T0,
            T1,
            5
        )
    )

    # 14: if index >= 5 -> Korean branch at instruction 19
    words.append(
        mod.branch(
            0x04,
            T1,
            ZERO,
            cave_va + 14 * 4,
            cave_va + 19 * 4
        )
    )
    words.append(0)

    # 16: Japanese U+3041 + index
    words.append(
        mod.I(
            0x09,
            T0,
            V0,
            0x3041
        )
    )

    # 17: unconditional branch -> done
    words.append(
        mod.branch(
            0x04,
            ZERO,
            ZERO,
            cave_va + 17 * 4,
            cave_va + 20 * 4
        )
    )
    words.append(0)

    # 19: Korean compatibility Jamo.
    # For index=5 => U+3131:
    # v0 = index + (0x3131 - 5) = index + 0x312C
    words.append(
        mod.I(
            0x09,
            T0,
            V0,
            0x312C
        )
    )

    # 20..23: restore + return
    words.append(
        mod.I(
            0x23,
            SP,
            RA,
            12
        )
    )
    words.append(
        mod.I(
            0x09,
            SP,
            SP,
            16
        )
    )
    words.append(
        mod.R(
            RA,
            ZERO,
            ZERO,
            0,
            0x08
        )
    )
    words.append(0)

    if len(words) != 24:
        raise RuntimeError(
            f"Unexpected instruction count: "
            f"{len(words)}"
        )

    blob = b"".join(
        struct.pack(
            "<I",
            w
        )
        for w in words
    )

    if len(blob) != 96:
        raise RuntimeError(
            f"Unexpected hook size: "
            f"{len(blob)}"
        )

    # No external table.
    return blob, words, 0


def make_probe_tbl():
    if not SOURCE_TBL.exists():
        raise RuntimeError(
            f"원본 event000.tbl 없음: "
            f"{SOURCE_TBL}"
        )

    P = [x[1] for x in PLACEHOLDERS]

    probes = [
        (
            "JAPANESE_IMMEDIATE",
            "JMAP:ぁあぃいぅ",
            b"JMAP:" + b"".join(P[0:5]),
        ),
        (
            "KOREAN_JAMO_IMMEDIATE",
            "KMAP:ㄱㄲㄳㄴㄵ",
            b"KMAP:" + b"".join(P[5:10]),
        ),
        (
            "MIX_IMMEDIATE",
            "MIX:ぁㄱあㄲ",
            b"MIX:"
            + P[0] + P[5]
            + P[1] + P[6],
        ),
        (
            "JP_ORIGINAL_CONTROL",
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
                name, expected, payload = (
                    probes[index]
                )

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
        OUT / "stage28_probe_map.tsv",
        report,
        [
            "probe",
            "probe_name",
            "line",
            "msg_id",
            "expected",
            "encoded_hex",
        ],
    )


def main():
    print("=" * 72)
    print("Naruto PSP Stage 28")
    print("Immediate Unicode diagnostic")
    print("=" * 72)

    mod = load_source()

    # Reuse all Stage26 ELF validation and ISO-compatible patch
    # logic, but remove the runtime replacement table entirely.
    mod.OUT = OUT
    mod.PATCHED_BOOT = PATCHED_BOOT
    mod.PATCHED_TBL = PATCHED_TBL
    mod.PLACEHOLDERS = PLACEHOLDERS
    mod.build_hook = build_immediate_hook
    mod.make_probe_tbl = make_probe_tbl

    mod.main()

    # Normalize report names.
    for p in list(
        OUT.glob(
            "stage26_*"
        )
    ):
        dest = p.with_name(
            p.name.replace(
                "stage26_",
                "stage28_",
                1
            )
        )
        if dest.exists():
            dest.unlink()
        p.rename(dest)

    (OUT / "stage28_diagnostic_guide.txt").write_text(
        "\n".join([
            "Naruto PSP Stage28",
            "=" * 72,
            "",
            "No Unicode replacement table is used.",
            "All target codepoints are generated by MIPS arithmetic.",
            "",
            "Expected:",
            "  JMAP:ぁあぃいぅ",
            "  KMAP:ㄱㄲㄳㄴㄵ",
            "  MIX:ぁㄱあㄲ",
            "  JP:日本語確認",
            "  ASCII:OK",
            "",
            "Interpretation:",
            "  JMAP clean + KMAP corrupt:",
            "    final Unicode hook is correct;",
            "    Korean font selection/rendering is the remaining issue.",
            "",
            "  JMAP + KMAP both clean:",
            "    previous corruption was the .data replacement table.",
            "",
            "  JMAP also corrupt:",
            "    the hook point/return semantics must be revised.",
        ]),
        encoding="utf-8"
    )

    print()
    print("Expected runtime:")
    print("  JMAP:ぁあぃいぅ")
    print("  KMAP:ㄱㄲㄳㄴㄵ")
    print("  MIX:ぁㄱあㄲ")
    print()
    print(PATCHED_BOOT)
    print(PATCHED_TBL)


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
        @("-m","py_compile",$driver)

    if ($code -ne 0) {
        throw "Stage28 Python 문법 오류"
    }

    $code = RunPy `
        "[1/3] immediate Unicode hook" `
        @($driver)

    if ($code -ne 0) {
        throw "Stage28 hook 생성 실패"
    }

    $probeTbl = Join-Path `
        $stage `
        "event000_stage28.tbl"

    $patchedBoot = Join-Path `
        $stage `
        "BOOT_stage28_immediate_hook.BIN"

    if (-not (Test-Path -LiteralPath $probeTbl)) {
        throw "event000_stage28.tbl 없음"
    }

    if (-not (Test-Path -LiteralPath $patchedBoot)) {
        throw "BOOT_stage28_immediate_hook.BIN 없음"
    }

    $patchOut = Join-Path $stage "patch"

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
            "--root",$base,
            "--output",$patchOut,
            "--replace",$replaceArg,
            "--force"
        )

    if ($code -ne 0) {
        throw "Stage28 DAT/IDX patch 실패"
    }

    $dat = Join-Path $patchOut "naruto.dat"
    $idx = Join-Path $patchOut "naruto.idx"

    $sourceIso = Join-Path `
        $base `
        "kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

    # ISO always at project root.
    $outIso = Join-Path `
        $base `
        "Naruto - Stage28 Immediate Unicode Diagnostic.iso"

    Remove-Item `
        -LiteralPath $outIso `
        -Force `
        -ErrorAction SilentlyContinue

    $code = RunPy `
        "[3/3] ISO patch" `
        @(
            $isoPatcher,
            "--source-iso",$sourceIso,
            "--dat",$dat,
            "--idx",$idx,
            "--boot",$patchedBoot,
            "--output-iso",$outIso,
            "--report-dir",$stage
        )

    if ($code -ne 0) {
        throw "Stage28 ISO patch 실패"
    }

    if (-not (Test-Path -LiteralPath $outIso)) {
        throw "Stage28 ISO 생성 안 됨"
    }

    # Success-only log archive.
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
            $_.Name -eq "stage28_immediate_unicode_diag.py"
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
        "Naruto PSP Stage 28"
        "생성: $(Get-Date)"
        ""
        "핵심:"
        " Stage26/27의 replacement table을 완전히 제거."
        " MIPS immediate arithmetic만으로 target Unicode 생성."
        ""
        "Expected:"
        " JMAP:ぁあぃいぅ"
        " KMAP:ㄱㄲㄳㄴㄵ"
        " MIX:ぁㄱあㄲ"
        ""
        "ISO:"
        " $outIso"
        ""
        "ChatGPT 업로드:"
        " naruto_stage28_upload.zip"
        ""
        "이전 성공 logs:"
        " $archive"
    ) | Set-Content `
        -LiteralPath $readme `
        -Encoding UTF8

    $zip = Join-Path `
        $logs `
        "naruto_stage28_upload.zip"

    Remove-Item `
        -LiteralPath $zip `
        -Force `
        -ErrorAction SilentlyContinue

    $zipInputs = Get-ChildItem `
        -LiteralPath $logs `
        -File |
        Where-Object {
            $_.Name -ne "naruto_stage28_upload.zip"
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
    Log " STAGE 28 SUCCESS"
    Log "=========================================="
    Log "ISO: $outIso"
    Log "ZIP: $zip"
}
catch {
    Fail $_.Exception.Message
    throw
}

