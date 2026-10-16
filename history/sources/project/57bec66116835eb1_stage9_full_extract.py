from pathlib import Path
from collections import defaultdict, Counter
import struct
import csv
import re
import hashlib
import shutil
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage9"

EXTRACT = OUT / "extracted"
SHARE   = OUT / "share"

KR_IDX = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.idx"
)

KR_DAT = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.dat"
)

US_DAT = (
    BASE / "us_extracted"
    / "PSP_GAME" / "USRDIR"
    / "naruto.dat"
)

for p in [
    EXTRACT / "kr",
    EXTRACT / "us",
    SHARE,
]:
    if p.exists():
        shutil.rmtree(p)

    p.mkdir(
        parents=True,
        exist_ok=True
    )


def u32(data, off):

    return struct.unpack_from(
        "<I",
        data,
        off
    )[0]


def sha256(data):

    return hashlib.sha256(
        data
    ).hexdigest()


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


def cstring(data, off):

    if off >= len(data):
        return ""

    end = data.find(
        b"\0",
        off
    )

    if end < 0:
        end = len(data)

    return data[
        off:end
    ].decode(
        "ascii",
        errors="replace"
    )


def safe_name(name):

    name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        name
    )

    name = name.rstrip(
        ". "
    )

    if not name:
        name = "_unnamed"

    return name


# ============================================================
# PIDX
# ============================================================

def parse_pidx(path):

    data = path.read_bytes()

    if data[:5] != b"PIDX0":

        raise RuntimeError(
            f"PIDX0 아님: {path}"
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
        data,
        4
    )

    if (
        info_off
        + files * 24
        != offset2
    ):

        raise RuntimeError(
            "PIDX 24-byte table "
            "validation failed"
        )

    names = data[
        names_off:
        names_off
        + names_size
    ]

    entries = []

    for i in range(files):

        off = (
            info_off
            + i * 24
        )

        (
            is_folder,
            name_off,
            pack_name_off,
            data_off,
            size,
            zsize,
        ) = struct.unpack_from(
            "<6I",
            data,
            off
        )

        entries.append({
            "entry": i,

            "is_folder":
                is_folder,

            "name":
                cstring(
                    names,
                    name_off
                ),

            "pack_name":
                cstring(
                    names,
                    pack_name_off
                ),

            "offset":
                data_off,

            "size":
                size,

            "zsize":
                zsize,
        })

    return entries


# IMPORTANT:
# zsize = actual bytes stored in DAT.
# size  = decompressed payload size.
#
# type 0 normally:
#   zsize = size + 8
#
# type 1 normally:
#   zsize < size
#
def stored_size(e):

    if e["zsize"]:
        return e["zsize"]

    return e["size"]


# ============================================================
# 3;x decoder
# ============================================================

def decode_3x(blob):

    if len(blob) < 8:

        raise RuntimeError(
            "container shorter than 8"
        )

    if blob[:3] != b" 3;":

        raise RuntimeError(
            "missing ' 3;' signature"
        )

    typ = blob[3]

    expected = u32(
        blob,
        4
    )

    # --------------------------------------------------------
    # type 0
    # --------------------------------------------------------

    if typ == ord("0"):

        out = bytes(
            b ^ 0x72
            for b in blob[8:]
        )

        if len(out) != expected:

            raise RuntimeError(
                f"3;0 size mismatch "
                f"{len(out)} != "
                f"{expected}"
            )

        return (
            out,
            "3;0",
            expected
        )

    # --------------------------------------------------------
    # type 1
    # --------------------------------------------------------

    if typ != ord("1"):

        raise RuntimeError(
            f"unknown 3;x type "
            f"0x{typ:02X}"
        )

    window = bytearray(
        0x1000
    )

    ring = 0xFEE

    src = 8
    flags = 0

    out = bytearray()

    while (
        src < len(blob)
        and len(out) < expected
    ):

        flags >>= 1

        if (
            flags & 0x100
        ) == 0:

            if src >= len(blob):
                break

            flags = (
                (blob[src] ^ 0x72)
                | 0xFF00
            )

            src += 1

        # literal
        if flags & 1:

            if src >= len(blob):
                break

            c = (
                blob[src]
                ^ 0x72
            )

            src += 1

            out.append(c)

            window[ring] = c

            ring = (
                ring + 1
            ) & 0xFFF

        # match
        else:

            if src + 1 >= len(blob):
                break

            b1 = (
                blob[src]
                ^ 0x72
            )

            b2 = (
                blob[src + 1]
                ^ 0x72
            )

            src += 2

            pos = (
                b1
                |
                (
                    (b2 & 0xF0)
                    << 4
                )
            )

            length = (
                (b2 & 0x0F)
                + 3
            )

            for j in range(length):

                c = window[
                    (pos + j)
                    & 0xFFF
                ]

                out.append(c)

                window[ring] = c

                ring = (
                    ring + 1
                ) & 0xFFF

                if (
                    len(out)
                    >= expected
                ):
                    break

    if len(out) != expected:

        raise RuntimeError(
            f"3;1 size mismatch "
            f"{len(out)} != "
            f"{expected}"
        )

    return (
        bytes(out),
        "3;1",
        expected
    )


# ============================================================
# output helpers
# ============================================================

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
                k: row.get(
                    k,
                    ""
                )
                for k in fields
            })


def printable_magic(data):

    raw = data[:16]

    text = "".join(
        chr(b)
        if 32 <= b <= 126
        else "."
        for b in raw
    )

    return (
        raw.hex(" "),
        text
    )


def flat(s):

    return (
        s
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", " ")
    )


# ============================================================
# Shift-JIS candidate scanner
# ============================================================

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


def sjis_samples(
    data,
    limit=30
):

    result = []

    i = 0
    n = len(data)

    while (
        i < n
        and len(result) < limit
    ):

        start = i
        buf = bytearray()
        jp_units = 0

        while i < n:

            a = data[i]

            # printable ASCII mixed into string
            if 0x20 <= a <= 0x7E:

                buf.append(a)
                i += 1
                continue

            # half-width kana
            if 0xA1 <= a <= 0xDF:

                buf.append(a)
                jp_units += 1
                i += 1
                continue

            # SJIS 2-byte
            if (
                i + 1 < n
                and (
                    0x81 <= a <= 0x9F
                    or
                    0xE0 <= a <= 0xFC
                )
            ):

                b = data[
                    i + 1
                ]

                if (
                    0x40 <= b <= 0xFC
                    and b != 0x7F
                ):

                    buf.extend(
                        data[i:i+2]
                    )

                    jp_units += 1
                    i += 2
                    continue

            break

        if (
            jp_units >= 2
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
                            s[:250]
                        )
                    )

            except Exception:
                pass

        if i <= start:
            i = start + 1
        else:
            i += 1

    return result


# ============================================================
# Parse index
# ============================================================

kr_entries = parse_pidx(
    KR_IDX
)

us_entries = parse_pidx(
    US_DAT
)

regions = {
    "KR": (
        KR_DAT,
        kr_entries
    ),

    "US": (
        US_DAT,
        us_entries
    ),
}


# ============================================================
# KR external IDX vs DAT prefix
# ============================================================

kr_idx_bytes = (
    KR_IDX.read_bytes()
)

with KR_DAT.open("rb") as f:

    kr_dat_prefix = f.read(
        len(kr_idx_bytes)
    )

idx_equal = (
    kr_idx_bytes
    == kr_dat_prefix
)

first_idx_diff = ""

if not idx_equal:

    for i, (
        a,
        b
    ) in enumerate(
        zip(
            kr_idx_bytes,
            kr_dat_prefix
        )
    ):

        if a != b:

            first_idx_diff = (
                f"0x{i:X}"
            )

            break


# ============================================================
# Full extraction
# ============================================================

validation_rows = []
layout_rows = []

paths_by_name = {
    "KR": defaultdict(list),
    "US": defaultdict(list),
}

codec_counts = Counter()

errors = []

for region, (
    dat_path,
    entries
) in regions.items():

    actual = [
        e
        for e in entries
        if e["is_folder"] == 0
    ]

    actual_sorted = sorted(
        actual,
        key=lambda x:
            x["offset"]
    )

    dat_size = (
        dat_path.stat().st_size
    )

    # layout
    for i, e in enumerate(
        actual_sorted
    ):

        n = stored_size(e)

        end = (
            e["offset"] + n
        )

        if i + 1 < len(
            actual_sorted
        ):

            next_off = (
                actual_sorted[
                    i + 1
                ]["offset"]
            )

        else:

            next_off = dat_size

        gap = (
            next_off - end
        )

        layout_rows.append({
            "region": region,
            "entry": e["entry"],
            "name": e["name"],

            "offset":
                e["offset"],

            "offset_hex":
                f'0x{e["offset"]:X}',

            "decoded_size":
                e["size"],

            "stored_size":
                n,

            "zsize":
                e["zsize"],

            "end_hex":
                f"0x{end:X}",

            "next_offset_hex":
                f"0x{next_off:X}",

            "gap":
                gap,

            "offset_mod_0x800":
                e["offset"]
                % 0x800,
        })

        if gap < 0:

            errors.append(
                f"{region} overlap: "
                f"{e['name']} "
                f"gap={gap}"
            )

    # extraction
    with dat_path.open("rb") as f:

        for num, e in enumerate(
            actual,
            1
        ):

            n = stored_size(e)

            try:

                if (
                    e["offset"] + n
                    > dat_size
                ):

                    raise RuntimeError(
                        "stored range "
                        "outside DAT"
                    )

                f.seek(
                    e["offset"]
                )

                blob = f.read(n)

                if len(blob) != n:

                    raise RuntimeError(
                        "short DAT read"
                    )

                decoded, codec, expected = (
                    decode_3x(blob)
                )

                if expected != e["size"]:

                    raise RuntimeError(
                        "header expected "
                        f"{expected} != "
                        f"PIDX size "
                        f"{e['size']}"
                    )

                if len(decoded) != e["size"]:

                    raise RuntimeError(
                        "decoded length "
                        f"{len(decoded)} != "
                        f"PIDX size "
                        f"{e['size']}"
                    )

                # type-specific relationship
                if codec == "3;0":

                    if e["zsize"]:

                        if (
                            e["zsize"]
                            != e["size"] + 8
                        ):

                            raise RuntimeError(
                                "3;0 expected "
                                "zsize=size+8, got "
                                f"{e['zsize']} / "
                                f"{e['size']}"
                            )

                safe = safe_name(
                    e["name"]
                )

                out_path = (
                    EXTRACT
                    / region.lower()
                    / (
                        f"entry"
                        f"{e['entry']:04d}"
                        f"__{safe}"
                    )
                )

                out_path.write_bytes(
                    decoded
                )

                paths_by_name[
                    region
                ][
                    e["name"].lower()
                ].append(
                    out_path
                )

                magic_hex, magic_ascii = (
                    printable_magic(
                        decoded
                    )
                )

                codec_counts[
                    (
                        region,
                        codec
                    )
                ] += 1

                validation_rows.append({
                    "region":
                        region,

                    "entry":
                        e["entry"],

                    "name":
                        e["name"],

                    "codec":
                        codec,

                    "offset_hex":
                        f'0x{e["offset"]:X}',

                    "pidx_size":
                        e["size"],

                    "pidx_zsize":
                        e["zsize"],

                    "stored_read":
                        n,

                    "header_expected":
                        expected,

                    "decoded_size":
                        len(decoded),

                    "status":
                        "OK",

                    "magic_hex":
                        magic_hex,

                    "magic_ascii":
                        magic_ascii,

                    "sha256":
                        sha256(decoded),
                })

            except Exception as ex:

                msg = (
                    f"{region} "
                    f"entry {e['entry']} "
                    f"{e['name']}: "
                    f"{ex}"
                )

                errors.append(msg)

                validation_rows.append({
                    "region":
                        region,

                    "entry":
                        e["entry"],

                    "name":
                        e["name"],

                    "codec":
                        "",

                    "offset_hex":
                        f'0x{e["offset"]:X}',

                    "pidx_size":
                        e["size"],

                    "pidx_zsize":
                        e["zsize"],

                    "stored_read":
                        n,

                    "header_expected":
                        "",

                    "decoded_size":
                        "",

                    "status":
                        "ERROR",

                    "magic_hex":
                        "",

                    "magic_ascii":
                        "",

                    "sha256":
                        "",

                    "error":
                        str(ex),
                })

            if (
                num % 100
                == 0
            ):

                print(
                    region,
                    "decoded",
                    num,
                    "/",
                    len(actual)
                )


write_tsv(
    OUT
    / "full_extract_validation.tsv",
    validation_rows,
    [
        "region",
        "entry",
        "name",
        "codec",
        "offset_hex",
        "pidx_size",
        "pidx_zsize",
        "stored_read",
        "header_expected",
        "decoded_size",
        "status",
        "magic_hex",
        "magic_ascii",
        "sha256",
        "error",
    ]
)


write_tsv(
    OUT
    / "archive_layout.tsv",
    layout_rows,
    [
        "region",
        "entry",
        "name",
        "offset",
        "offset_hex",
        "decoded_size",
        "stored_size",
        "zsize",
        "end_hex",
        "next_offset_hex",
        "gap",
        "offset_mod_0x800",
    ]
)


# ============================================================
# Find extracted file by name
# ============================================================

def one_file(
    region,
    name
):

    hits = paths_by_name[
        region
    ].get(
        name.lower(),
        []
    )

    if not hits:

        raise RuntimeError(
            f"{region} file not found: "
            f"{name}"
        )

    return hits[0]


# ============================================================
# Fixed text*.bin parser
# ============================================================

lang_files = {
    "en": "text.bin",
    "fr": "text_f.bin",
    "de": "text_g.bin",
    "it": "text_i.bin",
    "es": "text_s.bin",
}

lang_data = {}
encoding_rows = []

for lang, name in (
    lang_files.items()
):

    data = one_file(
        "US",
        name
    ).read_bytes()

    table_size = u32(
        data,
        0
    )

    if (
        table_size % 4
        or table_size > len(data)
    ):

        raise RuntimeError(
            f"{name}: "
            "invalid pointer table"
        )

    count = (
        table_size // 4
    )

    ptrs = [
        u32(
            data,
            i * 4
        )
        for i in range(count)
    ]

    strings = []

    utf8_ok = 0
    utf8_fail = 0

    for ptr in ptrs:

        if ptr >= len(data):

            raw = b""

        else:

            end = data.find(
                b"\0",
                ptr
            )

            if end < 0:
                end = len(data)

            raw = data[
                ptr:end
            ]

        try:

            text = raw.decode(
                "utf-8",
                errors="strict"
            )

            enc = "utf-8"
            utf8_ok += 1

        except UnicodeDecodeError:

            text = raw.decode(
                "cp1252",
                errors="replace"
            )

            enc = "cp1252-fallback"
            utf8_fail += 1

        strings.append(
            (
                ptr,
                raw,
                text,
                enc
            )
        )

    lang_data[
        lang
    ] = strings

    encoding_rows.append({
        "language":
            lang,

        "file":
            name,

        "slots":
            count,

        "utf8_ok":
            utf8_ok,

        "utf8_fail":
            utf8_fail,

        "decoded_size":
            len(data),
    })


counts = {
    len(v)
    for v in
    lang_data.values()
}

if len(counts) != 1:

    raise RuntimeError(
        f"text slot counts differ: "
        f"{counts}"
    )

slot_count = next(
    iter(counts)
)

fixed_rows = []

for i in range(
    slot_count
):

    row = {
        "id": i
    }

    for lang in (
        "en",
        "fr",
        "de",
        "it",
        "es"
    ):

        (
            ptr,
            raw,
            text,
            enc
        ) = lang_data[
            lang
        ][i]

        row[
            f"{lang}_offset"
        ] = f"0x{ptr:X}"

        row[
            f"{lang}_encoding"
        ] = enc

        row[
            lang
        ] = flat(text)

    fixed_rows.append(row)


fields = ["id"]

for lang in (
    "en",
    "fr",
    "de",
    "it",
    "es"
):

    fields += [
        f"{lang}_offset",
        f"{lang}_encoding",
        lang,
    ]


write_tsv(
    OUT
    / "text_multilang_fixed.tsv",
    fixed_rows,
    fields
)


write_tsv(
    OUT
    / "text_encoding_report.tsv",
    encoding_rows,
    [
        "language",
        "file",
        "slots",
        "utf8_ok",
        "utf8_fail",
        "decoded_size",
    ]
)


# ============================================================
# TBL helpers
# ============================================================

def tbl_text(
    region,
    name
):

    return one_file(
        region,
        name
    ).read_bytes().decode(
        "cp932",
        errors="replace"
    )


def parse_msgs(text):

    result = []

    for order, line in enumerate(
        text.splitlines()
    ):

        if not line.startswith(
            "MSG ="
        ):
            continue

        body = line[5:]

        parts = body.split(
            ",",
            2
        )

        if len(parts) < 3:
            continue

        result.append({
            "sequence":
                len(result),

            "line_number":
                order + 1,

            "speaker":
                parts[0],

            "msg_id":
                parts[1],

            "text":
                parts[2],
        })

    return result


# ============================================================
# Event pairing V2 + quality
# ============================================================

event_names = sorted(
    name
    for name in
    paths_by_name["KR"]
    if re.fullmatch(
        r"event\d+\.tbl",
        name
    )
    and name in
    paths_by_name["US"]
)

event_pairs = []
event_summary = []

for name in event_names:

    km = parse_msgs(
        tbl_text(
            "KR",
            name
        )
    )

    um = parse_msgs(
        tbl_text(
            "US",
            name
        )
    )

    us_occ = defaultdict(
        list
    )

    for m in um:

        if m["msg_id"]:

            us_occ[
                m["msg_id"]
            ].append(m)

    used_occ = Counter()

    matched = 0
    exact_id = 0
    fallback = 0
    speaker_mismatch = 0

    for i, k in enumerate(km):

        u = None
        method = ""

        if k["msg_id"]:

            occ = used_occ[
                k["msg_id"]
            ]

            candidates = (
                us_occ.get(
                    k["msg_id"],
                    []
                )
            )

            if occ < len(candidates):

                u = candidates[occ]

                used_occ[
                    k["msg_id"]
                ] += 1

                method = (
                    "msg_id"
                )

                exact_id += 1

        if (
            u is None
            and i < len(um)
        ):

            u = um[i]

            method = (
                "sequence"
            )

            fallback += 1

        if u is not None:

            matched += 1

            if (
                k["speaker"]
                != u["speaker"]
            ):

                speaker_mismatch += 1

        event_pairs.append({
            "file":
                name,

            "sequence":
                i,

            "match_method":
                method,

            "msg_id":
                k["msg_id"],

            "speaker_jp":
                k["speaker"],

            "speaker_en":
                (
                    u["speaker"]
                    if u else ""
                ),

            "speaker_match":
                (
                    bool(u)
                    and
                    k["speaker"]
                    == u["speaker"]
                ),

            "japanese":
                flat(
                    k["text"]
                ),

            "english":
                (
                    flat(
                        u["text"]
                    )
                    if u
                    else ""
                ),
        })

    event_summary.append({
        "file":
            name,

        "kr_messages":
            len(km),

        "us_messages":
            len(um),

        "matched":
            matched,

        "msg_id_matches":
            exact_id,

        "sequence_fallback":
            fallback,

        "speaker_mismatch":
            speaker_mismatch,

        "same_message_count":
            len(km)
            == len(um),
    })


write_tsv(
    OUT
    / "event_dialogue_pairs_v2.tsv",
    event_pairs,
    [
        "file",
        "sequence",
        "match_method",
        "msg_id",
        "speaker_jp",
        "speaker_en",
        "speaker_match",
        "japanese",
        "english",
    ]
)


write_tsv(
    OUT
    / "event_structure_summary.tsv",
    event_summary,
    [
        "file",
        "kr_messages",
        "us_messages",
        "matched",
        "msg_id_matches",
        "sequence_fallback",
        "speaker_mismatch",
        "same_message_count",
    ]
)


# ============================================================
# Quiz split - DO NOT pair keys directly
# ============================================================

def parse_quiz(
    region,
    name
):

    text = tbl_text(
        region,
        name
    )

    groups = defaultdict(
        dict
    )

    for line in (
        text.splitlines()
    ):

        m = re.match(
            r"^\s*#(\d+)\s*=(.*)$",
            line
        )

        if not m:
            continue

        key = int(
            m.group(1)
        )

        group = (
            key // 10
        )

        slot = (
            key % 10
        )

        groups[
            group
        ][slot] = (
            m.group(2)
            .strip()
        )

    rows = []

    for group in sorted(
        groups
    ):

        g = groups[
            group
        ]

        extras = [
            f"{k}:{g[k]}"
            for k in sorted(g)
            if k not in (
                0,1,2,3
            )
        ]

        rows.append({
            "region":
                region,

            "file":
                name,

            "question_index":
                group,

            "question":
                flat(
                    g.get(
                        0,
                        ""
                    )
                ),

            "correct":
                flat(
                    g.get(
                        1,
                        ""
                    )
                ),

            "wrong1":
                flat(
                    g.get(
                        2,
                        ""
                    )
                ),

            "wrong2":
                flat(
                    g.get(
                        3,
                        ""
                    )
                ),

            "extras":
                flat(
                    " | ".join(
                        extras
                    )
                ),
        })

    return rows


quiz_kr = []
quiz_us = []

for name in (
    "quiz1.tbl",
    "quiz2.tbl",
):

    quiz_kr += parse_quiz(
        "KR",
        name
    )

    quiz_us += parse_quiz(
        "US",
        name
    )


quiz_fields = [
    "region",
    "file",
    "question_index",
    "question",
    "correct",
    "wrong1",
    "wrong2",
    "extras",
]


write_tsv(
    OUT
    / "quiz_kr_questions.tsv",
    quiz_kr,
    quiz_fields
)


write_tsv(
    OUT
    / "quiz_us_questions.tsv",
    quiz_us,
    quiz_fields
)


quiz_summary = []

for name in (
    "quiz1.tbl",
    "quiz2.tbl"
):

    k = [
        r for r in quiz_kr
        if r["file"] == name
    ]

    u = [
        r for r in quiz_us
        if r["file"] == name
    ]

    quiz_summary.append({
        "file":
            name,

        "kr_questions":
            len(k),

        "us_questions":
            len(u),

        "same_count":
            len(k)
            == len(u),
    })


write_tsv(
    OUT
    / "quiz_structure_summary.tsv",
    quiz_summary,
    [
        "file",
        "kr_questions",
        "us_questions",
        "same_count",
    ]
)


# ============================================================
# KR CCS Japanese string scan
# ============================================================

jp_scan_rows = []

for name, paths in (
    paths_by_name[
        "KR"
    ].items()
):

    if not name.endswith(
        ".ccs"
    ):
        continue

    for path in paths:

        data = path.read_bytes()

        hits = sjis_samples(
            data,
            30
        )

        if not hits:
            continue

        jp_scan_rows.append({
            "file":
                name,

            "entry_file":
                path.name,

            "hits_capped":
                len(hits),

            "first_offset":
                f"0x{hits[0][0]:X}",

            "sample":
                " | ".join(
                    flat(s)
                    for _, s
                    in hits[:10]
                ),
        })


jp_scan_rows.sort(
    key=lambda r:
        r["hits_capped"],
    reverse=True
)


write_tsv(
    OUT
    / "kr_ccs_japanese_scan.tsv",
    jp_scan_rows,
    [
        "file",
        "entry_file",
        "hits_capped",
        "first_offset",
        "sample",
    ]
)


# ============================================================
# Font-ish / text-ish names and internal ASCII markers
# ============================================================

font_rows = []

name_re = re.compile(
    r"font|fnt|moji|glyph|"
    r"letter|kanji|jis|ascii|"
    r"charcode",
    re.I
)

markers = [
    b"font",
    b"FONT",
    b"glyph",
    b"GLYPH",
    b"Shift_JIS",
    b"SHIFT_JIS",
    b"sjis",
    b"SJIS",
]

for region in (
    "KR",
    "US"
):

    for name, paths in (
        paths_by_name[
            region
        ].items()
    ):

        for path in paths:

            data = path.read_bytes()

            marker_hits = []

            for marker in markers:

                pos = data.find(
                    marker
                )

                if pos >= 0:

                    marker_hits.append(
                        f"{marker.decode('ascii')}"
                        f"@0x{pos:X}"
                    )

            if (
                name_re.search(name)
                or marker_hits
            ):

                font_rows.append({
                    "region":
                        region,

                    "name":
                        name,

                    "entry_file":
                        path.name,

                    "name_match":
                        bool(
                            name_re.search(
                                name
                            )
                        ),

                    "markers":
                        ",".join(
                            marker_hits
                        ),

                    "size":
                        path.stat().st_size,
                })


write_tsv(
    OUT
    / "font_candidates.tsv",
    font_rows,
    [
        "region",
        "name",
        "entry_file",
        "name_match",
        "markers",
        "size",
    ]
)


# ============================================================
# Selected UI resources for later inspection
# ============================================================

ui_names = [
    "title.ccs",
    "modesel1.ccs",
    "charsel1.ccs",
    "mapsel1.ccs",
    "setting.ccs",
    "option.ccs",
    "mcmn.ccs",
    "cmnselect.ccs",
    "book.ccs",
    "home.ccs",
]


def share_file(
    region,
    name
):

    hits = paths_by_name[
        region
    ].get(
        name.lower(),
        []
    )

    if not hits:
        return

    src = hits[0]

    data = src.read_bytes()

    prefix = (
        f"{region}__"
        f"{safe_name(name)}"
    )

    if len(data) <= (
        1024 * 1024
    ):

        (
            SHARE
            / prefix
        ).write_bytes(
            data
        )

    else:

        (
            SHARE
            / (
                prefix
                + ".head256k.bin"
            )
        ).write_bytes(
            data[:262144]
        )

        (
            SHARE
            / (
                prefix
                + ".tail64k.bin"
            )
        ).write_bytes(
            data[-65536:]
        )


for name in ui_names:

    share_file(
        "KR",
        name
    )

    share_file(
        "US",
        name
    )


# ============================================================
# Summary
# ============================================================

layout_negative = sum(
    1
    for r in layout_rows
    if r["gap"] < 0
)

extract_errors = sum(
    1
    for r in validation_rows
    if r["status"] != "OK"
)


summary = (
    OUT
    / "stage9_summary.txt"
)

with summary.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "Naruto PSP Stage 9\n"
    )

    f.write(
        "=" * 72
        + "\n\n"
    )

    f.write(
        f"KR IDX SHA256: "
        f"{sha256_file(KR_IDX)}\n"
    )

    f.write(
        f"KR IDX == "
        f"KR DAT prefix: "
        f"{idx_equal}\n"
    )

    if first_idx_diff:

        f.write(
            f"First difference: "
            f"{first_idx_diff}\n"
        )

    f.write("\n")

    f.write(
        f"KR entries: "
        f"{len(kr_entries)}\n"
    )

    f.write(
        f"US entries: "
        f"{len(us_entries)}\n"
    )

    f.write(
        f"Decoded actual files: "
        f"{len(validation_rows)}\n"
    )

    f.write(
        f"Decode errors: "
        f"{extract_errors}\n"
    )

    f.write(
        f"Layout overlaps: "
        f"{layout_negative}\n\n"
    )

    for key in sorted(
        codec_counts
    ):

        f.write(
            f"{key[0]} {key[1]}: "
            f"{codec_counts[key]}\n"
        )

    f.write("\n")

    f.write(
        f"text.bin slots: "
        f"{slot_count}\n"
    )

    for r in encoding_rows:

        f.write(
            f"{r['language']}: "
            f"UTF8 OK={r['utf8_ok']} "
            f"FAIL={r['utf8_fail']}\n"
        )

    f.write("\n")

    f.write(
        f"Event files: "
        f"{len(event_summary)}\n"
    )

    f.write(
        f"Event rows: "
        f"{len(event_pairs)}\n"
    )

    f.write(
        f"Event speaker mismatches: "
        f"{sum(r['speaker_mismatch'] for r in event_summary)}\n"
    )

    f.write("\n")

    for r in quiz_summary:

        f.write(
            f"{r['file']}: "
            f"KR={r['kr_questions']} "
            f"US={r['us_questions']}\n"
        )

    f.write("\n")

    f.write(
        f"KR CCS Japanese candidates: "
        f"{len(jp_scan_rows)}\n"
    )

    f.write(
        f"Font candidates: "
        f"{len(font_rows)}\n"
    )


# ============================================================
# hard validation
# ============================================================

if errors:

    (
        OUT / "stage9_errors.txt"
    ).write_text(
        "\n".join(errors),
        encoding="utf-8"
    )

    print()
    print(
        "STAGE 9 ERRORS:",
        len(errors)
    )

    for x in errors[:20]:
        print(x)

    sys.exit(2)


print()
print("=" * 72)
print("STAGE 9 COMPLETE")
print("=" * 72)

print(
    "Decoded files:",
    len(validation_rows)
)

print(
    "KR IDX == DAT prefix:",
    idx_equal
)

print(
    "Codec counts:",
    dict(codec_counts)
)

print(
    "Event rows:",
    len(event_pairs)
)

print(
    "KR quiz:",
    len(quiz_kr)
)

print(
    "US quiz:",
    len(quiz_us)
)

print(
    "Output:",
    OUT
)
