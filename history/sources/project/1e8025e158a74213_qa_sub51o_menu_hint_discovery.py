from pathlib import Path
import os, re, json, hashlib, zipfile, traceback, datetime

ROOT = Path(r"PROJECT_ROOT")
OUT = ROOT / r"analysis\sub\sub51o_menu_hint_discovery"
LOGS = ROOT / "logs"

TEXT_EXTS={".py",".ps1",".txt",".md",".json",".tsv",".csv",".ini",".xml",".yaml",".yml",".bat",".cmd"}
IMG_EXTS={".png",".bmp",".jpg",".jpeg",".webp",".dds",".tm2",".gim"}
SKIP_EXTS={".iso",".zip",".7z",".rar",".mp4",".pmf",".wav",".at3"}

KEYWORDS=[
    "새로 시작","이어서 시작","결정","취소","뒤로","돌아가기",
    "○","×","O 버튼","X 버튼","決定","戻る","キャンセル","選択",
    "titlehome","title_home","continue","new game","press","button","hint",
    "sub51m","sub51n","menu","atlas"
]

JP_HINTS=["○決定","×戻る","○ 決定","× 戻る","決定","戻る","キャンセル","選択"]
ENCODINGS=["utf-8","utf-8-sig","cp932","shift_jis","latin1"]

def sha1(p):
    h=hashlib.sha1()
    with open(p,"rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def safe_rel(p):
    try:return str(p.relative_to(ROOT))
    except:return str(p)

def collect_roots():
    roots=[]
    preferred=[
        ROOT/r"analysis\sub\sub51n_titlehomepolish",
        ROOT/r"analysis\sub",
        ROOT/r"generated_macros",
        ROOT/r"work",
    ]
    for p in preferred:
        if p.exists(): roots.append(p)
    return roots

def iter_files(root):
    for dp, dns, fns in os.walk(root):
        # avoid logs/old and generated huge build trees where possible, but retain sub51n exact tree
        dns[:] = [d for d in dns if d.lower() not in {"old","__pycache__",".git","temp","tmp"}]
        for fn in fns:
            p=Path(dp)/fn
            try:
                if p.suffix.lower() in SKIP_EXTS: continue
                if p.stat().st_size > 64*1024*1024: continue
                yield p
            except: pass

def decode_text(raw):
    for enc in ENCODINGS:
        try:
            s=raw.decode(enc)
            # Prefer decodes that produce visible text
            if len(s.strip()) >= 2:
                return s,enc
        except: pass
    return None,None

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    results={"stage":"SUB51O_MENU_HINT_DISCOVERY","roots":[],"text_hits":[],"binary_hits":[],"images":[],"scripts":[]}
    seen=set()
    roots=collect_roots()
    results["roots"]=[str(x) for x in roots]

    # Prioritize exact SUB51N and recent SUB51* source files.
    allfiles=[]
    for r in roots:
        for p in iter_files(r):
            key=str(p).lower()
            if key in seen: continue
            seen.add(key); allfiles.append(p)

    # File inventory around relevant stages.
    for p in allfiles:
        name=p.name.lower()
        rel=safe_rel(p)
        try:size=p.stat().st_size
        except:continue
        if p.suffix.lower() in {".py",".ps1",".bat",".cmd"} and any(k in rel.lower() for k in ["sub51","title","menu","ui"]):
            results["scripts"].append({"path":rel,"size":size,"sha1":sha1(p)})
        if p.suffix.lower() in IMG_EXTS and any(k in rel.lower() for k in ["sub51","title","menu","ui","atlas","option","home"]):
            try:
                item={"path":rel,"size":size,"sha1":sha1(p)}
                if p.suffix.lower()==".png":
                    try:
                        from PIL import Image
                        with Image.open(p) as im:item["wh"]=[im.width,im.height]
                    except:pass
                results["images"].append(item)
            except:pass

    # Text/script search.
    for p in allfiles:
        if p.suffix.lower() not in TEXT_EXTS: continue
        try:raw=p.read_bytes()
        except:continue
        s,enc=decode_text(raw)
        if s is None:continue
        lines=s.splitlines()
        matches=[]
        for i,line in enumerate(lines,1):
            low=line.lower()
            hit=[k for k in KEYWORDS if k.lower() in low]
            if hit:
                matches.append({"line":i,"keys":hit,"text":line[:500]})
        if matches:
            results["text_hits"].append({"path":safe_rel(p),"encoding":enc,"matches":matches[:120]})

    # Binary exact search for common Japanese button hints in CP932/UTF variants.
    needles=[]
    for t in JP_HINTS:
        for enc in ["cp932","utf-8","utf-16le","utf-16be"]:
            try:
                b=t.encode(enc)
                needles.append((t,enc,b))
            except:pass
    # Limit binary scan to analysis/sub source/build artifacts, excluding ISO.
    for p in allfiles:
        if p.suffix.lower() in TEXT_EXTS or p.suffix.lower() in IMG_EXTS: continue
        try:
            size=p.stat().st_size
            if size>32*1024*1024: continue
            raw=p.read_bytes()
        except:continue
        hits=[]
        for t,enc,b in needles:
            off=raw.find(b)
            if off>=0:
                hits.append({"text":t,"encoding":enc,"offset":off})
        if hits:
            results["binary_hits"].append({"path":safe_rel(p),"size":size,"hits":hits[:20]})

    # Rank likely useful files.
    def score_path(s):
        l=s.lower(); score=0
        for k,w in [("sub51n",20),("titlehome",20),("sub51m",12),("title",8),("menu",7),("home",6),("atlas",5),("option",4),("ui",3)]:
            if k in l: score+=w
        return score
    results["scripts"]=sorted(results["scripts"],key=lambda x:(-score_path(x["path"]),x["path"]))[:200]
    results["images"]=sorted(results["images"],key=lambda x:(-score_path(x["path"]),x["path"]))[:400]
    results["text_hits"]=sorted(results["text_hits"],key=lambda x:(-score_path(x["path"]),x["path"]))[:300]

    (OUT/"discovery.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[
        "Naruto SUB51O Menu/Hint Discovery",
        "",
        "PURPOSE: locate exact source/texture/script for title-menu contrast and untranslated O/X hints.",
        "GAME DATA MODIFIED: NO",
        f"Roots: {len(roots)}",
        f"Text hit files: {len(results['text_hits'])}",
        f"Binary hit files: {len(results['binary_hits'])}",
        f"Candidate scripts: {len(results['scripts'])}",
        f"Candidate images: {len(results['images'])}",
        "",
        "TOP TEXT HITS:"
    ]
    for ent in results["text_hits"][:40]:
        lines.append(f"- {ent['path']} [{ent['encoding']}]")
        for m in ent["matches"][:6]:
            lines.append(f"  L{m['line']}: {m['text']}")
    lines += ["","BINARY BUTTON-HINT HITS:"]
    for ent in results["binary_hits"][:40]:
        lines.append(f"- {ent['path']}: "+", ".join(f"{h['text']}({h['encoding']})@0x{h['offset']:X}" for h in ent["hits"]))
    lines += ["","TOP CANDIDATE SCRIPTS:"]
    for ent in results["scripts"][:40]: lines.append(f"- {ent['path']} size={ent['size']} sha1={ent['sha1']}")
    lines += ["","TOP CANDIDATE IMAGES:"]
    for ent in results["images"][:60]:
        wh=f" {ent.get('wh','')}" if ent.get("wh") else ""
        lines.append(f"- {ent['path']} size={ent['size']}{wh} sha1={ent['sha1']}")
    (OUT/"SUMMARY.txt").write_text("\n".join(lines),encoding="utf-8-sig")

    # Copy only small relevant source scripts/text to source_snapshot preserving relative path.
    snap=OUT/"source_snapshot"
    copied=0
    candidate_paths=[]
    for ent in results["scripts"][:100]:
        candidate_paths.append(ROOT/ent["path"])
    for ent in results["text_hits"][:120]:
        candidate_paths.append(ROOT/ent["path"])
    uniq=[]
    seen2=set()
    for p in candidate_paths:
        k=str(p).lower()
        if k in seen2:continue
        seen2.add(k);uniq.append(p)
    for p in uniq:
        try:
            if p.exists() and p.stat().st_size <= 2*1024*1024:
                rel=p.relative_to(ROOT)
                dst=snap/rel
                dst.parent.mkdir(parents=True,exist_ok=True)
                dst.write_bytes(p.read_bytes()); copied+=1
        except:pass

    # Create upload ZIP.
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath=LOGS/"naruto_sub51o_menu_hint_discovery_upload.zip"
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
        for p in OUT.rglob("*"):
            if p.is_file(): z.write(p,p.relative_to(OUT))
    print((OUT/"SUMMARY.txt").read_text(encoding="utf-8-sig"))
    print(f"\nCopied source files: {copied}")
    print("UPLOAD_ZIP="+str(zpath))

if __name__=="__main__":
    try:
        main()
    except Exception:
        LOGS.mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
        err=traceback.format_exc()
        (OUT/"FAILURE.txt").write_text(err,encoding="utf-8")
        zpath=LOGS/"fail_naruto_sub51o_menu_hint_discovery_upload.zip"
        with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
            for p in OUT.rglob("*"):
                if p.is_file(): z.write(p,p.relative_to(OUT))
        print(err)
        print("UPLOAD_ZIP="+str(zpath))
        raise
