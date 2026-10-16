#!/usr/bin/env python3
# Naruto PSP MOV03T - install final dm001..dm010 PMFs into a COPY of KR ISO
#
# Safe in-place ISO9660 extent patch:
# - NEVER modifies source KR ISO.
# - First checks each final PMF against the source file's existing sector allocation.
# - If every replacement fits, copies the source ISO to a new output ISO.
# - Overwrites each existing file extent, zero-fills remaining old allocation.
# - Updates ISO9660 directory record file size (LE + BE).
# - Re-opens the patched ISO and verifies every file SHA256 == final PMF.
#
# If ANY file does not fit, no patched ISO is created.

from __future__ import annotations
import csv, hashlib, math, os, shutil, struct, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
SRC_ISO = ROOT / "kr" / "Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
FINAL_DIR = ROOT / "analysis" / "mov" / "mov03s_final_batch" / "output"

STAGE = ROOT / "analysis" / "mov" / "mov03t_iso_install"
OUTDIR = STAGE / "output"
for p in (STAGE, OUTDIR):
    p.mkdir(parents=True, exist_ok=True)

OUT_ISO = OUTDIR / "Naruto_KR_MOV03S_KoreanMovies.iso"

SECTOR = 2048
TARGET_DIR = ["PSP_GAME", "USRDIR", "movie"]
MOVIES = [f"dm{i:03d}.pmf" for i in range(1, 11)]

def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def sha_region(f, offset, size):
    h = hashlib.sha256()
    f.seek(offset)
    remain = size
    while remain:
        b = f.read(min(remain, 1024 * 1024))
        if not b:
            break
        h.update(b)
        remain -= len(b)
    if remain:
        raise RuntimeError("Unexpected EOF while hashing ISO region")
    return h.hexdigest()

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def norm_iso_name(raw):
    # ISO9660 identifiers are normally uppercase and versioned as ;1.
    s = raw.decode("ascii", errors="replace")
    if ";" in s:
        s = s.split(";", 1)[0]
    return s.rstrip(".").lower()

def read_dir_entries(f, extent_lba, data_len):
    """
    Returns records with absolute directory-record offsets so file size fields
    can be patched later.
    """
    base = extent_lba * SECTOR
    f.seek(base)
    data = f.read(data_len)
    out = []
    pos = 0

    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            # Remaining bytes in this logical sector are padding.
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue
        if pos + rec_len > len(data):
            raise RuntimeError("Malformed ISO9660 directory record")

        rec = data[pos:pos+rec_len]
        if len(rec) < 34:
            raise RuntimeError("Short ISO9660 directory record")

        extent_le = struct.unpack_from("<I", rec, 2)[0]
        extent_be = struct.unpack_from(">I", rec, 6)[0]
        size_le = struct.unpack_from("<I", rec, 10)[0]
        size_be = struct.unpack_from(">I", rec, 14)[0]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33:33+name_len]

        if extent_le != extent_be or size_le != size_be:
            raise RuntimeError("ISO9660 endian-mirror mismatch")

        if name == b"\x00":
            disp = "."
        elif name == b"\x01":
            disp = ".."
        else:
            disp = norm_iso_name(name)

        out.append(dict(
            name=disp,
            extent=extent_le,
            size=size_le,
            flags=flags,
            is_dir=bool(flags & 0x02),
            record_offset=base + pos,
            record_len=rec_len,
        ))
        pos += rec_len
    return out

def pvd_root(f):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if len(pvd) != SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise RuntimeError("ISO9660 Primary Volume Descriptor not found")
    rec = pvd[156:]
    rec_len = rec[0]
    rec = rec[:rec_len]
    extent = struct.unpack_from("<I", rec, 2)[0]
    size = struct.unpack_from("<I", rec, 10)[0]
    return extent, size

def find_entry(f, path_parts):
    extent, size = pvd_root(f)
    current_path = []
    entry = None

    for idx, part in enumerate(path_parts):
        entries = read_dir_entries(f, extent, size)
        wanted = part.lower()
        matches = [e for e in entries if e["name"] == wanted]
        if not matches:
            raise FileNotFoundError("/".join(current_path + [part]))
        entry = matches[0]
        current_path.append(part)

        if idx < len(path_parts) - 1:
            if not entry["is_dir"]:
                raise RuntimeError("/".join(current_path) + " is not a directory")
            extent, size = entry["extent"], entry["size"]

    return entry

def patch_dir_record_size(f, record_offset, new_size):
    # Directory record:
    # +10..13 data length little-endian
    # +14..17 data length big-endian
    f.seek(record_offset + 10)
    f.write(struct.pack("<I", new_size))
    f.write(struct.pack(">I", new_size))

def main():
    # Remove stale failure marker from previous unrelated runs.
    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("=" * 80, flush=True)
    print(" Naruto PSP MOV03T - final movie ISO installer", flush=True)
    print("=" * 80, flush=True)
    print("Source ISO is READ-ONLY. Patched output is a separate ISO.", flush=True)

    if not SRC_ISO.exists():
        raise RuntimeError(f"Source ISO missing: {SRC_ISO}")

    for m in MOVIES:
        p = FINAL_DIR / m
        if not p.exists():
            raise RuntimeError(f"Final MOV03S PMF missing: {p}")

    rows = []
    entries = {}

    # PASS 1: inspect the original ISO only.
    with SRC_ISO.open("rb") as f:
        for movie in MOVIES:
            iso_path = TARGET_DIR + [movie]
            e = find_entry(f, iso_path)
            entries[movie] = e

            final = FINAL_DIR / movie
            final_size = final.stat().st_size
            alloc = math.ceil(e["size"] / SECTOR) * SECTOR
            fit = final_size <= alloc

            rows.append(dict(
                movie=movie,
                iso_path="/" + "/".join(iso_path),
                extent_lba=e["extent"],
                original_size=e["size"],
                allocated_bytes=alloc,
                final_size=final_size,
                delta_bytes=final_size - e["size"],
                spare_after_final=alloc - final_size,
                fit="YES" if fit else "NO",
                final_sha256=sha_file(final),
                status="CHECKED",
            ))

    all_fit = all(r["fit"] == "YES" for r in rows)
    write_tsv(STAGE / "iso_patch_report.tsv", rows)

    if not all_fit:
        nofit = [r["movie"] for r in rows if r["fit"] == "NO"]
        summary = [
            "Naruto PSP MOV03T - ISO install preflight",
            "=" * 80,
            "",
            "RESULT=NO PATCH",
            "Source ISO was NOT modified.",
            "Output ISO was NOT created.",
            "",
            "These final PMFs exceed their original ISO sector allocation:",
            "  " + ", ".join(nofit),
            "",
            "See iso_patch_report.tsv for exact sizes.",
            "",
            "A rebuild/relocation strategy is required instead of in-place extent patching.",
        ]
        (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
        print("\n".join(summary), flush=True)
        return 2

    # PASS 2: create a separate ISO copy.
    if OUT_ISO.exists():
        OUT_ISO.unlink()

    print(f"Copying source ISO -> {OUT_ISO}", flush=True)
    shutil.copyfile(SRC_ISO, OUT_ISO)

    # PASS 3: patch each extent and corresponding directory record.
    with OUT_ISO.open("r+b") as f:
        for r in rows:
            movie = r["movie"]
            e = entries[movie]
            final = FINAL_DIR / movie
            payload = final.read_bytes()
            alloc = int(r["allocated_bytes"])

            f.seek(e["extent"] * SECTOR)
            f.write(payload)

            remain = alloc - len(payload)
            zero = b"\x00" * min(SECTOR * 16, max(1, remain))
            while remain > 0:
                n = min(remain, len(zero))
                f.write(zero[:n])
                remain -= n

            patch_dir_record_size(f, e["record_offset"], len(payload))
            r["status"] = "PATCHED"

    # PASS 4: re-open output ISO, resolve paths again, verify sizes/extents/SHA.
    verify_ok = True
    with OUT_ISO.open("rb") as f:
        for r in rows:
            movie = r["movie"]
            e2 = find_entry(f, TARGET_DIR + [movie])
            expected_sha = r["final_sha256"]
            actual_sha = sha_region(f, e2["extent"] * SECTOR, e2["size"])

            r["verified_iso_size"] = e2["size"]
            r["verified_extent_lba"] = e2["extent"]
            r["verified_sha256"] = actual_sha
            r["size_match"] = "YES" if e2["size"] == int(r["final_size"]) else "NO"
            r["extent_unchanged"] = "YES" if e2["extent"] == int(r["extent_lba"]) else "NO"
            r["sha_match"] = "YES" if actual_sha == expected_sha else "NO"

            ok = (
                r["size_match"] == "YES"
                and r["extent_unchanged"] == "YES"
                and r["sha_match"] == "YES"
            )
            r["status"] = "PASS" if ok else "FAIL"
            if not ok:
                verify_ok = False

    write_tsv(STAGE / "iso_patch_report.tsv", rows)

    if not verify_ok:
        raise RuntimeError("Patched ISO verification failed; see iso_patch_report.tsv")

    out_size = OUT_ISO.stat().st_size
    src_size = SRC_ISO.stat().st_size

    summary = [
        "Naruto PSP MOV03T - final movie ISO installer",
        "=" * 80,
        "",
        "RESULT=PASS",
        "10/10 final PMFs installed into a COPY of the KR ISO.",
        "",
        "Safety:",
        "  Source KR ISO was not modified.",
        "  Existing file extents/LBAs were preserved.",
        "  Every replacement fit inside its original sector allocation.",
        "  ISO9660 file sizes were updated.",
        "  10/10 embedded file SHA256 values match MOV03S outputs.",
        "",
        f"Source ISO size={src_size}",
        f"Output ISO size={out_size}",
        f"Output ISO={OUT_ISO}",
        "",
        "Next validation:",
        "  boot this ISO in PPSSPP and play one or more DM cutscenes.",
    ]
    (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        (STAGE / "FAILURE.txt").write_text(tb, encoding="utf-8-sig")
        print(tb, file=sys.stderr, flush=True)
        raise SystemExit(1)
