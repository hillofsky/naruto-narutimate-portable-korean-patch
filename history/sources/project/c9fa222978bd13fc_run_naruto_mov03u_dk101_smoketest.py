#!/usr/bin/env python3
# Naruto PSP MOV03U - early-cutscene smoke ISO
#
# Purpose:
#   Replace early dk101.pmf slot with FINAL dm001.pmf in a COPY of the
#   already-patched MOV03T ISO, so final PMF playback can be tested almost
#   immediately in-game.
#
# This is ONLY a temporary smoke-test ISO.
#
# Base ISO:
#   MOV03T final patched ISO
#
# Replacement:
#   /PSP_GAME/USRDIR/movie/dk101.pmf
#       <- MOV03S final dm001.pmf
#
# Safety:
# - Never modifies MOV03T ISO.
# - Checks dm001 fits dk101's existing ISO sector allocation first.
# - Keeps dk101 LBA/extent unchanged.
# - Updates only dk101 ISO9660 file-size field.
# - Verifies embedded SHA256 == source dm001 final PMF.

from __future__ import annotations
import csv, hashlib, math, shutil, struct, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")

BASE_ISO = ROOT / "analysis" / "mov" / "mov03t_iso_install" / "output" / "Naruto_KR_MOV03S_KoreanMovies.iso"
FINAL_DM001 = ROOT / "analysis" / "mov" / "mov03s_final_batch" / "output" / "dm001.pmf"

STAGE = ROOT / "analysis" / "mov" / "mov03u_dk101_smoketest"
OUTDIR = STAGE / "output"
OUTDIR.mkdir(parents=True, exist_ok=True)

OUT_ISO = OUTDIR / "Naruto_KR_MOV03U_dk101_as_dm001_smoketest.iso"

SECTOR = 2048
TARGET_PATH = ["PSP_GAME", "USRDIR", "movie", "dk101.pmf"]

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

def write_tsv(path, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def norm_name(raw):
    s = raw.decode("ascii", errors="replace")
    if ";" in s:
        s = s.split(";", 1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if len(pvd) != SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise RuntimeError("ISO9660 PVD not found")
    rec = pvd[156:]
    rec = rec[:rec[0]]
    extent = struct.unpack_from("<I", rec, 2)[0]
    size = struct.unpack_from("<I", rec, 10)[0]
    return extent, size

def read_dir(f, extent, size):
    base = extent * SECTOR
    f.seek(base)
    data = f.read(size)
    out = []
    pos = 0

    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue
        if pos + rec_len > len(data):
            raise RuntimeError("Malformed ISO9660 directory record")

        rec = data[pos:pos+rec_len]
        ext_le = struct.unpack_from("<I", rec, 2)[0]
        ext_be = struct.unpack_from(">I", rec, 6)[0]
        sz_le = struct.unpack_from("<I", rec, 10)[0]
        sz_be = struct.unpack_from(">I", rec, 14)[0]
        if ext_le != ext_be or sz_le != sz_be:
            raise RuntimeError("ISO9660 endian mirror mismatch")

        flags = rec[25]
        nlen = rec[32]
        raw = rec[33:33+nlen]

        if raw == b"\x00":
            name = "."
        elif raw == b"\x01":
            name = ".."
        else:
            name = norm_name(raw)

        out.append(dict(
            name=name,
            extent=ext_le,
            size=sz_le,
            is_dir=bool(flags & 0x02),
            record_offset=base + pos,
        ))
        pos += rec_len

    return out

def find_entry(f, parts):
    extent, size = pvd_root(f)
    entry = None

    for i, part in enumerate(parts):
        entries = read_dir(f, extent, size)
        matches = [e for e in entries if e["name"] == part.lower()]
        if not matches:
            raise FileNotFoundError("/" + "/".join(parts[:i+1]))
        entry = matches[0]

        if i < len(parts) - 1:
            if not entry["is_dir"]:
                raise RuntimeError(f"{part} is not a directory")
            extent, size = entry["extent"], entry["size"]

    return entry

def patch_size(f, record_offset, new_size):
    f.seek(record_offset + 10)
    f.write(struct.pack("<I", new_size))
    f.write(struct.pack(">I", new_size))

def main():
    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("=" * 80, flush=True)
    print(" Naruto PSP MOV03U - dk101 early final-PMF smoke test", flush=True)
    print("=" * 80, flush=True)

    if not BASE_ISO.exists():
        raise RuntimeError(f"MOV03T patched ISO missing: {BASE_ISO}")
    if not FINAL_DM001.exists():
        raise RuntimeError(f"MOV03S final dm001 missing: {FINAL_DM001}")

    dm_size = FINAL_DM001.stat().st_size
    dm_sha = sha_file(FINAL_DM001)

    # Preflight against dk101's existing allocation.
    with BASE_ISO.open("rb") as f:
        dk = find_entry(f, TARGET_PATH)
        allocation = math.ceil(dk["size"] / SECTOR) * SECTOR

    fit = dm_size <= allocation

    row = dict(
        target="/PSP_GAME/USRDIR/movie/dk101.pmf",
        source_final_pmf=str(FINAL_DM001),
        dk101_extent_lba=dk["extent"],
        dk101_original_size=dk["size"],
        dk101_allocated_bytes=allocation,
        dm001_final_size=dm_size,
        spare_after_patch=allocation - dm_size,
        fit="YES" if fit else "NO",
        dm001_sha256=dm_sha,
    )

    if not fit:
        row["status"] = "NO_PATCH"
        write_tsv(STAGE / "smoke_patch_report.tsv", [row])
        summary = [
            "Naruto PSP MOV03U",
            "=" * 80,
            "",
            "RESULT=NO PATCH",
            "dm001 final PMF does not fit inside dk101's existing sector allocation.",
            "No smoke-test ISO was created.",
            "",
            f"dk101 allocation={allocation}",
            f"dm001 size={dm_size}",
        ]
        (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
        print("\n".join(summary), flush=True)
        return 2

    if OUT_ISO.exists():
        OUT_ISO.unlink()

    print("Preflight: FIT=YES", flush=True)
    print(f"Copying base ISO -> {OUT_ISO}", flush=True)
    shutil.copyfile(BASE_ISO, OUT_ISO)

    # Patch dk101 extent with final dm001.
    payload = FINAL_DM001.read_bytes()
    with OUT_ISO.open("r+b") as f:
        dk2 = find_entry(f, TARGET_PATH)

        if dk2["extent"] != dk["extent"]:
            raise RuntimeError("dk101 extent changed unexpectedly")

        f.seek(dk2["extent"] * SECTOR)
        f.write(payload)

        remain = allocation - len(payload)
        zero = b"\x00" * min(32768, max(1, remain))
        while remain > 0:
            n = min(remain, len(zero))
            f.write(zero[:n])
            remain -= n

        patch_size(f, dk2["record_offset"], len(payload))

    # Verify by reopening ISO.
    with OUT_ISO.open("rb") as f:
        ve = find_entry(f, TARGET_PATH)
        embedded_sha = sha_region(f, ve["extent"] * SECTOR, ve["size"])

    row.update(
        patched_iso=str(OUT_ISO),
        verified_size=ve["size"],
        verified_extent_lba=ve["extent"],
        extent_unchanged="YES" if ve["extent"] == dk["extent"] else "NO",
        size_match="YES" if ve["size"] == dm_size else "NO",
        embedded_sha256=embedded_sha,
        sha_match="YES" if embedded_sha == dm_sha else "NO",
    )

    ok = (
        row["extent_unchanged"] == "YES"
        and row["size_match"] == "YES"
        and row["sha_match"] == "YES"
    )
    row["status"] = "PASS" if ok else "FAIL"
    write_tsv(STAGE / "smoke_patch_report.tsv", [row])

    if not ok:
        raise RuntimeError("Smoke ISO verification failed")

    summary = [
        "Naruto PSP MOV03U - dk101 early final-PMF smoke test",
        "=" * 80,
        "",
        "RESULT=PASS",
        "",
        "Temporary test substitution:",
        "  dk101.pmf slot -> MOV03S final dm001.pmf",
        "",
        "What this tests in-game:",
        "  PSP PMF container compatibility",
        "  Korean burned subtitle playback",
        "  KR original Japanese ATRAC3+ playback",
        "  video/audio synchronization",
        "  return-to-game behavior after the movie ends",
        "",
        "This ISO is ONLY for smoke testing.",
        "The normal MOV03T ISO remains untouched.",
        "",
        f"Output ISO={OUT_ISO}",
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
