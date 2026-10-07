from pathlib import Path
import re
import sys


BASE = Path(r"D:\narutimate portable")

SRC_HOOK = (
    BASE / "analysis" / "stage23"
    / "stage23_hangul_hook.py"
)

SRC_ISO = (
    BASE / "analysis" / "stage23"
    / "stage23_iso_multi_patch.py"
)

OUT = (
    BASE / "analysis" / "stage24"
)

DST_HOOK = (
    OUT / "stage24_hangul_hook.py"
)

DST_ISO = (
    OUT / "stage24_iso_multi_patch.py"
)


def main():

    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    if not SRC_HOOK.exists():
        raise RuntimeError(
            f"Stage23 hook source 없음: {SRC_HOOK}"
        )

    if not SRC_ISO.exists():
        raise RuntimeError(
            f"Stage23 ISO source 없음: {SRC_ISO}"
        )

    text = SRC_HOOK.read_text(
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # Stage23 -> Stage24 output names
    # --------------------------------------------------------

    text = text.replace(
        'stage23',
        'stage24'
    )

    text = text.replace(
        'Stage 23',
        'Stage 24'
    )

    text = text.replace(
        'Stage23',
        'Stage24'
    )

    text = text.replace(
        'STAGE23',
        'STAGE24'
    )

    # --------------------------------------------------------
    # Replace the invalid F0-F9 mapping.
    #
    # These codes:
    #   - are accepted by the game's SJIS parser
    #   - are unassigned in Sony CP932 cptbl
    #   - map to contiguous internal codes 0x222F..0x2238
    # --------------------------------------------------------

    new_mapping = r'''MAPPING = [
    (b"\x81\xAD", 0x222F, "한", 0xD55C),
    (b"\x81\xAE", 0x2230, "글", 0xAE00),
    (b"\x81\xAF", 0x2231, "테", 0xD14C),
    (b"\x81\xB0", 0x2232, "스", 0xC2A4),
    (b"\x81\xB1", 0x2233, "트", 0xD2B8),

    (b"\x81\xB2", 0x2234, "가", 0xAC00),
    (b"\x81\xB3", 0x2235, "나", 0xB098),
    (b"\x81\xB4", 0x2236, "다", 0xB2E4),
    (b"\x81\xB5", 0x2237, "라", 0xB77C),
    (b"\x81\xB6", 0x2238, "마", 0xB9C8),
]

'''

    pattern = re.compile(
        r'MAPPING\s*=\s*\[\s*.*?\n\]\s*\n',
        re.S
    )

    text, count = pattern.subn(
        new_mapping,
        text,
        count=1
    )

    if count != 1:
        raise RuntimeError(
            f"MAPPING 교체 실패: count={count}"
        )

    # --------------------------------------------------------
    # Stage23 hook checked:
    #
    #     v0 - 0x7F21
    #
    # New valid range starts at 0x222F.
    #
    # Make it automatically follow MAPPING[0].
    # --------------------------------------------------------

    if "-0x7F21" not in text:
        raise RuntimeError(
            "Stage23 hook의 -0x7F21 기준값을 찾지 못했습니다."
        )

    text = text.replace(
        "-0x7F21",
        "-MAPPING[0][1]",
        1
    )

    # Cosmetic labels only.
    text = text.replace(
        "F0-F9 custom Hangul hook",
        "valid-unused-SJIS Hangul hook"
    )

    text = text.replace(
        "F0-F9 Hangul hook",
        "valid unused SJIS Hangul hook"
    )

    DST_HOOK.write_text(
        text,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # ISO patcher copy
    # --------------------------------------------------------

    iso = SRC_ISO.read_text(
        encoding="utf-8-sig"
    )

    iso = iso.replace(
        "stage23",
        "stage24"
    )

    iso = iso.replace(
        "Stage23",
        "Stage24"
    )

    iso = iso.replace(
        "STAGE23",
        "STAGE24"
    )

    DST_ISO.write_text(
        iso,
        encoding="utf-8"
    )

    print("=" * 72)
    print("Stage24 source generation complete")
    print("=" * 72)

    print()
    print("Custom valid unused SJIS mapping:")

    pairs = [
        ("81 AD", "222F", "한"),
        ("81 AE", "2230", "글"),
        ("81 AF", "2231", "테"),
        ("81 B0", "2232", "스"),
        ("81 B1", "2233", "트"),
        ("81 B2", "2234", "가"),
        ("81 B3", "2235", "나"),
        ("81 B4", "2236", "다"),
        ("81 B5", "2237", "라"),
        ("81 B6", "2238", "마"),
    ]

    for sjis, internal, ch in pairs:
        print(
            f"  {sjis} -> "
            f"0x{internal} -> {ch}"
        )

    print()
    print(
        "Hook:",
        DST_HOOK
    )

    print(
        "ISO patcher:",
        DST_ISO
    )


if __name__ == "__main__":
    main()
