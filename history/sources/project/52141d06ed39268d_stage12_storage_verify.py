from pathlib import Path
from collections import defaultdict, Counter
import importlib.util
import struct
import csv
import hashlib
import sys
import traceback

BASE = Path(r"PROJECT_ROOT")
OUT  = BASE / "analysis" / "stage12"

OUT.mkdir(
    parents=True,
    exist_ok=True
)

S11 = (
    BASE
    / "analysis"
    / "stage11"
    / "stage11_fsts_map.py"
)

KR_IDX = (
    BASE
    / "kr_extracted"
    / "PSP_GAME"
    / "USRDIR"
    / "naruto.idx"
)

KR_DAT = (
    BASE
    / "kr_extracted"
    / "PSP_GAME"
    / "USRDIR"
    / "naruto.dat"
)

US_DAT = (
    BASE
    / "us_extracted"
    / "PSP_GAME"
    / "USRDIR"
    / "naruto.dat"
)


def load_stage11():

    if not S11.exists():

        raise RuntimeError(
            f"Stage11 script missing: {S11}"
        )

    spec = importlib.util.spec_from_file_location(
        "stage11",
        S11
    )

    mod = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(mod)

    return mod


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
# 3;0 encoder
# ============================================================

def encode_3_0(data):

    return (
        b" 3;0"
        + struct.pack(
            "<I",
            len(data)
        )
        + bytes(
            x ^ 0x72
            for x in data
        )
    )


# ============================================================
# Corrected FSTS parser
#
# Important correction:
#
# zsize != 0 means that many bytes exist in the bundle.
#
# In particular:
#
#     3;0:
#       zsize == size + 8
#
# So zsize >= size MUST NOT automatically mean
# "read only SIZE bytes raw".
# ============================================================

def parse_fsts_corrected(
    s11,
    bundle,
    bundle_name
):

    if (
        len(bundle) < 0x20
        or bundle[:4] != b"FSTS"
    ):

        raise RuntimeError(
            f"{bundle_name}: not FSTS"
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

    members = []

    for i in range(files):

        p = (
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
            p
        )

        name = s11.cstring(
            names,
            name_off
        )

        # Corrected physical length.
        stored_len = (
            zsize
            if zsize
            else size
        )

        if (
            file_off
            + stored_len
            > len(bundle)
        ):

            raise RuntimeError(
                f"{bundle_name}: "
                f"member {i} outside "
                f"offset=0x{file_off:X} "
                f"stored={stored_len}"
            )

        stored = bundle[
            file_off:
            file_off
            + stored_len
        ]

        codec = "raw"
        decoded = stored
        error = ""

        # Naruto 3;x container
        if stored[:3] == b" 3;":

            try:

                decoded = (
                    s11.decode_3x(
                        stored
                    )
                )

                codec = (
                    stored[:4]
                    .decode(
                        "ascii",
                        errors="replace"
                    )
                )

            except Exception as ex:

                codec = (
                    "3;x_DECODE_ERROR"
                )

                error = str(ex)

        elif zsize and zsize < size:

            # Other compression fallback from Stage11.
            (
                decoded,
                codec,
                error
            ) = s11.decode_compressed(
                stored
            )

        members.append({
            "member_index":
                i,

            "name":
                name,

            "basename":
                s11.basename(
                    name
                ),

            "offset":
                file_off,

            "size":
                size,

            "zsize":
                zsize,

            "stored_size":
                stored_len,

            "codec":
                codec,

            "decode_error":
                error,

            "stored":
                stored,

            "decoded":
                decoded,

            "decoded_size":
                len(decoded),

            "decoded_sha256":
                sha256(decoded),
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
            members,
    }


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 72)
    print("Naruto PSP Stage 12")
    print("FSTS storage correction / 3;0 verification")
    print("=" * 72)

    s11 = load_stage11()

    kr_pidx = s11.parse_pidx(
        KR_IDX.read_bytes()
    )

    us_pidx = s11.parse_pidx(
        s11.read_embedded_pidx(
            US_DAT
        )
    )

    (
        kr_primary,
        kr_by_base
    ) = s11.build_primary(
        KR_DAT,
        kr_pidx["primary"]
    )

    (
        us_primary,
        us_by_base
    ) = s11.build_primary(
        US_DAT,
        us_pidx["primary"]
    )

    regions = {
        "KR": {
            "dat":
                KR_DAT,

            "offset2":
                kr_pidx["offset2"],

            "primary":
                kr_primary,

            "by_base":
                kr_by_base,
        },

        "US": {
            "dat":
                US_DAT,

            "offset2":
                us_pidx["offset2"],

            "primary":
                us_primary,

            "by_base":
                us_by_base,
        },
    }

    member_rows = []
    layout_rows = []

    codec_counts = Counter()

    total_exact = 0
    total_name_matches = 0
    mismatches = []

    plus8_rows = []

    # ========================================================
    # Reparse every FSTS correctly
    # ========================================================

    for region, robj in regions.items():

        dat = robj["dat"]

        dat_size = (
            dat.stat().st_size
        )

        with dat.open("rb") as f:

            for off2 in robj["offset2"]:

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

                    raise RuntimeError(
                        f"{region} "
                        f"{bundle_name}: "
                        "outside DAT"
                    )

                f.seek(start)

                bundle = f.read(size)

                parsed = (
                    parse_fsts_corrected(
                        s11,
                        bundle,
                        bundle_name
                    )
                )

                members = (
                    parsed["members"]
                )

                # --------------------------------------------
                # Member layout
                # --------------------------------------------

                sorted_members = sorted(
                    members,
                    key=lambda x:
                        x["offset"]
                )

                for j, m in enumerate(
                    sorted_members
                ):

                    end = (
                        m["offset"]
                        + m["stored_size"]
                    )

                    if (
                        j + 1
                        < len(sorted_members)
                    ):

                        next_off = (
                            sorted_members[
                                j + 1
                            ]["offset"]
                        )

                    else:

                        next_off = (
                            len(bundle)
                        )

                    layout_rows.append({
                        "region":
                            region,

                        "bundle":
                            bundle_name,

                        "member_index":
                            m["member_index"],

                        "basename":
                            m["basename"],

                        "offset":
                            f'0x{m["offset"]:X}',

                        "offset_mod_0x800":
                            m["offset"]
                            % 0x800,

                        "stored_size":
                            m["stored_size"],

                        "end":
                            f"0x{end:X}",

                        "next_offset":
                            f"0x{next_off:X}",

                        "gap":
                            next_off - end,
                    })

                # --------------------------------------------
                # Compare with primary
                # --------------------------------------------

                for m in members:

                    codec_counts[
                        (
                            region,
                            m["codec"]
                        )
                    ] += 1

                    candidates = (
                        robj[
                            "by_base"
                        ].get(
                            m["basename"],
                            []
                        )
                    )

                    exact = [
                        p
                        for p in candidates
                        if (
                            p[
                                "decoded_sha256"
                            ]
                            ==
                            m[
                                "decoded_sha256"
                            ]
                        )
                    ]

                    if candidates:

                        total_name_matches += 1

                    if exact:

                        total_exact += 1

                    row = {
                        "region":
                            region,

                        "bundle":
                            bundle_name,

                        "member_index":
                            m["member_index"],

                        "member_name":
                            m["name"],

                        "basename":
                            m["basename"],

                        "offset":
                            f'0x{m["offset"]:X}',

                        "size":
                            m["size"],

                        "zsize":
                            m["zsize"],

                        "zsize_minus_size":
                            (
                                m["zsize"]
                                - m["size"]
                            ),

                        "stored_size":
                            m["stored_size"],

                        "codec":
                            m["codec"],

                        "decoded_size":
                            m["decoded_size"],

                        "primary_matches":
                            len(candidates),

                        "primary_exact_matches":
                            len(exact),

                        "same_as_primary":
                            bool(exact),

                        "decode_error":
                            m["decode_error"],
                    }

                    member_rows.append(row)

                    if (
                        m["zsize"]
                        ==
                        m["size"] + 8
                    ):

                        plus8_rows.append({
                            **row,

                            "header_hex":
                                m["stored"][
                                    :16
                                ].hex(" "),

                            "signature":
                                (
                                    m["stored"][:4]
                                    .decode(
                                        "ascii",
                                        errors="replace"
                                    )
                                ),
                        })

                    if (
                        candidates
                        and not exact
                    ):

                        mismatches.append(row)

    # ========================================================
    # 3;0 roundtrip on every translation primary resource
    # ========================================================

    type0_rows = []

    for region, robj in regions.items():

        for p in robj["primary"]:

            if not s11.is_translation_name(
                p["name"]
            ):
                continue

            decoded = p["decoded"]

            encoded = encode_3_0(
                decoded
            )

            roundtrip = (
                s11.decode_3x(
                    encoded
                )
            )

            if roundtrip != decoded:

                raise RuntimeError(
                    f"3;0 roundtrip failed: "
                    f"{region} "
                    f"{p['name']}"
                )

            current_stored = (
                p["stored_size"]
            )

            new_stored = (
                len(encoded)
            )

            type0_rows.append({
                "region":
                    region,

                "primary_entry":
                    p["entry"],

                "name":
                    p["name"],

                "decoded_size":
                    len(decoded),

                "current_codec":
                    p["codec"],

                "current_stored_size":
                    current_stored,

                "type0_stored_size":
                    new_stored,

                "growth_bytes":
                    new_stored
                    - current_stored,

                "growth_percent":
                    round(
                        (
                            new_stored
                            / current_stored
                            - 1
                        ) * 100,
                        3
                    )
                    if current_stored
                    else 0,

                "fits_current_space":
                    new_stored
                    <= current_stored,

                "roundtrip_ok":
                    True,
            })

    # ========================================================
    # Reports
    # ========================================================

    write_tsv(
        OUT / "fsts_members_corrected.tsv",
        member_rows,
        [
            "region",
            "bundle",
            "member_index",
            "member_name",
            "basename",
            "offset",
            "size",
            "zsize",
            "zsize_minus_size",
            "stored_size",
            "codec",
            "decoded_size",
            "primary_matches",
            "primary_exact_matches",
            "same_as_primary",
            "decode_error",
        ]
    )

    write_tsv(
        OUT / "fsts_plus8_verification.tsv",
        plus8_rows,
        [
            "region",
            "bundle",
            "member_index",
            "member_name",
            "basename",
            "offset",
            "size",
            "zsize",
            "zsize_minus_size",
            "stored_size",
            "codec",
            "decoded_size",
            "primary_matches",
            "primary_exact_matches",
            "same_as_primary",
            "decode_error",
            "signature",
            "header_hex",
        ]
    )

    write_tsv(
        OUT / "fsts_layout_corrected.tsv",
        layout_rows,
        [
            "region",
            "bundle",
            "member_index",
            "basename",
            "offset",
            "offset_mod_0x800",
            "stored_size",
            "end",
            "next_offset",
            "gap",
        ]
    )

    write_tsv(
        OUT / "type0_repack_estimate.tsv",
        type0_rows,
        [
            "region",
            "primary_entry",
            "name",
            "decoded_size",
            "current_codec",
            "current_stored_size",
            "type0_stored_size",
            "growth_bytes",
            "growth_percent",
            "fits_current_space",
            "roundtrip_ok",
        ]
    )

    write_tsv(
        OUT / "fsts_remaining_mismatches.tsv",
        mismatches,
        [
            "region",
            "bundle",
            "member_index",
            "member_name",
            "basename",
            "offset",
            "size",
            "zsize",
            "zsize_minus_size",
            "stored_size",
            "codec",
            "decoded_size",
            "primary_matches",
            "primary_exact_matches",
            "same_as_primary",
            "decode_error",
        ]
    )

    # ========================================================
    # Summary
    # ========================================================

    plus8_all_3_0 = (
        len(plus8_rows) > 0
        and all(
            r["signature"]
            == " 3;0"
            for r in plus8_rows
        )
    )

    plus8_exact = sum(
        1
        for r in plus8_rows
        if r["same_as_primary"]
    )

    aligned = sum(
        1
        for r in layout_rows
        if (
            int(
                r[
                    "offset_mod_0x800"
                ]
            )
            == 0
        )
    )

    needs_relocation = sum(
        1
        for r in type0_rows
        if (
            r[
                "fits_current_space"
            ]
            is False
        )
    )

    summary = (
        OUT
        / "stage12_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 12\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"FSTS members reparsed: "
            f"{len(member_rows)}\n"
        )

        f.write(
            f"Members with primary basename: "
            f"{total_name_matches}\n"
        )

        f.write(
            f"Exact decoded primary copies: "
            f"{total_exact}\n"
        )

        f.write(
            f"Remaining basename mismatches: "
            f"{len(mismatches)}\n\n"
        )

        f.write(
            f"zsize == size+8 members: "
            f"{len(plus8_rows)}\n"
        )

        f.write(
            f"size+8 members with 3;0 signature: "
            f"{sum(1 for r in plus8_rows if r['signature'] == ' 3;0')}\n"
        )

        f.write(
            f"All size+8 are 3;0: "
            f"{plus8_all_3_0}\n"
        )

        f.write(
            f"size+8 exact primary copies: "
            f"{plus8_exact}/"
            f"{len(plus8_rows)}\n\n"
        )

        f.write(
            f"FSTS member offsets 0x800 aligned: "
            f"{aligned}/"
            f"{len(layout_rows)}\n\n"
        )

        f.write(
            "Corrected codec countLOCAL_PATH"
        )

        for key, count in sorted(
            codec_counts.items()
        ):

            f.write(
                f"  {key[0]} "
                f"{key[1]}: "
                f"{count}\n"
            )

        f.write("\n")

        f.write(
            f"Translation primary resources "
            f"tested with 3;0 encoder: "
            f"{len(type0_rows)}\n"
        )

        f.write(
            f"3;0 roundtrip failures: "
            f"{sum(1 for r in type0_rows if not r['roundtrip_ok'])}\n"
        )

        f.write(
            f"Would exceed current stored slot: "
            f"{needs_relocation}/"
            f"{len(type0_rows)}\n"
        )

    print()
    print("=" * 72)
    print("STAGE 12 COMPLETE")
    print("=" * 72)

    print(
        "FSTS members:",
        len(member_rows)
    )

    print(
        "Exact primary copies:",
        total_exact
    )

    print(
        "Remaining mismatches:",
        len(mismatches)
    )

    print(
        "size+8:",
        len(plus8_rows)
    )

    print(
        "size+8 all 3;0:",
        plus8_all_3_0
    )

    print(
        "0x800 aligned:",
        aligned,
        "/",
        len(layout_rows)
    )

    print(
        "Type0 test resources:",
        len(type0_rows)
    )

    print(
        "Require relocation:",
        needs_relocation
    )

    print(
        "Output:",
        OUT
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:

        traceback.print_exc()
        sys.exit(1)
