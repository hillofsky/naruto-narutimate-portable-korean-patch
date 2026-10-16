#!/usr/bin/env python3
from __future__ import annotations
import csv, math, shutil, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
STAGE = ROOT / "analysis" / "mov" / "mov03c_event_table_analysis"
EXTRACT = STAGE / "pidx_extract"
DECOMP = STAGE / "decompressed_event"
UNRES = STAGE / "unresolved_decompression"
LOGS = STAGE / "decompression_logs"
MAGIC = 0x313B3320

def entropy(data: bytes) -> float:
    if not data: return 0.0
    c=Counter(data); n=len(data)
    return -sum((v/n)*math.log2(v/n) for v in c.values())

def printable_ratio(data: bytes) -> float:
    if not data: return 0.0
    n=sum(1 for x in data if x in (9,10,13) or 32 <= x < 127)
    return n/len(data)

def find_quickbms():
    for base in [ROOT/"tools"/"quickbms", ROOT/"tools", ROOT]:
        if not base.exists():
            continue
        hits=list(base.rglob("quickbms.exe"))
        if hits:
            return hits[0]
    return None

def write_tsv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("",encoding="utf-8-sig")
        return
    fields=[]
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def run_variant(qb: Path, src: Path, tmp_root: Path, label: str,
                comtype: str, offset: int, zsize: int, out_capacity: int):
    tmp=tmp_root/label
    if tmp.exists():
        shutil.rmtree(tmp,ignore_errors=True)
    tmp.mkdir(parents=True,exist_ok=True)

    bms=tmp_root/f"{src.stem}_{label}.bms"
    bms.write_text(
        f'comtype {comtype}\n'
        f'clog "decompressed.bin" {offset} {zsize} {out_capacity}\n',
        encoding="ascii"
    )
    log=LOGS/f"{src.stem}_{label}.log"
    cmd=[str(qb),"-o",str(bms),str(src),str(tmp)]
    cp=subprocess.run(
        cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding="utf-8",errors="replace"
    )
    log.write_text(cp.stdout,encoding="utf-8-sig")
    out=tmp/"decompressed.bin"
    data=out.read_bytes() if out.exists() else b""
    return {
        "label":label,
        "comtype":comtype,
        "offset":offset,
        "zsize":zsize,
        "capacity":out_capacity,
        "quickbms_exit":cp.returncode,
        "output_size":len(data),
        "entropy":round(entropy(data),4) if data else "",
        "printable_ratio":round(printable_ratio(data),4) if data else "",
        "data":data,
        "log":str(log),
    }

def main():
    if DECOMP.exists():
        shutil.rmtree(DECOMP,ignore_errors=True)
    if UNRES.exists():
        shutil.rmtree(UNRES,ignore_errors=True)
    DECOMP.mkdir(parents=True,exist_ok=True)
    UNRES.mkdir(parents=True,exist_ok=True)
    LOGS.mkdir(parents=True,exist_ok=True)

    qb=find_quickbms()
    if not qb:
        raise RuntimeError("quickbms.exe not found under PROJECT_ROOT\\tools")

    chosen={}
    for p in sorted(EXTRACT.rglob("event*.tbl")):
        if p.is_file():
            chosen.setdefault(p.name.lower(),p)
    src=list(chosen.values())
    if not src:
        raise RuntimeError("No compressed event*.tbl files found under pidx_extract.")

    print("="*76,flush=True)
    print(" Naruto PSP MOV03C FIX3 - Partial-safe event decompression",flush=True)
    print("="*76,flush=True)
    print(f"QuickBMS : {qb}",flush=True)
    print(f"Events   : {len(src)}",flush=True)

    rows=[]
    usable=0
    raw_ok=0
    alt_ok=0
    unresolved=0

    for i,p in enumerate(src,1):
        b=p.read_bytes()
        clean_name=p.name.replace("unknown_","")
        if len(b)<8:
            rows.append({
                "event_file":clean_name,
                "status":"TOO_SMALL",
                "source_path":str(p),
                "source_size":len(b),
            })
            unresolved += 1
            continue

        sig,usize=struct.unpack_from("<II",b,0)
        csize=len(b)-8
        dst=DECOMP/clean_name

        # Variant order:
        #   A. lzfu_raw with exact declared capacity (known-good for 37/39)
        #   B. lzfu with exact capacity (non-raw MS-RTF-style variant)
        #   C. lzfu_raw with oversized output buffer; accept ONLY if actual
        #      returned output is exactly the declared uncompressed size.
        variants=[
            ("raw_exact","lzfu_raw",8,csize,usize),
            ("lzfu_exact","lzfu",8,csize,usize),
            ("raw_oversize","lzfu_raw",8,csize,usize+0x10000),
        ]

        attempts=[]
        accepted=None
        for label,ctype,off,zs,cap in variants:
            a=run_variant(qb,p,LOGS,label,ctype,off,zs,cap)
            attempts.append(a)
            if sig==MAGIC and a["output_size"]==usize:
                accepted=a
                break

        if accepted is not None:
            dst.write_bytes(accepted["data"])
            usable += 1
            if accepted["label"]=="raw_exact":
                status="OK_RAW"
                raw_ok += 1
            elif accepted["label"]=="lzfu_exact":
                status="OK_LZFU"
                alt_ok += 1
            else:
                status="OK_RAW_OVERSIZE_EXACT"
                alt_ok += 1
        else:
            status="UNRESOLVED"
            unresolved += 1
            # Preserve every nonempty candidate for later forensic comparison.
            udir=UNRES/Path(clean_name).stem
            udir.mkdir(parents=True,exist_ok=True)
            for a in attempts:
                if a["data"]:
                    (udir/f'{a["label"]}_{a["output_size"]}.bin').write_bytes(a["data"])
            # Also preserve source header + payload.
            (udir/"source.tbl").write_bytes(b)

        best=max(attempts,key=lambda a:a["output_size"]) if attempts else None
        row={
            "event_file":clean_name,
            "source_path":str(p),
            "source_size":len(b),
            "signature_hex":f"0x{sig:08X}",
            "expected_uncompressed_size":usize,
            "compressed_payload_size":csize,
            "compressed_entropy":round(entropy(b[8:]),4),
            "status":status,
            "accepted_variant":accepted["label"] if accepted else "",
            "accepted_output_size":accepted["output_size"] if accepted else "",
            "accepted_entropy":accepted["entropy"] if accepted else "",
            "accepted_printable_ratio":accepted["printable_ratio"] if accepted else "",
            "raw_exact_size":attempts[0]["output_size"] if len(attempts)>0 else "",
            "raw_exact_exit":attempts[0]["quickbms_exit"] if len(attempts)>0 else "",
            "lzfu_exact_size":attempts[1]["output_size"] if len(attempts)>1 else "",
            "lzfu_exact_exit":attempts[1]["quickbms_exit"] if len(attempts)>1 else "",
            "raw_oversize_size":attempts[2]["output_size"] if len(attempts)>2 else "",
            "raw_oversize_exit":attempts[2]["quickbms_exit"] if len(attempts)>2 else "",
            "best_nonexact_size":best["output_size"] if (best and not accepted) else "",
            "best_nonexact_entropy":best["entropy"] if (best and not accepted) else "",
            "best_nonexact_printable_ratio":best["printable_ratio"] if (best and not accepted) else "",
            "source_head64_hex":b[:64].hex(" "),
        }
        rows.append(row)

        att_desc=", ".join(
            f'{a["label"]}:{a["output_size"]}' for a in attempts
        )
        print(
            f"[{i:02d}/{len(src):02d}] {clean_name}: "
            f"0x{sig:08X} payload={csize} expected={usize} "
            f"{status} [{att_desc}]",
            flush=True
        )

    write_tsv(STAGE/"decompression_report.tsv",rows)

    coverage=usable/max(1,len(src))
    summary=[
        "Naruto PSP MOV03C FIX3 - Partial-safe event decompression",
        "="*76,"",
        f"Input event files={len(src)}",
        f"Usable decompressions={usable}/{len(src)}",
        f"raw_exact_success={raw_ok}",
        f"alternative_exact_success={alt_ok}",
        f"unresolved={unresolved}",
        f"coverage={coverage:.4f}",
        f"Expected signature=0x{MAGIC:08X}",
        "",
    ]

    # 90% is sufficient for structural reconnaissance. Missing files remain
    # explicitly marked; no fake opcode interpretation is made for them.
    if coverage >= 0.90:
        summary += [
            "Result=PROCEED_PARTIAL" if unresolved else "Result=SUCCESS",
            "Structural analysis may proceed on exact-size decompressed files.",
            "Unresolved files are excluded and preserved under unresolved_decompression.",
        ]
        rc=0
    else:
        summary += [
            "Result=FAILED_LOW_COVERAGE",
            "Too few event files decompressed exactly for reliable structural analysis.",
        ]
        rc=2

    (STAGE/"DECOMPRESSION_SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",encoding="utf-8-sig"
    )
    print("\n".join(summary),flush=True)
    return rc

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"DECOMPRESSION_FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
