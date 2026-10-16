from pathlib import Path
import csv
import hashlib
import mmap
import os
import struct
import sys
import traceback


BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage22"

OUT.mkdir(parents=True, exist_ok=True)


KR_BOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "BOOT.BIN"
)

KR_EBOOT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "SYSDIR"
    / "EBOOT.BIN"
)


KNOWN_FORWARD = {
    0x2121: 0x3000,
    0x2122: 0x3001,
    0x2123: 0x3002,
    0x2421: 0x3041,
    0x2422: 0x3042,
    0x2521: 0x30A1,
    0x2522: 0x30A2,
    0x334E: 0x78BA,
    0x386C: 0x8A9E,
    0x467C: 0x65E5,
    0x4727: 0x8A8D,
    0x4B5C: 0x672C,
}


SEARCH_NAMES = {
    "cptbl.dat",
    "cp949_table.dat",
    "kr0.pgf",
    "jpn0.pgf",
}


STRING_NEEDLES = [
    b"cptbl.dat",
    b"codepage",
    b"flash0:",
    b"cp949_table.dat",
    b"kr0.pgf",
    b"jpn0.pgf",
    b"sceCcc",
]


def u16(data, off):

    return struct.unpack_from(
        "<H",
        data,
        off
    )[0]


def sha256_file(path):

    h = hashlib.sha256()

    with path.open("rb") as f:

        while True:

            b = f.read(
                1024 * 1024
            )

            if not b:
                break

            h.update(b)

    return h.hexdigest()


def write_tsv(
    path,
    rows,
    fields
):

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


def find_all(data, needle):

    p = 0

    while True:

        p = data.find(
            needle,
            p
        )

        if p < 0:
            break

        yield p

        p += 1


# ============================================================
# Search BOOT/EBOOT for firmware/codepage strings
# ============================================================

def scan_strings(path, label):

    rows = []

    if not path.exists():
        return rows

    data = path.read_bytes()
    lower = data.lower()

    for needle in STRING_NEEDLES:

        lowneedle = needle.lower()

        for pos in find_all(
            lower,
            lowneedle
        ):

            start = max(
                0,
                pos - 64
            )

            end = min(
                len(data),
                pos + 160
            )

            preview = data[
                start:end
            ].decode(
                "latin1",
                errors="replace"
            )

            rows.append({
                "binary":
                    label,

                "needle":
                    needle.decode(
                        "ascii",
                        errors="replace"
                    ),

                "offset":
                    pos,

                "offset_hex":
                    f"0x{pos:X}",

                "preview":
                    preview.replace(
                        "\r",
                        "\\r"
                    ).replace(
                        "\n",
                        "\\n"
                    ),
            })

    return rows


# ============================================================
# Locate PPSSPP / PSP firmware files
# ============================================================

def candidate_roots():

    roots = []

    home = Path.home()

    possible = [
        BASE,

        home / "Documents",
        home / "Documents" / "PPSSPP",
        home / "Documents" / "PPSSPP" / "PSP",

        home / "AppData" / "Roaming",
        home / "AppData" / "Roaming" / "PPSSPP",

        home / "AppData" / "Local",
        home / "AppData" / "Local" / "PPSSPP",

        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH Files\PPSSPP"),
        Path(r"LOCAL_PATH Files (x86)\PPSSPP"),
    ]

    seen = set()

    for p in possible:

        try:
            rp = str(
                p.resolve()
            ).lower()

        except Exception:
            rp = str(p).lower()

        if rp in seen:
            continue

        seen.add(rp)

        if p.exists():
            roots.append(p)

    return roots


def should_skip_dir(path):

    name = path.name.lower()

    return name in {
        "temp",
        "tmp",
        "cache",
        "caches",
        "node_modules",
        ".git",
        "windows",
        "winsxs",
    }


def find_firmware_files():

    found = []
    seen = set()

    roots = candidate_roots()

    print(
        "Search roots:",
        len(roots)
    )

    for root_index, root in enumerate(
        roots,
        1
    ):

        print(
            f"[search root] "
            f"{root_index}/"
            f"{len(roots)} "
            f"{root}"
        )

        try:

            for dirpath, dirnames, filenames in os.walk(
                root
            ):

                current = Path(dirpath)

                dirnames[:] = [
                    d
                    for d in dirnames
                    if not should_skip_dir(
                        current / d
                    )
                ]

                for filename in filenames:

                    if filename.lower() not in SEARCH_NAMES:
                        continue

                    path = current / filename

                    try:
                        key = str(
                            path.resolve()
                        ).lower()

                    except Exception:
                        key = str(path).lower()

                    if key in seen:
                        continue

                    seen.add(key)

                    try:
                        size = path.stat().st_size
                        digest = sha256_file(path)

                    except Exception:
                        continue

                    found.append({
                        "name":
                            filename,

                        "path":
                            str(path),

                        "size":
                            size,

                        "sha256":
                            digest,
                    })

        except Exception:
            pass

    # User can also simply drop files into project root.
    for name in SEARCH_NAMES:

        path = BASE / name

        if not path.exists():
            continue

        key = str(
            path.resolve()
        ).lower()

        if key in seen:
            continue

        seen.add(key)

        found.append({
            "name":
                path.name,

            "path":
                str(path),

            "size":
                path.stat().st_size,

            "sha256":
                sha256_file(path),
        })

    return found


# ============================================================
# Table verification
# ============================================================

def verify_forward(
    data,
    base
):

    if base < 0:
        return False

    max_idx = max(
        KNOWN_FORWARD
    )

    if (
        base
        + max_idx * 2
        + 2
        > len(data)
    ):
        return False

    for jis, uni in (
        KNOWN_FORWARD.items()
    ):

        if (
            u16(
                data,
                base + jis * 2
            )
            != uni
        ):
            return False

    return True


def verify_reverse(
    data,
    base
):

    if base < 0:
        return False

    max_uni = max(
        KNOWN_FORWARD.values()
    )

    if (
        base
        + max_uni * 2
        + 2
        > len(data)
    ):
        return False

    for jis, uni in (
        KNOWN_FORWARD.items()
    ):

        if (
            u16(
                data,
                base + uni * 2
            )
            != jis
        ):
            return False

    return True


def scan_cptbl(path):

    rows = []

    size = path.stat().st_size

    if size < 0x20000:
        return rows

    with path.open("rb") as f:

        mm = mmap.mmap(
            f.fileno(),
            0,
            access=mmap.ACCESS_READ
        )

        # ----------------------------------------------------
        # JIS -> Unicode
        # table[0x2121] == U+3000
        # ----------------------------------------------------

        needle = struct.pack(
            "<H",
            0x3000
        )

        pos = 0

        while True:

            pos = mm.find(
                needle,
                pos
            )

            if pos < 0:
                break

            base = (
                pos
                - 0x2121 * 2
            )

            if verify_forward(
                mm,
                base
            ):

                rows.append({
                    "direction":
                        "JIS_TO_UNICODE",

                    "table_offset":
                        base,

                    "table_offset_hex":
                        f"0x{base:X}",
                })

            pos += 1

        # ----------------------------------------------------
        # Unicode -> JIS
        # table[U+3000] == 0x2121
        # ----------------------------------------------------

        needle = struct.pack(
            "<H",
            0x2121
        )

        pos = 0

        while True:

            pos = mm.find(
                needle,
                pos
            )

            if pos < 0:
                break

            base = (
                pos
                - 0x3000 * 2
            )

            if verify_reverse(
                mm,
                base
            ):

                rows.append({
                    "direction":
                        "UNICODE_TO_JIS",

                    "table_offset":
                        base,

                    "table_offset_hex":
                        f"0x{base:X}",
                })

            pos += 1

        mm.close()

    # dedupe
    unique = []
    seen = set()

    for r in rows:

        key = (
            r["direction"],
            r["table_offset"]
        )

        if key in seen:
            continue

        seen.add(key)

        unique.append(r)

    return unique


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 72)
    print("Naruto PSP Stage 22")
    print("PPSSPP / PSP cptbl.dat probe")
    print("=" * 72)

    string_rows = []

    string_rows += scan_strings(
        KR_BOOT,
        "KR_BOOT"
    )

    string_rows += scan_strings(
        KR_EBOOT,
        "KR_EBOOT"
    )

    write_tsv(
        OUT
        / "boot_codepage_strings.tsv",
        string_rows,
        [
            "binary",
            "needle",
            "offset",
            "offset_hex",
            "preview",
        ]
    )

    print(
        "BOOT/EBOOT codepage string hits:",
        len(string_rows)
    )

    firmware = find_firmware_files()

    write_tsv(
        OUT
        / "local_firmware_files.tsv",
        firmware,
        [
            "name",
            "path",
            "size",
            "sha256",
        ]
    )

    print()
    print(
        "Firmware/codepage files found:",
        len(firmware)
    )

    for row in firmware:

        print(
            " ",
            row["name"],
            row["size"],
            row["path"]
        )

    table_rows = []

    for row in firmware:

        if (
            row["name"].lower()
            != "cptbl.dat"
        ):
            continue

        path = Path(
            row["path"]
        )

        try:

            matches = scan_cptbl(
                path
            )

        except Exception as ex:

            table_rows.append({
                "file":
                    str(path),

                "direction":
                    "ERROR",

                "table_offset":
                    "",

                "table_offset_hex":
                    "",

                "error":
                    str(ex),
            })

            continue

        for m in matches:

            table_rows.append({
                "file":
                    str(path),

                "file_size":
                    path.stat().st_size,

                **m,
            })

    write_tsv(
        OUT
        / "cptbl_table_candidates.tsv",
        table_rows,
        [
            "file",
            "file_size",
            "direction",
            "table_offset",
            "table_offset_hex",
            "error",
        ]
    )

    forward = [
        x
        for x in table_rows
        if x.get(
            "direction"
        ) == "JIS_TO_UNICODE"
    ]

    reverse = [
        x
        for x in table_rows
        if x.get(
            "direction"
        ) == "UNICODE_TO_JIS"
    ]

    status = (
        "CPTBL_TABLES_FOUND"
        if forward and reverse
        else (
            "CPTBL_FOUND_NO_RAW_TABLE"
            if any(
                x["name"].lower()
                == "cptbl.dat"
                for x in firmware
            )
            else
            "CPTBL_NOT_FOUND"
        )
    )

    (
        OUT
        / "stage22_status.txt"
    ).write_text(
        status + "\n",
        encoding="ascii"
    )

    summary = (
        OUT
        / "stage22_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 22\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"Status: {status}\n\n"
        )

        f.write(
            f"BOOT/EBOOT codepage string hits: "
            f"{len(string_rows)}\n"
        )

        f.write(
            f"Local firmware files found: "
            f"{len(firmware)}\n"
        )

        f.write(
            f"JIS->Unicode table candidates: "
            f"{len(forward)}\n"
        )

        f.write(
            f"Unicode->JIS table candidates: "
            f"{len(reverse)}\n\n"
        )

        for row in firmware:

            f.write(
                f"{row['name']} "
                f"{row['size']} "
                f"{row['path']}\n"
            )

        if table_rows:

            f.write(
                "\nTable candidateLOCAL_PATH"
            )

            for row in table_rows:

                f.write(
                    f"  "
                    f"{row.get('direction','')} "
                    f"{row.get('file','')} "
                    f"{row.get('table_offset_hex','')}\n"
                )

    print()
    print("=" * 72)
    print("STAGE 22 COMPLETE")
    print("=" * 72)

    print(
        "STATUS:",
        status
    )

    print(
        "Forward tables:",
        len(forward)
    )

    print(
        "Reverse tables:",
        len(reverse)
    )

    print(
        "Output:",
        OUT
    )

    if status == "CPTBL_NOT_FOUND":

        print()
        print(
            "cptbl.dat을 자동으로 찾지 못했습니다."
        )

        print(
            "PPSSPP/PSP의 cptbl.dat을 "
            "PROJECT_ROOT\\cptbl.dat "
            "위치에 복사한 뒤 Stage22를 다시 실행하면 됩니다."
        )


if __name__ == "__main__":

    try:

        main()

    except Exception:

        traceback.print_exc()
        sys.exit(1)
