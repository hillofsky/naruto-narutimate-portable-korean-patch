from pathlib import Path, PurePosixPath
from collections import defaultdict, Counter
import struct
import csv
import hashlib
import re
import shutil
import zlib
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage11"

SHARE = OUT / "share"

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

if SHARE.exists():
    shutil.rmtree(SHARE)

SHARE.mkdir(
    parents=True,
    exist_ok=True
)


def u16le(data, off):
    return struct.unpack_from(
        "<H", data, off
    )[0]


def u32(data, off):
    return struct.unpack_from(
        "<I", data, off
    )[0]


def be16(data, off):
    return struct.unpack_from(
        ">H", data, off
    )[0]


def be32(data, off):
    return struct.unpack_from(
        ">I", data, off
    )[0]


def sha256(data):

    return hashlib.sha256(
        data
    ).hexdigest()


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


def basename(name):

    name = name.replace(
        "\\",
        "/"
    )

    return PurePosixPath(
        name
    ).name.lower()


def safe_name(name):

    name = name.replace(
        "\\",
        "__"
    ).replace(
        "/",
        "__"
    )

    return re.sub(
        r'[<>:"|?*]',
        "_",
        name
    )


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

        for r in rows:

            w.writerow({
                k: r.get(k, "")
                for k in fields
            })


# ============================================================
# PIDX
# ============================================================

def read_embedded_pidx(dat):

    with dat.open("rb") as f:

        head = f.read(0x50)

        if head[:5] != b"PIDX0":
            raise RuntimeError(
                f"PIDX0 없음: {dat}"
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


def parse_pidx(blob):

    if blob[:5] != b"PIDX0":
        raise RuntimeError(
            "invalid PIDX"
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
        blob,
        4
    )

    names = blob[
        names_off:
        names_off + names_size
    ]

    primary = []

    for i in range(files):

        off = (
            info_off
            + i * 24
        )

        (
            is_folder,
            name_off,
            pack_name_off,
            file_off,
            size,
            zsize,
        ) = struct.unpack_from(
            "<6I",
            blob,
            off
        )

        primary.append({
            "entry":
                i,

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
                file_off,

            "size":
                size,

            "zsize":
                zsize,
        })

    # OFFSET2
    block = blob[
        offset2:
        offset2 + offset2_size
    ]

    count = u32(
        block,
        0
    )

    offset2_rows = []

    for i in range(count):

        ptr = u32(
            block,
            4 + i * 4
        )

        if ptr + 16 > len(block):

            raise RuntimeError(
                f"bad OFFSET2 ptr "
                f"{i}: 0x{ptr:X}"
            )

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

        offset2_rows.append({
            "index":
                i,

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

            "file_off":
                file_off,

            "file_size":
                file_size,
        })

    return {
        "primary":
            primary,

        "offset2":
            offset2_rows,
    }


# ============================================================
# Naruto 3;x
# ============================================================

def decode_3x(blob):

    if (
        len(blob) < 8
        or blob[:3] != b" 3;"
    ):

        raise RuntimeError(
            "not 3;x"
        )

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
                f"3;0 size "
                f"{len(out)} != "
                f"{expected}"
            )

        return out

    if typ != ord("1"):

        raise RuntimeError(
            f"unknown 3;{chr(typ)}"
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

                if (
                    len(out)
                    >= expected
                ):
                    break

    if len(out) != expected:

        raise RuntimeError(
            f"3;1 size "
            f"{len(out)} != "
            f"{expected}"
        )

    return bytes(out)


# ============================================================
# SEGS
# ============================================================

def decode_segs(blob):

    if (
        len(blob) < 16
        or blob[:4] != b"segs"
    ):

        raise RuntimeError(
            "not SEGS"
        )

    flags = be16(
        blob,
        4
    )

    chunks = be16(
        blob,
        6
    )

    full_size = be32(
        blob,
        8
    )

    full_zsize = be32(
        blob,
        12
    )

    base2 = (
        16
        + chunks * 8
    )

    desc = []

    for i in range(chunks):

        o = (
            16
            + i * 8
        )

        zsize = be16(
            blob,
            o
        )

        size = be16(
            blob,
            o + 2
        )

        off = be32(
            blob,
            o + 4
        )

        off -= 1

        desc.append(
            (
                zsize,
                size,
                off
            )
        )

    workaround = (
        len(desc) > 0
        and desc[0][2] == 0
    )

    out = bytearray()

    for (
        zsize,
        size,
        off
    ) in desc:

        if size == 0:
            size = 0x10000

        if workaround:

            real_off = (
                base2 + off
            )

        else:

            real_off = off

        chunk = blob[
            real_off:
            real_off + zsize
        ]

        if len(chunk) != zsize:

            raise RuntimeError(
                "SEGS chunk outside"
            )

        if size == zsize:

            dec = chunk

        else:

            dec = zlib.decompress(
                chunk,
                -15
            )

        if len(dec) != size:

            raise RuntimeError(
                f"SEGS chunk size "
                f"{len(dec)} != "
                f"{size}"
            )

        out.extend(dec)

    if len(out) != full_size:

        raise RuntimeError(
            f"SEGS full size "
            f"{len(out)} != "
            f"{full_size}"
        )

    return bytes(out)


# ============================================================
# Generic compressed member
# ============================================================

def decode_compressed(blob):

    if blob[:3] == b" 3;":

        return (
            decode_3x(blob),
            "3;x",
            ""
        )

    if blob[:4] == b"segs":

        return (
            decode_segs(blob),
            "segs",
            ""
        )

    try:

        return (
            zlib.decompress(blob),
            "zlib",
            ""
        )

    except Exception:
        pass

    try:

        return (
            zlib.decompress(
                blob,
                -15
            ),
            "deflate",
            ""
        )

    except Exception as ex:

        return (
            blob,
            "UNKNOWN_COMPRESSED",
            str(ex)
        )


# ============================================================
# Primary files
# ============================================================

def build_primary(
    dat,
    entries
):

    result = []
    by_base = defaultdict(list)

    dat_size = (
        dat.stat().st_size
    )

    with dat.open("rb") as f:

        for e in entries:

            if e["is_folder"] != 0:
                continue

            stored = (
                e["zsize"]
                if e["zsize"]
                else e["size"]
            )

            if (
                e["offset"]
                + stored
                > dat_size
            ):

                raise RuntimeError(
                    f"primary outside DAT: "
                    f"{e['name']}"
                )

            f.seek(
                e["offset"]
            )

            raw = f.read(stored)

            if raw[:3] == b" 3;":

                decoded = (
                    decode_3x(raw)
                )

                codec = (
                    raw[:4]
                    .decode(
                        "ascii",
                        errors="replace"
                    )
                )

            else:

                decoded = raw
                codec = "raw"

            row = {
                **e,

                "stored_size":
                    len(raw),

                "decoded_sha256":
                    sha256(decoded),

                "codec":
                    codec,

                "decoded":
                    decoded,
            }

            result.append(row)

            by_base[
                e["name"].lower()
            ].append(row)

    return result, by_base


# ============================================================
# FSTS
# ============================================================

def parse_fsts(
    bundle,
    bundle_name
):

    if (
        len(bundle) < 0x20
        or bundle[:4] != b"FSTS"
    ):

        raise RuntimeError(
            f"{bundle_name}: "
            "not FSTS"
        )

    files = u32(
        bundle,
        4
    )

    info_off = u32(
        bundle,
        8
    )

    names_off = u32(
        bundle,
        12
    )

    names_size = u32(
        bundle,
        16
    )

    if (
        info_off
        + files * 16
        > len(bundle)
    ):

        raise RuntimeError(
            f"{bundle_name}: "
            "info table outside"
        )

    if (
        names_off
        + names_size
        > len(bundle)
    ):

        raise RuntimeError(
            f"{bundle_name}: "
            "name table outside"
        )

    names = bundle[
        names_off:
        names_off + names_size
    ]

    rows = []

    for i in range(files):

        off = (
            info_off
            + i * 16
        )

        (
            name_off,
            file_off,
            size,
            zsize,
        ) = struct.unpack_from(
            "<4I",
            bundle,
            off
        )

        name = cstring(
            names,
            name_off
        )

        # Same rule as macross_fsts.bms:
        # zsize == 0       -> raw SIZE
        # zsize >= size    -> raw SIZE
        # zsize < size     -> compressed ZSIZE
        if (
            zsize == 0
            or zsize >= size
        ):

            stored_len = size
            compressed = False

        else:

            stored_len = zsize
            compressed = True

        if (
            file_off
            + stored_len
            > len(bundle)
        ):

            raise RuntimeError(
                f"{bundle_name}: "
                f"member {i} outside "
                f"0x{file_off:X}+"
                f"0x{stored_len:X}"
            )

        stored = bundle[
            file_off:
            file_off + stored_len
        ]

        if compressed:

            (
                decoded,
                codec,
                decode_error
            ) = decode_compressed(
                stored
            )

        else:

            decoded = stored
            codec = "raw"
            decode_error = ""

        rows.append({
            "member_index":
                i,

            "name":
                name,

            "basename":
                basename(name),

            "offset":
                file_off,

            "size":
                size,

            "zsize":
                zsize,

            "stored_size":
                stored_len,

            "compressed":
                compressed,

            "codec":
                codec,

            "decode_error":
                decode_error,

            "stored_sha256":
                sha256(stored),

            "decoded_sha256":
                sha256(decoded),

            "decoded_size":
                len(decoded),

            "stored":
                stored,

            "decoded":
                decoded,
        })

    return {
        "files":
            files,

        "info_off":
            info_off,

        "names_off":
            names_off,

        "names_size":
            names_size,

        "members":
            rows,
    }


# ============================================================
# Translation classifier
# ============================================================

ui_re = re.compile(
    r"(title|select|menu|mode|"
    r"option|setting|skill|name|"
    r"window|message|dialog|"
    r"story|guide|help|char)",
    re.I
)


def is_translation_name(name):

    low = name.lower()

    if low.endswith(".tbl"):
        return True

    if (
        low.startswith("text")
        and low.endswith(".bin")
    ):
        return True

    if (
        ui_re.search(low)
        and low.endswith(
            (
                ".ccs",
                ".bin",
                ".tbl",
            )
        )
    ):
        return True

    return False


# ============================================================
# Load indexes
# ============================================================

kr_pidx = parse_pidx(
    KR_IDX.read_bytes()
)

us_pidx = parse_pidx(
    read_embedded_pidx(
        US_DAT
    )
)

kr_primary, kr_by_base = (
    build_primary(
        KR_DAT,
        kr_pidx["primary"]
    )
)

us_primary, us_by_base = (
    build_primary(
        US_DAT,
        us_pidx["primary"]
    )
)


regions = {
    "KR": {
        "dat":
            KR_DAT,

        "offset2":
            kr_pidx["offset2"],

        "primary":
            kr_primary,

        "primary_by_base":
            kr_by_base,
    },

    "US": {
        "dat":
            US_DAT,

        "offset2":
            us_pidx["offset2"],

        "primary":
            us_primary,

        "primary_by_base":
            us_by_base,
    },
}


# ============================================================
# Parse every FSTS
# ============================================================

bundle_rows = []
member_rows = []
copy_rows = []

errors = []

selected_share_names = {
    "event000.tbl",
    "event001.tbl",
    "event100.tbl",
    "quiz1.tbl",
    "quiz2.tbl",
    "text.bin",
    "text_f.bin",
    "text_g.bin",
    "text_i.bin",
    "text_s.bin",
    "title.ccs",
    "modesel1.ccs",
    "charsel1.ccs",
    "charaselect.ccs",
    "mapsel1.ccs",
    "setting.ccs",
    "option.ccs",
    "mcmn.ccs",
}

for region, robj in (
    regions.items()
):

    dat = robj["dat"]

    by_base = (
        robj[
            "primary_by_base"
        ]
    )

    dat_size = (
        dat.stat().st_size
    )

    with dat.open("rb") as f:

        for off2 in (
            robj["offset2"]
        ):

            bundle_name = (
                off2["name"]
            )

            start = (
                off2["file_off"]
            )

            size = (
                off2["file_size"]
            )

            if (
                start + size
                > dat_size
            ):

                errors.append(
                    f"{region} "
                    f"{bundle_name}: "
                    "FSTS outside DAT"
                )

                continue

            f.seek(start)

            bundle = f.read(size)

            try:

                parsed = parse_fsts(
                    bundle,
                    bundle_name
                )

            except Exception as ex:

                errors.append(
                    f"{region} "
                    f"{bundle_name}: "
                    f"{ex}"
                )

                continue

            primary_matches = 0
            exact_matches = 0
            translation_members = 0
            unknown_codec = 0

            for m in (
                parsed["members"]
            ):

                candidates = (
                    by_base.get(
                        m["basename"],
                        []
                    )
                )

                exact = []

                for pe in candidates:

                    if (
                        pe[
                            "decoded_sha256"
                        ]
                        ==
                        m[
                            "decoded_sha256"
                        ]
                    ):

                        exact.append(pe)

                if candidates:
                    primary_matches += 1

                if exact:
                    exact_matches += 1

                if is_translation_name(
                    m["basename"]
                ):
                    translation_members += 1

                if (
                    m["codec"]
                    ==
                    "UNKNOWN_COMPRESSED"
                ):
                    unknown_codec += 1

                member_row = {
                    "region":
                        region,

                    "bundle_index":
                        off2["index"],

                    "bundle_name":
                        bundle_name,

                    "bundle_file_off":
                        f"0x{start:X}",

                    "bundle_size":
                        size,

                    "member_index":
                        m["member_index"],

                    "member_name":
                        m["name"],

                    "basename":
                        m["basename"],

                    "member_offset":
                        f'0x{m["offset"]:X}',

                    "size":
                        m["size"],

                    "zsize":
                        m["zsize"],

                    "stored_size":
                        m["stored_size"],

                    "decoded_size":
                        m["decoded_size"],

                    "codec":
                        m["codec"],

                    "decode_error":
                        m["decode_error"],

                    "decoded_sha256":
                        m[
                            "decoded_sha256"
                        ],

                    "primary_matches":
                        len(candidates),

                    "primary_exact_matches":
                        len(exact),

                    "same_as_primary":
                        bool(exact),

                    "primary_entries":
                        ",".join(
                            str(x["entry"])
                            for x in candidates
                        ),

                    "translation_candidate":
                        is_translation_name(
                            m["basename"]
                        ),
                }

                member_rows.append(
                    member_row
                )

                if candidates:

                    copy_rows.append(
                        member_row
                    )

                # --------------------------------------------
                # Share strategic files and any non-identical
                # translation duplicates.
                # --------------------------------------------

                should_share = False

                if (
                    m["basename"]
                    in selected_share_names
                ):
                    should_share = True

                if (
                    is_translation_name(
                        m["basename"]
                    )
                    and candidates
                    and not exact
                ):
                    should_share = True

                if (
                    should_share
                    and len(
                        m["decoded"]
                    ) <= 4_000_000
                ):

                    fn = (
                        f"{region}"
                        f"__FSTS_"
                        f"{off2['index']:03d}"
                        f"_{safe_name(bundle_name)}"
                        f"__M"
                        f"{m['member_index']:03d}"
                        f"__{safe_name(m['basename'])}"
                    )

                    (
                        SHARE / fn
                    ).write_bytes(
                        m["decoded"]
                    )

            bundle_rows.append({
                "region":
                    region,

                "bundle_index":
                    off2["index"],

                "bundle_name":
                    bundle_name,

                "file_off":
                    f"0x{start:X}",

                "bundle_size":
                    size,

                "members":
                    parsed["files"],

                "info_off":
                    f'0x{parsed["info_off"]:X}',

                "names_off":
                    f'0x{parsed["names_off"]:X}',

                "names_size":
                    parsed["names_size"],

                "members_matching_primary":
                    primary_matches,

                "members_exact_primary":
                    exact_matches,

                "translation_members":
                    translation_members,

                "unknown_codec_members":
                    unknown_codec,
            })


# ============================================================
# Primary coverage
# ============================================================

copies_by_key = defaultdict(
    list
)

for r in copy_rows:

    copies_by_key[
        (
            r["region"],
            r["basename"]
        )
    ].append(r)


coverage_rows = []

for region, robj in (
    regions.items()
):

    for p in (
        robj["primary"]
    ):

        if not is_translation_name(
            p["name"]
        ):
            continue

        copies = copies_by_key.get(
            (
                region,
                p["name"].lower()
            ),
            []
        )

        exact = [
            x
            for x in copies
            if x["same_as_primary"]
        ]

        nonexact = [
            x
            for x in copies
            if not x["same_as_primary"]
        ]

        coverage_rows.append({
            "region":
                region,

            "primary_entry":
                p["entry"],

            "primary_name":
                p["name"],

            "primary_decoded_size":
                len(
                    p["decoded"]
                ),

            "primary_sha256":
                p[
                    "decoded_sha256"
                ],

            "fsts_copy_count":
                len(copies),

            "fsts_exact_count":
                len(exact),

            "fsts_nonexact_count":
                len(nonexact),

            "bundles":
                ",".join(
                    sorted(
                        {
                            x[
                                "bundle_name"
                            ]
                            for x in copies
                        }
                    )
                ),
        })


# ============================================================
# Important translation map
# ============================================================

translation_map = [
    r
    for r in member_rows
    if r[
        "translation_candidate"
    ]
]


nonidentical = [
    r
    for r in translation_map
    if (
        r["primary_matches"]
        and not r["same_as_primary"]
    )
]


# ============================================================
# Event-specific summary
# ============================================================

event_rows = []

event_re = re.compile(
    r"^event\d+\.tbl$",
    re.I
)

for region, robj in (
    regions.items()
):

    for p in robj["primary"]:

        low = p[
            "name"
        ].lower()

        if not event_re.fullmatch(
            low
        ):
            continue

        copies = copies_by_key.get(
            (
                region,
                low
            ),
            []
        )

        event_rows.append({
            "region":
                region,

            "event_file":
                p["name"],

            "primary_entry":
                p["entry"],

            "copies":
                len(copies),

            "exact_copies":
                sum(
                    1
                    for x in copies
                    if x[
                        "same_as_primary"
                    ]
                ),

            "nonexact_copies":
                sum(
                    1
                    for x in copies
                    if not x[
                        "same_as_primary"
                    ]
                ),

            "bundles":
                ",".join(
                    sorted(
                        {
                            x["bundle_name"]
                            for x in copies
                        }
                    )
                ),
        })


# ============================================================
# Reports
# ============================================================

write_tsv(
    OUT / "fsts_bundle_summary.tsv",
    bundle_rows,
    [
        "region",
        "bundle_index",
        "bundle_name",
        "file_off",
        "bundle_size",
        "members",
        "info_off",
        "names_off",
        "names_size",
        "members_matching_primary",
        "members_exact_primary",
        "translation_members",
        "unknown_codec_members",
    ]
)


member_fields = [
    "region",
    "bundle_index",
    "bundle_name",
    "bundle_file_off",
    "bundle_size",
    "member_index",
    "member_name",
    "basename",
    "member_offset",
    "size",
    "zsize",
    "stored_size",
    "decoded_size",
    "codec",
    "decode_error",
    "decoded_sha256",
    "primary_matches",
    "primary_exact_matches",
    "same_as_primary",
    "primary_entries",
    "translation_candidate",
]


write_tsv(
    OUT / "fsts_members.tsv",
    member_rows,
    member_fields
)


write_tsv(
    OUT / "primary_fsts_copy_map.tsv",
    copy_rows,
    member_fields
)


write_tsv(
    OUT / "translation_fsts_map.tsv",
    translation_map,
    member_fields
)


write_tsv(
    OUT / "nonidentical_translation_copies.tsv",
    nonidentical,
    member_fields
)


write_tsv(
    OUT / "translation_primary_coverage.tsv",
    coverage_rows,
    [
        "region",
        "primary_entry",
        "primary_name",
        "primary_decoded_size",
        "primary_sha256",
        "fsts_copy_count",
        "fsts_exact_count",
        "fsts_nonexact_count",
        "bundles",
    ]
)


write_tsv(
    OUT / "event_fsts_coverage.tsv",
    event_rows,
    [
        "region",
        "event_file",
        "primary_entry",
        "copies",
        "exact_copies",
        "nonexact_copies",
        "bundles",
    ]
)


# ============================================================
# Notes
# ============================================================

notes = r"""Naruto PSP FSTS format

Validated against macross_fsts.bms:

Header:
  +0x00  "FSTS"
  +0x04  u32 files
  +0x08  u32 info_off
  +0x0C  u32 names_off
  +0x10  u32 names_size

Each file record is 16 bytes:
  +0x00  u32 name_off
  +0x04  u32 file_offset
  +0x08  u32 size
  +0x0C  u32 zsize

Storage rule used by the original QuickBMS script:
  zsize == 0    -> read SIZE bytes raw
  zsize >= size -> read SIZE bytes raw
  zsize < size  -> read ZSIZE bytes and decompress

Known compressed member formats:
  " 3;0"
  " 3;1"
  "segs"
  zlib / deflate

This stage compares DECOMPRESSED member hashes against
DECOMPRESSED primary PIDX files by basename.
"""

(
    OUT / "fsts_format_notes.txt"
).write_text(
    notes,
    encoding="utf-8"
)


# ============================================================
# Summary
# ============================================================

codec_counts = Counter(
    r["codec"]
    for r in member_rows
)

kr_bundles = [
    x
    for x in bundle_rows
    if x["region"] == "KR"
]

us_bundles = [
    x
    for x in bundle_rows
    if x["region"] == "US"
]

event_with_copies = [
    x
    for x in event_rows
    if x["copies"] > 0
]

event_nonexact = [
    x
    for x in event_rows
    if x[
        "nonexact_copies"
    ] > 0
]

coverage_with_copies = [
    x
    for x in coverage_rows
    if x[
        "fsts_copy_count"
    ] > 0
]

summary = (
    OUT / "stage11_summary.txt"
)

with summary.open(
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "Naruto PSP Stage 11\n"
    )

    f.write(
        "=" * 72
        + "\n\n"
    )

    f.write(
        f"KR FSTS bundles: "
        f"{len(kr_bundles)}\n"
    )

    f.write(
        f"US FSTS bundles: "
        f"{len(us_bundles)}\n"
    )

    f.write(
        f"FSTS members total: "
        f"{len(member_rows)}\n"
    )

    f.write(
        f"Members matching a primary basename: "
        f"{len(copy_rows)}\n"
    )

    f.write(
        f"Exact decompressed primary copies: "
        f"{sum(1 for x in copy_rows if x['same_as_primary'])}\n"
    )

    f.write(
        f"Non-identical basename matches: "
        f"{sum(1 for x in copy_rows if not x['same_as_primary'])}\n"
    )

    f.write("\n")

    f.write(
        f"Translation-like FSTS members: "
        f"{len(translation_map)}\n"
    )

    f.write(
        f"Non-identical translation copies: "
        f"{len(nonidentical)}\n"
    )

    f.write(
        f"Primary translation resources "
        f"with >=1 FSTS copy: "
        f"{len(coverage_with_copies)}"
        f"/{len(coverage_rows)}\n"
    )

    f.write("\n")

    f.write(
        f"Event TBL resources: "
        f"{len(event_rows)}\n"
    )

    f.write(
        f"Event TBL with FSTS copies: "
        f"{len(event_with_copies)}\n"
    )

    f.write(
        f"Event TBL with non-identical "
        f"FSTS copies: "
        f"{len(event_nonexact)}\n"
    )

    f.write("\nCodec countLOCAL_PATH")

    for codec, count in (
        codec_counts.most_common()
    ):

        f.write(
            f"  {codec}: "
            f"{count}\n"
        )

    f.write("\n")

    f.write(
        f"Parse/decode errors: "
        f"{len(errors)}\n"
    )


if errors:

    (
        OUT / "stage11_errors.txt"
    ).write_text(
        "\n".join(errors),
        encoding="utf-8"
    )

    print()
    print("Errors:", len(errors))

    for e in errors[:20]:
        print(e)

    sys.exit(2)


print()
print("=" * 72)
print("STAGE 11 COMPLETE")
print("=" * 72)

print(
    "KR bundles:",
    len(kr_bundles)
)

print(
    "US bundles:",
    len(us_bundles)
)

print(
    "FSTS members:",
    len(member_rows)
)

print(
    "Primary basename matches:",
    len(copy_rows)
)

print(
    "Exact copies:",
    sum(
        1
        for x in copy_rows
        if x["same_as_primary"]
    )
)

print(
    "Translation FSTS:",
    len(translation_map)
)

print(
    "Events with copies:",
    len(event_with_copies),
    "/",
    len(event_rows)
)

print(
    "Output:",
    OUT
)
