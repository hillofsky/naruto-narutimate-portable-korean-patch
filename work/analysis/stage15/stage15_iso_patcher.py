from pathlib import Path
import argparse
import csv
import hashlib
import math
import os
import shutil
import struct
import sys
import traceback


SECTOR = 2048


def align_up(v, a=SECTOR):
    return (v + a - 1) & ~(a - 1)


def le32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def both32_set(buf, off, value):
    struct.pack_into(
        "<I",
        buf,
        off,
        value
    )

    struct.pack_into(
        ">I",
        buf,
        off + 4,
        value
    )


def sha256_file(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            b = f.read(
                4 * 1024 * 1024
            )

            if not b:
                break

            h.update(b)

    return h.hexdigest()


def sha256_extent(
    f,
    lba,
    size
):
    h = hashlib.sha256()

    f.seek(
        lba * SECTOR
    )

    remain = size

    while remain:
        b = f.read(
            min(
                remain,
                4 * 1024 * 1024
            )
        )

        if not b:
            raise RuntimeError(
                "Unexpected EOF "
                "while hashing extent"
            )

        h.update(b)
        remain -= len(b)

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


# ============================================================
# ISO9660 directory record
# ============================================================

def decode_identifier(
    raw,
    joliet
):
    if raw == b"\x00":
        return "."

    if raw == b"\x01":
        return ".."

    if joliet:
        try:
            text = raw.decode(
                "utf-16-be"
            )
        except Exception:
            text = raw.decode(
                "latin1",
                errors="replace"
            )

    else:
        text = raw.decode(
            "ascii",
            errors="replace"
        )

    # ISO file version suffix
    if ";" in text:
        text = text.split(
            ";",
            1
        )[0]

    return text


def parse_dir_record(
    record,
    absolute_offset,
    joliet
):
    if len(record) < 34:
        raise RuntimeError(
            "Short ISO directory record"
        )

    extent = le32(
        record,
        2
    )

    size = le32(
        record,
        10
    )

    flags = record[25]

    id_len = record[32]

    if (
        33 + id_len
        > len(record)
    ):
        raise RuntimeError(
            "Bad ISO identifier length"
        )

    raw_name = record[
        33:
        33 + id_len
    ]

    name = decode_identifier(
        raw_name,
        joliet
    )

    return {
        "record_offset":
            absolute_offset,

        "extent":
            extent,

        "size":
            size,

        "flags":
            flags,

        "is_dir":
            bool(flags & 0x02),

        "name":
            name,
    }


def iter_directory(
    f,
    extent,
    size,
    joliet
):
    start = (
        extent * SECTOR
    )

    read_size = align_up(
        size
    )

    f.seek(start)

    data = f.read(
        read_size
    )

    if len(data) < size:
        raise RuntimeError(
            "Directory extent short read"
        )

    pos = 0

    while pos < size:
        rec_len = data[pos]

        if rec_len == 0:
            # End of sector padding.
            pos = (
                (pos // SECTOR) + 1
            ) * SECTOR

            continue

        if (
            pos + rec_len
            > len(data)
        ):
            raise RuntimeError(
                "Directory record outside "
                "directory extent"
            )

        rec = data[
            pos:
            pos + rec_len
        ]

        yield parse_dir_record(
            rec,
            start + pos,
            joliet
        )

        pos += rec_len


# ============================================================
# Volume descriptors
# ============================================================

def read_volume_descriptors(f):
    descriptors = []

    sector = 16

    while True:
        f.seek(
            sector * SECTOR
        )

        data = f.read(
            SECTOR
        )

        if len(data) != SECTOR:
            raise RuntimeError(
                "ISO volume descriptor "
                "short read"
            )

        vd_type = data[0]

        if data[1:6] != b"CD001":
            raise RuntimeError(
                f"Invalid volume descriptor "
                f"at sector {sector}"
            )

        version = data[6]

        if vd_type in (1, 2):
            escape = data[
                88:91
            ]

            joliet = (
                vd_type == 2
                and escape in (
                    b"%/@",
                    b"%/C",
                    b"%/E",
                )
            )

            root_len = data[156]

            root_raw = data[
                156:
                156 + root_len
            ]

            root = parse_dir_record(
                root_raw,
                sector * SECTOR + 156,
                joliet
            )

            descriptors.append({
                "sector":
                    sector,

                "type":
                    vd_type,

                "joliet":
                    joliet,

                "root":
                    root,

                "volume_space":
                    le32(
                        data,
                        80
                    ),
            })

        if vd_type == 255:
            break

        sector += 1

        if sector > 128:
            raise RuntimeError(
                "Volume descriptor "
                "terminator not found"
            )

    return descriptors


def find_path(
    f,
    descriptor,
    components
):
    current = descriptor[
        "root"
    ]

    for component in components:
        if not current[
            "is_dir"
        ]:
            raise RuntimeError(
                f"Not a directory before "
                f"{component}"
            )

        found = None

        for rec in iter_directory(
            f,
            current["extent"],
            current["size"],
            descriptor["joliet"]
        ):
            if rec["name"] in (
                ".",
                ".."
            ):
                continue

            if (
                rec["name"].casefold()
                ==
                component.casefold()
            ):
                found = rec
                break

        if found is None:
            return None

        current = found

    return current


# ============================================================
# ISO record patch
# ============================================================

def patch_directory_record(
    f,
    record_offset,
    new_lba,
    new_size
):
    f.seek(
        record_offset
    )

    rec_len_raw = f.read(1)

    if not rec_len_raw:
        raise RuntimeError(
            "Cannot read ISO record"
        )

    rec_len = rec_len_raw[0]

    f.seek(
        record_offset
    )

    rec = bytearray(
        f.read(rec_len)
    )

    if len(rec) != rec_len:
        raise RuntimeError(
            "Short ISO record"
        )

    # Extent location:
    # LE 4 + BE 4
    both32_set(
        rec,
        2,
        new_lba
    )

    # File byte length:
    # LE 4 + BE 4
    both32_set(
        rec,
        10,
        new_size
    )

    f.seek(
        record_offset
    )

    f.write(rec)


def update_volume_space(
    f,
    descriptors,
    sectors
):
    for vd in descriptors:
        off = (
            vd["sector"]
            * SECTOR
            + 80
        )

        f.seek(off)

        buf = bytearray(
            f.read(8)
        )

        if len(buf) != 8:
            raise RuntimeError(
                "Cannot read "
                "volume space field"
            )

        both32_set(
            buf,
            0,
            sectors
        )

        f.seek(off)
        f.write(buf)


# ============================================================
# Copy source ISO with progress
# ============================================================

def copy_iso(
    src,
    dst
):
    total = src.stat().st_size

    copied = 0
    next_report = 64 * 1024 * 1024

    with (
        src.open("rb") as fi,
        dst.open("wb") as fo
    ):
        while True:
            b = fi.read(
                8 * 1024 * 1024
            )

            if not b:
                break

            fo.write(b)

            copied += len(b)

            if (
                copied >= next_report
                or copied == total
            ):
                pct = (
                    copied
                    * 100.0
                    / total
                )

                print(
                    f"[ISO copy] "
                    f"{copied // (1024*1024)}"
                    f"/"
                    f"{total // (1024*1024)} MB "
                    f"({pct:.1f}%)"
                )

                next_report += (
                    64
                    * 1024
                    * 1024
                )


def append_file_sector_aligned(
    iso,
    source_file,
    label
):
    iso.seek(
        0,
        os.SEEK_END
    )

    end = iso.tell()

    aligned = align_up(end)

    if aligned > end:
        iso.write(
            b"\0"
            * (
                aligned - end
            )
        )

    start = iso.tell()

    if start % SECTOR:
        raise RuntimeError(
            "ISO append offset "
            "not sector aligned"
        )

    lba = (
        start // SECTOR
    )

    total = (
        source_file.stat().st_size
    )

    written = 0
    next_report = (
        32
        * 1024
        * 1024
    )

    with source_file.open(
        "rb"
    ) as f:

        while True:
            b = f.read(
                8 * 1024 * 1024
            )

            if not b:
                break

            iso.write(b)

            written += len(b)

            if (
                written >= next_report
                or written == total
            ):
                pct = (
                    written
                    * 100.0
                    / total
                )

                print(
                    f"[append {label}] "
                    f"{written // (1024*1024)}"
                    f"/"
                    f"{max(1,total // (1024*1024))} MB "
                    f"({pct:.1f}%)"
                )

                next_report += (
                    32
                    * 1024
                    * 1024
                )

    if written != total:
        raise RuntimeError(
            f"{label}: append size mismatch"
        )

    padded = align_up(
        iso.tell()
    )

    if padded > iso.tell():
        iso.write(
            b"\0"
            * (
                padded
                - iso.tell()
            )
        )

    return {
        "lba": lba,
        "size": total,
        "padded_end":
            padded,
    }


# ============================================================
# Main patch
# ============================================================

def patch_iso(
    source_iso,
    replacement_dat,
    replacement_idx,
    output_iso,
    report_dir
):
    print("=" * 72)
    print("Naruto PSP Stage 15")
    print("ISO9660 automatic file relocation")
    print("=" * 72)

    if not source_iso.exists():
        raise RuntimeError(
            f"Source ISO 없음: "
            f"{source_iso}"
        )

    if not replacement_dat.exists():
        raise RuntimeError(
            f"Patched DAT 없음: "
            f"{replacement_dat}"
        )

    if not replacement_idx.exists():
        raise RuntimeError(
            f"Patched IDX 없음: "
            f"{replacement_idx}"
        )

    report_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_iso.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if output_iso.exists():
        output_iso.unlink()

    print()
    print("[1/5] 원본 ISO 복사")

    copy_iso(
        source_iso,
        output_iso
    )

    old_iso_size = (
        source_iso.stat().st_size
    )

    old_sector_count = (
        math.ceil(
            old_iso_size / SECTOR
        )
    )

    # --------------------------------------------------------
    # Inspect paths before patch.
    # --------------------------------------------------------

    with output_iso.open(
        "r+b"
    ) as iso:

        descriptors = (
            read_volume_descriptors(
                iso
            )
        )

        filesystem_rows = []

        targets = {}

        paths = {
            "naruto.dat": [
                "PSP_GAME",
                "USRDIR",
                "naruto.dat",
            ],

            "naruto.idx": [
                "PSP_GAME",
                "USRDIR",
                "naruto.idx",
            ],
        }

        print()
        print(
            "[2/5] ISO9660/Joliet "
            "디렉터리 탐색"
        )

        for vd in descriptors:
            if vd["type"] not in (
                1,
                2
            ):
                continue

            fs_name = (
                "Joliet"
                if vd["joliet"]
                else (
                    "PVD"
                    if vd["type"] == 1
                    else "SVD"
                )
            )

            for key, path in (
                paths.items()
            ):
                rec = find_path(
                    iso,
                    vd,
                    path
                )

                filesystem_rows.append({
                    "filesystem":
                        fs_name,

                    "descriptor_sector":
                        vd["sector"],

                    "target":
                        key,

                    "found":
                        rec is not None,

                    "old_lba":
                        (
                            rec["extent"]
                            if rec
                            else ""
                        ),

                    "old_size":
                        (
                            rec["size"]
                            if rec
                            else ""
                        ),

                    "record_offset":
                        (
                            f"0x"
                            f"{rec['record_offset']:X}"
                            if rec
                            else ""
                        ),
                })

                if rec is not None:
                    targets.setdefault(
                        key,
                        []
                    ).append({
                        "descriptor":
                            vd,

                        "record":
                            rec,
                    })

        # Primary ISO9660 must contain both.
        pvd_targets = {
            k: [
                x
                for x in v
                if (
                    x[
                        "descriptor"
                    ]["type"] == 1
                )
            ]
            for k, v
            in targets.items()
        }

        if not pvd_targets.get(
            "naruto.dat"
        ):
            raise RuntimeError(
                "PVD에서 naruto.dat "
                "찾지 못함"
            )

        if not pvd_targets.get(
            "naruto.idx"
        ):
            raise RuntimeError(
                "PVD에서 naruto.idx "
                "찾지 못함"
            )

        print(
            "Descriptors:",
            len(descriptors)
        )

        print(
            "naruto.dat records:",
            len(
                targets[
                    "naruto.dat"
                ]
            )
        )

        print(
            "naruto.idx records:",
            len(
                targets[
                    "naruto.idx"
                ]
            )
        )

        # ----------------------------------------------------
        # Append new files.
        # ----------------------------------------------------

        print()
        print(
            "[3/5] 패치 DAT/IDX "
            "ISO 끝에 추가"
        )

        dat_new = (
            append_file_sector_aligned(
                iso,
                replacement_dat,
                "naruto.dat"
            )
        )

        idx_new = (
            append_file_sector_aligned(
                iso,
                replacement_idx,
                "naruto.idx"
            )
        )

        print(
            "new DAT LBA:",
            dat_new["lba"]
        )

        print(
            "new IDX LBA:",
            idx_new["lba"]
        )

        # ----------------------------------------------------
        # Patch all discoverable directory records.
        # ----------------------------------------------------

        print()
        print(
            "[4/5] ISO 디렉터리 "
            "레코드 갱신"
        )

        for item in targets[
            "naruto.dat"
        ]:
            patch_directory_record(
                iso,
                item[
                    "record"
                ]["record_offset"],
                dat_new["lba"],
                dat_new["size"]
            )

        for item in targets[
            "naruto.idx"
        ]:
            patch_directory_record(
                iso,
                item[
                    "record"
                ]["record_offset"],
                idx_new["lba"],
                idx_new["size"]
            )

        iso.flush()

        final_size = (
            iso.seek(
                0,
                os.SEEK_END
            )
            or iso.tell()
        )

        # Python seek returns position.
        final_size = iso.tell()

        if final_size % SECTOR:
            raise RuntimeError(
                "Final ISO not sector aligned"
            )

        final_sectors = (
            final_size // SECTOR
        )

        update_volume_space(
            iso,
            descriptors,
            final_sectors
        )

        iso.flush()

    # --------------------------------------------------------
    # Self-validation using primary ISO9660.
    # --------------------------------------------------------

    print()
    print(
        "[5/5] 완성 ISO 재추출 검증"
    )

    validation_rows = []

    with output_iso.open(
        "rb"
    ) as iso:

        descriptors_after = (
            read_volume_descriptors(
                iso
            )
        )

        pvd = next(
            x
            for x in descriptors_after
            if x["type"] == 1
        )

        rec_dat = find_path(
            iso,
            pvd,
            paths["naruto.dat"]
        )

        rec_idx = find_path(
            iso,
            pvd,
            paths["naruto.idx"]
        )

        if rec_dat is None:
            raise RuntimeError(
                "Patched ISO DAT path missing"
            )

        if rec_idx is None:
            raise RuntimeError(
                "Patched ISO IDX path missing"
            )

        expected_dat_hash = (
            sha256_file(
                replacement_dat
            )
        )

        expected_idx_hash = (
            sha256_file(
                replacement_idx
            )
        )

        actual_dat_hash = (
            sha256_extent(
                iso,
                rec_dat["extent"],
                rec_dat["size"]
            )
        )

        actual_idx_hash = (
            sha256_extent(
                iso,
                rec_idx["extent"],
                rec_idx["size"]
            )
        )

        validation_rows.append({
            "target":
                "naruto.dat",

            "expected_lba":
                dat_new["lba"],

            "actual_lba":
                rec_dat["extent"],

            "expected_size":
                replacement_dat
                .stat()
                .st_size,

            "actual_size":
                rec_dat["size"],

            "expected_sha256":
                expected_dat_hash,

            "actual_sha256":
                actual_dat_hash,

            "ok":
                (
                    rec_dat["extent"]
                    == dat_new["lba"]
                    and
                    rec_dat["size"]
                    ==
                    replacement_dat
                    .stat()
                    .st_size
                    and
                    actual_dat_hash
                    ==
                    expected_dat_hash
                ),
        })

        validation_rows.append({
            "target":
                "naruto.idx",

            "expected_lba":
                idx_new["lba"],

            "actual_lba":
                rec_idx["extent"],

            "expected_size":
                replacement_idx
                .stat()
                .st_size,

            "actual_size":
                rec_idx["size"],

            "expected_sha256":
                expected_idx_hash,

            "actual_sha256":
                actual_idx_hash,

            "ok":
                (
                    rec_idx["extent"]
                    == idx_new["lba"]
                    and
                    rec_idx["size"]
                    ==
                    replacement_idx
                    .stat()
                    .st_size
                    and
                    actual_idx_hash
                    ==
                    expected_idx_hash
                ),
        })

        volume_ok = (
            pvd["volume_space"]
            ==
            output_iso
            .stat()
            .st_size
            // SECTOR
        )

    if not all(
        x["ok"]
        for x in validation_rows
    ):
        raise RuntimeError(
            "ISO extraction validation failed"
        )

    if not volume_ok:
        raise RuntimeError(
            "ISO volume space size mismatch"
        )

    # --------------------------------------------------------
    # Reports
    # --------------------------------------------------------

    write_tsv(
        report_dir
        / "iso_filesystem_records.tsv",
        filesystem_rows,
        [
            "filesystem",
            "descriptor_sector",
            "target",
            "found",
            "old_lba",
            "old_size",
            "record_offset",
        ]
    )

    write_tsv(
        report_dir
        / "iso_validation.tsv",
        validation_rows,
        [
            "target",
            "expected_lba",
            "actual_lba",
            "expected_size",
            "actual_size",
            "expected_sha256",
            "actual_sha256",
            "ok",
        ]
    )

    new_iso_size = (
        output_iso.stat().st_size
    )

    summary = (
        report_dir
        / "stage15_summary.txt"
    )

    with summary.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "Naruto PSP Stage 15\n"
        )

        f.write(
            "=" * 72
            + "\n\n"
        )

        f.write(
            f"Source ISO: "
            f"{source_iso}\n"
        )

        f.write(
            f"Patched ISO: "
            f"{output_iso}\n\n"
        )

        f.write(
            f"Original ISO size: "
            f"{old_iso_size}\n"
        )

        f.write(
            f"Patched ISO size: "
            f"{new_iso_size}\n"
        )

        f.write(
            f"Growth: "
            f"{new_iso_size - old_iso_size}\n\n"
        )

        f.write(
            f"Original sectors: "
            f"{old_sector_count}\n"
        )

        f.write(
            f"Patched sectors: "
            f"{new_iso_size // SECTOR}\n\n"
        )

        f.write(
            f"New DAT LBA: "
            f"{dat_new['lba']}\n"
        )

        f.write(
            f"New DAT size: "
            f"{dat_new['size']}\n"
        )

        f.write(
            f"New IDX LBA: "
            f"{idx_new['lba']}\n"
        )

        f.write(
            f"New IDX size: "
            f"{idx_new['size']}\n\n"
        )

        f.write(
            f"ISO SHA256: "
            f"{sha256_file(output_iso)}\n\n"
        )

        f.write(
            "DAT extraction validation: PASS\n"
        )

        f.write(
            "IDX extraction validation: PASS\n"
        )

        f.write(
            "Volume size validation: PASS\n"
        )

        f.write(
            "SELF VALIDATION: PASS\n"
        )

    print()
    print("=" * 72)
    print("STAGE 15 COMPLETE")
    print("=" * 72)

    print(
        "Patched ISO:",
        output_iso
    )

    print(
        "ISO size:",
        new_iso_size
    )

    print(
        "DAT extraction: PASS"
    )

    print(
        "IDX extraction: PASS"
    )

    print(
        "Volume descriptor: PASS"
    )

    print(
        "SELF VALIDATION: PASS"
    )


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--source-iso",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--dat",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--idx",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--output-iso",
        type=Path,
        required=True
    )

    ap.add_argument(
        "--report-dir",
        type=Path,
        required=True
    )

    args = ap.parse_args()

    patch_iso(
        args.source_iso.resolve(),
        args.dat.resolve(),
        args.idx.resolve(),
        args.output_iso.resolve(),
        args.report_dir.resolve()
    )


if __name__ == "__main__":
    try:
        main()

    except Exception:
        traceback.print_exc()
        sys.exit(1)
