from pathlib import Path
import os, json, hashlib, zipfile, traceback, datetime, sys

ROOT = Path(r"PROJECT_ROOT")
OUT = ROOT / r"analysis\sub\sub51o_menu_hint_discovery_fix1"
LOGS = ROOT / "logs"

TEXT_EXTS={".py",".ps1",".txt",".md",".json",".tsv",".csv",".ini",".xml",".yaml",".yml",".bat",".cmd"}
IMG_EXTS={".png",".bmp",".jpg",".jpeg",".webp",".dds",".tm2",".gim"}
KEYWORDS=[
    "새로 시작","이어서 시작","결정","취소","뒤로","돌아가기",
    "○","×","O 버튼","X 버튼","決定","戻る","キャンセル","選択",
    "titlehome","title_home","continue","new game","press","button","hint",
    "sub51m","sub51n","menu","atlas"
]
JP_HINTS=["○決定","×戻る","○ 決定","× 戻る","決定","戻る","キャンセル","選択"]
ENCODINGS=["utf-8","utf-8-sig","cp932","shift_jis","latin1"]

def log(msg):
    print(msg, flush=True)

def sha1(p):
    h=hashlib.sha1()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def safe_rel(p):
    try:return str(p.relative_to(ROOT))
    except:return str(p)

def decode_text(raw):
    for enc in ENCODINGS:
        try:return raw.decode(enc),enc
        except:pass
    return None,None

def add_if_exists(lst,p):
    if p.exists(): lst.append(p)

def candidate_roots():
    roots=[]
    # Exact/current stage trees first
    for rel in [
        r"analysis\sub\sub51n_titlehomepolish",
        r"analysis\sub\sub51n",
        r"analysis\sub\sub51m",
        r"analysis\sub\sub51l",
        r"analysis\sub\sub51k",
        r"analysis\sub\sub51j",
        r"analysis\sub\sub51i",
        r"analysis\sub\sub51h",
        r"analysis\sub\sub51g",
        r"analysis\sub\sub51f",
        r"analysis\sub\sub51e",
        r"analysis\sub\sub51d",
        r"analysis\sub\sub51c",
        r"analysis\sub\sub51b",
        r"analysis\sub\sub51a",
        r"generated_macros",
        r"work",
    ]:
        add_if_exists(roots, ROOT/rel)

    # Also include top-level files in analysis/sub whose names contain sub51/title/menu/ui.
    sub=ROOT/r"analysis\sub"
    if sub.exists():
        roots.append(sub)
    return roots

def iter_bounded(root):
    # analysis/sub root itself: only top-level files and explicitly named sub51* dirs, never all history.
    if root == ROOT/r"analysis\sub":
        try:
            for p in root.iterdir():
                n=p.name.lower()
                if p.is_file():
                    if any(k in n for k in ["sub51","title","menu","ui"]):
                        yield p
                elif p.is_dir() and any(k in n for k in ["sub51","titlehome"]):
                    # bounded recursive walk, depth <= 4
                    base_depth=len(p.parts)
                    for dp,dns,fns in os.walk(p):
                        cur=Path(dp)
                        depth=len(cur.parts)-base_depth
                        if depth >= 4:
                            dns[:] = []
                        dns[:] = [d for d in dns if d.lower() not in {"old","__pycache__",".git","temp","tmp","logs"}]
                        for fn in fns:
                            fp=cur/fn
                            try:
                                if fp.stat().st_size <= 32*1024*1024:
                                    yield fp
                            except: pass
        except Exception: pass
        return

    # Other preferred roots: depth <= 4 and skip heavy dirs.
    base_depth=len(root.parts)
    for dp,dns,fns in os.walk(root):
        cur=Path(dp)
        depth=len(cur.parts)-base_depth
        if depth >= 4:
            dns[:] = []
        dns[:] = [d for d in dns if d.lower() not in {
            "old","__pycache__",".git","temp","tmp","logs","iso","isos","backup","backups","frames","captures"
        }]
        for fn in fns:
            p=cur/fn
            try:
                if p.suffix.lower() in {".iso",".zip",".7z",".rar",".mp4",".pmf",".wav",".at3"}: continue
                if p.stat().st_size > 32*1024*1024: continue
                yield p
            except: pass

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    results={"stage":"SUB51O_MENU_HINT_DISCOVERY_FIX1","roots":[],"text_hits":[],"binary_hits":[],"images":[],"scripts":[]}

    roots=candidate_roots()
    results["roots"]=[str(x) for x in roots]
    log(f"[1/5] Candidate roots: {len(roots)}")

    files=[]
    seen=set()
    for idx,r in enumerate(roots,1):
        log(f"      scanning {idx}/{len(roots)}: {safe_rel(r)}")
        for p in iter_bounded(r):
            k=str(p).lower()
            if k in seen: continue
            seen.add(k); files.append(p)
    log(f"[2/5] Files collected: {len(files)}")

    for i,p in enumerate(files,1):
        if i % 100 == 0: log(f"      inventory {i}/{len(files)}")
        rel=safe_rel(p); n=rel.lower()
        try:size=p.stat().st_size
        except:continue
        if p.suffix.lower() in {".py",".ps1",".bat",".cmd"} and any(k in n for k in ["sub51","title","menu","ui"]):
            try: results["scripts"].append({"path":rel,"size":size,"sha1":sha1(p)})
            except: pass
        if p.suffix.lower() in IMG_EXTS and any(k in n for k in ["sub51","title","menu","ui","atlas","option","home"]):
            try:
                item={"path":rel,"size":size,"sha1":sha1(p)}
                if p.suffix.lower()==".png":
                    try:
                        from PIL import Image
                        with Image.open(p) as im:item["wh"]=[im.width,im.height]
                    except:pass
                results["images"].append(item)
            except:pass

    log("[3/5] Text keyword scan")
    for i,p in enumerate(files,1):
        if i % 100 == 0: log(f"      text {i}/{len(files)}")
        if p.suffix.lower() not in TEXT_EXTS: continue
        try: raw=p.read_bytes()
        except: continue
        s,enc=decode_text(raw)
        if s is None: continue
        matches=[]
        for ln,line in enumerate(s.splitlines(),1):
            low=line.lower()
            hit=[k for k in KEYWORDS if k.lower() in low]
            if hit: matches.append({"line":ln,"keys":hit,"text":line[:500]})
        if matches:
            results["text_hits"].append({"path":safe_rel(p),"encoding":enc,"matches":matches[:100]})

    log("[4/5] Small binary hint scan")
    needles=[]
    for t in JP_HINTS:
        for enc in ["cp932","utf-8","utf-16le","utf-16be"]:
            try: needles.append((t,enc,t.encode(enc)))
            except: pass
    for i,p in enumerate(files,1):
        if i % 200 == 0: log(f"      binary {i}/{len(files)}")
        if p.suffix.lower() in TEXT_EXTS or p.suffix.lower() in IMG_EXTS: continue
        try:
            if p.stat().st_size > 8*1024*1024: continue
            raw=p.read_bytes()
        except: continue
        hits=[]
        for t,enc,b in needles:
            off=raw.find(b)
            if off>=0: hits.append({"text":t,"encoding":enc,"offset":off})
        if hits: results["binary_hits"].append({"path":safe_rel(p),"hits":hits})

    def score(s):
        l=s.lower();v=0
        for k,w in [("sub51n",30),("titlehome",25),("sub51m",20),("sub51l",15),("title",10),("menu",8),("atlas",6),("option",5),("ui",4)]:
            if k in l:v+=w
        return v
    for k in ["scripts","images","text_hits"]:
        results[k]=sorted(results[k],key=lambda x:(-score(x["path"]),x["path"]))

    log("[5/5] Writing report/package")
    (OUT/"discovery.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[
        "Naruto SUB51O Menu/Hint Discovery FIX1","",
        "PPSSPP launch: NOT REQUIRED (file/resource discovery only)",
        "Game/ISO modification: NO","",
        f"files={len(files)}",
        f"text_hit_files={len(results['text_hits'])}",
        f"binary_hit_files={len(results['binary_hits'])}",
        f"scripts={len(results['scripts'])}",
        f"images={len(results['images'])}","",
        "TOP TEXT HITS:"
    ]
    for ent in results["text_hits"][:50]:
        lines.append(f"- {ent['path']} [{ent['encoding']}]")
        for m in ent["matches"][:8]:
            lines.append(f"  L{m['line']}: {m['text']}")
    lines += ["","BINARY HITS:"]
    for ent in results["binary_hits"][:50]:
        lines.append(f"- {ent['path']}: "+", ".join(f"{h['text']}:{h['encoding']}@0x{h['offset']:X}" for h in ent["hits"]))
    lines += ["","TOP SCRIPTS:"]
    for ent in results["scripts"][:60]: lines.append(f"- {ent['path']}")
    lines += ["","TOP IMAGES:"]
    for ent in results["images"][:80]: lines.append(f"- {ent['path']} {ent.get('wh','')}")
    (OUT/"SUMMARY.txt").write_text("\n".join(lines),encoding="utf-8-sig")

    snap=OUT/"source_snapshot"; copied=0
    cand=[]
    for ent in results["scripts"][:80]: cand.append(ROOT/ent["path"])
    for ent in results["text_hits"][:100]: cand.append(ROOT/ent["path"])
    seen2=set()
    for p in cand:
        k=str(p).lower()
        if k in seen2:continue
        seen2.add(k)
        try:
            if p.exists() and p.stat().st_size<=2*1024*1024:
                rel=p.relative_to(ROOT); dst=snap/rel
                dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(p.read_bytes());copied+=1
        except: pass

    zpath=LOGS/"naruto_sub51o_fix1_menu_hint_discovery_upload.zip"
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
        for p in OUT.rglob("*"):
            if p.is_file(): z.write(p,p.relative_to(OUT))
    log(f"DONE. copied_sources={copied}")
    log("UPLOAD_ZIP="+str(zpath))

if __name__=="__main__":
    try: main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        err=traceback.format_exc()
        (OUT/"FAILURE.txt").write_text(err,encoding="utf-8")
        zpath=LOGS/"fail_naruto_sub51o_fix1_menu_hint_discovery_upload.zip"
        with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
            for p in OUT.rglob("*"):
                if p.is_file(): z.write(p,p.relative_to(OUT))
        print(err,flush=True); print("UPLOAD_ZIP="+str(zpath),flush=True)
        raise
