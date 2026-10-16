from pathlib import Path
import shutil, zipfile, json, hashlib, traceback

ROOT = Path(r"PROJECT_ROOT")
OUT = ROOT / r"analysis\sub\sub51p_texred_ko_candidates"
LOGS = ROOT / "logs"

EXACT = [
    ROOT / r"analysis\sub\sub51n_titlehomepolish\build_assets\j__TEX_red_KO_STYLED.png",
    ROOT / r"sub43_assets\entry0214__gauge__0247__TEX_red_upright_ko.png",
    ROOT / r"analysis\sub\sub51e_fix1_ui_style_source_export\mugen\entry0214__gauge__0247__TEX_red_upright_ko_e4320f7bd77e.png",
    ROOT / r"analysis\sub\sub51e_fix1_ui_style_source_export\mugen\gauge_ccs__TEX_red_e69df976c7a0.png",
    ROOT / r"analysis\sub\sub51e_fix1_ui_style_source_export\mugen\gauge_ccs__TEX_red_f4a41459c3cf.png",
    ROOT / r"analysis\sub\sub48_menu_atlas_cleanup\review_textures\gauge_ccs__TEX_red.png",
    ROOT / r"analysis\sub\sub47_network_option_home\discovery_textures\gauge_ccs__TEX_red.png",
    ROOT / r"analysis\sub\sub51f_official_kr_ui_donor\jp_png\gauge__TEX_red_JP.png",
    ROOT / r"analysis\sub\sub51f_official_kr_ui_donor\official_kr_png\gauge__TEX_red_KR.png",
    ROOT / r"analysis\sub\sub51f_official_kr_ui_donor\pairs\gauge__TEX_red_JP_vs_KR.png",
    ROOT / r"analysis\sub\sub51p_texred_original\gauge.ccs_TEX_red_ORIGINAL.png",
    ROOT / r"analysis\sub\sub51p_texred_original\gauge.ccs_TEX_red_ORIGINAL_grid16.png",
]

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    found=[]
    missing=[]

    print("=== SUB51P TEX_red KO CANDIDATE COLLECTION ===", flush=True)

    for i,p in enumerate(EXACT,1):
        print(f"[{i}/{len(EXACT)}] {p}", flush=True)
        if not p.exists():
            missing.append(str(p))
            print("  MISSING", flush=True)
            continue
        safe = f"{i:02d}__{p.name}"
        dst = OUT / safe
        shutil.copy2(p,dst)
        item = {
            "source": str(p),
            "copied_as": safe,
            "size": p.stat().st_size,
            "sha256": sha256(p),
        }
        try:
            from PIL import Image
            with Image.open(p) as im:
                item["width"]=im.width
                item["height"]=im.height
                item["mode"]=im.mode
        except Exception:
            pass
        found.append(item)
        print("  FOUND ->", safe, flush=True)

    # Also bounded-search only exact TEX_red translated-looking names under known dirs.
    roots = [
        ROOT / r"analysis\sub\sub51e_fix1_ui_style_source_export",
        ROOT / r"analysis\sub\sub51n_titlehomepolish",
        ROOT / r"analysis\sub\sub48_menu_atlas_cleanup",
        ROOT / r"sub43_assets",
    ]
    seen={x["sha256"] for x in found}
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.png"):
            n=p.name.lower()
            if "tex_red" not in n:
                continue
            if not any(k in n for k in ["ko","styled","upright","gauge"]):
                continue
            try:
                h=sha256(p)
            except Exception:
                continue
            if h in seen:
                continue
            seen.add(h)
            safe=f"extra__{len(found)+1:02d}__{p.name}"
            dst=OUT/safe
            shutil.copy2(p,dst)
            found.append({
                "source":str(p),
                "copied_as":safe,
                "size":p.stat().st_size,
                "sha256":h,
            })
            print("  EXTRA ->", p, flush=True)

    report={"stage":"SUB51P_TEXRED_KO_CANDIDATES","found":found,"missing":missing}
    (OUT/"collection.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "SUB51P TEX_red Korean candidate collection\n\n"
        f"Found={len(found)} Missing={len(missing)}\n"
        "Purpose: compare existing historical Koreanized TEX_red atlases against exact SUB51N original.\n"
        "No ISO modification / no PPSSPP / no story automation.\n",
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub51p_texred_ko_candidates_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for q in OUT.iterdir():
            if q.is_file():
                zz.write(q,q.name)
    print("UPLOAD_ZIP="+str(z), flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True)
        LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51p_texred_ko_candidates_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for q in OUT.iterdir():
                if q.is_file():
                    zz.write(q,q.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
