from pathlib import Path, PurePosixPath
from collections import defaultdict
import argparse
import csv
import hashlib
import shutil
import struct
import sys
import traceback
import zlib


ALIGN = 0x800


def u16be(data, off):
    return struct.unpack_from(">H", data, off)[0]


def u32be(data, off):
    return struct.unpack_from(">I", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def p32(data, off, value):
    struct.pack_into("<I", data, off, value)


def align_up(value, alignment=ALIGN):
    return (
        value
        + alignment - 1
    ) & ~(alignment - 1)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)

            if not b:
                break

            h.update(b)

    return h.hexdigest()


def cstring(data, off):
    if off < 0 or off >= len(data):
        return ""

    end = data.find(b"\0", off)

    if end < 0:
        end = len(data)

    return data[off:end].decode(
        "ascii",
        errors="replace"
    )


def basename(name):
    return PurePosixPath(
        name.replace("\\", "/")
    ).name.lower()


def write_tsv(path, rows, fields):
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

def read_embedded_index(dat_path):
    with dat_path.open("rb") as f:
        head = f.read(0x50)

        if head[:5] != b"PIDX0":
            raise RuntimeError(
                f"PIDX0 없음: {dat_path}"
            )

        names_off = u32(head, 0x20)
        names_size = u32(head, 0x24)

        total = names_off + names_size

        f.seek(0)

        return f.read(total)


def parse_pidx(blob, label):
    if blob[:5] != b"PIDX0":
        raise RuntimeError(
            f"{label}: invalid PIDX0"
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

    if info_off + files * 24 != offset2:
        raise RuntimeError(
            f"{label}: "
            "primary table size invalid"
        )

    if names_off + names_size > len(blob):
        raise RuntimeError(
            f"{label}: "
            "name table outside index"
        )

    names = blob[
        names_off:
        names_off + names_size
    ]

    primary = []

    for i in range(files):
        rec = info_off + i * 24

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
            rec
        )

        primary.append({
            "entry": i,
            "record_off": rec,

            "is_folder": is_folder,

            "name": cstring(
                names,
                name_off
            ),

            "pack_name": cstring(
                names,
                pack_name_off
            ),

            "offset": file_off,
            "size": size,
            "zsize": zsize,
        })

    block = blob[
        offset2:
        offset2 + offset2_size
    ]

    count = u32(block, 0)

    offset2_rows = []

    for i in range(count):
        ptr = u32(
            block,
            4 + i * 4
        )

        if ptr + 16 > len(block):
            raise RuntimeError(
                f"{label}: "
                f"bad OFFSET2 pointer "
                f"{i}: 0x{ptr:X}"
            )

        rec_abs = offset2 + ptr

        (
            name_off,
            pack_name_off,
            file_off,
            file_size,
        ) = struct.unpack_from(
            "<4I",
            blob,
            rec_abs
        )

        offset2_rows.append({
            "index": i,

            "pointer": ptr,
            "record_abs": rec_abs,

            "name": cstring(
                names,
                name_off
            ),

            "pack_name": cstring(
                names,
                pack_name_off
            ),

            "file_off": file_off,
            "file_size": file_size,
        })

    return {
        "blob": blob,

        "info_off": info_off,
        "files": files,

        "offset2": offset2,
        "offset2_size": offset2_size,

        "names_off": names_off,
        "names_size": names_size,

        "index_end": (
            names_off
            + names_size
        ),

        "primary": primary,

        "offset2_rows":
            offset2_rows,
    }


# ============================================================
# Naruto 3;x
# ============================================================

def encode_3_0(data):
    return (
        b" 3;0"
        + struct.pack(
            "<I",
            len(data)
        )
        + bytes(
            b ^ 0x72
            for b in data
        )
    )


def decode_3x(blob):
    if (
        len(blob) < 8
        or blob[:3] != b" 3;"
    ):
        raise RuntimeError(
            "not a 3;x container"
        )

    typ = blob[3]
    expected = u32(blob, 4)

    # --------------------------------------------------------
    # 3;0
    # --------------------------------------------------------

    if typ == ord("0"):
        out = bytes(
            b ^ 0x72
            for b in blob[8:]
        )

        if len(out) != expected:
            raise RuntimeError(
                f"3;0 size mismatch: "
                f"{len(out)} != "
                f"{expected}"
            )

        return out

    # --------------------------------------------------------
    # 3;1
    # --------------------------------------------------------

    if typ != ord("1"):
        raise RuntimeError(
            f"unknown 3;x type "
            f"0x{typ:02X}"
        )

    window = bytearray(0x1000)

    ring = 0xFEE
    src = 8
    flags = 0

    out = bytearray()

    while (
        src < len(blob)
        and len(out) < expected
    ):
        flags >>= 1

        if (flags & 0x100) == 0:
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

            c = blob[src] ^ 0x72
            src += 1

            out.append(c)

            window[ring] = c
            ring = (ring + 1) & 0xFFF

        else:
            if src + 1 >= len(blob):
                break

            b1 = blob[src] ^ 0x72
            b2 = blob[src + 1] ^ 0x72

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
                ring = (ring + 1) & 0xFFF

                if len(out) >= expected:
                    break

    if len(out) != expected:
        raise RuntimeError(
            f"3;1 size mismatch: "
            f"{len(out)} != "
            f"{expected}"
        )

    return bytes(out)


# ============================================================
# SEGS / other compressed FSTS members
# ============================================================

def decode_segs(blob):
    if (
        len(blob) < 16
        or blob[:4] != b"segs"
    ):
        raise RuntimeError(
            "not SEGS"
        )

    chunks = u16be(blob, 6)
    full_size = u32be(blob, 8)

    desc = []

    for i in range(chunks):
        o = 16 + i * 8

        zsize = u16be(blob, o)
        size = u16be(blob, o + 2)
        off = u32be(blob, o + 4) - 1

        desc.append(
            (zsize, size, off)
        )

    base2 = (
        16
        + chunks * 8
    )

    workaround = (
        bool(desc)
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

        real_off = (
            base2 + off
            if workaround
            else off
        )

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
                "SEGS chunk size mismatch"
            )

        out.extend(dec)

    if len(out) != full_size:
        raise RuntimeError(
            f"SEGS size mismatch: "
            f"{len(out)} != "
            f"{full_size}"
        )

    return bytes(out)


def decode_stored(
    stored,
    size,
    zsize
):
    if stored[:3] == b" 3;":
        return decode_3x(stored)

    if stored[:4] == b"segs":
        return decode_segs(stored)

    if zsize and zsize < size:
        try:
            return zlib.decompress(stored)
        except Exception:
            pass

        try:
            return zlib.decompress(
                stored,
                -15
            )
        except Exception:
            pass

        raise RuntimeError(
            "unknown compressed member"
        )

    return stored


# ============================================================
# FSTS
# ============================================================

def parse_fsts(bundle, label):
    if (
        len(bundle) < 0x20
        or bundle[:4] != b"FSTS"
    ):
        raise RuntimeError(
            f"{label}: invalid FSTS"
        )

    files = u32(bundle, 4)
    info_off = u32(bundle, 8)
    names_off = u32(bundle, 12)
    names_size = u32(bundle, 16)

    if (
        info_off
        + files * 16
        > len(bundle)
    ):
        raise RuntimeError(
            f"{label}: "
            "FSTS info outside"
        )

    if (
        names_off
        + names_size
        > len(bundle)
    ):
        raise RuntimeError(
            f"{label}: "
            "FSTS names outside"
        )

    names = bundle[
        names_off:
        names_off + names_size
    ]

    members = []

    for i in range(files):
        rec = (
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
            rec
        )

        stored_size = (
            zsize
            if zsize
            else size
        )

        if (
            file_off
            + stored_size
            > len(bundle)
        ):
            raise RuntimeError(
                f"{label}: "
                f"member {i} outside"
            )

        members.append({
            "index": i,
            "record_off": rec,

            "name": cstring(
                names,
                name_off
            ),

            "basename":
                basename(
                    cstring(
                        names,
                        name_off
                    )
                ),

            "offset": file_off,
            "size": size,
            "zsize": zsize,

            "stored_size":
                stored_size,

            "stored":
                bundle[
                    file_off:
                    file_off
                    + stored_size
                ],
        })

    return {
        "files": files,

        "info_off": info_off,

        "names_off": names_off,
        "names_size": names_size,

        "metadata_end": (
            names_off
            + names_size
        ),

        "members": members,
    }


def rebuild_fsts(
    bundle,
    label,
    replacements
):
    parsed = parse_fsts(
        bundle,
        label
    )

    # Empty FSTS
    if parsed["files"] == 0:
        return (
            bytes(bundle),
            []
        )

    member_payloads = {}
    changes = []

    # --------------------------------------------------------
    # Decide changed member payloads first.
    # --------------------------------------------------------

    for m in parsed["members"]:
        target = replacements.get(
            m["basename"]
        )

        if target is None:
            member_payloads[
                m["index"]
            ] = {
                "stored":
                    m["stored"],

                "size":
                    m["size"],

                "zsize":
                    m["zsize"],

                "changed":
                    False,
            }

            continue

        original_decoded = (
            decode_stored(
                m["stored"],
                m["size"],
                m["zsize"]
            )
        )

        original_hash = sha256(
            original_decoded
        )

        if (
            original_hash
            != target[
                "original_sha256"
            ]
        ):
            raise RuntimeError(
                f"{label}: "
                f"basename collision for "
                f"{m['name']}; "
                "FSTS copy differs from "
                "primary resource"
            )

        encoded = encode_3_0(
            target["new_decoded"]
        )

        member_payloads[
            m["index"]
        ] = {
            "stored":
                encoded,

            "size":
                len(
                    target[
                        "new_decoded"
                    ]
                ),

            "zsize":
                len(encoded),

            "changed":
                True,
        }

        changes.append({
            "bundle": label,
            "member_index":
                m["index"],

            "member_name":
                m["name"],

            "basename":
                m["basename"],

            "old_size":
                m["size"],

            "new_size":
                len(
                    target[
                        "new_decoded"
                    ]
                ),

            "old_zsize":
                m["zsize"],

            "new_zsize":
                len(encoded),
        })

    # No relevant copies -> byte-identical bundle.
    if not changes:
        return (
            bytes(bundle),
            []
        )

    # --------------------------------------------------------
    # Rebuild metadata + aligned payloads.
    # --------------------------------------------------------

    out = bytearray(
        bundle[
            :parsed["metadata_end"]
        ]
    )

    cursor = align_up(
        parsed["metadata_end"]
    )

    if len(out) < cursor:
        out.extend(
            b"\0"
            * (
                cursor
                - len(out)
            )
        )

    ordered = sorted(
        parsed["members"],
        key=lambda x:
            x["offset"]
    )

    for m in ordered:
        payload = member_payloads[
            m["index"]
        ]

        new_off = align_up(
            cursor
        )

        if len(out) < new_off:
            out.extend(
                b"\0"
                * (
                    new_off
                    - len(out)
                )
            )

        # offset
        p32(
            out,
            m["record_off"] + 4,
            new_off
        )

        # decoded size
        p32(
            out,
            m["record_off"] + 8,
            payload["size"]
        )

        # stored size
        p32(
            out,
            m["record_off"] + 12,
            payload["zsize"]
        )

        out.extend(
            payload["stored"]
        )

        cursor = (
            new_off
            + len(
                payload["stored"]
            )
        )

    final_size = align_up(
        len(out)
    )

    if len(out) < final_size:
        out.extend(
            b"\0"
            * (
                final_size
                - len(out)
            )
        )

    return (
        bytes(out),
        changes
    )


# ============================================================
# Range helpers
# ============================================================

def copy_range(
    source,
    dest,
    offset,
    size
):
    source.seek(offset)

    remain = size

    while remain:
        chunk = source.read(
            min(
                remain,
                1024 * 1024
            )
        )

        if not chunk:
            raise RuntimeError(
                "unexpected EOF"
            )

        dest.write(chunk)
        remain -= len(chunk)


def pad_to(f, target):
    current = f.tell()

    if current > target:
        raise RuntimeError(
            f"output passed target "
            f"0x{current:X} > "
            f"0x{target:X}"
        )

    remain = target - current
    zero = b"\0" * (1024 * 1024)

    while remain:
        n = min(
            remain,
            len(zero)
        )

        f.write(
            zero[:n]
        )

        remain -= n


def read_primary_stored(
    dat,
    entry
):
    stored_size = (
        entry["zsize"]
        if entry["zsize"]
        else entry["size"]
    )

    with dat.open("rb") as f:
        f.seek(
            entry["offset"]
        )

        raw = f.read(
            stored_size
        )

    if len(raw) != stored_size:
        raise RuntimeError(
            f"short primary read: "
            f"{entry['name']}"
        )

    return raw


def decode_primary(
    dat,
    entry
):
    stored = read_primary_stored(
        dat,
        entry
    )

    return decode_stored(
        stored,
        entry["size"],
        entry["zsize"]
    )


# ============================================================
# Replacement preparation
# ============================================================

def resolve_primary_target(
    idx,
    target_name
):
    low = target_name.lower()

    actual = [
        x
        for x in idx["primary"]
        if x["is_folder"] == 0
    ]

    exact = [
        x
        for x in actual
        if x["name"].lower() == low
    ]

    if len(exact) == 1:
        return exact[0]

    by_base = [
        x
        for x in actual
        if basename(
            x["name"]
        ) == basename(low)
    ]

    if len(by_base) == 1:
        return by_base[0]

    raise RuntimeError(
        f"Primary target resolution failed "
        f"for {target_name!r}: "
        f"exact={len(exact)}, "
        f"basename={len(by_base)}"
    )


def build_stage14_test(
    dat,
    idx,
    output
):
    entry = resolve_primary_target(
        idx,
        "event000.tbl"
    )

    original = decode_primary(
        dat,
        entry
    )

    prefix = (
        b"MSG =SIK,"
        b"s_a01_000,"
    )

    pos = original.find(
        prefix
    )

    if pos < 0:
        raise RuntimeError(
            "event000.tbl에서 "
            "s_a01_000을 찾지 못했습니다."
        )

    text_start = (
        pos + len(prefix)
    )

    newline = original.find(
        b"\n",
        text_start
    )

    if newline < 0:
        raise RuntimeError(
            "첫 MSG 행 끝을 찾지 못했습니다."
        )

    text_end = newline

    if (
        text_end > text_start
        and original[
            text_end - 1
        ] == 0x0D
    ):
        text_end -= 1

    old_message = original[
        text_start:text_end
    ]

    new_message = (
        b"STAGE14 PATCH TEST"
    )

    patched = (
        original[:text_start]
        + new_message
        + original[text_end:]
    )

    original_file = (
        output
        / "event000_original.tbl"
    )

    patched_file = (
        output
        / "event000_patched.tbl"
    )

    original_file.write_bytes(
        original
    )

    patched_file.write_bytes(
        patched
    )

    try:
        old_text = old_message.decode(
            "cp932"
        )
    except Exception:
        old_text = old_message.hex()

    return {
        "name":
            "event000.tbl",

        "path":
            patched_file,

        "old_message":
            old_text,

        "new_message":
            new_message.decode(
                "ascii"
            ),
    }


# ============================================================
# Build patched KR archive
# ============================================================

def patch_kr(
    root,
    output,
    replacement_specs
):
    kr_usr = (
        root
        / "kr_extracted"
        / "PSP_GAME"
        / "USRDIR"
    )

    source_dat = (
        kr_usr
        / "naruto.dat"
    )

    source_idx = (
        kr_usr
        / "naruto.idx"
    )

    if not source_dat.exists():
        raise RuntimeError(
            f"KR DAT 없음: {source_dat}"
        )

    if not source_idx.exists():
        raise RuntimeError(
            f"KR IDX 없음: {source_idx}"
        )

    embedded_blob = (
        read_embedded_index(
            source_dat
        )
    )

    external_blob = (
        source_idx.read_bytes()
    )

    embedded = parse_pidx(
        embedded_blob,
        "KR_EMBEDDED"
    )

    external = parse_pidx(
        external_blob,
        "KR_EXTERNAL"
    )

    # Stage10/13 invariant.
    if (
        len(embedded["primary"])
        != len(external["primary"])
    ):
        raise RuntimeError(
            "embedded/external primary "
            "count mismatch"
        )

    if (
        len(
            embedded[
                "offset2_rows"
            ]
        )
        != len(
            external[
                "offset2_rows"
            ]
        )
    ):
        raise RuntimeError(
            "embedded/external OFFSET2 "
            "count mismatch"
        )

    # --------------------------------------------------------
    # Resolve replacements against primary files.
    # --------------------------------------------------------

    replacements = {}

    manifest_rows = []

    for spec in replacement_specs:
        target_name = spec["name"]
        new_path = spec["path"]

        if not new_path.exists():
            raise RuntimeError(
                f"replacement missing: "
                f"{new_path}"
            )

        entry = resolve_primary_target(
            embedded,
            target_name
        )

        key = basename(
            entry["name"]
        )

        if key in replacements:
            raise RuntimeError(
                f"duplicate replacement "
                f"for {key}"
            )

        original_decoded = (
            decode_primary(
                source_dat,
                entry
            )
        )

        new_decoded = (
            new_path.read_bytes()
        )

        encoded = encode_3_0(
            new_decoded
        )

        replacements[key] = {
            "target_name":
                entry["name"],

            "entry":
                entry["entry"],

            "original_sha256":
                sha256(
                    original_decoded
                ),

            "new_sha256":
                sha256(
                    new_decoded
                ),

            "original_decoded":
                original_decoded,

            "new_decoded":
                new_decoded,

            "new_stored":
                encoded,

            "new_size":
                len(new_decoded),

            "new_zsize":
                len(encoded),

            "source_file":
                str(new_path),
        }

        manifest_rows.append({
            "target":
                entry["name"],

            "entry":
                entry["entry"],

            "replacement_file":
                str(new_path),

            "old_decoded_size":
                len(
                    original_decoded
                ),

            "new_decoded_size":
                len(
                    new_decoded
                ),

            "old_sha256":
                sha256(
                    original_decoded
                ),

            "new_sha256":
                sha256(
                    new_decoded
                ),

            "new_codec":
                "3;0",

            "new_stored_size":
                len(encoded),
        })

    # --------------------------------------------------------
    # Scan/rebuild FSTS.
    # Only bundles containing an exact copy are changed.
    # --------------------------------------------------------

    tmp = (
        output
        / "_fsts_tmp"
    )

    if tmp.exists():
        shutil.rmtree(tmp)

    tmp.mkdir(
        parents=True
    )

    off2_sorted = sorted(
        embedded["offset2_rows"],
        key=lambda x:
            x["file_off"]
    )

    rebuilt_fsts = {}

    fsts_patch_rows = []

    expected_copy_counts = defaultdict(
        int
    )

    with source_dat.open("rb") as f:
        total = len(
            off2_sorted
        )

        for number, rec in enumerate(
            off2_sorted,
            1
        ):
            f.seek(
                rec["file_off"]
            )

            bundle = f.read(
                rec["file_size"]
            )

            if len(bundle) != rec["file_size"]:
                raise RuntimeError(
                    f"short FSTS read: "
                    f"{rec['name']}"
                )

            rebuilt, changes = (
                rebuild_fsts(
                    bundle,
                    rec["name"],
                    replacements
                )
            )

            if changes:
                path = (
                    tmp
                    / (
                        f"{rec['index']:04d}"
                        f".fsts"
                    )
                )

                path.write_bytes(
                    rebuilt
                )

                rebuilt_fsts[
                    rec["index"]
                ] = {
                    "path":
                        path,

                    "new_size":
                        len(rebuilt),

                    "changed":
                        True,
                }

                for c in changes:
                    expected_copy_counts[
                        c["basename"]
                    ] += 1

                    fsts_patch_rows.append({
                        "bundle_index":
                            rec["index"],

                        "bundle_name":
                            rec["name"],

                        **c,
                    })

            else:
                rebuilt_fsts[
                    rec["index"]
                ] = {
                    "path": None,

                    "new_size":
                        rec["file_size"],

                    "changed":
                        False,
                }

            if (
                number % 25 == 0
                or number == total
            ):
                print(
                    f"[FSTS scan] "
                    f"{number}/{total}"
                )

    # Every replacement should have at least one known FSTS
    # copy for resources observed in previous stages.
    for key in replacements:
        print(
            f"[FSTS copies] "
            f"{key}: "
            f"{expected_copy_counts[key]}"
        )

    # --------------------------------------------------------
    # Primary plan
    # --------------------------------------------------------

    actual_primary = [
        e
        for e in embedded["primary"]
        if e["is_folder"] == 0
    ]

    primary_sorted = sorted(
        actual_primary,
        key=lambda x:
            x["offset"]
    )

    cursor = align_up(
        embedded["index_end"]
    )

    primary_plan = []

    replacements_by_entry = {
        v["entry"]: v
        for v in replacements.values()
    }

    for e in primary_sorted:
        replacement = (
            replacements_by_entry.get(
                e["entry"]
            )
        )

        if replacement is not None:
            stored_size = (
                replacement[
                    "new_zsize"
                ]
            )

            new_size = (
                replacement[
                    "new_size"
                ]
            )

            new_zsize = (
                replacement[
                    "new_zsize"
                ]
            )

            changed = True

        else:
            stored_size = (
                e["zsize"]
                if e["zsize"]
                else e["size"]
            )

            new_size = e["size"]
            new_zsize = e["zsize"]
            changed = False

        new_off = align_up(
            cursor
        )

        primary_plan.append({
            "entry":
                e["entry"],

            "name":
                e["name"],

            "old_offset":
                e["offset"],

            "new_offset":
                new_off,

            "old_size":
                e["size"],

            "new_size":
                new_size,

            "old_zsize":
                e["zsize"],

            "new_zsize":
                new_zsize,

            "stored_size":
                stored_size,

            "changed":
                changed,
        })

        cursor = (
            new_off
            + stored_size
        )

    cursor = align_up(
        cursor
    )

    # --------------------------------------------------------
    # OFFSET2 / FSTS plan
    # --------------------------------------------------------

    off2_plan = []

    for rec in off2_sorted:
        robj = rebuilt_fsts[
            rec["index"]
        ]

        new_off = align_up(
            cursor
        )

        off2_plan.append({
            "index":
                rec["index"],

            "name":
                rec["name"],

            "old_offset":
                rec["file_off"],

            "new_offset":
                new_off,

            "old_size":
                rec["file_size"],

            "new_size":
                robj["new_size"],

            "changed":
                robj["changed"],

            "path":
                robj["path"],
        })

        cursor = (
            new_off
            + robj["new_size"]
        )

    final_size = cursor

    # --------------------------------------------------------
    # Patch embedded + external PIDX.
    # --------------------------------------------------------

    patched_embedded = bytearray(
        embedded_blob
    )

    patched_external = bytearray(
        external_blob
    )

    ext_primary = {
        e["entry"]: e
        for e in external["primary"]
    }

    for plan in primary_plan:
        emb = embedded["primary"][
            plan["entry"]
        ]

        ext = ext_primary[
            plan["entry"]
        ]

        for blob, rec in (
            (patched_embedded, emb),
            (patched_external, ext),
        ):
            p32(
                blob,
                rec["record_off"] + 12,
                plan["new_offset"]
            )

            p32(
                blob,
                rec["record_off"] + 16,
                plan["new_size"]
            )

            p32(
                blob,
                rec["record_off"] + 20,
                plan["new_zsize"]
            )

    emb_off2 = {
        r["index"]: r
        for r in embedded[
            "offset2_rows"
        ]
    }

    ext_off2 = {
        r["index"]: r
        for r in external[
            "offset2_rows"
        ]
    }

    for plan in off2_plan:
        for blob, table in (
            (
                patched_embedded,
                emb_off2
            ),
            (
                patched_external,
                ext_off2
            ),
        ):
            rec = table[
                plan["index"]
            ]

            p32(
                blob,
                rec["record_abs"] + 8,
                plan["new_offset"]
            )

            p32(
                blob,
                rec["record_abs"] + 12,
                plan["new_size"]
            )

    # --------------------------------------------------------
    # Write DAT
    # --------------------------------------------------------

    out_dat = (
        output
        / "naruto.dat"
    )

    out_idx = (
        output
        / "naruto.idx"
    )

    with (
        source_dat.open("rb") as src,
        out_dat.open("wb") as dst
    ):
        dst.write(
            patched_embedded
        )

        total = len(
            primary_plan
        )

        for number, plan in enumerate(
            primary_plan,
            1
        ):
            pad_to(
                dst,
                plan["new_offset"]
            )

            replacement = (
                replacements_by_entry.get(
                    plan["entry"]
                )
            )

            if replacement is not None:
                dst.write(
                    replacement[
                        "new_stored"
                    ]
                )

            else:
                copy_range(
                    src,
                    dst,
                    plan["old_offset"],
                    plan["stored_size"]
                )

            if (
                number % 100 == 0
                or number == total
            ):
                print(
                    f"[PRIMARY write] "
                    f"{number}/{total}"
                )

        total = len(
            off2_plan
        )

        for number, plan in enumerate(
            off2_plan,
            1
        ):
            pad_to(
                dst,
                plan["new_offset"]
            )

            if plan["changed"]:
                with (
                    plan["path"].open(
                        "rb"
                    )
                ) as ff:
                    shutil.copyfileobj(
                        ff,
                        dst,
                        length=1024 * 1024
                    )

            else:
                copy_range(
                    src,
                    dst,
                    plan["old_offset"],
                    plan["old_size"]
                )

            if (
                number % 25 == 0
                or number == total
            ):
                print(
                    f"[FSTS write] "
                    f"{number}/{total}"
                )

    if (
        out_dat.stat().st_size
        != final_size
    ):
        raise RuntimeError(
            f"DAT final size mismatch: "
            f"{out_dat.stat().st_size} "
            f"!= {final_size}"
        )

    out_idx.write_bytes(
        patched_external
    )

    # --------------------------------------------------------
    # Self-validation
    # --------------------------------------------------------

    print()
    print("[VALIDATION]")

    rebuilt_blob = (
        read_embedded_index(
            out_dat
        )
    )

    rebuilt_idx = parse_pidx(
        rebuilt_blob,
        "PATCHED_EMBEDDED"
    )

    rebuilt_external = parse_pidx(
        out_idx.read_bytes(),
        "PATCHED_EXTERNAL"
    )

    validation_rows = []

    # Embedded/external semantic equality.
    if (
        len(
            rebuilt_idx[
                "primary"
            ]
        )
        != len(
            rebuilt_external[
                "primary"
            ]
        )
    ):
        raise RuntimeError(
            "patched indexes primary count mismatch"
        )

    for i in range(
        len(
            rebuilt_idx[
                "primary"
            ]
        )
    ):
        a = rebuilt_idx[
            "primary"
        ][i]

        b = rebuilt_external[
            "primary"
        ][i]

        for k in (
            "offset",
            "size",
            "zsize",
        ):
            if a[k] != b[k]:
                raise RuntimeError(
                    f"IDX mismatch "
                    f"entry={i} {k}"
                )

    # Target primary validation.
    for key, target in (
        replacements.items()
    ):
        entry = rebuilt_idx[
            "primary"
        ][
            target["entry"]
        ]

        decoded = decode_primary(
            out_dat,
            entry
        )

        ok = (
            sha256(decoded)
            == target["new_sha256"]
        )

        validation_rows.append({
            "check":
                "primary_replacement",

            "target":
                key,

            "expected":
                target["new_sha256"],

            "actual":
                sha256(decoded),

            "ok":
                ok,
        })

        if not ok:
            raise RuntimeError(
                f"patched primary verification "
                f"failed: {key}"
            )

    # Verify all FSTS replacement copies.
    found_counts = defaultdict(
        int
    )

    with out_dat.open("rb") as f:
        total = len(
            rebuilt_idx[
                "offset2_rows"
            ]
        )

        for number, rec in enumerate(
            rebuilt_idx[
                "offset2_rows"
            ],
            1
        ):
            f.seek(
                rec["file_off"]
            )

            bundle = f.read(
                rec["file_size"]
            )

            parsed = parse_fsts(
                bundle,
                rec["name"]
            )

            for m in parsed[
                "members"
            ]:
                target = (
                    replacements.get(
                        m["basename"]
                    )
                )

                if target is None:
                    continue

                decoded = decode_stored(
                    m["stored"],
                    m["size"],
                    m["zsize"]
                )

                actual_hash = sha256(
                    decoded
                )

                ok = (
                    actual_hash
                    == target[
                        "new_sha256"
                    ]
                )

                validation_rows.append({
                    "check":
                        "fsts_replacement",

                    "target":
                        m["basename"],

                    "bundle":
                        rec["name"],

                    "member":
                        m["name"],

                    "expected":
                        target[
                            "new_sha256"
                        ],

                    "actual":
                        actual_hash,

                    "ok":
                        ok,
                })

                if not ok:
                    raise RuntimeError(
                        f"patched FSTS "
                        f"verification failed: "
                        f"{rec['name']} / "
                        f"{m['name']}"
                    )

                found_counts[
                    m["basename"]
                ] += 1

            if (
                number % 25 == 0
                or number == total
            ):
                print(
                    f"[VALIDATE FSTS] "
                    f"{number}/{total}"
                )

    for key in replacements:
        expected = (
            expected_copy_counts[
                key
            ]
        )

        actual = (
            found_counts[
                key
            ]
        )

        if expected != actual:
            raise RuntimeError(
                f"FSTS copy count mismatch "
                f"{key}: "
                f"{actual} != "
                f"{expected}"
            )

        validation_rows.append({
            "check":
                "fsts_copy_count",

            "target":
                key,

            "expected":
                expected,

            "actual":
                actual,

            "ok":
                True,
        })

    # --------------------------------------------------------
    # Ensure all unchanged primary stored data stayed identical.
    # --------------------------------------------------------

    print()
    print("[VALIDATE unchanged primary]")

    with (
        source_dat.open("rb") as src,
        out_dat.open("rb") as dst
    ):
        patched_by_entry = {
            p["entry"]: p
            for p in primary_plan
        }

        unchanged = [
            x
            for x in primary_plan
            if not x["changed"]
        ]

        total = len(
            unchanged
        )

        for number, p in enumerate(
            unchanged,
            1
        ):
            src.seek(
                p["old_offset"]
            )

            a = src.read(
                p["stored_size"]
            )

            dst.seek(
                p["new_offset"]
            )

            b = dst.read(
                p["stored_size"]
            )

            if a != b:
                raise RuntimeError(
                    f"unchanged primary altered: "
                    f"{p['name']}"
                )

            if (
                number % 100 == 0
                or number == total
            ):
                print(
                    f"[UNCHANGED PRIMARY] "
                    f"{number}/{total}"
                )

    # --------------------------------------------------------
    # Reports
    # --------------------------------------------------------

    write_tsv(
        output
        / "replacement_manifest.tsv",
        manifest_rows,
        [
            "target",
            "entry",
            "replacement_file",
            "old_decoded_size",
            "new_decoded_size",
            "old_sha256",
            "new_sha256",
            "new_codec",
            "new_stored_size",
        ]
    )

    write_tsv(
        output
        / "primary_patch_map.tsv",
        primary_plan,
        [
            "entry",
            "name",
            "old_offset",
            "new_offset",
            "old_size",
            "new_size",
            "old_zsize",
            "new_zsize",
            "stored_size",
            "changed",
        ]
    )

    write_tsv(
        output
        / "fsts_patch_map.tsv",
        fsts_patch_rows,
        [
            "bundle_index",
            "bundle_name",
            "bundle",
            "member_index",
            "member_name",
            "basename",
            "old_size",
            "new_size",
            "old_zsize",
            "new_zsize",
        ]
    )

    write_tsv(
        output
        / "validation.tsv",
        validation_rows,
        [
            "check",
            "target",
            "bundle",
            "member",
            "expected",
            "actual",
            "ok",
        ]
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    old_dat_size = (
        source_dat
        .stat()
        .st_size
    )

    new_dat_size = (
        out_dat
        .stat()
        .st_size
    )

    summary = (
        output
        / "stage14_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "Naruto PSP Stage 14\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"Source DAT: {source_dat}\n"
        )

        f.write(
            f"Source IDX: {source_idx}\n\n"
        )

        f.write(
            f"Replacement resources: "
            f"{len(replacements)}\n"
        )

        f.write(
            f"Changed primary files: "
            f"{sum(1 for x in primary_plan if x['changed'])}\n"
        )

        f.write(
            f"Changed FSTS members: "
            f"{len(fsts_patch_rows)}\n"
        )

        f.write(
            f"Changed FSTS bundles: "
            f"{sum(1 for x in off2_plan if x['changed'])}\n\n"
        )

        for key in replacements:
            f.write(
                f"{key}: "
                f"FSTS copies="
                f"{expected_copy_counts[key]}\n"
            )

        f.write("\n")

        f.write(
            f"Original DAT size: "
            f"{old_dat_size}\n"
        )

        f.write(
            f"Patched DAT size: "
            f"{new_dat_size}\n"
        )

        f.write(
            f"Growth: "
            f"{new_dat_size - old_dat_size}\n\n"
        )

        f.write(
            f"Patched DAT SHA256: "
            f"{sha256_file(out_dat)}\n"
        )

        f.write(
            f"Patched IDX SHA256: "
            f"{sha256_file(out_idx)}\n\n"
        )

        f.write(
            "SELF VALIDATION: PASS\n"
        )

    instructions = (
        output
        / "TEST_INSTRUCTIONS.txt"
    )

    instructions.write_text(
        "\n".join([
            "Naruto PSP Stage 14 테스트 패치",
            "",
            "생성 파일:",
            f"  {out_dat}",
            f"  {out_idx}",
            "",
            "변경:",
            "  event000.tbl",
            "  s_a01_000 첫 대사 -> STAGE14 PATCH TEST",
            "",
            "원본 KR ISO/USRDIR의 naruto.dat 및 naruto.idx를",
            "직접 덮어쓰지 말고 복사본 ISO에 삽입해서 테스트하세요.",
            "",
            "PPSSPP에서 해당 첫 이벤트를 재생해",
            "STAGE14 PATCH TEST가 표시되면",
            "primary/FSTS/PIDX/DAT 패치 경로가 실기동 검증됩니다.",
            "",
            "패처 자체의 내부 검증은 PASS 상태입니다.",
        ]),
        encoding="utf-8"
    )

    # Temp FSTS files no longer needed.
    if tmp.exists():
        shutil.rmtree(tmp)

    print()
    print("=" * 72)
    print("PATCH BUILD COMPLETE")
    print("=" * 72)

    print(
        "Patched DAT:",
        out_dat
    )

    print(
        "Patched IDX:",
        out_idx
    )

    print(
        "Changed FSTS members:",
        len(fsts_patch_rows)
    )

    print(
        "DAT growth:",
        new_dat_size
        - old_dat_size
    )

    print(
        "SELF VALIDATION: PASS"
    )

    return {
        "output": output,
        "summary": summary,
        "out_dat": out_dat,
        "out_idx": out_idx,
    }


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Naruto PSP PIDX/FSTS "
            "translation resource patcher"
        )
    )

    ap.add_argument(
        "--root",
        type=Path,
        default=Path(
            r"D:\narutimate portable"
        )
    )

    ap.add_argument(
        "--output",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--replace",
        action="append",
        default=[],
        metavar="NAME=FILE",
        help=(
            "Decoded primary resource "
            "replacement. Repeatable."
        )
    )

    ap.add_argument(
        "--stage14-test",
        action="store_true"
    )

    ap.add_argument(
        "--force",
        action="store_true"
    )

    args = ap.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()

    if output.exists():
        if not args.force:
            raise RuntimeError(
                f"Output exists: {output}. "
                "Use --force."
            )

        shutil.rmtree(output)

    output.mkdir(
        parents=True
    )

    kr_dat = (
        root
        / "kr_extracted"
        / "PSP_GAME"
        / "USRDIR"
        / "naruto.dat"
    )

    embedded = parse_pidx(
        read_embedded_index(
            kr_dat
        ),
        "KR_EMBEDDED"
    )

    specs = []

    if args.stage14_test:
        test = build_stage14_test(
            kr_dat,
            embedded,
            output
        )

        specs.append({
            "name":
                test["name"],

            "path":
                test["path"],
        })

        (
            output
            / "stage14_test_change.txt"
        ).write_text(
            (
                "Original:\n"
                + test["old_message"]
                + "\n\nPatched:\n"
                + test["new_message"]
                + "\n"
            ),
            encoding="utf-8"
        )

    for item in args.replace:
        if "=" not in item:
            raise RuntimeError(
                f"--replace format is "
                f"NAME=FILE: {item}"
            )

        name, path = item.split(
            "=",
            1
        )

        specs.append({
            "name":
                name.strip(),

            "path":
                Path(
                    path.strip()
                ).resolve(),
        })

    if not specs:
        raise RuntimeError(
            "No replacements supplied."
        )

    patch_kr(
        root,
        output,
        specs
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
