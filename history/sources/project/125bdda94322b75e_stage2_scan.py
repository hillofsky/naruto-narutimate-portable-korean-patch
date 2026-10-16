from pathlib import Path
import mmap
import hashlib
import struct
import re
import csv
import sys
import os

BASE = Path(r"PROJECT_ROOT")

KR = BASE / "kr_extracted"
US = BASE / "us_extracted"
OUT = BASE / "analysis" / "stage2"

OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "KR_IDX": KR / "PSP_GAME" / "USRDIR" / "naruto.idx",
    "KR_DAT": KR / "PSP_GAME" / "USRDIR" / "naruto.dat",
    "US_DAT": US / "PSP_GAME" / "USRDIR" / "naruto.dat",
    "KR_EBOOT": KR / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN",
    "US_EBOOT": US / "PSP_GAME" / "SYSDIR" / "EBOOT.BIN",
}

MAGICS = {
    "PIDX0": b"PIDX0",
    "#CCS#": b"#CCS#",
    "CCS": b"CCS",
    "GIM_MIG": b"MIG.00.1PSP",
    "PNG": b"\x89PNG\r\n\x1a\n",
    "PSMF": b"PSMF",
    "RIFF": b"RIFF",
    "OggS": b"OggS",
    "VAGp": b"VAGp",
    "TIM2": b"TIM2",
    "ELF": b"\x7fELF",
}


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def hex_dump(data, base=0, width=16):
    lines = []

    for i in range(0, len(data), width):
        chunk = data[i:i+width]

        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(
            chr(b) if 32 <= b <= 126 else "."
            for b in chunk
        )

        lines.append(
            f"{base+i:08X}  {hx:<47}  {asc}"
        )

    return "\n".join(lines)


def dump_head_tail(name, path):
    size = path.stat().st_size

    with path.open("rb") as f:
        head = f.read(min(4096, size))

        if size > 4096:
            f.seek(max(0, size - 4096))
            tail_offset = f.tell()
            tail = f.read(4096)
        else:
            tail_offset = 0
            tail = head

    out = OUT / f"{name.lower()}_head_tail.txt"

    with out.open("w", encoding="utf-8") as w:
        w.write(f"FILE: {path}\n")
        w.write(f"SIZE: {size}\n\n")

        w.write("===== HEAD =====\n")
        w.write(hex_dump(head, 0))
        w.write("\n\n")

        w.write("===== TAIL =====\n")
        w.write(hex_dump(tail, tail_offset))
        w.write("\n")


def find_all(mm, needle, limit=10000):
    result = []
    pos = 0

    while len(result) < limit:
        pos = mm.find(needle, pos)

        if pos < 0:
            break

        result.append(pos)
        pos += 1

    return result


def scan_magics(name, path):
    rows = []

    with path.open("rb") as f:
        with mmap.mmap(
            f.fileno(),
            0,
            access=mmap.ACCESS_READ
        ) as mm:

            for magic_name, magic in MAGICS.items():
                offsets = find_all(mm, magic)

                rows.append({
                    "file": name,
                    "magic": magic_name,
                    "count": len(offsets),
                    "first_offsets": ",".join(
                        f"0x{x:X}" for x in offsets[:50]
                    )
                })

    return rows


def extract_ascii(path, limit=30000, minimum=5):
    results = []

    pat = re.compile(
        rb"[\x20-\x7E]{" + str(minimum).encode() + rb",}"
    )

    with path.open("rb") as f:
        with mmap.mmap(
            f.fileno(),
            0,
            access=mmap.ACCESS_READ
        ) as mm:

            for m in pat.finditer(mm):
                raw = m.group()

                try:
                    text = raw.decode("ascii")
                except:
                    continue

                # 단순 바이너리 잡음 제거
                alpha = sum(c.isalpha() for c in text)

                if alpha < 2:
                    continue

                results.append(
                    (m.start(), text[:500])
                )

                if len(results) >= limit:
                    break

    return results


def valid_sjis_pair(a, b):
    lead = (
        0x81 <= a <= 0x9F
        or
        0xE0 <= a <= 0xFC
    )

    trail = (
        0x40 <= b <= 0x7E
        or
        0x80 <= b <= 0xFC
    )

    return lead and trail and b != 0x7F


def has_japanese(text):
    for c in text:
        o = ord(c)

        if (
            0x3040 <= o <= 0x30FF
            or
            0x3400 <= o <= 0x4DBF
            or
            0x4E00 <= o <= 0x9FFF
            or
            0xFF61 <= o <= 0xFF9F
        ):
            return True

    return False


def extract_sjis(path, limit=30000):
    results = []

    data = path.read_bytes()
    n = len(data)

    i = 0

    while i < n - 1 and len(results) < limit:
        start = i
        buf = bytearray()
        jp_pairs = 0

        while i < n:
            b = data[i]

            # ASCII 가시문자
            if 0x20 <= b <= 0x7E:
                buf.append(b)
                i += 1
                continue

            # Shift-JIS 2바이트 문자
            if (
                i + 1 < n
                and valid_sjis_pair(data[i], data[i+1])
            ):
                buf.extend(data[i:i+2])
                jp_pairs += 1
                i += 2
                continue

            # 반각 가나
            if 0xA1 <= b <= 0xDF:
                buf.append(b)
                jp_pairs += 1
                i += 1
                continue

            break

        if jp_pairs >= 1 and len(buf) >= 4:
            try:
                text = bytes(buf).decode(
                    "cp932",
                    errors="strict"
                )

                if has_japanese(text):
                    results.append(
                        (start, text[:500])
                    )

            except:
                pass

        if i <= start:
            i = start + 1
        else:
            i += 1

    return results


def save_strings(filename, rows, encoding_name):
    p = OUT / filename

    with p.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        w = csv.writer(f, delimiter="\t")

        w.writerow([
            "offset_hex",
            "offset_dec",
            "encoding",
            "text"
        ])

        for offset, text in rows:
            w.writerow([
                f"0x{offset:X}",
                offset,
                encoding_name,
                text
            ])


def idx_report(path):
    data = path.read_bytes()

    out = OUT / "kr_idx_report.txt"

    with out.open("w", encoding="utf-8") as w:
        w.write(f"SIZE: {len(data)}\n")
        w.write(
            f"SHA256: {hashlib.sha256(data).hexdigest()}\n\n"
        )

        nul = data.count(0)
        printable = sum(
            1 for b in data
            if 32 <= b <= 126
        )

        w.write(
            f"NUL count: {nul} "
            f"({nul / max(1,len(data)):.4%})\n"
        )

        w.write(
            f"ASCII printable: {printable} "
            f"({printable / max(1,len(data)):.4%})\n\n"
        )

        w.write(
            "===== FIRST 128 UINT32 LE =====\n"
        )

        count = min(len(data) // 4, 128)

        for i in range(count):
            v = struct.unpack_from(
                "<I",
                data,
                i * 4
            )[0]

            w.write(
                f"{i:04d} "
                f"@0x{i*4:08X} : "
                f"{v:10d} "
                f"0x{v:08X}\n"
            )

        w.write(
            "\n===== FIRST 128 UINT32 BE =====\n"
        )

        for i in range(count):
            v = struct.unpack_from(
                ">I",
                data,
                i * 4
            )[0]

            w.write(
                f"{i:04d} "
                f"@0x{i*4:08X} : "
                f"{v:10d} "
                f"0x{v:08X}\n"
            )

        w.write(
            "\n===== POSSIBLE TEXT DECODING =====\n"
        )

        for enc in (
            "utf-8",
            "cp932",
            "shift_jis",
            "latin1"
        ):
            try:
                s = data.decode(enc)
                sample = s[:3000]

                w.write(f"\n[{enc}]\n")
                w.write(sample)
                w.write("\n")

            except Exception as e:
                w.write(
                    f"\n[{enc}] decode failed: {e}\n"
                )


print("==========================================")
print("Stage 2 Python analyzer")
print("==========================================")

summary_lines = []

for name, path in FILES.items():

    if not path.exists():
        print(f"[MISS] {name}: {path}")
        continue

    size = path.stat().st_size
    sha = sha256_file(path)

    print(f"[{name}]")
    print(f"  Path   : {path}")
    print(f"  Size   : {size}")
    print(f"  SHA256 : {sha}")

    summary_lines.append(
        f"{name}\t{size}\t{sha}\t{path}"
    )

    dump_head_tail(name, path)


with (OUT / "file_summary.tsv").open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "name\tsize\tsha256\tpath\n"
    )

    for line in summary_lines:
        f.write(line + "\n")


print()
print("[1] KR naruto.idx 분석")

idx = FILES["KR_IDX"]

if idx.exists():

    idx_report(idx)

    ascii_rows = extract_ascii(
        idx,
        limit=10000,
        minimum=4
    )

    sjis_rows = extract_sjis(
        idx,
        limit=10000
    )

    save_strings(
        "kr_idx_ascii.tsv",
        ascii_rows,
        "ASCII"
    )

    save_strings(
        "kr_idx_sjis.tsv",
        sjis_rows,
        "CP932"
    )

    print(
        f"  ASCII strings: {len(ascii_rows)}"
    )

    print(
        f"  SJIS strings : {len(sjis_rows)}"
    )


print()
print("[2] Magic signature scan")

magic_rows = []

for name in (
    "KR_IDX",
    "KR_DAT",
    "US_DAT",
    "KR_EBOOT",
    "US_EBOOT"
):

    path = FILES[name]

    if not path.exists():
        continue

    rows = scan_magics(name, path)
    magic_rows.extend(rows)

    print(f"\n{name}")

    for r in rows:
        if r["count"]:
            print(
                f'  {r["magic"]}: '
                f'{r["count"]} '
                f'{r["first_offsets"]}'
            )


with (OUT / "magic_offsets.tsv").open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=[
            "file",
            "magic",
            "count",
            "first_offsets"
        ]
    )

    w.writeheader()
    w.writerows(magic_rows)


print()
print("[3] EBOOT 문자열 추출")

for name in (
    "KR_EBOOT",
    "US_EBOOT"
):

    path = FILES[name]

    if not path.exists():
        continue

    ascii_rows = extract_ascii(
        path,
        limit=30000,
        minimum=5
    )

    save_strings(
        name.lower() + "_ascii.tsv",
        ascii_rows,
        "ASCII"
    )

    print(
        f"  {name} ASCII: "
        f"{len(ascii_rows)}"
    )


print()
print("[4] DAT 문자열 샘플 추출")

# US DAT : 영어 문자열
us_dat = FILES["US_DAT"]

if us_dat.exists():

    rows = extract_ascii(
        us_dat,
        limit=30000,
        minimum=5
    )

    save_strings(
        "us_dat_ascii.tsv",
        rows,
        "ASCII"
    )

    print(
        f"  US_DAT ASCII: {len(rows)}"
    )


# KR DAT : 일본어 Shift-JIS 문자열
kr_dat = FILES["KR_DAT"]

if kr_dat.exists():

    rows = extract_sjis(
        kr_dat,
        limit=30000
    )

    save_strings(
        "kr_dat_sjis.tsv",
        rows,
        "CP932"
    )

    print(
        f"  KR_DAT SJIS: {len(rows)}"
    )


print()
print("==========================================")
print("Stage 2 complete")
print("==========================================")
print(f"Output: {OUT}")

