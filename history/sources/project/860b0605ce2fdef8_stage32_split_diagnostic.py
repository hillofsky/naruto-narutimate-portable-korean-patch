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
