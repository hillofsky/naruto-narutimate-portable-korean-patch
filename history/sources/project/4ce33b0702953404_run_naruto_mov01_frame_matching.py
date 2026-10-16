#!/usr/bin/env python3
# Naruto PSP MOV01 - coarse PMF <-> YouTube source frame matching
# Standard library only. Requires ffmpeg + ffprobe executables.

from __future__ import annotations
import csv, json, math, os, re, shutil, subprocess, sys, time, traceback, zipfile
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
ANALYSIS = ROOT / "analysis"
STAGE = ANALYSIS / "mov" / "mov01_frame_matching"
VERIFY = STAGE / "verification"
CACHE = STAGE / "fingerprint_cache"
KR_MOVIE = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
INVENTORY = ANALYSIS / "stage38f_movie_inventory" / "movie_inventory.csv"

TARGETS = {
    "part1": 7327.720,  # last Stage37 Part1 completed-frame timestamp
    "part2": 2971.669,  # last Stage37B Part2 completed-frame timestamp
}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m2ts"}
EXCLUDE_DIR_TOKENS = {
    "stage38a_cuda", "cuda_runtime", "fingerprint_cache", "verification",
    "kr_extracted", "us_extracted", "thumbnails",
}
PMF_LOGOS = {"logo_a.pmf","logo_b.pmf","logo_c.pmf"}

def eprint(*a):
    print(*a, file=sys.stderr, flush=True)

def find_tool(name: str) -> str | None:
    x = shutil.which(name)
    if x:
        return x
    candidates = [
        ROOT / "tools", ROOT / "ffmpeg", ANALYSIS,
        Path(r"LOCAL_PATH"), Path(r"LOCAL_PATH Files\ffmpeg"),
        Path(r"LOCAL_PATH Files (x86)\ffmpeg"),
    ]
    exe_names = [name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        exe_names.insert(0, name + ".exe")
    for base in candidates:
        if not base.exists():
            continue
        for en in exe_names:
            for p in base.rglob(en):
                if p.is_file():
                    return str(p)
    return None

def run_text(cmd: list[str], timeout=120) -> tuple[int,str,str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr

def probe_duration(ffprobe: str, path: Path) -> float | None:
    rc,out,err = run_text([
        ffprobe, "-v","error", "-show_entries","format=duration",
        "-of","default=nw=1:nk=1", str(path)
    ], timeout=30)
    if rc != 0:
        return None
    try:
        return float(out.strip().splitlines()[0])
    except Exception:
        return None

def safe_rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except Exception:
        return str(p)

def discover_source_candidates(ffprobe: str) -> list[dict]:
    rows=[]
    seen=set()
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        lowparts={x.lower() for x in p.parts}
        if any(tok.lower() in lowparts for tok in EXCLUDE_DIR_TOKENS):
            continue
        if p.stat().st_size < 20*1024*1024:
            continue
        key=str(p.resolve()).lower()
        if key in seen: continue
        seen.add(key)
        dur=probe_duration(ffprobe,p)
        if dur is None: continue
        d1=abs(dur-TARGETS["part1"])
        d2=abs(dur-TARGETS["part2"])
        rows.append({
            "path":str(p),"relative_path":safe_rel(p),"bytes":p.stat().st_size,
            "duration_sec":dur,"diff_part1":d1,"diff_part2":d2,
            "score_part1":d1,"score_part2":d2
        })
    rows.sort(key=lambda r:min(r["diff_part1"],r["diff_part2"]))
    return rows

def read_override() -> dict[str,str]:
    p=STAGE/"source_override.txt"
    out={}
    if not p.exists(): return out
    for line in p.read_text(encoding="utf-8-sig",errors="replace").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v=line.split("=",1)
        k=k.strip().lower(); v=v.strip().strip('"')
        if k in ("part1","part2") and v:
            out[k]=v
    return out

def choose_sources(cands:list[dict]) -> tuple[dict[str,Path],list[str]]:
    notes=[]
    override=read_override()
    chosen={}
    for part in ("part1","part2"):
        if part in override:
            p=Path(override[part])
            if not p.is_absolute(): p=ROOT/p
            if not p.exists():
                raise RuntimeError(f"{part} override file not found: {p}")
            chosen[part]=p
            notes.append(f"{part}: override -> {p}")
            continue
        ranked=sorted(cands,key=lambda r:r[f"diff_{part}"])
        if not ranked:
            raise RuntimeError("No source video candidates found")
        best=ranked[0]
        # Last completed-frame timestamp should be near, but source may have some tail.
        if best[f"diff_{part}"] > 180:
            top="\n".join(f"  {r['duration_sec']:.3f}s diff={r[f'diff_{part}']:.3f} {r['path']}" for r in ranked[:10])
            raise RuntimeError(
                f"Could not confidently auto-select {part}; nearest duration differs by >180s.\n"
                f"Create {STAGE/'source_override.txt'} with PART1=... / PART2=...\nTop candidateLOCAL_PATH"
            )
        chosen[part]=Path(best["path"])
        notes.append(f"{part}: auto -> {best['path']} ({best['duration_sec']:.3f}s, diff={best[f'diff_{part}']:.3f}s)")
    if chosen["part1"].resolve()==chosen["part2"].resolve():
        raise RuntimeError("Part1 and Part2 resolved to the same source video")
    return chosen,notes

def dhashes_from_raw(raw:bytes) -> list[int]:
    frame_size=9*8
    n=len(raw)//frame_size
    hashes=[]
    for i in range(n):
        f=raw[i*frame_size:(i+1)*frame_size]
        h=0
        bit=0
        for y in range(8):
            off=y*9
            for x in range(8):
                if f[off+x] > f[off+x+1]:
                    h |= 1<<bit
                bit+=1
        hashes.append(h)
    return hashes

def fingerprint(ffmpeg:str,path:Path,kind:str) -> list[int]:
    CACHE.mkdir(parents=True,exist_ok=True)
    sig=f"{path.stat().st_size}_{int(path.stat().st_mtime)}"
    cache=CACHE/f"{kind}_{re.sub(r'[^A-Za-z0-9_.-]+','_',path.stem)}_{sig}.json"
    if cache.exists():
        try:
            obj=json.loads(cache.read_text(encoding="utf-8"))
            return [int(x,16) for x in obj["hashes"]]
        except Exception:
            pass
    # Ignore bottom 30% where JP/KR subtitles live. Normalize to one frame/sec.
    vf="crop=iw:trunc(ih*0.70/2)*2:0:0,fps=1,scale=9:8:flags=area,format=gray"
    cmd=[ffmpeg,"-hide_banner","-loglevel","error","-i",str(path),
         "-an","-sn","-dn","-vf",vf,"-f","rawvideo","-pix_fmt","gray","-"]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1800)
    if p.returncode!=0:
        raise RuntimeError(f"ffmpeg fingerprint failed: {path}\n{p.stderr.decode('utf-8','replace')[-1500:]}")
    hashes=dhashes_from_raw(p.stdout)
    cache.write_text(json.dumps({"source":str(path),"hashes":[f"{x:016x}" for x in hashes]},ensure_ascii=False),
                     encoding="utf-8")
    return hashes

def sample_indices(n:int,max_samples=48) -> list[int]:
    if n<=0:return []
    lo=min(3,max(0,n-1)); hi=max(lo,n-4)
    if hi<=lo:return list(range(n))
    count=min(max_samples,hi-lo+1)
    if count<=1:return [(lo+hi)//2]
    idx=[]
    for i in range(count):
        x=round(lo+(hi-lo)*i/(count-1))
        if not idx or x!=idx[-1]: idx.append(x)
    return idx

def match_one(pmf_hashes:list[int], source_hashes:list[int]) -> dict:
    n=len(pmf_hashes); m=len(source_hashes)
    if n<3 or m<n:
        return {"best_offset":None,"best_score":999.0,"second_score":999.0,"margin":0.0,"samples":0}
    idxs=sample_indices(n,48)
    best_score=999.0; best_off=None
    scores=[]
    max_off=m-n
    for off in range(max_off+1):
        total=0
        for j in idxs:
            total += (pmf_hashes[j]^source_hashes[off+j]).bit_count()
        score=total/len(idxs)
        scores.append((score,off))
        if score<best_score:
            best_score=score; best_off=off
    # second distinct basin: at least 8 seconds away from best
    second=999.0
    for score,off in sorted(scores):
        if best_off is None or abs(off-best_off)>=8:
            second=score; break
    margin=second-best_score if second<999 else 0.0
    return {"best_offset":best_off,"best_score":best_score,"second_score":second,
            "margin":margin,"samples":len(idxs)}

def confidence(best:float,margin:float)->str:
    # dHash 64 bits. Exact/same-video matches typically very low.
    if best<=6.0 and margin>=3.0: return "HIGH"
    if best<=10.0 and margin>=1.5: return "MEDIUM"
    return "LOW"

def extract_frame(ffmpeg:str,src:Path,t:float,out:Path):
    out.parent.mkdir(parents=True,exist_ok=True)
    cmd=[ffmpeg,"-y","-hide_banner","-loglevel","error","-ss",f"{max(0,t):.3f}","-i",str(src),
         "-frames:v","1","-vf","scale=480:-2:flags=area", "-q:v","5",str(out)]
    subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)

def load_pmf_candidates() -> list[dict]:
    rows=[]
    if INVENTORY.exists():
        with INVENTORY.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                name=r.get("filename","")
                if not name.lower().endswith(".pmf") or name.lower() in PMF_LOGOS: continue
                if r.get("subtitle_candidate","YES")!="YES": continue
                rows.append(r)
    else:
        for p in sorted(KR_MOVIE.glob("*.pmf")):
            if p.name.lower() not in PMF_LOGOS:
                rows.append({"filename":p.name,"family":p.stem[:2].upper(),"duration_sec":""})
    return rows

def main():
    STAGE.mkdir(parents=True,exist_ok=True); VERIFY.mkdir(parents=True,exist_ok=True)
    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"ffmpeg/ffprobe required. ffmpeg={ffmpeg} ffprobe={ffprobe}")
    print(f"ffmpeg : {ffmpeg}",flush=True)
    print(f"ffprobe: {ffprobe}",flush=True)

    print("\n[1/6] Discover source videos",flush=True)
    cands=discover_source_candidates(ffprobe)
    with (STAGE/"source_candidates.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        cols=["duration_sec","diff_part1","diff_part2","bytes","relative_path","path"]
        w=csv.DictWriter(f,fieldnames=cols,delimiter="\t",extrasaction="ignore"); w.writeheader(); w.writerows(cands)
    for r in cands[:15]:
        print(f"  {r['duration_sec']:9.3f}s  d1={r['diff_part1']:8.3f} d2={r['diff_part2']:8.3f}  {r['relative_path']}",flush=True)

    sources,notes=choose_sources(cands)
    for n in notes: print("  "+n,flush=True)
    with (STAGE/"selected_sources.txt").open("w",encoding="utf-8-sig") as f:
        for part,p in sources.items():
            f.write(f"{part.upper()}={p}\n")

    print("\n[2/6] Fingerprint Part1/Part2 source videos (1 fps, bottom 30% masked)",flush=True)
    source_hash={}
    for part,p in sources.items():
        print(f"  {part}: {p}",flush=True)
        h=fingerprint(ffmpeg,p,f"src_{part}")
        source_hash[part]=h
        print(f"    frames={len(h)}",flush=True)

    print("\n[3/6] Match 21 PMFs",flush=True)
    pmfs=load_pmf_candidates()
    if len(pmfs)!=21:
        print(f"  WARNING: expected 21 subtitle candidates, got {len(pmfs)}",flush=True)

    results=[]
    for i,r in enumerate(pmfs,1):
        name=r["filename"]; p=KR_MOVIE/name
        print(f"\n[{i:02d}/{len(pmfs):02d}] {name}",flush=True)
        ph=fingerprint(ffmpeg,p,f"pmf_{p.stem}")
        candidates=[]
        for part in ("part1","part2"):
            mm=match_one(ph,source_hash[part])
            mm["part"]=part
            candidates.append(mm)
            print(f"  {part}: offset={mm['best_offset']} score={mm['best_score']:.3f} second={mm['second_score']:.3f} margin={mm['margin']:.3f}",flush=True)
        best=min(candidates,key=lambda x:x["best_score"])
        conf=confidence(best["best_score"],best["margin"])
        dur=probe_duration(ffprobe,p) or float(r.get("duration_sec") or 0)
        start=float(best["best_offset"]) if best["best_offset"] is not None else -1
        end=start+dur if start>=0 else -1
        print(f"  => {best['part']} {start:.3f}s ~ {end:.3f}s  confidence={conf}",flush=True)
        results.append({
            "filename":name,"family":r.get("family",p.stem[:2].upper()),
            "pmf_duration_sec":round(dur,3),"source_part":best["part"],
            "source_start_coarse_sec":round(start,3),"source_end_coarse_sec":round(end,3),
            "best_mean_hamming":round(best["best_score"],4),
            "second_mean_hamming":round(best["second_score"],4),
            "margin":round(best["margin"],4),"sample_points":best["samples"],
            "confidence":conf,
            "source_path":str(sources[best["part"]]),
        })

    with (STAGE/"pmf_source_mapping_coarse.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        cols=list(results[0].keys()) if results else []
        w=csv.DictWriter(f,fieldnames=cols,delimiter="\t"); w.writeheader(); w.writerows(results)
    with (STAGE/"pmf_source_mapping_coarse.csv").open("w",encoding="utf-8-sig",newline="") as f:
        cols=list(results[0].keys()) if results else []
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(results)

    print("\n[4/6] Extract verification frames (start/mid/end)",flush=True)
    verify_rows=[]
    for r in results:
        pmf=KR_MOVIE/r["filename"]; src=Path(r["source_path"])
        dur=float(r["pmf_duration_sec"]); start=float(r["source_start_coarse_sec"])
        if start<0: continue
        for label,local in [("start",min(1.0,max(0,dur*0.10))),("mid",dur*0.50),("end",max(0,dur-1.0))]:
            p1=VERIFY/f"{pmf.stem}_{label}_pmf.jpg"
            p2=VERIFY/f"{pmf.stem}_{label}_{r['source_part']}.jpg"
            extract_frame(ffmpeg,pmf,local,p1)
            extract_frame(ffmpeg,src,start+local,p2)
            verify_rows.append({
                "filename":r["filename"],"point":label,"pmf_local_sec":round(local,3),
                "source_part":r["source_part"],"source_sec":round(start+local,3),
                "pmf_image":p1.name if p1.exists() else "",
                "source_image":p2.name if p2.exists() else "",
            })
    with (STAGE/"verification_manifest.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        cols=list(verify_rows[0].keys()) if verify_rows else []
        w=csv.DictWriter(f,fieldnames=cols,delimiter="\t"); w.writeheader(); w.writerows(verify_rows)

    print("\n[5/6] Summary",flush=True)
    counts={}
    for r in results: counts[r["confidence"]]=counts.get(r["confidence"],0)+1
    with (STAGE/"SUMMARY.txt").open("w",encoding="utf-8-sig") as f:
        f.write("Naruto PSP MOV01 - PMF <-> YouTube coarse frame matching\n")
        f.write("="*72+"\n\n")
        for n in notes: f.write(n+"\n")
        f.write(f"\nPMF candidates={len(results)}\n")
        f.write("Confidence: "+", ".join(f"{k}={v}" for k,v in sorted(counts.items()))+"\n")
        f.write("\nMatching methoLOCAL_PATH")
        f.write("- 1 fps fingerprints\n- top 70% video only (subtitle area masked)\n")
        f.write("- 9x8 grayscale dHash\n- up to 48 temporal sample points per PMF\n")
        f.write("\nNext MOV02:\n- refine each coarse start within +/-2 sec at 0.1 sec resolution\n")
        f.write("- derive exact YouTube->PMF time transform for subtitle timing\n")
        f.write("- manually review LOW confidence matches before subtitle burn-in\n")
    print((STAGE/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

    print("\n[6/6] Done",flush=True)
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        STAGE.mkdir(parents=True,exist_ok=True)
        msg=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(msg,encoding="utf-8-sig")
        eprint("\nMOV01 FAILED:",e)
        eprint(msg)
        raise SystemExit(1)
