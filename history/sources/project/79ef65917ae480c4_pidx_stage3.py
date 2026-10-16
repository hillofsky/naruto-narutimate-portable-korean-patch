from pathlib import Path
import struct
import csv
import hashlib
import re
import zlib
import traceback

BASE = Path(r"PROJECT_ROOT")

KR_ROOT = BASE / "kr_extracted" / "PSP_GAME" / "USRDIR"
US_ROOT = BASE / "us_extracted" / "PSP_GAME" / "USRDIR"

KR_IDX = KR_ROOT / "naruto.idx"
KR_DAT = KR_ROOT / "naruto.dat"

US_DAT = US_ROOT / "naruto.dat"

OUT = BASE / "analysis" / "stage3"

EXTRACT = OUT / "extracted"
SHARE = OUT / "share"

for p in [
    OUT,
    EXTRACT / "kr",
    EXTRACT / "us",
    SHARE,
]:
    p.mkdir(parents=True, exist_ok=True)


def file_sha256(path):

    h = hashlib.sha256()

    with path.open("rb") as f:

        while True:

            b = f.read(1024 * 1024)

            if not b:
                break

            h.update(b)

    return h.hexdigest()


def bytes_sha256(data):
    return hashlib.sha256(data).hexdigest()


def cstring(data, offset):

    if offset < 0 or offset >= len(data):
        return f"<BAD_OFFSET_0x{offset:X}>"

    end = data.find(b"\x00", offset)

    if end < 0:
        end = len(data)

    raw = data[offset:end]

    try:
        return raw.decode("ascii")

    except Exception:
        return raw.decode(
            "latin1",
            errors="replace"
        )


def parse_pidx(index_file, data_file, region):

    with index_file.open("rb") as f:

        hdr = f.read(0x50)

        if len(hdr) < 0x30:
            raise RuntimeError(
                f"{region}: PIDX header too short"
            )

        if hdr[:5] != b"PIDX0":
            raise RuntimeError(
                f"{region}: PIDX0 signature 없음"
            )

        (
            packs_off,
            packs,
            info_off,
            files,
            dummy,
            offset2,
            offset2_size,
            names_off,
            names_size,
        ) = struct.unpack_from(
            "<9I",
            hdr,
            4
        )

        expected_offset2 = (
            info_off + files * 24
        )

        if names_off + names_size > index_file.stat().st_size:

            raise RuntimeError(
                f"{region}: names table outside index "
                f"(0x{names_off:X}+0x{names_size:X})"
            )

        f.seek(names_off)

        names = f.read(names_size)

        f.seek(info_off)

        entries = []

        for i in range(files):

            raw = f.read(24)

            if len(raw) != 24:

                raise RuntimeError(
                    f"{region}: entry {i} 잘림"
                )

            (
                is_folder,
                name_off,
                pack_name_off,
                offset,
                size,
                zsize,
            ) = struct.unpack(
                "<6I",
                raw
            )

            name = cstring(
                names,
                name_off
            )

            pack_name = cstring(
                names,
                pack_name_off
            )

            entries.append({
                "region": region,
                "entry": i,

                "is_folder": is_folder,

                "name_off": name_off,
                "name": name,

                "pack_name_off": pack_name_off,
                "pack_name": pack_name,

                "offset": offset,
                "size": size,
                "zsize": zsize,
            })

    info = {
        "region": region,

        "index_file": str(index_file),
        "data_file": str(data_file),

        "packs_off": packs_off,
        "packs": packs,

        "info_off": info_off,
        "files": files,

        "dummy": dummy,

        "offset2": offset2,
        "offset2_size": offset2_size,

        "names_off": names_off,
        "names_size": names_size,

        "expected_offset2": expected_offset2,

        "table_valid":
            expected_offset2 == offset2,
    }

    return info, entries


def write_manifest(path, entries):

    fields = [
        "region",
        "entry",
        "is_folder",

        "name_off",
        "name",

        "pack_name_off",
        "pack_name",

        "offset",
        "offset_hex",

        "size",
        "zsize",
    ]

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

        for e in entries:

            row = dict(e)

            row["offset_hex"] = (
                f'0x{e["offset"]:X}'
            )

            w.writerow(row)


def segs_unpack(blob):

    if len(blob) < 16:
        raise RuntimeError(
            "SEGS header too short"
        )

    if blob[:4] != b"segs":
        raise RuntimeError(
            "not SEGS"
        )

    flags, chunks = struct.unpack_from(
        ">HH",
        blob,
        4
    )

    full_size, full_zsize = (
        struct.unpack_from(
            ">II",
            blob,
            8
        )
    )

    table_off = 16

    base2 = (
        16 + chunks * 8
    )

    desc = []

    for i in range(chunks):

        pos = (
            table_off + i * 8
        )

        if pos + 8 > len(blob):

            raise RuntimeError(
                "SEGS table outside input"
            )

        zsize, size, off = (
            struct.unpack_from(
                ">HHI",
                blob,
                pos
            )
        )

        off -= 1

        desc.append(
            (zsize, size, off)
        )

    workaround = (
        bool(desc)
        and desc[0][2] == 0
    )

    result = bytearray()

    for zsize, size, off in desc:

        if size == 0:
            size = 0x10000

        if workaround:
            real_off = base2 + off
        else:
            real_off = off

        if real_off < 0:

            raise RuntimeError(
                "SEGS negative offset"
            )

        chunk = blob[
            real_off:
            real_off + zsize
        ]

        if len(chunk) != zsize:

            raise RuntimeError(
                "SEGS chunk outside input"
            )

        if size == zsize:

            out = chunk

        else:

            out = zlib.decompress(
                chunk,
                -15
            )

        result.extend(out)

    if (
        full_size
        and len(result) != full_size
    ):

        raise RuntimeError(
            "SEGS size mismatch: "
            f"{len(result)} != "
            f"{full_size}"
        )

    return bytes(result)


def extract_entry(data_file, e):

    offset = e["offset"]
    size = e["size"]
    zsize = e["zsize"]

    data_size = (
        data_file.stat().st_size
    )

    if zsize == 0:

        read_size = size
        mode = "raw"

    elif zsize >= size:

        read_size = size
        mode = "raw"

    else:

        read_size = zsize
        mode = "compressed"

    if read_size < 0:

        raise RuntimeError(
            "negative read size"
        )

    if (
        offset < 0
        or offset + read_size > data_size
    ):

        raise RuntimeError(
            f"outside DAT: "
            f"offset=0x{offset:X}, "
            f"read=0x{read_size:X}, "
            f"dat=0x{data_size:X}"
        )

    with data_file.open("rb") as f:

        f.seek(offset)

        blob = f.read(read_size)

    if mode == "raw":

        return blob, "raw"

    sign = blob[:4]

    if sign == b"segs":

        try:

            return (
                segs_unpack(blob),
                "segs"
            )

        except Exception as ex:

            return (
                blob,
                "segs_failed:"
                + str(ex)
            )

    if sign in (
        b" 3;0",
        b" 3;1"
    ):

        return (
            blob,
            "unknown_3x_raw"
        )

    try:

        out = zlib.decompress(blob)

        if size and len(out) != size:

            return (
                out,
                "zlib_size_mismatch"
            )

        return out, "zlib"

    except Exception:

        pass

    try:

        out = zlib.decompress(
            blob,
            -15
        )

        if size and len(out) != size:

            return (
                out,
                "deflate_size_mismatch"
            )

        return out, "deflate"

    except Exception:

        return (
            blob,
            "compressed_raw_unknown"
        )


def safe_filename(name):

    name = name.replace(
        "\\",
        "__"
    )

    name = name.replace(
        "/",
        "__"
    )

    name = name.replace(
        ":",
        "_"
    )

    if not name:
        return "_unnamed"

    return name


translation_re = re.compile(
    r"("
    r"text|event|quiz|title|select|menu|"
    r"message|msg|dialog|talk|story|"
    r"scenario|skill|name|guide|help|"
    r"char|mode"
    r")",
    re.I
)


def is_candidate(name):

    low = name.lower()

    if low.endswith(".tbl"):
        return True

    if (
        low.startswith("text")
        and low.endswith(".bin")
    ):
        return True

    if translation_re.search(name):

        if low.endswith(
            (
                ".bin",
                ".tbl",
                ".ccs",
                ".dat",
            )
        ):
            return True

    return False


def ascii_strings(data, limit=300):

    rx = re.compile(
        rb"[\x20-\x7e]{5,}"
    )

    result = []

    for m in rx.finditer(data):

        s = m.group().decode(
            "ascii",
            errors="ignore"
        )

        alpha = sum(
            c.isalpha()
            for c in s
        )

        if alpha < 3:
            continue

        result.append(
            (
                m.start(),
                s[:300]
            )
        )

        if len(result) >= limit:
            break

    return result


def has_japanese(s):

    for c in s:

        n = ord(c)

        if (
            0x3040 <= n <= 0x30FF
            or
            0x3400 <= n <= 0x4DBF
            or
            0x4E00 <= n <= 0x9FFF
            or
            0xFF61 <= n <= 0xFF9F
        ):
            return True

    return False


def sjis_strings(data, limit=300):

    result = []

    n = len(data)
    i = 0

    while (
        i < n - 1
        and len(result) < limit
    ):

        start = i

        buf = bytearray()
        pairs = 0

        while i < n:

            a = data[i]

            if 0x20 <= a <= 0x7E:

                buf.append(a)
                i += 1
                continue

            if 0xA1 <= a <= 0xDF:

                buf.append(a)
                i += 1

                pairs += 1
                continue

            if (
                i + 1 < n
                and (
                    0x81 <= a <= 0x9F
                    or
                    0xE0 <= a <= 0xFC
                )
            ):

                b = data[i + 1]

                if (
                    0x40 <= b <= 0xFC
                    and b != 0x7F
                ):

                    buf.extend(
                        data[i:i+2]
                    )

                    i += 2
                    pairs += 1

                    continue

            break

        if (
            pairs >= 1
            and len(buf) >= 4
        ):

            try:

                s = bytes(buf).decode(
                    "cp932"
                )

                if has_japanese(s):

                    result.append(
                        (
                            start,
                            s[:300]
                        )
                    )

            except Exception:
                pass

        if i <= start:
            i = start + 1
        else:
            i += 1

    return result


def sanitize_sample(s):

    return (
        s
        .replace("\t", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )


print("=" * 72)
print("Naruto PSP Stage 3")
print("PIDX parser / extractor")
print("=" * 72)

print()
print("[0] Input hashes")

for label, path in [
    ("KR_IDX", KR_IDX),
    ("KR_DAT", KR_DAT),
    ("US_DAT", US_DAT),
]:

    print(
        f"{label}: "
        f"{path.stat().st_size} bytes"
    )

    print(
        f"  SHA256: "
        f"{file_sha256(path)}"
    )


# ============================================================
# PIDX
# ============================================================

print()
print("[1] PIDX parsing")

kr_info, kr_entries = parse_pidx(
    KR_IDX,
    KR_DAT,
    "KR"
)

us_info, us_entries = parse_pidx(
    US_DAT,
    US_DAT,
    "US"
)

for info in [
    kr_info,
    us_info
]:

    print()
    print(
        f'[{info["region"]}]'
    )

    print(
        "FILES       :",
        info["files"]
    )

    print(
        "INFO_OFF    :",
        f'0x{info["info_off"]:X}'
    )

    print(
        "OFFSET2     :",
        f'0x{info["offset2"]:X}'
    )

    print(
        "EXPECTED    :",
        f'0x{info["expected_offset2"]:X}'
    )

    print(
        "OFFSET2_SIZE:",
        f'0x{info["offset2_size"]:X}'
    )

    print(
        "NAMES_OFF   :",
        f'0x{info["names_off"]:X}'
    )

    print(
        "NAMES_SIZE  :",
        f'0x{info["names_size"]:X}'
    )

    print(
        "TABLE VALID :",
        info["table_valid"]
    )

    if not info["table_valid"]:

        raise RuntimeError(
            f'{info["region"]}: '
            "24-byte table validation failed"
        )


write_manifest(
    OUT / "kr_pidx_manifest.tsv",
    kr_entries
)

write_manifest(
    OUT / "us_pidx_manifest.tsv",
    us_entries
)


# ============================================================
# 파일 엔트리 판별
# ============================================================

print()
print("[2] Entry classification")

kr_folder_values = {}

for e in kr_entries:

    kr_folder_values[
        e["is_folder"]
    ] = (
        kr_folder_values.get(
            e["is_folder"],
            0
        ) + 1
    )


us_folder_values = {}

for e in us_entries:

    us_folder_values[
        e["is_folder"]
    ] = (
        us_folder_values.get(
            e["is_folder"],
            0
        ) + 1
    )


print(
    "KR is_folder values:",
    kr_folder_values
)

print(
    "US is_folder values:",
    us_folder_values
)


# 일반적으로 0 = 실제 파일
kr_files = [
    e
    for e in kr_entries
    if e["is_folder"] == 0
]

us_files = [
    e
    for e in us_entries
    if e["is_folder"] == 0
]


print(
    "KR actual files:",
    len(kr_files)
)

print(
    "US actual files:",
    len(us_files)
)


# ============================================================
# 이름 비교
# ============================================================

print()
print("[3] Filename comparison")


def build_name_map(entries):

    result = {}

    for e in entries:

        k = e["name"].lower()

        result.setdefault(
            k,
            []
        ).append(e)

    return result


kr_map = build_name_map(
    kr_files
)

us_map = build_name_map(
    us_files
)

all_names = sorted(
    set(kr_map)
    | set(us_map)
)

compare_rows = []

for low in all_names:

    k = kr_map.get(
        low,
        []
    )

    u = us_map.get(
        low,
        []
    )

    if k and u:
        status = "BOTH"

    elif k:
        status = "KR_ONLY"

    else:
        status = "US_ONLY"

    name = (
        k[0]["name"]
        if k
        else u[0]["name"]
    )

    compare_rows.append({
        "name": name,

        "status": status,

        "kr_count": len(k),
        "us_count": len(u),

        "kr_entry":
            k[0]["entry"]
            if k else "",

        "us_entry":
            u[0]["entry"]
            if u else "",

        "kr_size":
            k[0]["size"]
            if k else "",

        "kr_zsize":
            k[0]["zsize"]
            if k else "",

        "us_size":
            u[0]["size"]
            if u else "",

        "us_zsize":
            u[0]["zsize"]
            if u else "",
    })


compare_fields = [
    "name",
    "status",

    "kr_count",
    "us_count",

    "kr_entry",
    "us_entry",

    "kr_size",
    "kr_zsize",

    "us_size",
    "us_zsize",
]

with (
    OUT / "common_name_compare.tsv"
).open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=compare_fields
    )

    w.writeheader()
    w.writerows(compare_rows)


common_count = sum(
    1
    for r in compare_rows
    if r["status"] == "BOTH"
)

print(
    "Common filenames:",
    common_count
)


# ============================================================
# 번역 후보
# ============================================================

print()
print("[4] Translation candidates")

candidate_rows = []

for region, entries in [
    ("KR", kr_files),
    ("US", us_files),
]:

    for e in entries:

        if not is_candidate(
            e["name"]
        ):
            continue

        candidate_rows.append({
            "region": region,
            "entry": e["entry"],

            "name": e["name"],
            "pack_name": e["pack_name"],

            "offset":
                e["offset"],

            "offset_hex":
                f'0x{e["offset"]:X}',

            "size":
                e["size"],

            "zsize":
                e["zsize"],
        })


candidate_fields = [
    "region",
    "entry",

    "name",
    "pack_name",

    "offset",
    "offset_hex",

    "size",
    "zsize",
]

with (
    OUT / "translation_candidates.tsv"
).open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=candidate_fields
    )

    w.writeheader()
    w.writerows(candidate_rows)


print(
    "Candidate entries:",
    len(candidate_rows)
)


# ============================================================
# 중요 후보
# ============================================================

strategic = {
    "text.bin",
    "text_f.bin",
    "text_g.bin",
    "text_i.bin",
    "text_s.bin",

    "event000.tbl",
    "event100.tbl",

    "quiz1.tbl",

    "title.ccs",

    "cmnselect.ccs",
    "modesel1.ccs",
    "charsel1.ccs",
}


# ============================================================
# 추출
# ============================================================

print()
print("[5] Candidate extraction")

extract_report = []
scan_rows = []

seen_names = {
    "KR": {},
    "US": {},
}


for (
    region,
    data_file,
    entries
) in [

    (
        "KR",
        KR_DAT,
        kr_files
    ),

    (
        "US",
        US_DAT,
        us_files
    ),
]:

    region_dir = (
        EXTRACT
        / region.lower()
    )

    for e in entries:

        name = e["name"]

        if not is_candidate(name):
            continue

        try:

            payload, mode = (
                extract_entry(
                    data_file,
                    e
                )
            )

            safe = safe_filename(
                name
            )

            seen = (
                seen_names[region]
                .get(
                    safe,
                    0
                )
            )

            seen_names[region][safe] = (
                seen + 1
            )

            if seen:

                safe = (
                    f"{safe}"
                    f"__entry"
                    f"{e['entry']:04d}"
                )

            out = (
                region_dir
                / safe
            )

            out.write_bytes(
                payload
            )

            ascii_hits = (
                ascii_strings(
                    payload
                )
            )

            sjis_hits = (
                sjis_strings(
                    payload
                )
            )

            ascii_sample = " | ".join(
                sanitize_sample(s)
                for _, s
                in ascii_hits[:20]
            )

            sjis_sample = " | ".join(
                sanitize_sample(s)
                for _, s
                in sjis_hits[:20]
            )

            scan_rows.append({
                "region": region,
                "entry": e["entry"],

                "name": name,

                "extract_mode":
                    mode,

                "output_size":
                    len(payload),

                "ascii_hits":
                    len(ascii_hits),

                "sjis_hits":
                    len(sjis_hits),

                "ascii_sample":
                    ascii_sample,

                "sjis_sample":
                    sjis_sample,
            })

            extract_report.append({
                "region": region,
                "entry": e["entry"],

                "name": name,

                "status": "OK",
                "mode": mode,

                "offset_hex":
                    f'0x{e["offset"]:X}',

                "size":
                    e["size"],

                "zsize":
                    e["zsize"],

                "output_size":
                    len(payload),

                "sha256":
                    bytes_sha256(
                        payload
                    ),

                "error": "",
            })

            # -------------------------------------------
            # ChatGPT 검토용 핵심 바이너리만 별도 복사
            # -------------------------------------------

            if (
                name.lower()
                in strategic
            ):

                share_name = (
                    f"{region}"
                    f"__entry{e['entry']:04d}"
                    f"__{safe}"
                )

                if len(payload) <= 2_000_000:

                    (
                        SHARE
                        / share_name
                    ).write_bytes(
                        payload
                    )

                else:

                    (
                        SHARE
                        / (
                            share_name
                            + ".head512k.bin"
                        )
                    ).write_bytes(
                        payload[:524288]
                    )

                    (
                        SHARE
                        / (
                            share_name
                            + ".tail128k.bin"
                        )
                    ).write_bytes(
                        payload[-131072:]
                    )

        except Exception as ex:

            extract_report.append({
                "region": region,
                "entry": e["entry"],

                "name": name,

                "status": "ERROR",
                "mode": "",

                "offset_hex":
                    f'0x{e["offset"]:X}',

                "size":
                    e["size"],

                "zsize":
                    e["zsize"],

                "output_size": "",
                "sha256": "",

                "error":
                    str(ex),
            })

            print(
                "[WARN]",
                region,
                e["entry"],
                name,
                ex
            )


extract_fields = [
    "region",
    "entry",

    "name",

    "status",
    "mode",

    "offset_hex",

    "size",
    "zsize",

    "output_size",
    "sha256",

    "error",
]

with (
    OUT / "extraction_report.tsv"
).open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=extract_fields
    )

    w.writeheader()
    w.writerows(
        extract_report
    )


scan_fields = [
    "region",
    "entry",

    "name",

    "extract_mode",
    "output_size",

    "ascii_hits",
    "sjis_hits",

    "ascii_sample",
    "sjis_sample",
]

with (
    OUT / "candidate_scan.tsv"
).open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=scan_fields
    )

    w.writeheader()
    w.writerows(
        scan_rows
    )


# ============================================================
# text*.bin 전용 목록
# ============================================================

text_rows = []

for e in us_files:

    low = e["name"].lower()

    if (
        low.startswith("text")
        and low.endswith(".bin")
    ):

        text_rows.append({
            "region": "US",

            "entry":
                e["entry"],

            "name":
                e["name"],

            "offset_hex":
                f'0x{e["offset"]:X}',

            "size":
                e["size"],

            "zsize":
                e["zsize"],
        })


for e in kr_files:

    low = e["name"].lower()

    if (
        low.startswith("text")
        and low.endswith(".bin")
    ):

        text_rows.append({
            "region": "KR",

            "entry":
                e["entry"],

            "name":
                e["name"],

            "offset_hex":
                f'0x{e["offset"]:X}',

            "size":
                e["size"],

            "zsize":
                e["zsize"],
        })


with (
    OUT / "text_bin_candidates.tsv"
).open(
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    fields = [
        "region",
        "entry",
        "name",
        "offset_hex",
        "size",
        "zsize",
    ]

    w = csv.DictWriter(
        f,
        delimiter="\t",
        fieldnames=fields
    )

    w.writeheader()
    w.writerows(
        text_rows
    )


# ============================================================
# 요약
# ============================================================

ok = sum(
    1
    for r in extract_report
    if r["status"] == "OK"
)

err = sum(
    1
    for r in extract_report
    if r["status"] == "ERROR"
)


summary = (
    OUT / "pidx_summary.txt"
)

with summary.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "Naruto PSP Stage 3\n"
    )

    f.write(
        "=" * 60
        + "\n\n"
    )

    for info in [
        kr_info,
        us_info
    ]:

        f.write(
            f'{info["region"]}\n'
        )

        f.write(
            f' files       = '
            f'{info["files"]}\n'
        )

        f.write(
            f' info_off    = '
            f'0x{info["info_off"]:X}\n'
        )

        f.write(
            f' offset2     = '
            f'0x{info["offset2"]:X}\n'
        )

        f.write(
            f' expected    = '
            f'0x{info["expected_offset2"]:X}\n'
        )

        f.write(
            f' names_off   = '
            f'0x{info["names_off"]:X}\n'
        )

        f.write(
            f' names_size  = '
            f'0x{info["names_size"]:X}\n'
        )

        f.write(
            f' table_valid = '
            f'{info["table_valid"]}\n\n'
        )

    f.write(
        "KR is_folder values: "
        + repr(kr_folder_values)
        + "\n"
    )

    f.write(
        "US is_folder values: "
        + repr(us_folder_values)
        + "\n\n"
    )

    f.write(
        f"KR actual files: "
        f"{len(kr_files)}\n"
    )

    f.write(
        f"US actual files: "
        f"{len(us_files)}\n"
    )

    f.write(
        f"Common filenames: "
        f"{common_count}\n"
    )

    f.write(
        f"Translation candidates: "
        f"{len(candidate_rows)}\n"
    )

    f.write(
        f"text*.bin candidates: "
        f"{len(text_rows)}\n"
    )

    f.write(
        f"Extract OK: "
        f"{ok}\n"
    )

    f.write(
        f"Extract ERROR: "
        f"{err}\n"
    )


print()
print("=" * 72)
print("Stage 3 complete")
print("=" * 72)

print(
    "KR actual files :",
    len(kr_files)
)

print(
    "US actual files :",
    len(us_files)
)

print(
    "Common names    :",
    common_count
)

print(
    "Candidates      :",
    len(candidate_rows)
)

print(
    "text*.bin       :",
    len(text_rows)
)

print(
    "Extract OK      :",
    ok
)

print(
    "Extract ERROR   :",
    err
)

print()
print(
    "Output:",
    OUT
)

print(
    "Share :",
    SHARE
)
