from pathlib import Path
import re

BASE = Path(r"D:\narutimate portable")

SRC_HOOK = (
    BASE / "analysis" / "stage23"
    / "stage23_hangul_hook.py"
)

SRC_ISO = (
    BASE / "analysis" / "stage23"
    / "stage23_iso_multi_patch.py"
)

OUT = BASE / "analysis" / "stage24"

DST_HOOK = OUT / "stage24_hangul_hook.py"
DST_ISO  = OUT / "stage24_iso_multi_patch.py"


NEW_MAPPING = r'''MAPPING = [
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


def replace_mapping(text):

    # Locate only. Do NOT use regex replacement strings,
    # because \x81 etc. would be interpreted by re.sub().
    m = re.search(
        r"(?ms)^MAPPING\s*=\s*\[.*?^\]\s*\n",
        text
    )

    if m is None:
        raise RuntimeError(
            "Stage23 MAPPING block을 찾지 못했습니다."
        )

    return (
        text[:m.start()]
        + NEW_MAPPING
        + text[m.end():]
    )


def main():

    OUT.mkdir(
        parents=True,
        exist_ok=True
    )

    hook = SRC_HOOK.read_text(
        encoding="utf-8-sig"
    )

    # The Stage23 source on disk must be the version
    # which already passed the loader-gap hook test.
    if "find_loader_gap_cave" not in hook:
        raise RuntimeError(
            "Stage23 source에 loader-gap fix가 없습니다."
        )

    hook = replace_mapping(
        hook
    )

    # Stage23 custom range was 0x7F21.
    # Stage24 custom range starts at 0x222F.
    if "-0x7F21" in hook:

        hook = hook.replace(
            "-0x7F21",
            "-MAPPING[0][1]",
            1
        )

    elif "-MAPPING[0][1]" not in hook:

        raise RuntimeError(
            "hook range-base 식을 찾지 못했습니다."
        )

    # Rename outputs/reports.
    hook = hook.replace(
        "stage23",
        "stage24"
    )

    hook = hook.replace(
        "Stage23",
        "Stage24"
    )

    hook = hook.replace(
        "STAGE23",
        "STAGE24"
    )

    hook = hook.replace(
        "Stage 23",
        "Stage 24"
    )

    hook = hook.replace(
        "F0-F9 custom Hangul hook",
        "Valid-unused-SJIS Hangul hook"
    )

    hook = hook.replace(
        "F0-F9 Hangul hook",
        "Valid-unused-SJIS Hangul hook"
    )

    checks = [
        r'b"\x81\xAD"',
        r'b"\x81\xB6"',
        "0x222F",
        "0x2238",
        '"한"',
        '"마"',
        "find_loader_gap_cave",
        "-MAPPING[0][1]",
    ]

    for check in checks:
        if check not in hook:
            raise RuntimeError(
                f"Stage24 hook sanity check 실패: {check}"
            )

    DST_HOOK.write_text(
        hook,
        encoding="utf-8"
    )


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

    iso = iso.replace(
        "Stage 23",
        "Stage 24"
    )

    DST_ISO.write_text(
        iso,
        encoding="utf-8"
    )


    print("=" * 72)
    print("STAGE24 CLEAN BUILD PASS")
    print("=" * 72)
    print()

    print("Stage23 source:")
    print(SRC_HOOK)

    print()
    print("Stage24 hook:")
    print(DST_HOOK)

    print()
    print("Stage24 ISO patcher:")
    print(DST_ISO)

    print()
    print("Mappings:")

    mappings = [
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

    for sjis, internal, char in mappings:
        print(
            f"  {sjis} -> "
            f"0x{internal} -> {char}"
        )


if __name__ == "__main__":
    main()
