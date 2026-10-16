#!/usr/bin/env python3
# Naruto PSP MOV04D - install MOV04C final DA/DK movies into the MOV03T final ISO
#
# Base ISO already contains translated dm001..dm010 from MOV03T.
# This stage adds:
#   da101 da201 dk101 dk102 dk202
#
# Safety:
# - Never modifies the MOV03T base ISO.
# - Preflights all five replacements against existing sector allocation.
# - Keeps each file's LBA/extent unchanged.
# - Updates ISO9660 file-size fields.
# - Verifies embedded SHA256 == MOV04C final PMF for all five.

from __future__ import annotations
import csv, hashlib, math, shutil, struct, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")

BASE_ISO = ROOT / "analysis" / "mov" / "mov03t_iso_install" / "output" / "Naruto_KR_MOV03S_KoreanMovies.iso"
FINAL_DIR = ROOT / "analysis" / "mov" / "mov04c_final_batch" / "output"

STAGE = ROOT / "analysis" / "mov" / "mov04d_integrated_iso"
OUTDIR = STAGE / "output"
OUTDIR.mkdir(parents=True, exist_ok=True)

OUT_ISO = OUTDIR / "Naruto_KR_MOV04D_AllTranslatedMovies.iso"

SECTOR = 2048
TARGET_DIR = ["PSP_GAME", "USRDIR", "movie"]
MOVIES = ["da101.pmf","da201.pmf","dk101.pmf","dk102.pmf","dk202.pmf"]

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def sha_region(f, offset, size):
    h=hashlib.sha256()
    f.seek(offset)
    remain=size
    while remain:
        b=f.read(min(remain,1024*1024))
        if not b: break
        h.update(b)
        remain-=len(b)
    if remain:
        raise RuntimeError("Unexpected EOF while hashing ISO region")
    return h.hexdigest()

def write_tsv(path, rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def norm_name(raw):
    s=raw.decode("ascii",errors="replace")
    if ";" in s:
        s=s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR)
    pvd=f.read(SECTOR)
    if len(pvd)!=SECTOR or pvd[0]!=1 or pvd[1:6]!=b"CD001":
        raise RuntimeError("ISO9660 PVD not found")
    rec=pvd[156:]
    rec=rec[:rec[0]]
    return struct.unpack_from("<I",rec,2)[0], struct.unpack_from("<I",rec,10)[0]

def read_dir(f, extent, size):
    base=extent*SECTOR
    f.seek(base)
    data=f.read(size)
    out=[]
    pos=0
    while pos<len(data):
        rec_len=data[pos]
        if rec_len==0:
            pos=((pos//SECTOR)+1)*SECTOR
            continue
        if pos+rec_len>len(data):
            raise RuntimeError("Malformed ISO9660 directory record")
        rec=data[pos:pos+rec_len]
        ext_le=struct.unpack_from("<I",rec,2)[0]
        ext_be=struct.unpack_from(">I",rec,6)[0]
        sz_le=struct.unpack_from("<I",rec,10)[0]
        sz_be=struct.unpack_from(">I",rec,14)[0]
        if ext_le!=ext_be or sz_le!=sz_be:
            raise RuntimeError("ISO9660 endian mirror mismatch")
        flags=rec[25]
        nlen=rec[32]
        raw=rec[33:33+nlen]
        if raw==b"\x00": name="."
        elif raw==b"\x01": name=".."
        else: name=norm_name(raw)
        out.append(dict(
            name=name, extent=ext_le, size=sz_le,
            is_dir=bool(flags&2), record_offset=base+pos
        ))
        pos+=rec_len
    return out

def find_entry(f, parts):
    extent,size=pvd_root(f)
    entry=None
    for i,part in enumerate(parts):
        entries=read_dir(f,extent,size)
        matches=[e for e in entries if e["name"]==part.lower()]
        if not matches:
            raise FileNotFoundError("/"+"/".join(parts[:i+1]))
        entry=matches[0]
        if i<len(parts)-1:
            if not entry["is_dir"]:
                raise RuntimeError(part+" is not a directory")
            extent,size=entry["extent"],entry["size"]
    return entry

def patch_size(f, record_offset, new_size):
    f.seek(record_offset+10)
    f.write(struct.pack("<I",new_size))
    f.write(struct.pack(">I",new_size))

def main():
    failure=STAGE/"FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV04D - integrated translated movie ISO",flush=True)
    print("="*80,flush=True)

    if not BASE_ISO.exists():
        raise RuntimeError(f"MOV03T base ISO missing: {BASE_ISO}")

    for m in MOVIES:
        p=FINAL_DIR/m
        if not p.exists():
            raise RuntimeError(f"MOV04C final PMF missing: {p}")

    rows=[]
    entries={}

    # Preflight all five against current allocation in MOV03T base ISO.
    with BASE_ISO.open("rb") as f:
        for m in MOVIES:
            e=find_entry(f,TARGET_DIR+[m])
            entries[m]=e
            src=FINAL_DIR/m
            final_size=src.stat().st_size
            alloc=math.ceil(e["size"]/SECTOR)*SECTOR
            fit=final_size<=alloc
            rows.append(dict(
                movie=m,
                extent_lba=e["extent"],
                base_file_size=e["size"],
                allocated_bytes=alloc,
                final_size=final_size,
                delta_bytes=final_size-e["size"],
                spare_after_final=alloc-final_size,
                fit="YES" if fit else "NO",
                final_sha256=sha_file(src),
                status="CHECKED",
            ))

    write_tsv(STAGE/"iso_patch_report.tsv",rows)

    if not all(r["fit"]=="YES" for r in rows):
        bad=[r["movie"] for r in rows if r["fit"]=="NO"]
        summary=[
            "Naruto PSP MOV04D",
            "="*80,"",
            "RESULT=NO PATCH",
            "MOV03T base ISO was NOT modified.",
            "No integrated ISO was created.",
            "",
            "Files exceeding current allocation:",
            "  "+", ".join(bad),
            "",
            "See iso_patch_report.tsv.",
        ]
        (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
        print("\n".join(summary),flush=True)
        return 2

    if OUT_ISO.exists():
        OUT_ISO.unlink()

    print(f"Copying MOV03T base ISO -> {OUT_ISO}",flush=True)
    shutil.copyfile(BASE_ISO,OUT_ISO)

    with OUT_ISO.open("r+b") as f:
        for r in rows:
            m=r["movie"]
            e=entries[m]
            payload=(FINAL_DIR/m).read_bytes()
            alloc=int(r["allocated_bytes"])

            f.seek(e["extent"]*SECTOR)
            f.write(payload)

            remain=alloc-len(payload)
            block=b"\x00"*min(32768,max(1,remain))
            while remain>0:
                n=min(remain,len(block))
                f.write(block[:n])
                remain-=n

            patch_size(f,e["record_offset"],len(payload))
            r["status"]="PATCHED"

    # Re-open and verify every embedded replacement.
    all_ok=True
    with OUT_ISO.open("rb") as f:
        for r in rows:
            m=r["movie"]
            e2=find_entry(f,TARGET_DIR+[m])
            actual=sha_region(f,e2["extent"]*SECTOR,e2["size"])

            r["verified_size"]=e2["size"]
            r["verified_extent_lba"]=e2["extent"]
            r["size_match"]="YES" if e2["size"]==int(r["final_size"]) else "NO"
            r["extent_unchanged"]="YES" if e2["extent"]==int(r["extent_lba"]) else "NO"
            r["embedded_sha256"]=actual
            r["sha_match"]="YES" if actual==r["final_sha256"] else "NO"

            ok=(
                r["size_match"]=="YES" and
                r["extent_unchanged"]=="YES" and
                r["sha_match"]=="YES"
            )
            r["status"]="PASS" if ok else "FAIL"
            all_ok &= ok

    write_tsv(STAGE/"iso_patch_report.tsv",rows)

    if not all_ok:
        raise RuntimeError("Integrated ISO verification failed")

    summary=[
        "Naruto PSP MOV04D - integrated translated movie ISO",
        "="*80,"",
        "RESULT=PASS",
        "",
        "Base ISO already contains:",
        "  dm001..dm010 Korean-subtitle movies",
        "",
        "Added in this stage:",
        "  da101 da201 dk101 dk102 dk202",
        "",
        "Verification:",
        "  5/5 replacements fit existing allocation",
        "  5/5 extents/LBAs unchanged",
        "  5/5 ISO embedded file sizes match",
        "  5/5 ISO embedded SHA256 values match MOV04C outputs",
        "",
        "Early runtime check:",
        "  dk101 is now the actual translated dk101 movie.",
        "  Start the game normally and verify the early cutscene.",
        "",
        f"Output ISO={OUT_ISO}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
