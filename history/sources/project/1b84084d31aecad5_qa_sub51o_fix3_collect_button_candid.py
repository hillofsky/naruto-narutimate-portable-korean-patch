from pathlib import Path
import shutil, zipfile, json, hashlib, traceback, os

ROOT=Path(r"PROJECT_ROOT")
BASE=ROOT/r"analysis\sub\sub51n_titlehomepolish"
OUT=ROOT/r"analysis\sub\sub51o_fix3_button_candidates"
LOGS=ROOT/"logs"

TARGETS=[
 ("gauge.ccs","TEX_xpad"),
 ("gauge.ccs","TEX_xselect"),
 ("gauge.ccs","TEX_xselect2"),
 ("gauge.ccs","TEX_xselect5"),
 ("cmnselect.ccs","TEX_button01"),
 ("cmnselect.ccs","TEX_button02"),
 ("cmnselect.ccs","TEX_button03"),
 ("cmnselect.ccs","TEX_button04"),
 ("cmnselect.ccs","TEX_xselect3"),
 ("xselect3.ccs","TEX_xselect4"),
]

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def find_named(resource,tex):
    names=[
        f"{resource}_{tex}.png",
        f"{resource.replace('.ccs','')}__{tex}.png",
        f"{tex}.png",
        f"l__{resource.replace('.ccs','')}__{tex}_KO.png",
        f"n__{tex}_KO_HC.png",
    ]
    search_roots=[
        BASE/"orig_dump",
        BASE/"build_assets",
        ROOT/r"analysis\sub\sub51k_residual_ui_sweep",
        ROOT/r"analysis\sub\sub51l_fix2_consolidated_ui",
    ]
    hits=[]
    for sr in search_roots:
        if not sr.exists(): continue
        for name in names:
            p=sr/name
            if p.exists(): hits.append(p)
        # bounded filename search only
        try:
            for p in sr.glob("*.png"):
                n=p.name.lower()
                if tex.lower() in n and resource.replace(".ccs","").lower() in n:
                    hits.append(p)
        except: pass
    # unique
    out=[]; seen=set()
    for p in hits:
        k=str(p).lower()
        if k not in seen:seen.add(k);out.append(p)
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    found=[];missing=[]
    print("=== SUB51O FIX3 BUTTON CANDIDATES ===",flush=True)
    for i,(res,tex) in enumerate(TARGETS,1):
        print(f"[{i}/{len(TARGETS)}] {res} {tex}",flush=True)
        hits=find_named(res,tex)
        if not hits:
            missing.append({"resource":res,"texture":tex})
            print("  MISSING existing PNG",flush=True)
            continue
        for j,p in enumerate(hits):
            safe=f"{res.replace('.ccs','')}__{tex}__{j}__{p.name}"
            dst=OUT/safe
            shutil.copy2(p,dst)
            item={"resource":res,"texture":tex,"source":str(p),"file":safe,"size":p.stat().st_size,"sha256":sha256(p)}
            try:
                from PIL import Image
                with Image.open(p) as im:item["width"]=im.width;item["height"]=im.height;item["mode"]=im.mode
            except:pass
            found.append(item)
            print("  FOUND",p,flush=True)

    # Collect residual inventory for mapping.
    inv=ROOT/r"analysis\sub\sub51k_residual_ui_sweep\sub51k_ui_textures.tsv"
    if inv.exists(): shutil.copy2(inv,OUT/"sub51k_ui_textures.tsv")

    report={"found":found,"missing":missing}
    (OUT/"collection.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["SUB51O FIX3 button candidate collection",f"Found={len(found)} Missing={len(missing)}",""]
    for x in found: lines.append(f"{x['resource']} {x['texture']} -> {x['file']} <- {x['source']}")
    if missing:
        lines+=["","MISSING:"]+[f"{x['resource']} {x['texture']}" for x in missing]
    (OUT/"SUMMARY.txt").write_text("\n".join(lines),encoding="utf-8-sig")

    z=LOGS/"naruto_sub51o_fix3_button_candidates_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file():zz.write(p,p.name)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix3_button_candidates_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file():zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
