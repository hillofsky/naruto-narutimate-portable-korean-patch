#!/usr/bin/env python3
from __future__ import annotations
import csv, math, shutil, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
STAGE = ROOT / "analysis" / "mov" / "mov03c_event_table_analysis"
EXTRACT = STAGE / "pidx_extract"
DECOMP = STAGE / "decompressed_event"
LOGS = STAGE / "decompression_logs"
BMS = STAGE / "event_lzfu_raw.bms"
MAGIC = 0x313B3320

def entropy(data: bytes) -> float:
    if not data: return 0.0
    c=Counter(data); n=len(data)
    return -sum((v/n)*math.log2(v/n) for v in c.values())

def find_quickbms():
    for base in [ROOT/"tools"/"quickbms", ROOT/"tools", ROOT]:
        if not base.exists(): continue
        hits=list(base.rglob("quickbms.exe"))
        if hits: return hits[0]
    return None

def write_tsv(path, rows):
    if not rows:
        path.write_text("",encoding="utf-8-sig"); return
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()),delimiter="\t")
        w.writeheader(); w.writerows(rows)

def main():
    DECOMP.mkdir(parents=True,exist_ok=True)
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

    bms_text = (
        'get SIGN long\n'
        'get SIZE long\n'
        'get ZSIZE asize\n'
        'math ZSIZE -= 8\n'
        'comtype lzfu_raw\n'
        'clog "decompressed.bin" 8 ZSIZE SIZE\n'
    )
    BMS.write_text(bms_text,encoding="ascii")

    print("="*76,flush=True)
    print(" Naruto PSP MOV03C FIX2 - LZFU_RAW event decompression",flush=True)
    print("="*76,flush=True)
    print(f"QuickBMS : {qb}",flush=True)
    print(f"Events   : {len(src)}",flush=True)

    rows=[]; ok=0
    for i,p in enumerate(src,1):
        b=p.read_bytes()
        if len(b)<8:
            rows.append({"event_file":p.name,"status":"TOO_SMALL"})
            continue
        sig,usize=struct.unpack_from("<II",b,0)
        csize=len(b)-8

        tmp=LOGS/(p.stem+"_tmp")
        if tmp.exists(): shutil.rmtree(tmp,ignore_errors=True)
        tmp.mkdir(parents=True,exist_ok=True)
        log=LOGS/(p.stem+"_quickbms.log")

        cmd=[str(qb),"-o",str(BMS),str(p),str(tmp)]
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          text=True,encoding="utf-8",errors="replace")
        log.write_text(cp.stdout,encoding="utf-8-sig")
        dec=tmp/"decompressed.bin"

        status="FAILED"; outsize=0; ent_out=""; printable_ratio=""
        dst=DECOMP/p.name.replace("unknown_","")
        if dec.exists():
            data=dec.read_bytes()
            outsize=len(data)
            ent_out=round(entropy(data),4)
            printable=sum(1 for x in data if x in (9,10,13) or 32<=x<127)
            printable_ratio=round(printable/max(1,len(data)),4)
            if sig==MAGIC and outsize==usize:
                dst.write_bytes(data)
                status="OK"; ok+=1
            else:
                status="SIZE_OR_MAGIC_MISMATCH"

        rows.append({
            "event_file":p.name.replace("unknown_",""),
            "source_path":str(p),
            "signature_hex":f"0x{sig:08X}",
            "expected_uncompressed_size":usize,
            "compressed_payload_size":csize,
            "quickbms_exit":cp.returncode,
            "output_size":outsize,
            "compressed_entropy":round(entropy(b[8:]),4),
            "decompressed_entropy":ent_out,
            "decompressed_printable_ratio":printable_ratio,
            "status":status,
        })
        print(f"[{i:02d}/{len(src):02d}] {p.name}: "
              f"0x{sig:08X} {csize}->{outsize}/{usize} {status}",flush=True)
        shutil.rmtree(tmp,ignore_errors=True)

    write_tsv(STAGE/"decompression_report.tsv",rows)
    summary=[
        "Naruto PSP MOV03C FIX2 - LZFU_RAW event decompression",
        "="*76,"",
        f"Input event files={len(src)}",
        f"Exact-size successful decompressions={ok}/{len(src)}",
        f"Expected signature=0x{MAGIC:08X}",""
    ]
    if ok==len(src):
        summary += ["Result=SUCCESS",
                    "All event TBLs decompressed to header-declared size.",
                    "Proceed to structural MOVIE/voice analysis."]
    elif ok>0:
        summary += ["Result=PARTIAL",
                    "Some event files decompressed. Structural analysis is blocked."]
    else:
        summary += ["Result=FAILED",
                    "LZFU_RAW did not produce exact header-declared sizes.",
                    "Do not analyze compressed bytes as opcodes."]
    (STAGE/"DECOMPRESSION_SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0 if ok==len(src) else 2

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
