from pathlib import Path
import re
import sys


TARGET = Path(
    r"PROJECT_ROOT\analysis\stage23\stage23_hangul_hook.py"
)

text = TARGET.read_text(
    encoding="utf-8-sig"
)


# ============================================================
# 1. Add deterministic PT_LOAD/BSS injection-space finder.
#
# KR ELF layout:
#
#   PT_LOAD file-backed bytes end
#       
#   unused bytes in ELF file
#       
#   .rel.text begins
#
# Memory already reserves additional bytes through p_memsz,
# and PT_LOAD has RWX flags.
#
# So extend p_filesz slightly into the existing BSS memory
# instead of requiring an unused cave inside .text.
# ============================================================

marker = '''
# ============================================================
# Hook
# ============================================================
'''

if marker not in text:
    raise RuntimeError(
        "Hook marker를 찾을 수 없습니다."
    )


new_function = r'''
# ============================================================
# Deterministic loader-gap injection
# ============================================================

def find_loader_gap_cave(
    elf,
    minimum=0xA0
):
    candidates = []

    for p in elf.programs:

        # PT_LOAD
        if p["type"] != 1:
            continue

        # Must be executable.
        # ELF PF_X == 1.
        if not (
            p["flags"] & 0x1
        ):
            continue

        file_end = (
            p["offset"]
            + p["filesz"]
        )

        mem_end = (
            p["offset"]
            + p["memsz"]
        )

        memory_slack = (
            p["memsz"]
            - p["filesz"]
        )

        if memory_slack < minimum:
            continue

        # Find the next real file-backed ELF section.
        #
        # SHT_NOBITS (.bss) occupies memory but has no bytes
        # in the file, so it does not block this injection.
        next_file_offset = len(
            elf.data
        )

        blocking = []

        for s in elf.sections:

            # SHT_NOBITS
            if s["type"] == 8:
                continue

            if s["size"] <= 0:
                continue

            soff = s["offset"]

            if soff >= file_end:

                next_file_offset = min(
                    next_file_offset,
                    soff
                )

        file_gap = (
            next_file_offset
            - file_end
        )

        if file_gap < minimum:
            continue

        cave_off = (
            file_end + 3
        ) & ~3

        alignment_loss = (
            cave_off
            - file_end
        )

        available = min(
            file_gap - alignment_loss,
            memory_slack - alignment_loss
        )

        if available < minimum:
            continue

        cave_va = (
            p["vaddr"]
            + (
                cave_off
                - p["offset"]
            )
        )

        cave_end = (
            cave_off
            + minimum
        )

        # Make absolutely sure this range does not overlap
        # any existing file-backed section.
        overlap = False

        for s in elf.sections:

            if s["type"] == 8:
                continue

            if s["size"] <= 0:
                continue

            s0 = s["offset"]
            s1 = (
                s["offset"]
                + s["size"]
            )

            if (
                cave_off < s1
                and cave_end > s0
            ):
                overlap = True
                blocking.append(
                    s["name"]
                )

        if overlap:
            continue

        old_filesz = p[
            "filesz"
        ]

        new_filesz = (
            cave_end
            - p["offset"]
        )

        if new_filesz > p["memsz"]:
            continue

        phdr_offset = (
            elf.e_phoff
            + p["index"]
            * elf.e_phentsize
        )

        row = {
            "file_offset":
                cave_off,

            "file_offset_hex":
                f"0x{cave_off:X}",

            "va":
                cave_va,

            "va_hex":
                f"0x{cave_va:08X}",

            "available":
                available,

            "branch_targets":
                0,

            "relocations":
                0,

            "data_pointers":
                0,

            "preceded_by_control":
                False,

            "safe":
                True,

            "requires_zero":
                False,

            "extend_load":
                True,

            "program_index":
                p["index"],

            "phdr_offset":
                phdr_offset,

            "old_filesz":
                old_filesz,

            "new_filesz":
                new_filesz,

            "old_memsz":
                p["memsz"],

            "file_gap":
                file_gap,

            "memory_slack":
                memory_slack,

            "next_file_offset":
                next_file_offset,
        }

        candidates.append(
            row
        )

    if not candidates:
        raise RuntimeError(
            "PT_LOAD 끝과 다음 ELF section 사이에 "
            "0xA0-byte 삽입 공간을 찾지 못했습니다."
        )

    # Prefer the smallest sufficient file gap.
    candidates.sort(
        key=lambda x: (
            x["available"],
            x["file_offset"]
        )
    )

    chosen = candidates[0]

    # Keep Stage23's existing required report name.
    write_tsv(
        OUT
        / "stage23_code_caves.tsv",
        candidates,
        [
            "file_offset",
            "file_offset_hex",
            "va",
            "va_hex",
            "available",
            "branch_targets",
            "relocations",
            "data_pointers",
            "preceded_by_control",
            "safe",
            "program_index",
            "phdr_offset",
            "old_filesz",
            "new_filesz",
            "old_memsz",
            "file_gap",
            "memory_slack",
            "next_file_offset",
        ]
    )

    return chosen


'''


text = text.replace(
    marker,
    new_function + marker,
    1
)


# ============================================================
# 2. Replace old .text-only cave selection.
# ============================================================

old_call = '''    cave = find_code_cave(
        elf,
        minimum=0xA0
    )
'''

new_call = '''    cave = find_loader_gap_cave(
        elf,
        minimum=0xA0
    )
'''


if old_call not in text:
    raise RuntimeError(
        "기존 find_code_cave 호출을 찾지 못했습니다."
    )


text = text.replace(
    old_call,
    new_call,
    1
)


# ============================================================
# 3. Bytes in the loader gap do not need to be zero.
#
# They are currently outside p_filesz and therefore aren't
# loaded at runtime.  We intentionally overwrite only bytes
# before the next file-backed section.
# ============================================================

old_zero_check = '''    if any(old_cave):
        raise RuntimeError(
            "Chosen cave is not all-zero"
        )
'''

new_zero_check = '''    if (
        cave.get(
            "requires_zero",
            True
        )
        and any(old_cave)
    ):
        raise RuntimeError(
            "Chosen cave is not all-zero"
        )
'''


if old_zero_check not in text:
    raise RuntimeError(
        "기존 zero-cave 검증문을 찾지 못했습니다."
    )


text = text.replace(
    old_zero_check,
    new_zero_check,
    1
)


# ============================================================
# 4. Extend PT_LOAD p_filesz after writing the hook.
#
# Program header layout:
#
# +0x00 p_type
# +0x04 p_offset
# +0x08 p_vaddr
# +0x0C p_paddr
# +0x10 p_filesz   <-- update this
# +0x14 p_memsz
# +0x18 p_flags
# +0x1C p_align
# ============================================================

old_write = '''    patched[
        cave_off:
        cave_off + len(blob)
    ] = blob
'''

new_write = '''    patched[
        cave_off:
        cave_off + len(blob)
    ] = blob


    if cave.get(
        "extend_load",
        False
    ):

        phdr_offset = cave[
            "phdr_offset"
        ]

        p_filesz_off = (
            phdr_offset
            + 0x10
        )

        p_memsz_off = (
            phdr_offset
            + 0x14
        )

        actual_old_filesz = u32(
            patched,
            p_filesz_off
        )

        actual_memsz = u32(
            patched,
            p_memsz_off
        )

        if (
            actual_old_filesz
            != cave["old_filesz"]
        ):
            raise RuntimeError(
                "PT_LOAD p_filesz verification failed: "
                f"0x{actual_old_filesz:X} != "
                f"0x{cave['old_filesz']:X}"
            )

        if (
            actual_memsz
            != cave["old_memsz"]
        ):
            raise RuntimeError(
                "PT_LOAD p_memsz verification failed: "
                f"0x{actual_memsz:X} != "
                f"0x{cave['old_memsz']:X}"
            )

        if (
            cave["new_filesz"]
            > actual_memsz
        ):
            raise RuntimeError(
                "New PT_LOAD p_filesz exceeds p_memsz"
            )

        # Only p_filesz changes.
        # p_memsz already includes this BSS memory.
        p32(
            patched,
            p_filesz_off,
            cave["new_filesz"]
        )
'''


if old_write not in text:
    raise RuntimeError(
        "hook write 지점을 찾지 못했습니다."
    )


text = text.replace(
    old_write,
    new_write,
    1
)


# ============================================================
# 5. Add loader-gap details to summary.
# ============================================================

old_summary = '''        f.write(
            f"Hook size: "
            f"{len(blob)}\\n"
        )
'''

new_summary = '''        f.write(
            f"Hook size: "
            f"{len(blob)}\\\\n"
        )

        f.write(
            f"Injection method: "
            f"PT_LOAD file-gap / BSS-backed\\\\n"
        )

        f.write(
            f"PT_LOAD old p_filesz: "
            f"0x{cave['old_filesz']:X}\\\\n"
        )

        f.write(
            f"PT_LOAD new p_filesz: "
            f"0x{cave['new_filesz']:X}\\\\n"
        )

        f.write(
            f"PT_LOAD p_memsz: "
            f"0x{cave['old_memsz']:X}\\\\n"
        )

        f.write(
            f"File gap available: "
            f"0x{cave['file_gap']:X}\\\\n"
        )
'''

# Summary extension is useful but not required for correctness.
# Only modify it when the exact original snippet is found.
if old_summary in text:
    text = text.replace(
        old_summary,
        new_summary,
        1
    )


TARGET.write_text(
    text,
    encoding="utf-8"
)

print(
    "Stage23 loader-gap patch applied:"
)

print(
    TARGET
)
