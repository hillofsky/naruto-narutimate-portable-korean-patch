from pathlib import Path
import shutil, zipfile, traceback, json, os

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub51o_fix4_contact_collection"
LOGS=ROOT/"logs"

CONTACT_NAMES=["gauge_contact.png","cmnselect_contact.png","title_contact.png","modesel1_contact.png","option_contact.png"]
SEARCH_ROOTS=[
    ROOT/r"analysis\sub\sub51k_residual_ui_sweep",
    ROOT/r"analysis\sub\sub51n_titlehomepolish",
    ROOT/r"analysis\sub\sub51l_fix2_consolidated_ui",
]

TOKENS=["button","select","pad","guide","help","hint","botan","command","panel","title"]

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    found=[]

    print("=== SUB51O FIX4 CONTACT COLLECTION ===",flush=True)
    # Exact contact sheets
    for name in CONTACT_NAMES:
        hit=None
        for root in SEARCH_ROOTS:
            if not root.exists(): continue
            for p in root.rglob(name):
                hit=p; break
            if hit: break
        if hit:
            dst=OUT/name
            shutil.copy2(hit,dst)
            found.append(str(hit))
            print("FOUND",hit,flush=True)
        else:
            print("MISSING",name,flush=True)

    # Nearby small PNG assets only, bounded by name tokens.
    copied=0
    for root in SEARCH_ROOTS:
        if not root.exists(): continue
        for dp,dns,fns in os.walk(root):
            dns[:] = [d for d in dns if d.lower() not in {"old","logs","frames","captures","tmp","temp","__pycache__"}]
            # depth guard
            rel=Path(dp).relative_to(root)
            if len(rel.parts)>=4:
                dns[:] = []
            for fn in fns:
                if not fn.lower().endswith(".png"): continue
                low=fn.lower()
                if not any(t in low for t in TOKENS): continue
                p=Path(dp)/fn
                try:
                    if p.stat().st_size>2*1024*1024: continue
                    safe=(str(rel).replace("\\","__").replace("/","__")+"__"+fn).lstrip("_")
                    dst=OUT/safe
                    if not dst.exists():
                        shutil.copy2(p,dst);copied+=1
                except: pass

    (OUT/"SUMMARY.txt").write_text(
        "SUB51O FIX4 contact collection\n"
        "Read-only / no PPSSPP / no ISO modification\n"
        f"Exact contacts found={len(found)}\nNearby PNG copied={copied}\n\n"+
        "\n".join(found),
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub51o_fix4_contact_collection_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file(): zz.write(p,p.name)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try: main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix4_contact_collection_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file():zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
