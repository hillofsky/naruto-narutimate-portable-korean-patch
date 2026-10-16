#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse, os, shutil, hashlib, json, csv, sys, traceback

NEEDLES=[
    "TEX_mod_bg00","modesel1","TEX_option01","TEX_sel","TEX_network",
    "TEX_rpgmenu01","parse_ccs","decode_texture","unswizzle","4bpp",
    "palette","indexed","TEX_yellow","TEX_name","CCS"
]
EXCLUDE_PARTS={
    "sub51e_ui_style_source_export",
    "sub51e_fix1_ui_style_source_export",
    "sub51e_fix2_pristine_source_recovery",
    "sub51e_fix3_pristine_source_recovery",
    "_upload","_work","logs","old","cache","temp","tmp",
}

def safe_walk_py(root: Path):
    root=root.resolve()
    for cur, dirs, files in os.walk(str(root), topdown=True):
        # prune recursive/self-generated trees aggressively
        kept=[]
        for d in dirs:
            dl=d.lower()
            if dl in EXCLUDE_PARTS: continue
            if dl.startswith("sub51e"): continue
            if dl.startswith("_"): continue
            kept.append(d)
        dirs[:] = kept
        for fn in files:
            if fn.lower().endswith(".py"):
                yield Path(cur)/fn

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"PROJECT_ROOT")
    ap.add_argument("--bundle",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.root); bundle=Path(a.bundle); out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)

    # 1) Install pristine CCS copied from the successful portion of FIX2 failure package.
    rawdir=out/"pristine_sub36_ccs"; rawdir.mkdir(exist_ok=True)
    rows=[]
    for p in sorted(bundle.glob("*.ccs")):
        dst=rawdir/p.name
        shutil.copy2(p,dst)
        rows.append({
            "resource":p.name,
            "size":dst.stat().st_size,
            "sha256":hashlib.sha256(dst.read_bytes()).hexdigest(),
            "status":"RECOVERED_FROM_FIX2_FAILURE_ZIP"
        })
    if len(rows)!=9:
        raise RuntimeError(f"Expected 9 pristine CCS files, got {len(rows)}")

    with (out/"pristine_resource_inventory.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["resource","size","sha256","status"],delimiter="\t")
        w.writeheader();w.writerows(rows)

    # 2) Safely collect helper scripts. Never recurse through SUB51E-generated output.
    sdir=out/"historical_scripts"; sdir.mkdir(exist_ok=True)
    copied=[]; total=0
    search_roots=[root/"analysis",root/"sub43_assets"]
    for sr in search_roots:
        if not sr.exists(): continue
        for p in safe_walk_py(sr):
            try:
                if p.stat().st_size>2_000_000: continue
                txt=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:
                continue
            hits=[n for n in NEEDLES if n.lower() in txt.lower()]
            if not hits: continue
            data=p.read_bytes()
            h=hashlib.sha256(data).hexdigest()
            dst=sdir/(p.stem+"_"+h[:12]+".py")
            if dst.exists(): continue
            dst.write_bytes(data)
            copied.append({
                "source_path":str(p),
                "copied_name":dst.name,
                "size":len(data),
                "sha256":h,
                "hits":";".join(hits[:20]),
            })
            total+=len(data)
            if len(copied)>=80 or total>=20_000_000:
                break
        if len(copied)>=80 or total>=20_000_000:
            break

    with (out/"historical_script_inventory.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["source_path","copied_name","size","sha256","hits"],delimiter="\t")
        w.writeheader();w.writerows(copied)

    summary={
        "stage":"SUB51E_FIX3_PRISTINE_SOURCE_RECOVERY",
        "pristine_ccs_count":len(rows),
        "historical_scripts_copied":len(copied),
        "historical_script_bytes":total,
        "recursion_bug_fixed":True,
        "game_data_modified":False,
        "ppsspp_executed":False,
        "bc250_used":False,
        "local_llm_used":False,
        "next":"Upload success ZIP so ChatGPT can identify texture decoder/reinsertion path and build styled Korean UI assets."
    }
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51E FIX3 - pristine source recovery\n\n"
        f"PristineCCS={len(rows)}/9\n"
        f"HistoricalScriptsCopied={len(copied)}\n"
        f"HistoricalScriptBytes={total}\n"
        "RecursionBugFixed=YES\n"
        "GameDataModified=NO\nPPSSPPExecuted=NO\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig"
    )
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"))

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
