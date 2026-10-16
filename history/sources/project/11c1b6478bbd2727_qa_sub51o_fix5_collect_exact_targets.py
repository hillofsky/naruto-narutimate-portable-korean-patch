from pathlib import Path
import shutil, zipfile, traceback, json, os, hashlib

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub51o_fix5_exact_targets"
LOGS=ROOT/"logs"

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def copy_hit(src, tag):
    dst=OUT/(tag+"__"+src.name)
    shutil.copy2(src,dst)
    print("FOUND",src,flush=True)
    return {"tag":tag,"source":str(src),"file":dst.name,"size":src.stat().st_size,"sha256":sha256(src)}

def first_existing(cands):
    for p in cands:
        if p.exists(): return p
    return None

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    found=[]; missing=[]

    # 1) Exact untranslated O/X guide texture.
    xpanel_cands=[
        ROOT/r"analysis\sub\sub51k_residual_ui_sweep\orig_dump\gauge.ccs_TEX_xpanel.png",
        ROOT/r"analysis\sub\sub51k_residual_ui_sweep\gauge.ccs_TEX_xpanel.png",
        ROOT/r"analysis\sub\sub51n_titlehomepolish\orig_dump\gauge.ccs_TEX_xpanel.png",
    ]
    p=first_existing(xpanel_cands)
    if p: found.append(copy_hit(p,"gauge_TEX_xpanel_ORIG"))
    else:
        # exact filename bounded fallback in known stage trees only
        hit=None
        for r in [ROOT/r"analysis\sub\sub51k_residual_ui_sweep", ROOT/r"analysis\sub\sub51n_titlehomepolish"]:
            if not r.exists(): continue
            for q in r.rglob("gauge.ccs_TEX_xpanel.png"):
                hit=q;break
            if hit:break
        if hit: found.append(copy_hit(hit,"gauge_TEX_xpanel_ORIG"))
        else: missing.append("gauge.ccs_TEX_xpanel.png")

    # 2) Current title assets and originals.
    base=ROOT/r"analysis\sub\sub51n_titlehomepolish"
    for name,tag in [
        ("n__TEX_panel_KO_HC.png","title_panel_KO"),
        ("n__TEX_panel2_KO_HC.png","title_panel2_KO"),
        ("n__TEX_panel3_KO_HC.png","title_panel3_KO"),
        ("title.ccs_TEX_panel.png","title_panel_ORIG"),
        ("title.ccs_TEX_panel2.png","title_panel2_ORIG"),
        ("title.ccs_TEX_panel3.png","title_panel3_ORIG"),
    ]:
        hit=None
        for d in [base/"build_assets",base/"assets_n",base/"orig_dump"]:
            q=d/name
            if q.exists():hit=q;break
        if hit is None and base.exists():
            for q in base.rglob(name):
                hit=q;break
        if hit:found.append(copy_hit(hit,tag))
        else:missing.append(name)

    # 3) Exact build/repack scripts around SUB51N and prior UI stages.
    script_patterns=[
        "build_naruto_sub51n*.py","build_naruto_sub51n*.ps1",
        "*sub51n*build*.py","*sub51n*build*.ps1",
        "*texture*.py","*ccs*.py","*fsts*.py"
    ]
    script_roots=[
        base,
        ROOT/r"analysis\sub\sub51l_fix2_consolidated_ui",
        ROOT/r"analysis\sub\sub51k_residual_ui_sweep",
        ROOT,
    ]
    copied_scripts=set()
    for sr in script_roots:
        if not sr.exists():continue
        # Top-level only for ROOT, bounded recursive for exact stage roots.
        candidates=[]
        if sr==ROOT:
            for pat in ["*sub51n*.py","*sub51n*.ps1"]:
                candidates += list(sr.glob(pat))
        else:
            for pat in script_patterns:
                candidates += list(sr.rglob(pat))
        for q in candidates:
            try:
                if q.stat().st_size>2*1024*1024:continue
            except:continue
            key=str(q).lower()
            if key in copied_scripts:continue
            copied_scripts.add(key)
            safe="script__"+str(q.relative_to(ROOT)).replace("\\","__").replace("/","__")
            dst=OUT/safe
            shutil.copy2(q,dst)
            found.append({"tag":"script","source":str(q),"file":dst.name,"size":q.stat().st_size,"sha256":sha256(q)})
            print("SCRIPT",q,flush=True)

    # 4) Current mapping/verification manifests.
    for name in ["sub51n_texture_patch.tsv","sub51n_preflight.tsv","SUB51N_static_verification.json","SUMMARY.txt"]:
        q=base/"build"/name
        if q.exists():
            dst=OUT/("manifest__"+name);shutil.copy2(q,dst)
            found.append({"tag":"manifest","source":str(q),"file":dst.name,"size":q.stat().st_size,"sha256":sha256(q)})

    report={"stage":"SUB51O_FIX5_EXACT_TARGETS","found":found,"missing":missing}
    (OUT/"collection.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY_FIX5.txt").write_text(
        "SUB51O FIX5 exact target collection\n"
        "Confirmed untranslated control guide: gauge.ccs / TEX_xpanel\n"
        "No PPSSPP / no ISO modification\n\n"
        f"found={len(found)} missing={len(missing)}\n"+
        ("\nMISSINLOCAL_PATH"+"\n".join(missing) if missing else ""),
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub51o_fix5_exact_targets_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for q in OUT.iterdir():
            if q.is_file():zz.write(q,q.name)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True);LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix5_exact_targets_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for q in OUT.iterdir():
                if q.is_file():zz.write(q,q.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
