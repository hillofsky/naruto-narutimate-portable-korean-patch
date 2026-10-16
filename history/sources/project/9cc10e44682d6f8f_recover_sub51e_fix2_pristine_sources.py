#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse, importlib.util, hashlib, json, shutil, sys, traceback

RESOURCES=[
    "modesel1.ccs",
    "option.ccs",
    "setting.ccs",
    "charsel1.ccs",
    "mugen.ccs",
    "network.ccs",
    "home.ccs",
    "gauge.ccs",
    "rpggauge.ccs",
]

SUB36_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"

def loadmod(path):
    spec=importlib.util.spec_from_file_location("stage14_patch",path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load "+str(path))
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

SECTOR=2048
def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":
        raise RuntimeError("bad ISO")
    r=p[156:190]
    return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR);data=f.read(size)
    out=[];pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//SECTOR)+1)*SECTOR;continue
        r=data[pos:pos+ln]
        if len(r)<34:break
        nb=r[33:33+r[32]]
        name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
        out.append(dict(name=name,lba=int.from_bytes(r[2:6],"little"),
                        size=int.from_bytes(r[10:14],"little"),is_dir=bool(r[25]&2)))
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso);cur=dict(lba=lba,size=size,is_dir=True)
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"])
                  if e["name"].casefold()==part.casefold()),None)
        if not hit: raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath)
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b:raise RuntimeError("EOF")
            fo.write(b);rem-=len(b)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"PROJECT_ROOT")
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.root);out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)

    iso=root/"analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"
    if not iso.exists():raise RuntimeError("SUB36 ISO missing")
    got=sha256_file(iso)
    if got!=SUB36_SHA:raise RuntimeError("SUB36 SHA mismatch: "+got)

    patcher=root/"analysis/stage14/naruto_patcher.py"
    if not patcher.exists():raise RuntimeError("stage14 patcher missing")
    m=loadmod(patcher)

    work=out/"_work";work.mkdir(exist_ok=True)
    dat=work/"naruto.dat"
    extract(iso,"PSP_GAME/USRDIR/naruto.dat",dat)

    table=m.parse_pidx(m.read_embedded_index(dat),"sub51e-fix2-sub36")
    rows=[]
    rawdir=out/"pristine_sub36_ccs";rawdir.mkdir(exist_ok=True)
    with dat.open("rb") as f:
        for name in RESOURCES:
            r=next((x for x in table["primary"] if x["name"]==name),None)
            if not r:
                rows.append(dict(resource=name,status="MISSING",size="",sha256=""))
                continue
            f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
            dec=m.decode_stored(stored,r["size"],r["zsize"])
            p=rawdir/name
            p.write_bytes(dec)
            rows.append(dict(resource=name,status="OK",size=len(dec),
                             sha256=hashlib.sha256(dec).hexdigest()))

    import csv
    with (out/"pristine_resource_inventory.tsv").open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=["resource","status","size","sha256"],delimiter="\t")
        w.writeheader();w.writerows(rows)

    # Collect likely historical texture/CCS helper scripts by CONTENT, not filename.
    scriptdir=out/"historical_scripts";scriptdir.mkdir(exist_ok=True)
    needles=[
        "TEX_mod_bg00","modesel1","TEX_option01","TEX_sel","TEX_network",
        "TEX_rpgmenu01","parse_ccs","decode_texture","unswizzle","4bpp",
        "palette","indexed","TEX_yellow","TEX_name"
    ]
    copied=0;copied_bytes=0
    roots=[root/"analysis",root/"sub43_assets"]
    for sr in roots:
        if not sr.exists():continue
        for p in sr.rglob("*.py"):
            try:
                if p.stat().st_size>2_000_000:continue
                txt=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:
                continue
            hits=[n for n in needles if n.lower() in txt.lower()]
            if not hits:continue
            digest=hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            dest=scriptdir/(p.stem+"_"+digest+".py")
            if not dest.exists():
                shutil.copy2(p,dest);copied+=1;copied_bytes+=dest.stat().st_size
                if copied>=80 or copied_bytes>20_000_000:break
        if copied>=80 or copied_bytes>20_000_000:break

    # Copy current KO mode textures for exact before/after comparison.
    cmpdir=out/"current_ko_reference";cmpdir.mkdir(exist_ok=True)
    src43=root/"sub43_assets"
    if src43.exists():
        for p in src43.glob("*modesel1*TEX_mod_bg*_ko.png"):
            if p.stat().st_size<=2_000_000:
                shutil.copy2(p,cmpdir/p.name)
        for pat in ("*TEX_option01*ko.png","*TEX_sel*ko.png","*TEX_network*ko.png"):
            for p in src43.glob(pat):
                if p.stat().st_size<=2_000_000:
                    shutil.copy2(p,cmpdir/p.name)

    summary={
        "stage":"SUB51E_FIX2_PRISTINE_UI_SOURCE_RECOVERY",
        "source":"SUB36",
        "source_sha256":SUB36_SHA,
        "resources_requested":RESOURCES,
        "resources_ok":sum(1 for r in rows if r["status"]=="OK"),
        "historical_scripts_copied":copied,
        "game_data_modified":False,
        "ppsspp_executed":False,
        "bc250_used":False,
        "local_llm_used":False,
    }
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51E FIX2 - pristine UI source recovery\n\n"
        f"SUB36_SHA256={SUB36_SHA}\n"
        f"PristineCCS={summary['resources_ok']}/{len(RESOURCES)}\n"
        f"HistoricalScriptsCopied={copied}\n"
        "GameDataModified=NO\nPPSSPPExecuted=NO\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig"
    )
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"))

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
