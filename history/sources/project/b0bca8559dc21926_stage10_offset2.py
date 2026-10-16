from pathlib import Path
from collections import defaultdict, Counter
import struct
import csv
import hashlib
import re
import shutil
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage10"

EXTRACT = OUT / "offset2_extracted"
SHARE   = OUT / "share"

KR_USR = (
    BASE / "kr_extracted"
    / "PSP_GAME" / "USRDIR"
)

US_USR = (
    BASE / "us_extracted"
    / "PSP_GAME" / "USRDIR"
)

KR_IDX = KR_USR / "naruto.idx"
KR_DAT = KR_USR / "naruto.dat"
US_DAT = US_USR / "naruto.dat"

for p in [
    OUT,
    EXTRACT / "kr_external",
    EXTRACT / "kr_embedded",
    EXTRACT / "us_embedded",
    SHARE,
]:
    p.mkdir(
        parents=True,
        exist_ok=True
    )


def u32(data, off):

    return struct.unpack_from(
        "<I", data, off
    )[0]


def sha256(data):

    return hashlib.sha256(
        data
    ).hexdigest()


def safe_name(s):

    s = (
        s.replace("\\", "_")
         .replace("/", "_")
         .replace(":", "_")
    )

    s = re.sub(
        r'[<>|?*"]',
        "_",
        s
    )

    return s or "_unnamed"


def cstring(data, off):

    if off < 0 or off >= len(data):
        return ""

    end = data.find(
        b"\x00",
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


# ============================================================
# PIDX
# ============================================================

def read_embedded_index(dat_path):

    with dat_path.open("rb") as f:

        head = f.read(0x50)

        if head[:5] != b"PIDX0":

            raise RuntimeError(
                f"Embedded PIDX0 없음: "
                f"{dat_path}"
            )

        names_off = u32(
            head,
            0x20
        )

        names_size = u32(
            head,
            0x24
        )

        total = (
            names_off
            + names_size
        )

        f.seek(0)

        return f.read(total)


def parse_pidx_blob(
    data,
    label
):

    if data[:5] != b"PIDX0":

        raise RuntimeError(
            f"{label}: PIDX0 아님"
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
        names_off + names_size
        > len(data)
    ):

        raise RuntimeError(
            f"{label}: "
            "name table outside index"
        )

    names = data[
        names_off:
        names_off + names_size
    ]

    primary = []

    for i in range(files):

        off = (
            info_off
            + i * 24
        )

        if off + 24 > len(data):

            raise RuntimeError(
                f"{label}: "
                f"primary {i} outside"
            )

        vals = struct.unpack_from(
            "<6I",
            data,
            off
        )

        primary.append({
            "entry": i,

            "is_folder":
                vals[0],

            "name_off":
                vals[1],

            "name":
                cstring(
                    names,
                    vals[1]
                ),

            "pack_name_off":
                vals[2],

            "pack_name":
                cstring(
                    names,
                    vals[2]
                ),

            "offset":
                vals[3],

            "size":
                vals[4],

            "zsize":
                vals[5],
        })

    header = {
        "label":
            label,

        "packs_off":
            packs_off,

        "packs":
            packs,

        "info_off":
            info_off,

        "files":
            files,

        "dummy":
            dummy,

        "offset2":
            offset2,

        "offset2_size":
            offset2_size,

        "names_off":
            names_off,

        "names_size":
            names_size,
    }

    return {
        "blob":
            data,

        "header":
            header,

        "names":
            names,

        "primary":
            primary,
    }


# ============================================================
# OFFSET2
#
# QuickBMS macross_pidx_offset2.bms:
#
# offset2 block:
#   u32 file_count
#   u32 record_pointer[file_count]
#
# record pointer is relative to beginning of OFFSET2 block.
#
# each record:
#   u32 name_off
#   u32 pack_name_off
#   u32 file_off
#   u32 file_size
# ============================================================

def parse_offset2(pidx):

    h = pidx["header"]
    blob = pidx["blob"]
    names = pidx["names"]

    start = h["offset2"]
    size  = h["offset2_size"]

    end = start + size

    if end > len(blob):

        raise RuntimeError(
            f'{h["label"]}: '
            "OFFSET2 outside PIDX"
        )

    block = blob[
        start:end
    ]

    if len(block) < 4:

        return [], {
            "count": 0,
            "status": "EMPTY",
        }

    count = u32(
        block,
        0
    )

    pointer_table_end = (
        4
        + count * 4
    )

    if pointer_table_end > len(block):

        raise RuntimeError(
            f'{h["label"]}: '
            f"OFFSET2 count={count} "
            "pointer table outside block"
        )

    rows = []

    for i in range(count):

        ptr = u32(
            block,
            4 + i * 4
        )

        row = {
            "index":
                i,

            "record_ptr":
                ptr,

            "record_ptr_hex":
                f"0x{ptr:X}",

            "status":
                "OK",
        }

        if (
            ptr < 0
            or ptr + 16 > len(block)
        ):

            row["status"] = (
                "BAD_RECORD_POINTER"
            )

            row.update({
                "name_off": "",
                "name": "",
                "pack_name_off": "",
                "pack_name": "",
                "file_off": "",
                "file_size": "",
            })

            rows.append(row)
            continue

        (
            name_off,
            pack_name_off,
            file_off,
            file_size,
        ) = struct.unpack_from(
            "<4I",
            block,
            ptr
        )

        row.update({
            "name_off":
                name_off,

            "name":
                cstring(
                    names,
                    name_off
                ),

            "pack_name_off":
                pack_name_off,

            "pack_name":
                cstring(
                    names,
                    pack_name_off
                ),

            "file_off":
                file_off,

            "file_off_hex":
                f"0x{file_off:X}",

            "file_size":
                file_size,
        })

        rows.append(row)

    meta = {
        "count":
            count,

        "block_size":
            len(block),

        "pointer_table_end":
            pointer_table_end,

        "status":
            "OK",
    }

    return rows, meta


# ============================================================
# 3;x decode
# ============================================================

def decode_3x(blob):

    if (
        len(blob) < 8
        or blob[:3] != b" 3;"
    ):

        return blob, "raw"

    typ = blob[3]

    expected = u32(
        blob,
        4
    )

    if typ == ord("0"):

        out = bytes(
            b ^ 0x72
            for b in blob[8:]
        )

        if len(out) != expected:

            raise RuntimeError(
                "3;0 size mismatch "
                f"{len(out)} != "
                f"{expected}"
            )

        return out, "3;0"

    if typ != ord("1"):

        return blob, (
            f"unknown_3;"
            f"{chr(typ)}"
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

                if len(out) >= expected:
                    break

    if len(out) != expected:

        raise RuntimeError(
            "3;1 size mismatch "
            f"{len(out)} != "
            f"{expected}"
        )

    return bytes(out), "3;1"


# ============================================================
# Helpers
# ============================================================

def resolve_pack(
    usrdir,
    pack_name,
    default_dat
):

    if not pack_name:

        return default_dat

    cleaned = (
        pack_name
        .replace("\\", "/")
        .lstrip("/")
    )

    candidates = [
        usrdir / cleaned,
        usrdir / Path(cleaned).name,
    ]

    for p in candidates:

        if p.exists():
            return p

    return default_dat


def read_record_raw(
    usrdir,
    default_dat,
    record
):

    if record["status"] != "OK":

        return None, None

    pack = resolve_pack(
        usrdir,
        record["pack_name"],
        default_dat
    )

    if not pack.exists():

        return None, pack

    off = record["file_off"]
    size = record["file_size"]

    if (
        off + size
        > pack.stat().st_size
    ):

        return None, pack

    with pack.open("rb") as f:

        f.seek(off)

        raw = f.read(size)

    return raw, pack


def read_primary_decoded(
    dat_path,
    entry
):

    stored = (
        entry["zsize"]
        if entry["zsize"]
        else entry["size"]
    )

    if (
        entry["offset"]
        + stored
        > dat_path.stat().st_size
    ):

        return None

    with dat_path.open("rb") as f:

        f.seek(
            entry["offset"]
        )

        raw = f.read(stored)

    try:

        dec, codec = (
            decode_3x(raw)
        )

        return dec

    except Exception:

        return None


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


def diff_ranges(
    a,
    b
):

    n = min(
        len(a),
        len(b)
    )

    ranges = []

    start = None

    for i in range(n):

        if a[i] != b[i]:

            if start is None:
                start = i

        else:

            if start is not None:

                ranges.append(
                    (start, i)
                )

                start = None

    if start is not None:

        ranges.append(
            (start, n)
        )

    if len(a) != len(b):

        ranges.append(
            (
                n,
                max(
                    len(a),
                    len(b)
                )
            )
        )

    return ranges


translation_re = re.compile(
    r"(event|quiz|text|title|"
    r"select|mode|menu|option|"
    r"setting|message|msg|"
    r"dialog|story|name|skill|"
    r"guide|help)",
    re.I
)


# ============================================================
# Read PIDX variants
# ============================================================

kr_ext_blob = (
    KR_IDX.read_bytes()
)

kr_emb_blob = (
    read_embedded_index(
        KR_DAT
    )
)

us_emb_blob = (
    read_embedded_index(
        US_DAT
    )
)

sources = {
    "KR_EXTERNAL": {
        "pidx":
            parse_pidx_blob(
                kr_ext_blob,
                "KR_EXTERNAL"
            ),

        "usrdir":
            KR_USR,

        "dat":
            KR_DAT,

        "outdir":
            EXTRACT
            / "kr_external",
    },

    "KR_EMBEDDED": {
        "pidx":
            parse_pidx_blob(
                kr_emb_blob,
                "KR_EMBEDDED"
            ),

        "usrdir":
            KR_USR,

        "dat":
            KR_DAT,

        "outdir":
            EXTRACT
            / "kr_embedded",
    },

    "US_EMBEDDED": {
        "pidx":
            parse_pidx_blob(
                us_emb_blob,
                "US_EMBEDDED"
            ),

        "usrdir":
            US_USR,

        "dat":
            US_DAT,

        "outdir":
            EXTRACT
            / "us_embedded",
    },
}


# ============================================================
# Header report
# ============================================================

header_rows = []

for label, obj in (
    sources.items()
):

    h = obj[
        "pidx"
    ]["header"]

    off2, meta = parse_offset2(
        obj["pidx"]
    )

    obj["offset2"] = off2
    obj["offset2_meta"] = meta

    header_rows.append({
        "source":
            label,

        "index_bytes":
            len(
                obj["pidx"]["blob"]
            ),

        "primary_entries":
            h["files"],

        "info_off":
            f'0x{h["info_off"]:X}',

        "offset2":
            f'0x{h["offset2"]:X}',

        "offset2_size":
            h["offset2_size"],

        "names_off":
            f'0x{h["names_off"]:X}',

        "names_size":
            h["names_size"],

        "offset2_files":
            meta["count"],

        "offset2_pointer_end":
            meta.get(
                "pointer_table_end",
                ""
            ),
    })


write_tsv(
    OUT / "pidx_variants.tsv",
    header_rows,
    [
        "source",
        "index_bytes",
        "primary_entries",
        "info_off",
        "offset2",
        "offset2_size",
        "names_off",
        "names_size",
        "offset2_files",
        "offset2_pointer_end",
    ]
)


# ============================================================
# KR external vs embedded byte differences
# ============================================================

diff_rows = []

for start, end in diff_ranges(
    kr_ext_blob,
    kr_emb_blob
):

    ext = kr_ext_blob[
        start:
        min(
            end,
            start + 64
        )
    ]

    emb = kr_emb_blob[
        start:
        min(
            end,
            start + 64
        )
    ]

    h = sources[
        "KR_EXTERNAL"
    ]["pidx"]["header"]

    if (
        h["offset2"]
        <= start
        < h["offset2"]
        + h["offset2_size"]
    ):

        area = "OFFSET2"

    elif (
        h["info_off"]
        <= start
        < h["offset2"]
    ):

        area = "PRIMARY"

    elif (
        h["names_off"]
        <= start
        < h["names_off"]
        + h["names_size"]
    ):

        area = "NAMES"

    else:

        area = "HEADER/OTHER"

    diff_rows.append({
        "start":
            f"0x{start:X}",

        "end":
            f"0x{end:X}",

        "length":
            end - start,

        "area":
            area,

        "external_hex":
            ext.hex(" "),

        "embedded_hex":
            emb.hex(" "),
    })


write_tsv(
    OUT / "kr_index_diff_ranges.tsv",
    diff_rows,
    [
        "start",
        "end",
        "length",
        "area",
        "external_hex",
        "embedded_hex",
    ]
)


# ============================================================
# Primary comparison
# ============================================================

kr_ext_primary = (
    sources[
        "KR_EXTERNAL"
    ]["pidx"]["primary"]
)

kr_emb_primary = (
    sources[
        "KR_EMBEDDED"
    ]["pidx"]["primary"]
)

primary_compare = []

max_primary = max(
    len(kr_ext_primary),
    len(kr_emb_primary)
)

for i in range(max_primary):

    a = (
        kr_ext_primary[i]
        if i < len(
            kr_ext_primary
        )
        else None
    )

    b = (
        kr_emb_primary[i]
        if i < len(
            kr_emb_primary
        )
        else None
    )

    if a is None or b is None:

        same = False

    else:

        same = all(
            a.get(k)
            == b.get(k)
            for k in (
                "is_folder",
                "name_off",
                "pack_name_off",
                "offset",
                "size",
                "zsize",
            )
        )

    primary_compare.append({
        "entry":
            i,

        "same":
            same,

        "external_name":
            a["name"]
            if a else "",

        "embedded_name":
            b["name"]
            if b else "",

        "external_offset":
            (
                f'0x{a["offset"]:X}'
                if a else ""
            ),

        "embedded_offset":
            (
                f'0x{b["offset"]:X}'
                if b else ""
            ),

        "external_size":
            a["size"]
            if a else "",

        "embedded_size":
            b["size"]
            if b else "",

        "external_zsize":
            a["zsize"]
            if a else "",

        "embedded_zsize":
            b["zsize"]
            if b else "",
    })


write_tsv(
    OUT / "kr_primary_compare.tsv",
    primary_compare,
    [
        "entry",
        "same",
        "external_name",
        "embedded_name",
        "external_offset",
        "embedded_offset",
        "external_size",
        "embedded_size",
        "external_zsize",
        "embedded_zsize",
    ]
)


# ============================================================
# OFFSET2 extraction and comparison with primary
# ============================================================

record_rows = []
translation_rows = []

source_stats = {}

for label, obj in (
    sources.items()
):

    records = obj["offset2"]

    primary_by_name = defaultdict(
        list
    )

    for e in (
        obj["pidx"]["primary"]
    ):

        if (
            e["is_folder"] == 0
            and e["name"]
        ):

            primary_by_name[
                e["name"].lower()
            ].append(e)

    valid_offsets = []

    for rec in records:

        row = {
            "source":
                label,

            **rec,
        }

        raw, pack_path = (
            read_record_raw(
                obj["usrdir"],
                obj["dat"],
                rec
            )
        )

        if pack_path is not None:

            row["resolved_pack"] = (
                str(pack_path)
            )

        if raw is None:

            row["read_status"] = (
                "READ_ERROR"
            )

            record_rows.append(row)
            continue

        row["read_status"] = "OK"

        valid_offsets.append(
            (
                rec["file_off"],
                rec["file_off"]
                + rec["file_size"]
            )
        )

        row["raw_sha256"] = (
            sha256(raw)
        )

        row["magic_hex"] = (
            raw[:16].hex(" ")
        )

        row["magic_ascii"] = "".join(
            chr(x)
            if 32 <= x <= 126
            else "."
            for x in raw[:16]
        )

        try:

            decoded, codec = (
                decode_3x(raw)
            )

            row["codec"] = codec
            row["decoded_size"] = (
                len(decoded)
            )

            row["decoded_sha256"] = (
                sha256(decoded)
            )

        except Exception as ex:

            decoded = raw

            row["codec"] = (
                "DECODE_ERROR"
            )

            row["decoded_size"] = (
                len(raw)
            )

            row["decoded_sha256"] = (
                sha256(raw)
            )

            row["decode_error"] = (
                str(ex)
            )

        matches = (
            primary_by_name.get(
                rec["name"].lower(),
                []
            )
            if rec["name"]
            else []
        )

        row["primary_name_matches"] = (
            len(matches)
        )

        same_primary = False

        for pe in matches:

            pdecoded = (
                read_primary_decoded(
                    obj["dat"],
                    pe
                )
            )

            if (
                pdecoded is not None
                and pdecoded == decoded
            ):

                same_primary = True
                break

        row["same_as_primary_decoded"] = (
            same_primary
        )

        # Save OFFSET2 raw file.
        filename = (
            f"{rec['index']:04d}"
            f"__{safe_name(rec['name'])}"
        )

        out_path = (
            obj["outdir"]
            / filename
        )

        out_path.write_bytes(raw)

        # Strategic small files for upload.
        if (
            rec["name"]
            and translation_re.search(
                rec["name"]
            )
        ):

            tr = dict(row)

            translation_rows.append(
                tr
            )

            if len(raw) <= 2_000_000:

                share_name = (
                    f"{label}"
                    f"__off2_"
                    f"{rec['index']:04d}"
                    f"__{safe_name(rec['name'])}"
                )

                (
                    SHARE
                    / share_name
                ).write_bytes(raw)

                if decoded != raw:

                    (
                        SHARE
                        / (
                            share_name
                            + ".decoded"
                        )
                    ).write_bytes(
                        decoded
                    )

        record_rows.append(row)

    if valid_offsets:

        min_start = min(
            x[0]
            for x in valid_offsets
        )

        max_end = max(
            x[1]
            for x in valid_offsets
        )

    else:

        min_start = None
        max_end = None

    source_stats[label] = {
        "count":
            len(records),

        "valid":
            sum(
                1
                for r in record_rows
                if (
                    r["source"] == label
                    and r.get(
                        "read_status"
                    ) == "OK"
                )
            ),

        "min_start":
            min_start,

        "max_end":
            max_end,

        "dat_size":
            obj["dat"]
            .stat()
            .st_size,

        "same_as_primary":
            sum(
                1
                for r in record_rows
                if (
                    r["source"] == label
                    and r.get(
                        "same_as_primary_decoded"
                    ) is True
                )
            ),
    }


fields = [
    "source",
    "index",

    "record_ptr",
    "record_ptr_hex",

    "status",

    "name_off",
    "name",

    "pack_name_off",
    "pack_name",

    "file_off",
    "file_off_hex",
    "file_size",

    "resolved_pack",
    "read_status",

    "magic_hex",
    "magic_ascii",

    "codec",
    "decoded_size",

    "raw_sha256",
    "decoded_sha256",

    "primary_name_matches",
    "same_as_primary_decoded",

    "decode_error",
]


write_tsv(
    OUT / "offset2_records.tsv",
    record_rows,
    fields
)


write_tsv(
    OUT / "offset2_translation_candidates.tsv",
    translation_rows,
    fields
)


# ============================================================
# KR OFFSET2 external vs embedded records
# ============================================================

a = sources[
    "KR_EXTERNAL"
]["offset2"]

b = sources[
    "KR_EMBEDDED"
]["offset2"]

kr_off2_compare = []

for i in range(
    max(
        len(a),
        len(b)
    )
):

    ea = (
        a[i]
        if i < len(a)
        else None
    )

    eb = (
        b[i]
        if i < len(b)
        else None
    )

    if (
        ea is not None
        and eb is not None
    ):

        same = all(
            ea.get(k)
            == eb.get(k)
            for k in (
                "record_ptr",
                "name_off",
                "pack_name_off",
                "file_off",
                "file_size",
            )
        )

    else:
        same = False

    kr_off2_compare.append({
        "index":
            i,

        "same":
            same,

        "external_name":
            ea.get(
                "name", ""
            )
            if ea else "",

        "embedded_name":
            eb.get(
                "name", ""
            )
            if eb else "",

        "external_record_ptr":
            (
                f'0x{ea["record_ptr"]:X}'
                if ea else ""
            ),

        "embedded_record_ptr":
            (
                f'0x{eb["record_ptr"]:X}'
                if eb else ""
            ),

        "external_file_off":
            (
                f'0x{ea["file_off"]:X}'
                if (
                    ea
                    and isinstance(
                        ea.get("file_off"),
                        int
                    )
                )
                else ""
            ),

        "embedded_file_off":
            (
                f'0x{eb["file_off"]:X}'
                if (
                    eb
                    and isinstance(
                        eb.get("file_off"),
                        int
                    )
                )
                else ""
            ),

        "external_file_size":
            ea.get(
                "file_size", ""
            )
            if ea else "",

        "embedded_file_size":
            eb.get(
                "file_size", ""
            )
            if eb else "",
    })


write_tsv(
    OUT / "kr_offset2_compare.tsv",
    kr_off2_compare,
    [
        "index",
        "same",
        "external_name",
        "embedded_name",
        "external_record_ptr",
        "embedded_record_ptr",
        "external_file_off",
        "embedded_file_off",
        "external_file_size",
        "embedded_file_size",
    ]
)


# ============================================================
# OFFSET2 physical layout / overlaps
# ============================================================

coverage_rows = []

for label, obj in (
    sources.items()
):

    recs = [
        r
        for r in obj["offset2"]
        if (
            r["status"] == "OK"
            and isinstance(
                r.get("file_off"),
                int
            )
            and isinstance(
                r.get("file_size"),
                int
            )
        )
    ]

    recs.sort(
        key=lambda x:
            x["file_off"]
    )

    for i, r in enumerate(recs):

        start = r["file_off"]
        end = (
            start
            + r["file_size"]
        )

        if i + 1 < len(recs):

            nxt = recs[
                i + 1
            ]["file_off"]

            gap = (
                nxt - end
            )

        else:

            nxt = (
                obj["dat"]
                .stat()
                .st_size
            )

            gap = (
                nxt - end
            )

        coverage_rows.append({
            "source":
                label,

            "index":
                r["index"],

            "name":
                r["name"],

            "start_hex":
                f"0x{start:X}",

            "end_hex":
                f"0x{end:X}",

            "size":
                r["file_size"],

            "next_hex":
                f"0x{nxt:X}",

            "gap":
                gap,

            "start_mod_0x800":
                start % 0x800,
        })


write_tsv(
    OUT / "offset2_layout.tsv",
    coverage_rows,
    [
        "source",
        "index",
        "name",
        "start_hex",
        "end_hex",
        "size",
        "next_hex",
        "gap",
        "start_mod_0x800",
    ]
)


# ============================================================
# Summary
# ============================================================

summary = (
    OUT / "stage10_summary.txt"
)

with summary.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "Naruto PSP Stage 10\n"
    )

    f.write(
        "=" * 72
        + "\n\n"
    )

    f.write(
        "KR external vs embedded PIDX\n"
    )

    f.write(
        f"  external bytes: "
        f"{len(kr_ext_blob)}\n"
    )

    f.write(
        f"  embedded bytes: "
        f"{len(kr_emb_blob)}\n"
    )

    f.write(
        f"  diff ranges: "
        f"{len(diff_rows)}\n"
    )

    if diff_rows:

        f.write(
            f"  first diff: "
            f"{diff_rows[0]['start']} "
            f"area={diff_rows[0]['area']}\n"
        )

    primary_diff = sum(
        1
        for r in primary_compare
        if not r["same"]
    )

    f.write(
        f"  primary entry differences: "
        f"{primary_diff}\n\n"
    )

    for label in (
        "KR_EXTERNAL",
        "KR_EMBEDDED",
        "US_EMBEDDED",
    ):

        s = source_stats[
            label
        ]

        f.write(
            f"{label}\n"
        )

        f.write(
            f"  OFFSET2 records: "
            f"{s['count']}\n"
        )

        f.write(
            f"  readable: "
            f"{s['valid']}\n"
        )

        f.write(
            f"  same as primary decoded: "
            f"{s['same_as_primary']}\n"
        )

        if s["min_start"] is not None:

            f.write(
                f"  first data offset: "
                f"0x{s['min_start']:X}\n"
            )

            f.write(
                f"  final data end: "
                f"0x{s['max_end']:X}\n"
            )

            f.write(
                f"  DAT size: "
                f"0x{s['dat_size']:X}\n"
            )

            f.write(
                f"  final uncovered tail: "
                f"{s['dat_size'] - s['max_end']}\n"
            )

        f.write("\n")

    off2_diff = sum(
        1
        for r in kr_off2_compare
        if not r["same"]
    )

    f.write(
        f"KR OFFSET2 record differences: "
        f"{off2_diff}\n"
    )

    f.write(
        f"Translation-like OFFSET2 records: "
        f"{len(translation_rows)}\n"
    )

    f.write("\n")

    codec_counts = Counter(
        r.get(
            "codec",
            ""
        )
        for r in record_rows
        if r.get(
            "read_status"
        ) == "OK"
    )

    f.write(
        "OFFSET2 codec/magic classificatioLOCAL_PATH"
    )

    for k, v in (
        codec_counts.most_common()
    ):

        f.write(
            f"  {k}: {v}\n"
        )


print()
print("=" * 72)
print("STAGE 10 COMPLETE")
print("=" * 72)

print(
    "KR PIDX diff ranges:",
    len(diff_rows)
)

print(
    "KR primary differences:",
    sum(
        1
        for x in primary_compare
        if not x["same"]
    )
)

for label, s in (
    source_stats.items()
):

    print(
        label,
        "OFFSET2 =",
        s["count"],
        "range =",
        (
            (
                f"0x{s['min_start']:X}"
                f"..0x{s['max_end']:X}"
            )
            if s["min_start"]
            is not None
            else "none"
        )
    )

print(
    "Translation-like OFFSET2:",
    len(translation_rows)
)

print(
    "Output:",
    OUT
)
