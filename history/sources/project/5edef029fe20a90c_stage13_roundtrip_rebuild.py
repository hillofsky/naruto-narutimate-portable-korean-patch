from pathlib import Path
from collections import defaultdict
import struct
import csv
import hashlib
import shutil
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage13"

REBUILT = OUT / "rebuilt"
FSTS_TMP = OUT / "_fsts_tmp"

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
    REBUILT,
    FSTS_TMP,
]:
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


def p32(data, off, value):

    struct.pack_into(
        "<I",
        data,
        off,
        value
    )


def align_up(value, alignment=0x800):

    return (
        value
        + alignment
        - 1
    ) & ~(alignment - 1)


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

    if (
        off < 0
        or off >= len(data)
    ):
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


# ============================================================
# PIDX
# ============================================================

def read_embedded_index(dat_path):

    with dat_path.open("rb") as f:

        head = f.read(0x50)

        if head[:5] != b"PIDX0":

            raise RuntimeError(
                f"PIDX0 없음: "
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


def parse_index(blob, label):

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

    if (
        info_off
        + files * 24
        != offset2
    ):

        raise RuntimeError(
            f"{label}: "
            "primary table boundary invalid"
        )

    if (
        names_off
        + names_size
        > len(blob)
    ):

        raise RuntimeError(
            f"{label}: "
            "names outside index"
        )

    names = blob[
        names_off:
        names_off + names_size
    ]

    primary = []

    for i in range(files):

        record_off = (
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
            record_off
        )

        primary.append({
            "entry":
                i,

            "record_off":
                record_off,

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

    block = blob[
        offset2:
        offset2 + offset2_size
    ]

    if len(block) < 4:

        raise RuntimeError(
            f"{label}: OFFSET2 empty"
        )

    off2_count = u32(
        block,
        0
    )

    offset2_rows = []

    for i in range(
        off2_count
    ):

        ptr = u32(
            block,
            4 + i * 4
        )

        if (
            ptr + 16
            > len(block)
        ):

            raise RuntimeError(
                f"{label}: "
                f"bad OFFSET2 pointer "
                f"{i} 0x{ptr:X}"
            )

        record_abs = (
            offset2 + ptr
        )

        (
            name_off,
            pack_name_off,
            file_off,
            file_size,
        ) = struct.unpack_from(
            "<4I",
            blob,
            record_abs
        )

        offset2_rows.append({
            "index":
                i,

            "pointer":
                ptr,

            "record_abs":
                record_abs,

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
        "blob":
            blob,

        "info_off":
            info_off,

        "files":
            files,

        "offset2":
            offset2,

        "offset2_size":
            offset2_size,

        "names_off":
            names_off,

        "names_size":
            names_size,

        "index_end":
            names_off + names_size,

        "primary":
            primary,

        "offset2_rows":
            offset2_rows,
    }


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
            f"{label}: "
            "FSTS info table outside"
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

        rec_off = (
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
            rec_off
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
            "index":
                i,

            "record_off":
                rec_off,

            "name":
                cstring(
                    names,
                    name_off
                ),

            "offset":
                file_off,

            "size":
                size,

            "zsize":
                zsize,

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
        "files":
            files,

        "info_off":
            info_off,

        "names_off":
            names_off,

        "names_size":
            names_size,

        "metadata_end":
            names_off + names_size,

        "members":
            members,
    }


def first_diff_bytes(a, b):

    n = min(
        len(a),
        len(b)
    )

    for i in range(n):

        if a[i] != b[i]:
            return i

    if len(a) != len(b):
        return n

    return None


def rebuild_fsts(
    source,
    label
):

    parsed = parse_fsts(
        source,
        label
    )

    # Empty bundle such as US intro.
    if parsed["files"] == 0:

        return (
            bytes(source),
            parsed,
            []
        )

    metadata_end = (
        parsed["metadata_end"]
    )

    out = bytearray(
        source[:metadata_end]
    )

    cursor = align_up(
        metadata_end
    )

    if len(out) < cursor:

        out.extend(
            b"\0"
            * (
                cursor
                - len(out)
            )
        )

    placement = []

    # Physical member order is offset order.
    ordered = sorted(
        parsed["members"],
        key=lambda x:
            x["offset"]
    )

    for m in ordered:

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

        # Patch member FILE_OFF.
        p32(
            out,
            m["record_off"] + 4,
            new_off
        )

        out.extend(
            m["stored"]
        )

        cursor = (
            new_off
            + len(
                m["stored"]
            )
        )

        placement.append({
            "member_index":
                m["index"],

            "name":
                m["name"],

            "old_offset":
                m["offset"],

            "new_offset":
                new_off,

            "stored_size":
                m["stored_size"],

            "same_offset":
                (
                    m["offset"]
                    == new_off
                ),
        })

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
        parsed,
        placement
    )


# ============================================================
# File comparison
# ============================================================

def compare_files(a, b):

    size_a = a.stat().st_size
    size_b = b.stat().st_size

    hash_a = sha256_file(a)
    hash_b = sha256_file(b)

    first_diff = None

    with (
        a.open("rb") as fa,
        b.open("rb") as fb
    ):

        absolute = 0

        while True:

            ba = fa.read(
                1024 * 1024
            )

            bb = fb.read(
                1024 * 1024
            )

            if not ba and not bb:
                break

            if ba != bb:

                n = min(
                    len(ba),
                    len(bb)
                )

                for i in range(n):

                    if ba[i] != bb[i]:

                        first_diff = (
                            absolute + i
                        )

                        break

                if (
                    first_diff
                    is None
                ):

                    first_diff = (
                        absolute + n
                    )

                break

            absolute += len(ba)

    return {
        "size_original":
            size_a,

        "size_rebuilt":
            size_b,

        "size_match":
            size_a == size_b,

        "sha256_original":
            hash_a,

        "sha256_rebuilt":
            hash_b,

        "sha256_match":
            hash_a == hash_b,

        "first_diff":
            (
                ""
                if first_diff is None
                else f"0x{first_diff:X}"
            ),

        "byte_identical":
            (
                size_a == size_b
                and hash_a == hash_b
            ),
    }


# ============================================================
# Copy source range
# ============================================================

def copy_range(
    src,
    dst,
    offset,
    size
):

    src.seek(offset)

    remaining = size

    while remaining:

        chunk = src.read(
            min(
                remaining,
                1024 * 1024
            )
        )

        if not chunk:

            raise RuntimeError(
                "Unexpected EOF "
                "during range copy"
            )

        dst.write(chunk)

        remaining -= len(chunk)


def pad_to(
    f,
    target
):

    current = f.tell()

    if current > target:

        raise RuntimeError(
            f"Output passed target: "
            f"0x{current:X} > "
            f"0x{target:X}"
        )

    remaining = (
        target - current
    )

    zero = b"\0" * (
        1024 * 1024
    )

    while remaining:

        n = min(
            remaining,
            len(zero)
        )

        f.write(
            zero[:n]
        )

        remaining -= n


# ============================================================
# Region rebuild
# ============================================================

def rebuild_region(
    region,
    dat_path,
    embedded_blob,
    external_blob=None
):

    print()
    print(
        "=" * 72
    )

    print(
        region,
        "ROUND-TRIP BUILD"
    )

    print(
        "=" * 72
    )

    idx = parse_index(
        embedded_blob,
        region + "_EMBEDDED"
    )

    external = None

    if external_blob is not None:

        external = parse_index(
            external_blob,
            region + "_EXTERNAL"
        )

    actual_primary = [
        e
        for e in idx["primary"]
        if e["is_folder"] == 0
    ]

    primary_sorted = sorted(
        actual_primary,
        key=lambda x:
            x["offset"]
    )

    off2_sorted = sorted(
        idx["offset2_rows"],
        key=lambda x:
            x["file_off"]
    )

    # --------------------------------------------------------
    # Rebuild every FSTS first.
    # --------------------------------------------------------

    region_tmp = (
        FSTS_TMP / region.lower()
    )

    if region_tmp.exists():

        shutil.rmtree(
            region_tmp
        )

    region_tmp.mkdir(
        parents=True
    )

    fsts_rows = []

    rebuilt_fsts = {}

    with dat_path.open("rb") as f:

        total_fsts = len(
            off2_sorted
        )

        for number, rec in enumerate(
            off2_sorted,
            1
        ):

            f.seek(
                rec["file_off"]
            )

            source = f.read(
                rec["file_size"]
            )

            if len(source) != rec["file_size"]:

                raise RuntimeError(
                    f"{region} "
                    f"FSTS short read: "
                    f"{rec['name']}"
                )

            rebuilt, parsed, placements = (
                rebuild_fsts(
                    source,
                    (
                        region
                        + ":"
                        + rec["name"]
                    )
                )
            )

            tmp = (
                region_tmp
                / (
                    f"{rec['index']:04d}"
                    f".fsts"
                )
            )

            tmp.write_bytes(
                rebuilt
            )

            rebuilt_fsts[
                rec["index"]
            ] = {
                "path":
                    tmp,

                "size":
                    len(rebuilt),

                "old_size":
                    rec["file_size"],

                "old_offset":
                    rec["file_off"],

                "name":
                    rec["name"],
            }

            first = (
                first_diff_bytes(
                    source,
                    rebuilt
                )
            )

            fsts_rows.append({
                "region":
                    region,

                "index":
                    rec["index"],

                "name":
                    rec["name"],

                "members":
                    parsed["files"],

                "original_size":
                    len(source),

                "rebuilt_size":
                    len(rebuilt),

                "size_match":
                    (
                        len(source)
                        == len(rebuilt)
                    ),

                "sha256_original":
                    hashlib.sha256(
                        source
                    ).hexdigest(),

                "sha256_rebuilt":
                    hashlib.sha256(
                        rebuilt
                    ).hexdigest(),

                "byte_identical":
                    source == rebuilt,

                "first_diff":
                    (
                        ""
                        if first is None
                        else f"0x{first:X}"
                    ),

                "member_offsets_same":
                    all(
                        x["same_offset"]
                        for x in placements
                    ),
            })

            if (
                number % 25 == 0
                or number == total_fsts
            ):

                print(
                    f"[{region}] "
                    f"FSTS "
                    f"{number}/"
                    f"{total_fsts}"
                )

    # --------------------------------------------------------
    # Plan entire DAT.
    # --------------------------------------------------------

    cursor = align_up(
        idx["index_end"]
    )

    primary_plan = []

    for e in primary_sorted:

        stored_size = (
            e["zsize"]
            if e["zsize"]
            else e["size"]
        )

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

            "stored_size":
                stored_size,

            "size":
                e["size"],

            "zsize":
                e["zsize"],
        })

        cursor = (
            new_off
            + stored_size
        )

    cursor = align_up(
        cursor
    )

    off2_plan = []

    for rec in off2_sorted:

        obj = rebuilt_fsts[
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
                obj["size"],

            "path":
                obj["path"],
        })

        cursor = (
            new_off
            + obj["size"]
        )

    final_dat_size = cursor

    # --------------------------------------------------------
    # Patch embedded PIDX.
    # --------------------------------------------------------

    patched_embedded = bytearray(
        embedded_blob
    )

    primary_plan_by_entry = {
        x["entry"]: x
        for x in primary_plan
    }

    for e in idx["primary"]:

        if e["is_folder"] != 0:
            continue

        plan = primary_plan_by_entry[
            e["entry"]
        ]

        # +0x0C file offset
        p32(
            patched_embedded,
            e["record_off"] + 12,
            plan["new_offset"]
        )

        # size/zsize remain unchanged
        p32(
            patched_embedded,
            e["record_off"] + 16,
            plan["size"]
        )

        p32(
            patched_embedded,
            e["record_off"] + 20,
            plan["zsize"]
        )

    off2_plan_by_index = {
        x["index"]: x
        for x in off2_plan
    }

    for rec in idx[
        "offset2_rows"
    ]:

        plan = off2_plan_by_index[
            rec["index"]
        ]

        # record:
        # +0 name_off
        # +4 pack_name_off
        # +8 file_off
        # +12 file_size
        p32(
            patched_embedded,
            rec["record_abs"] + 8,
            plan["new_offset"]
        )

        p32(
            patched_embedded,
            rec["record_abs"] + 12,
            plan["new_size"]
        )

    # --------------------------------------------------------
    # Patch external IDX independently.
    # --------------------------------------------------------

    patched_external = None

    if external is not None:

        patched_external = bytearray(
            external_blob
        )

        ext_primary_by_entry = {
            x["entry"]: x
            for x in external[
                "primary"
            ]
        }

        for plan in primary_plan:

            e = ext_primary_by_entry[
                plan["entry"]
            ]

            p32(
                patched_external,
                e["record_off"] + 12,
                plan["new_offset"]
            )

            p32(
                patched_external,
                e["record_off"] + 16,
                plan["size"]
            )

            p32(
                patched_external,
                e["record_off"] + 20,
                plan["zsize"]
            )

        ext_off2 = {
            x["index"]: x
            for x in external[
                "offset2_rows"
            ]
        }

        for plan in off2_plan:

            rec = ext_off2[
                plan["index"]
            ]

            p32(
                patched_external,
                rec["record_abs"] + 8,
                plan["new_offset"]
            )

            p32(
                patched_external,
                rec["record_abs"] + 12,
                plan["new_size"]
            )

    # --------------------------------------------------------
    # Write new DAT.
    # --------------------------------------------------------

    rebuilt_dat = (
        REBUILT
        / (
            region.lower()
            + "_naruto_roundtrip.dat"
        )
    )

    with (
        dat_path.open("rb") as src,
        rebuilt_dat.open("wb") as dst
    ):

        dst.write(
            patched_embedded
        )

        total_primary = len(
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

            copy_range(
                src,
                dst,
                plan["old_offset"],
                plan["stored_size"]
            )

            if (
                number % 100 == 0
                or number
                == total_primary
            ):

                print(
                    f"[{region}] "
                    f"PRIMARY "
                    f"{number}/"
                    f"{total_primary}"
                )

        total_off2 = len(
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

            with plan[
                "path"
            ].open("rb") as ff:

                shutil.copyfileobj(
                    ff,
                    dst,
                    length=1024*1024
                )

            if (
                number % 25 == 0
                or number
                == total_off2
            ):

                print(
                    f"[{region}] "
                    f"OFFSET2/FSTS "
                    f"{number}/"
                    f"{total_off2}"
                )

    if (
        rebuilt_dat.stat().st_size
        != final_dat_size
    ):

        raise RuntimeError(
            f"{region}: rebuilt DAT "
            f"size mismatch "
            f"{rebuilt_dat.stat().st_size} "
            f"!= {final_dat_size}"
        )

    # --------------------------------------------------------
    # External IDX output.
    # --------------------------------------------------------

    rebuilt_idx = None

    if patched_external is not None:

        rebuilt_idx = (
            REBUILT
            / (
                region.lower()
                + "_naruto_roundtrip.idx"
            )
        )

        rebuilt_idx.write_bytes(
            patched_external
        )

    # --------------------------------------------------------
    # Plan reports.
    # --------------------------------------------------------

    primary_rows = []

    for p in primary_plan:

        primary_rows.append({
            "region":
                region,

            **p,

            "old_offset_hex":
                f'0x{p["old_offset"]:X}',

            "new_offset_hex":
                f'0x{p["new_offset"]:X}',

            "offset_same":
                (
                    p["old_offset"]
                    == p["new_offset"]
                ),
        })

    off2_rows = []

    for p in off2_plan:

        off2_rows.append({
            "region":
                region,

            "index":
                p["index"],

            "name":
                p["name"],

            "old_offset_hex":
                f'0x{p["old_offset"]:X}',

            "new_offset_hex":
                f'0x{p["new_offset"]:X}',

            "offset_same":
                (
                    p["old_offset"]
                    == p["new_offset"]
                ),

            "old_size":
                p["old_size"],

            "new_size":
                p["new_size"],

            "size_same":
                (
                    p["old_size"]
                    == p["new_size"]
                ),
        })

    return {
        "region":
            region,

        "rebuilt_dat":
            rebuilt_dat,

        "rebuilt_idx":
            rebuilt_idx,

        "fsts_rows":
            fsts_rows,

        "primary_rows":
            primary_rows,

        "off2_rows":
            off2_rows,

        "final_dat_size":
            final_dat_size,
    }


# ============================================================
# Main
# ============================================================

def main():

    print(
        "=" * 72
    )

    print(
        "Naruto PSP Stage 13"
    )

    print(
        "Canonical no-op round-trip rebuild"
    )

    print(
        "=" * 72
    )

    kr_embedded = (
        read_embedded_index(
            KR_DAT
        )
    )

    us_embedded = (
        read_embedded_index(
            US_DAT
        )
    )

    kr_external = (
        KR_IDX.read_bytes()
    )

    results = []

    kr = rebuild_region(
        "KR",
        KR_DAT,
        kr_embedded,
        kr_external
    )

    results.append(kr)

    us = rebuild_region(
        "US",
        US_DAT,
        us_embedded,
        None
    )

    results.append(us)

    # ========================================================
    # Compare
    # ========================================================

    roundtrip_rows = []

    fsts_rows = []
    primary_rows = []
    off2_rows = []

    for obj in results:

        region = obj[
            "region"
        ]

        source_dat = (
            KR_DAT
            if region == "KR"
            else US_DAT
        )

        cmp_dat = compare_files(
            source_dat,
            obj["rebuilt_dat"]
        )

        roundtrip_rows.append({
            "region":
                region,

            "object":
                "naruto.dat",

            **cmp_dat,
        })

        if (
            region == "KR"
            and obj["rebuilt_idx"]
            is not None
        ):

            cmp_idx = compare_files(
                KR_IDX,
                obj["rebuilt_idx"]
            )

            roundtrip_rows.append({
                "region":
                    region,

                "object":
                    "naruto.idx",

                **cmp_idx,
            })

        fsts_rows.extend(
            obj["fsts_rows"]
        )

        primary_rows.extend(
            obj["primary_rows"]
        )

        off2_rows.extend(
            obj["off2_rows"]
        )

    write_tsv(
        OUT / "roundtrip_results.tsv",
        roundtrip_rows,
        [
            "region",
            "object",
            "size_original",
            "size_rebuilt",
            "size_match",
            "sha256_original",
            "sha256_rebuilt",
            "sha256_match",
            "first_diff",
            "byte_identical",
        ]
    )

    write_tsv(
        OUT / "fsts_roundtrip.tsv",
        fsts_rows,
        [
            "region",
            "index",
            "name",
            "members",
            "original_size",
            "rebuilt_size",
            "size_match",
            "sha256_original",
            "sha256_rebuilt",
            "byte_identical",
            "first_diff",
            "member_offsets_same",
        ]
    )

    write_tsv(
        OUT / "primary_roundtrip_layout.tsv",
        primary_rows,
        [
            "region",
            "entry",
            "name",
            "old_offset",
            "new_offset",
            "old_offset_hex",
            "new_offset_hex",
            "offset_same",
            "stored_size",
            "size",
            "zsize",
        ]
    )

    write_tsv(
        OUT / "offset2_roundtrip_layout.tsv",
        off2_rows,
        [
            "region",
            "index",
            "name",
            "old_offset_hex",
            "new_offset_hex",
            "offset_same",
            "old_size",
            "new_size",
            "size_same",
        ]
    )

    # ========================================================
    # Summary
    # ========================================================

    fsts_exact = sum(
        1
        for r in fsts_rows
        if r["byte_identical"]
    )

    fsts_total = len(
        fsts_rows
    )

    fsts_offsets_same = sum(
        1
        for r in fsts_rows
        if r["member_offsets_same"]
    )

    primary_same = sum(
        1
        for r in primary_rows
        if r["offset_same"]
    )

    off2_same = sum(
        1
        for r in off2_rows
        if r["offset_same"]
    )

    object_exact = sum(
        1
        for r in roundtrip_rows
        if r["byte_identical"]
    )

    all_exact = (
        object_exact
        == len(roundtrip_rows)
        and
        fsts_exact
        == fsts_total
    )

    summary = (
        OUT
        / "stage13_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 13\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"FSTS bundles rebuilt: "
            f"{fsts_total}\n"
        )

        f.write(
            f"FSTS byte-identical: "
            f"{fsts_exact}/"
            f"{fsts_total}\n"
        )

        f.write(
            f"FSTS member layouts unchanged: "
            f"{fsts_offsets_same}/"
            f"{fsts_total}\n\n"
        )

        f.write(
            f"Primary file offsets unchanged: "
            f"{primary_same}/"
            f"{len(primary_rows)}\n"
        )

        f.write(
            f"OFFSET2 bundle offsets unchanged: "
            f"{off2_same}/"
            f"{len(off2_rows)}\n\n"
        )

        for r in roundtrip_rows:

            f.write(
                f"{r['region']} "
                f"{r['object']}: "
                f"size_match={r['size_match']} "
                f"sha256_match={r['sha256_match']} "
                f"byte_identical={r['byte_identical']} "
                f"first_diff={r['first_diff']}\n"
            )

        f.write("\n")

        f.write(
            f"ALL ROUNDTRIP EXACT: "
            f"{all_exact}\n"
        )

    print()
    print(
        "=" * 72
    )

    print(
        "STAGE 13 COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        "FSTS byte-identical:",
        fsts_exact,
        "/",
        fsts_total
    )

    print(
        "Primary offsets unchanged:",
        primary_same,
        "/",
        len(primary_rows)
    )

    print(
        "OFFSET2 offsets unchanged:",
        off2_same,
        "/",
        len(off2_rows)
    )

    for r in roundtrip_rows:

        print(
            r["region"],
            r["object"],
            "EXACT =",
            r["byte_identical"],
            "FIRST_DIFF =",
            r["first_diff"]
        )

    print(
        "ALL ROUNDTRIP EXACT:",
        all_exact
    )

    # Exact test outputs are not needed afterwards.
    # Delete the large rebuilt DATs/IDX if everything matched.
    if all_exact:

        print()
        print(
            "Round-trip succeeded; "
            "removing large temporary rebuilt files."
        )

        for obj in results:

            if (
                obj["rebuilt_dat"]
                .exists()
            ):

                obj[
                    "rebuilt_dat"
                ].unlink()

            if (
                obj["rebuilt_idx"]
                is not None
                and obj[
                    "rebuilt_idx"
                ].exists()
            ):

                obj[
                    "rebuilt_idx"
                ].unlink()

        if FSTS_TMP.exists():

            shutil.rmtree(
                FSTS_TMP
            )

    else:

        print()
        print(
            "Mismatch detected. "
            "Rebuilt files are being retained "
            "under analysis\\stage13\\rebuilt."
        )


if __name__ == "__main__":

    try:

        main()

    except Exception:

        traceback.print_exc()
        sys.exit(1)
