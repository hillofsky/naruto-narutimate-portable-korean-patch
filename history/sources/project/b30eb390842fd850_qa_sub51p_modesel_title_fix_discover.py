from pathlib import Path
import os, shutil, zipfile, json, traceback, hashlib

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub51p_modesel_title_fix_discovery"
LOGS=ROOT/"logs"

SEARCH_ROOTS=[
    ROOT/r"analysis\sub\sub51k_residual_ui_sweep",
    ROOT/r"analysis\sub\sub51l_fix2_consolidated_ui",
    ROOT/r"analysis\sub\sub51n_titlehomepolish",
    ROOT/r"analysis\sub\sub51o_fix5_exact_targets",
    ROOT/r"analysis\sub\sub51o_fix6b_xpanel_extract",
]
TOKENS=[
    "mode","modesel","modesel1","game","title","panel","button","xpanel","xtext",
    "select","cmnselect","gauge","header","menu","home"
]
EXACT_CONTACTS=["modesel1_contact.png","title_contact.png","gauge_contact.png","cmnselect_contact.png","option_contact.png"]

def sha1(p):
    import hashlib
    h=hashlib.sha1()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    found=[]
    copied=set()

    print("=== SUB51P MODESEL/TITLE FIX DISCOVERY ===", flush=True)
    # Exact contact sheets
    for name in EXACT_CONTACTS:
        hit=None
        for root in SEARCH_ROOTS:
            if not root.exists(): 
                continue
            for p in root.rglob(name):
                hit=p
                break
            if hit: break
        if hit:
            dst=OUT/name
            shutil.copy2(hit,dst)
            found.append({"kind":"contact","name":name,"source":str(hit),"sha1":sha1(hit)})
            copied.add(str(dst).lower())
            print("FOUND CONTACT", hit, flush=True)
        else:
            print("MISSING CONTACT", name, flush=True)

    # Candidate PNGs and manifests
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        print("SCAN", root, flush=True)
        for dp,dns,fns in os.walk(root):
            dns[:] = [d for d in dns if d.lower() not in {"old","tmp","temp","__pycache__","logs","frames","captures","_work"}]
            relparts=Path(dp).relative_to(root).parts
            if len(relparts) >= 4:
                dns[:] = []
            for fn in fns:
                low=fn.lower()
                p=Path(dp)/fn
                try:
                    if p.stat().st_size > 4*1024*1024:
                        continue
                except:
                    continue
                if fn in {"sub51n_texture_patch.tsv","sub51o_texture_patch.tsv","SUMMARY.txt","collection.json"}:
                    dst=OUT/(root.name+"__"+fn)
                    if str(dst).lower() not in copied:
                        shutil.copy2(p,dst); copied.add(str(dst).lower())
                    continue
                if not low.endswith(".png"):
                    continue
                if any(tok in low for tok in TOKENS):
                    safe=root.name+"__"+("__".join(Path(dp).relative_to(root).parts))+"__"+fn
                    safe=safe.strip("_")
                    dst=OUT/safe
                    if str(dst).lower() in copied:
                        continue
                    shutil.copy2(p,dst)
                    copied.add(str(dst).lower())
                    found.append({"kind":"png","name":fn,"source":str(p),"sha1":sha1(p),"size":p.stat().st_size})
                    print("COPY", p, flush=True)

    report={"stage":"SUB51P_MODESEL_TITLE_FIX_DISCOVERY","files":found}
    (OUT/"SUMMARY.txt").write_text(
        "SUB51P discovery\n"
        "Goal: fix remaining Mode Select JP header / bottom button hints / title pressed white gap.\n"
        "No ISO modification. No PPSSPP launch.\n"
        f"Collected files={len(found)}\n",
        encoding="utf-8-sig"
    )
    (OUT/"discovery.json").write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding="utf-8")
    z=LOGS/"naruto_sub51p_modesel_title_fix_discovery_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file():
                zz.write(p,p.name)
    print("UPLOAD_ZIP="+str(z), flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(), encoding="utf-8")
        z=LOGS/"fail_naruto_sub51p_modesel_title_fix_discovery_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file():
                    zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z), flush=True)
        raise
