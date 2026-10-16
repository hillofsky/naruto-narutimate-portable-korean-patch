from pathlib import Path
import shutil, zipfile, traceback, json, hashlib

ROOT=Path(r"PROJECT_ROOT")
BASE=ROOT/r"analysis\sub\sub51n_titlehomepolish"
OUT=ROOT/r"analysis\sub\sub51o_fix2_target_assets"
LOGS=ROOT/"logs"

TARGET_NAMES=[
    "n__TEX_panel_KO_HC.png",
    "n__TEX_panel2_KO_HC.png",
    "n__TEX_panel3_KO_HC.png",
    "l__gauge__TEX_start_KO.png",
    "l__gauge__TEX_xstart_KO.png",
    "l__gauge__TEX_xtext_KO.png",
    "title.ccs_TEX_panel.png",
    "title.ccs_TEX_panel2.png",
    "title.ccs_TEX_panel3.png",
    "gauge.ccs_TEX_start.png",
    "gauge.ccs_TEX_xstart.png",
    "gauge.ccs_TEX_xtext.png",
]

def sha256(p):
    import hashlib
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    found=[]; missing=[]
    # exact likely directories first
    dirs=[BASE/"build_assets", BASE/"orig_dump"]
    for name in TARGET_NAMES:
        hit=None
        for d in dirs:
            p=d/name
            if p.exists():
                hit=p; break
        if hit is None:
            # bounded fallback only inside SUB51N tree
            for p in BASE.rglob(name):
                hit=p; break
        if hit:
            dst=OUT/hit.name
            shutil.copy2(hit,dst)
            info={"name":name,"source":str(hit),"size":hit.stat().st_size,"sha256":sha256(hit)}
            try:
                from PIL import Image
                with Image.open(hit) as im:
                    info["width"]=im.width; info["height"]=im.height; info["mode"]=im.mode
            except Exception: pass
            found.append(info)
            print("FOUND",hit,flush=True)
        else:
            missing.append(name)
            print("MISSING",name,flush=True)

    # also collect small manifests that prove current mapping
    for name in ["sub51n_texture_patch.tsv","sub51n_preflight.tsv","SUMMARY.txt","SUB51N_static_verification.json"]:
        p=BASE/"build"/name
        if p.exists(): shutil.copy2(p,OUT/name)

    report={"stage":"SUB51O_FIX2_TARGET_ASSET_COLLECTION","found":found,"missing":missing}
    (OUT/"collection.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "SUB51O FIX2 targeted asset collection\n"
        "Read-only; no ISO modification.\n"
        f"Found={len(found)} Missing={len(missing)}\n\n"+
        "\n".join("FOUND "+x["source"] for x in found)+
        ("\n\nMISSINLOCAL_PATH"+"\n".join(missing) if missing else ""),
        encoding="utf-8-sig"
    )
    z=LOGS/"naruto_sub51o_fix2_target_assets_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file(): zz.write(p,p.name)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try: main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix2_target_assets_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
