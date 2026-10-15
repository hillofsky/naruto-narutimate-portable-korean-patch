
from pathlib import Path
import shutil, zipfile, traceback, os, json, re

ROOT=Path(r"D:\narutimate portable")
OUT=ROOT/r"analysis\sub\sub52c_static_patch_sources"
LOGS=ROOT/"logs"

# Previous proven full-text pipeline/encoder candidates.
SCRIPT_ROOTS=[
    ROOT/r"analysis\sub\sub51d_full_text_apply",
    ROOT/r"analysis\sub\sub51c_full_text_prepare",
    ROOT/r"analysis\sub\sub51b_exact_source_collection",
    ROOT/r"analysis\stage33",
    ROOT/r"analysis\stage34",
    ROOT,
]

SCRIPT_HINTS=[
    "encode_korean","full_text","font","glyph","translation","translate",
    "naruto_patcher","pidx","rebuild_fsts"
]

# Exact static assets we want to translate/patch next.
TARGET_GLOBS=[
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\00??__*.ccs\*__TEX_name__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0183__eff3eye.ccs\*__TEX_xwinner__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0214__gauge.ccs\*__TEX_white__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0319__mgselect.ccs\*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0320__sik_pose.ccs\*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0322__slot.ccs\*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_st_*__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_blue__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_hanyou__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_white__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_red__*.png",
    r"analysis\sub\sub52a_full_static_asset_sweep\textures_primary\0373__mugen.ccs\*__TEX_name__*.png",
]

TABLE_NAMES=[
    "bunshin.tbl","nazonazo.tbl","quiz1.tbl","quiz2.tbl","mugen.tbl"
]

def safe_rel(p):
    try:return str(p.relative_to(ROOT))
    except:return str(p)

def copy_unique(src,dstdir,prefix=""):
    dstdir.mkdir(parents=True,exist_ok=True)
    name=(prefix+src.name) if prefix else src.name
    dst=dstdir/name
    n=1
    while dst.exists():
        if dst.read_bytes()==src.read_bytes():
            return dst
        dst=dstdir/(src.stem+f"__{n}"+src.suffix); n+=1
    shutil.copy2(src,dst)
    return dst

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    print("=== SUB52C STATIC PATCH SOURCE COLLECTION ===",flush=True)
    print("No PPSSPP. No gameplay. No ISO modification.",flush=True)

    assets=OUT/"target_assets"
    scripts=OUT/"previous_text_pipeline"
    tables=OUT/"target_tables"
    manifests=[]

    print("[1/4] Collect exact untranslated/static target PNGs",flush=True)
    for pattern in TARGET_GLOBS:
        for p in ROOT.glob(pattern):
            if not p.is_file(): continue
            # Preserve entry folder in filename for disambiguation.
            parent=p.parent.name
            dst=copy_unique(p,assets,parent+"__")
            manifests.append({"kind":"asset","source":safe_rel(p),"copy":str(dst.relative_to(OUT))})

    print("[2/4] Collect decoded target tables from SUB52B",flush=True)
    src_tables=ROOT/r"analysis\sub\sub52b_static_text_tables\decoded_tables"
    if src_tables.exists():
        for p in src_tables.glob("*.bin"):
            if any(("__"+n+".bin") in p.name for n in TABLE_NAMES):
                dst=copy_unique(p,tables)
                manifests.append({"kind":"table","source":safe_rel(p),"copy":str(dst.relative_to(OUT))})

    # Also include reports.
    for n in ["japanese_strings_filtered.tsv","exact_target_hits.tsv","SUMMARY.json","SUMMARY.txt"]:
        p=ROOT/r"analysis\sub\sub52b_static_text_tables"/n
        if p.exists():
            dst=copy_unique(p,tables)
            manifests.append({"kind":"table_report","source":safe_rel(p),"copy":str(dst.relative_to(OUT))})

    print("[3/4] Collect prior Naruto text encoder/patch scripts",flush=True)
    seen=set()
    for rr in SCRIPT_ROOTS:
        if not rr.exists(): continue
        # bounded walk
        for p in rr.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".py",".ps1",".json",".tsv",".txt",".md"}:
                continue
            try:
                if p.stat().st_size>3*1024*1024: continue
            except: continue
            low=p.name.lower()
            take=False
            if rr.name in {"sub51d_full_text_apply","sub51c_full_text_prepare","sub51b_exact_source_collection"}:
                take=True
            if any(h in low for h in SCRIPT_HINTS):
                take=True
            if not take: continue
            key=str(p.resolve()).lower()
            if key in seen: continue
            seen.add(key)
            prefix=re.sub(r'[^A-Za-z0-9._-]+','_',rr.name)+"__"
            dst=copy_unique(p,scripts,prefix)
            manifests.append({"kind":"script","source":safe_rel(p),"copy":str(dst.relative_to(OUT))})

    (OUT/"collection.json").write_text(json.dumps(manifests,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "Naruto SUB52C static patch source collection\n\n"
        f"Collected items={len(manifests)}\n"
        "Purpose: build one static residual translation patch without gameplay discovery.\n"
        "Target tables: bunshin/nazonazo/quiz1/quiz2/mugen.\n"
        "Target images: character TEX_name, winner, minigame, slot, mugen cards/UI.\n"
        "Previous SUB51D text encoder/patch sources are included when present.\n",
        encoding="utf-8-sig"
    )

    print("[4/4] Package",flush=True)
    z=LOGS/"naruto_sub52c_static_patch_sources_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.rglob("*"):
            if p.is_file(): zz.write(p,p.relative_to(OUT))
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub52c_static_patch_sources_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.rglob("*"):
                if p.is_file():zz.write(p,p.relative_to(OUT))
        print(traceback.format_exc(),flush=True)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
