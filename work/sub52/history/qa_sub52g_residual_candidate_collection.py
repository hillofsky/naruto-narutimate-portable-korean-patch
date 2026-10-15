from pathlib import Path
import hashlib, json, shutil, zipfile, traceback, re, csv, os

ROOT=Path(r"D:\narutimate portable")
OUT=ROOT/r"analysis\sub\sub52g_residual_candidate_collection"
LOGS=ROOT/"logs"

TARGETS=[
    ("1hakbod1.ccs","TEX_name"),
    ("gauge.ccs","TEX_xmenu"),
    ("gauge.ccs","TEX_xselect5"),
    ("mg_ki.ccs","TEX_mgtitle01"),
    ("mg_kinobori.ccs","TEX_mgtitle01"),
    ("sik_pose.ccs","TEX_2tyoglb0"),
    ("slot.ccs","TEX_slot_t01"),
    ("narup.ccs","TEX_narup"),
]

SEARCH_ROOTS=[
    ROOT/r"analysis\sub",
    ROOT/r"analysis",
    ROOT/"sub43_assets",
]

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def safe(s):
    return re.sub(r'[^A-Za-z0-9._-]+','_',s)

def png_dim(p):
    try:
        b=Path(p).read_bytes()[:24]
        if b[:8]==b"\x89PNG\r\n\x1a\n":
            import struct
            return struct.unpack(">II",b[16:24])
    except:pass
    return (None,None)

def match_target(path):
    low=str(path).lower().replace("\\","/")
    name=path.name.lower()
    out=[]
    for res,tex in TARGETS:
        r=res.lower().replace(".ccs","")
        t=tex.lower()
        # Accept both "resource__texture" and historical filename variations.
        if t in name and (r in name or r in low):
            out.append((res,tex))
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    LOGS.mkdir(parents=True,exist_ok=True)

    cand=OUT/"candidates"
    cand.mkdir(exist_ok=True)
    rows=[]
    seen_hash_by_target={}

    print("=== SUB52G RESIDUAL CANDIDATE COLLECTION ===",flush=True)
    print("Static only. No PPSSPP / no gameplay / no ISO modification.",flush=True)

    files=[]
    for rr in SEARCH_ROOTS:
        if not rr.exists():continue
        print("Search:",rr,flush=True)
        try:
            for p in rr.rglob("*.png"):
                files.append(p)
        except Exception as e:
            print("WARN search",rr,e,flush=True)

    print("PNG files scanned:",len(files),flush=True)

    for p in files:
        hits=match_target(p)
        if not hits:continue
        h=sha256(p)
        w,hh=png_dim(p)
        for res,tex in hits:
            key=(res,tex)
            if h in seen_hash_by_target.setdefault(key,set()):
                continue
            seen_hash_by_target[key].add(h)
            td=cand/(safe(res)+"__"+safe(tex))
            td.mkdir(parents=True,exist_ok=True)
            dst=td/(f"{len(seen_hash_by_target[key]):03d}__{h[:12]}__{safe(p.name)}")
            shutil.copy2(p,dst)
            rows.append({
                "resource":res,"texture":tex,
                "source_path":str(p),
                "sha256":h,"width":w or "","height":hh or "",
                "copy_path":str(dst.relative_to(OUT)),
            })

    # Also collect text/log references mentioning exact target texture names.
    refs=OUT/"references"
    refs.mkdir(exist_ok=True)
    refrows=[]
    text_ext={".tsv",".txt",".json",".py",".ps1",".md",".log"}
    for rr in SEARCH_ROOTS:
        if not rr.exists():continue
        for p in rr.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in text_ext:continue
            try:
                if p.stat().st_size>5*1024*1024:continue
                txt=p.read_text(encoding="utf-8",errors="ignore")
            except:continue
            matched=[]
            for res,tex in TARGETS:
                if tex.lower() in txt.lower() and res.lower() in txt.lower():
                    matched.append(res+"/"+tex)
            if not matched:continue
            refrows.append({"path":str(p),"targets":";".join(matched),"size":p.stat().st_size})

    with (OUT/"candidate_inventory.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["resource","texture","source_path","sha256","width","height","copy_path"]
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t")
        w.writeheader();w.writerows(rows)

    with (OUT/"reference_inventory.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["path","targets","size"]
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t")
        w.writeheader();w.writerows(refrows)

    summary={
        "stage":"SUB52G_RESIDUAL_CANDIDATE_COLLECTION",
        "targets":len(TARGETS),
        "unique_png_candidates":len(rows),
        "reference_files":len(refrows),
        "per_target":{
            f"{r}/{t}":sum(1 for x in rows if x["resource"]==r and x["texture"]==t)
            for r,t in TARGETS
        },
        "confirmed_residual_text":[
            {"entry":"mugen.tbl","key":"#1008"},
            {"entry":"mugen.tbl","key":"#2031"},
        ],
        "ppsspp_used":False,
        "gameplay_used":False,
        "iso_modified":False,
    }
    (OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "Naruto SUB52G residual candidate collection\n\n"+
        "\n".join(f"{k}={v}" for k,v in summary.items() if k!="per_target")+
        "\n\nPer target:\n"+
        "\n".join(f"{k}={v}" for k,v in summary["per_target"].items()),
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub52g_residual_candidate_collection_upload.zip"
    if z.exists():z.unlink()
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.rglob("*"):
            if p.is_file():
                zz.write(p,p.relative_to(OUT))
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True);LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub52g_residual_candidate_collection_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.rglob("*"):
                if p.is_file():zz.write(p,p.relative_to(OUT))
        print(traceback.format_exc(),flush=True)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
