from pathlib import Path
import shutil, zipfile, traceback, os

ROOT=Path(r"PROJECT_ROOT")
SRC=ROOT/r"analysis\sub\sub51k_residual_ui_sweep"
OUT=ROOT/r"analysis\sub\sub51p_fix1_fullcontacts"
LOGS=ROOT/"logs"

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    LOGS.mkdir(parents=True,exist_ok=True)
    print("=== SUB51P FIX1 FULL CONTACT COLLECTION ===",flush=True)
    if not SRC.exists():
        raise RuntimeError("SUB51K residual UI sweep folder missing: "+str(SRC))

    copied=0
    cs=SRC/"contact_sheets"
    if cs.exists():
        for p in sorted(cs.glob("*.png")):
            shutil.copy2(p,OUT/p.name)
            copied+=1
            print("CONTACT",p.name,flush=True)

    # exact inventories/manifests from SUB51K
    for name in ["sub51k_ui_textures.tsv","sub51k_resources.tsv","SUMMARY.txt",
                 "sub51k_texture_inventory.tsv","collection.json"]:
        p=SRC/name
        if p.exists():
            shutil.copy2(p,OUT/name)
            print("META",name,flush=True)

    # any TSV/JSON at top-level, small only
    for p in SRC.iterdir():
        if p.is_file() and p.suffix.lower() in {".tsv",".json",".txt"} and p.stat().st_size<2*1024*1024:
            dst=OUT/p.name
            if not dst.exists():
                shutil.copy2(p,dst)

    (OUT/"SUB51P_FIX1_NOTE.txt").write_text(
        "Purpose: identify exact texture for Game Mode Select header and bottom hints.\n"
        "Known already: gauge.ccs/TEX_xwhite contains the shown bottom Japanese hints.\n"
        "Title pressed-gap hypothesis: restore title TEX_panel2/TEX_panel3 originals; keep Korean TEX_panel.\n"
        "No ISO modification / no PPSSPP / no story automation.\n",
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub51p_fix1_fullcontacts_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file():
                zz.write(p,p.name)
    print(f"DONE contacts={copied}",flush=True)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51p_fix1_fullcontacts_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
