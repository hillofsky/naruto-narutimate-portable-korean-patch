from pathlib import Path
import importlib.util
import struct
import csv
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage18"

S17 = (
    BASE
    / "analysis"
    / "stage17"
    / "stage17_font_engine.py"
)

KR_BOOT = (
    BASE
    / "kr_extracted"
    / "PSP_GAME"
    / "SYSDIR"
    / "BOOT.BIN"
)


def load_stage17():

    spec = importlib.util.spec_from_file_location(
        "stage17",
        S17
    )

    mod = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        mod
    )

    return mod


def u32(data, off):

    return struct.unpack_from(
        "<I",
        data,
        off
    )[0]


def function_dump(
    s17,
    elf,
    start_va,
    max_bytes,
    name
):

    off = elf.va_to_offset(
        start_va
    )

    if off is None:
        raise RuntimeError(
            f"VA 변환 실패: "
            f"0x{start_va:X}"
        )

    lines = []

    lines.append(
        "=" * 78
    )

    lines.append(
        f"{name} "
        f"start=0x{start_va:08X} "
        f"file=0x{off:X}"
    )

    lines.append(
        "=" * 78
    )

    p = off
    end = min(
        len(elf.data),
        off + max_bytes
    )

    return_seen = 0

    while p + 4 <= end:

        pc = (
            start_va
            + p - off
        )

        ins = u32(
            elf.data,
            p
        )

        text = s17.decode_mips(
            ins,
            pc
        )

        lines.append(
            f"0x{pc:08X}: "
            f"{ins:08X}  "
            f"{text}"
        )

        # jr ra
        if ins == 0x03E00008:
            return_seen += 1

            # Include delay slot and stop at first
            # clear function return.
            if p + 8 <= end:
                p += 4

                ins2 = u32(
                    elf.data,
                    p
                )

                pc2 = (
                    start_va
                    + p - off
                )

                lines.append(
                    f"0x{pc2:08X}: "
                    f"{ins2:08X}  "
                    f"{s17.decode_mips(ins2, pc2)}"
                )

            break

        p += 4

    return "\n".join(
        lines
    )


def find_direct_calls(
    elf,
    target_va
):

    rows = []

    for sec in elf.sections:

        if not (
            sec["flags"] & 0x4
        ):
            continue

        start = sec["offset"]
        end = (
            sec["offset"]
            + sec["size"]
        )

        p = start

        while p + 4 <= end:

            ins = u32(
                elf.data,
                p
            )

            if (
                (ins >> 26)
                & 0x3F
            ) == 3:

                pc = (
                    sec["addr"]
                    + p
                    - sec["offset"]
                )

                target = (
                    ((pc + 4)
                     & 0xF0000000)
                    |
                    (
                        (ins
                         & 0x03FFFFFF)
                        << 2
                    )
                )

                if target == target_va:

                    rows.append({
                        "target":
                            f"0x{target_va:08X}",

                        "section":
                            sec["name"],

                        "call_va":
                            f"0x{pc:08X}",

                        "file_offset":
                            f"0x{p:X}",
                    })

            p += 4

    return rows


def main():

    print("=" * 72)
    print("Stage18 font selector / converter trace")
    print("=" * 72)

    if not S17.exists():
        raise RuntimeError(
            f"Stage17 script 없음: "
            f"{S17}"
        )

    s17 = load_stage17()

    elf = s17.ELF32(
        KR_BOOT
    )

    # From Stage17:
    #
    # 0x002AC72C:
    #   helper called immediately before choosing
    #   font handle +4 or +8.
    #
    # 0x002ACCF4:
    #   converts source text into the 16-bit
    #   character buffer consumed by the renderer.
    #
    targets = [
        (
            "KR_FONT_SELECTOR",
            0x002AC72C,
            0x300
        ),
        (
            "KR_TEXT_TO_16BIT",
            0x002ACCF4,
            0x800
        ),
        (
            "KR_FONT_RENDERER",
            0x002AC2A4,
            0x400
        ),
        (
            "KR_FONT_INIT",
            0x002AC584,
            0x180
        ),
    ]

    dumps = []

    all_calls = []

    for (
        name,
        va,
        size
    ) in targets:

        print(
            f"[dump] {name} "
            f"0x{va:08X}"
        )

        dumps.append(
            function_dump(
                s17,
                elf,
                va,
                size,
                name
            )
        )

        all_calls.extend(
            {
                **r,
                "target_name":
                    name,
            }
            for r in
            find_direct_calls(
                elf,
                va
            )
        )

    imports = (
        s17.parse_imports(
            elf
        )
    )

    ccc = [
        r
        for r in imports
        if (
            "ccc"
            in r[
                "library"
            ].lower()
            or
            "char"
            in r[
                "library"
            ].lower()
            or
            "code"
            in r[
                "library"
            ].lower()
        )
    ]

    dump_path = (
        OUT
        / "kr_font_functions.txt"
    )

    dump_path.write_text(
        "\n\n".join(dumps),
        encoding="utf-8"
    )

    with (
        OUT
        / "font_helper_calls.tsv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        fields = [
            "target_name",
            "target",
            "section",
            "call_va",
            "file_offset",
        ]

        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields
        )

        w.writeheader()

        for r in all_calls:
            w.writerow(r)

    with (
        OUT
        / "character_conversion_imports.tsv"
    ).open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        fields = [
            "library",
            "stub_index",
            "nid_hex",
            "stub_va_hex",
        ]

        w = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=fields
        )

        w.writeheader()

        for r in ccc:
            w.writerow({
                k: r.get(k, "")
                for k in fields
            })

    summary = (
        OUT
        / "stage18_static_summary.txt"
    )

    summary.write_text(
        "\n".join([
            "Naruto PSP Stage18 static analysis",
            "=" * 72,
            "",
            "Functions dumped:",
            "  0x002AC72C KR font selector",
            "  0x002ACCF4 KR source-text to 16-bit converter",
            "  0x002AC2A4 KR glyph renderer",
            "  0x002AC584 KR font init",
            "",
            f"Converter/CCC-like imports: {len(ccc)}",
            f"Direct helper callsites: {len(all_calls)}",
        ]),
        encoding="utf-8"
    )

    print(
        "CCC-like imports:",
        len(ccc)
    )

    print(
        "Output:",
        dump_path
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
