#!/usr/bin/env python3
# Naruto PSP MOV02 - KR PMF <-> US localized PMF pairing validation
#
# Goal:
#   Verify whether each KR DA/DK/DM PMF has a frame-identical/timing-identical
#   US "*e.pmf" counterpart (and compare against the US same-name PMF).
#
# If the visual stream matches after masking the subtitle area, we no longer
# need to find these cutscenes inside the long YouTube playthrough:
#   KR PMF timing == localized PMF timing
# and subtitle timing can be recovered directly from the localized movie.
#
# Standard library only. Requires ffmpeg + ffprobe.

from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
ANALYSIS = ROOT / "analysis"
STAGE = ANALYSIS / "mov" / "mov02_us_pmf_pairing"
VERIFY = STAGE / "verification"
CACHE = STAGE / "fingerprint_cache"

KR_DIR = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_DIR = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"
INVENTORY = ANALYSIS / "stage38f_movie_inventory" / "movie_inventory.csv"

FPS = 2.0
W = 40
H = 22
FRAME_BYTES = W * H

# Main scene signature: keep the upper 64% of the image.  This intentionally
# removes the JP/EN subtitle band at the bottom, so localization text does not
# prevent scene matching.
VF_SCENE = (
    "crop=iw:trunc(ih*0.64/2)*2:0:0,"
    f"fps={FPS:g},scale={W}:{H}:flags=area,format=gray"
)

# Full image signature is only a diagnostic.  A scene can still be confirmed
# when this score is worse because localized subtitle text is expected to differ.
VF_FULL = f"fps={FPS:g},scale={W}:{H}:flags=area,format=gray"

LOGOS = {"logo_a.pmf", "logo_b.pmf", "logo_c.pmf"}

def log(*a):
    print(*a, flush=True)

def find_tool(name: str) -> str | None:
    x = shutil.which(name)
    if x:
        return x
    for base in [
        ROOT/"tools", ROOT/"ffmpeg", Path(r"LOCAL_PATH"), Path(r"LOCAL_PATH"),
        ANALYSIS
    ]:
        if not base.exists():
            continue
        for en in ([name+".exe", name] if os.name == "nt" else [name]):
            for p in base.rglob(en):
                if p.is_file():
                    return str(p)
    return None

def run_text(cmd, timeout=120):
    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    return p.returncode, p.stdout, p.stderr

def duration(ffprobe: str, p: Path) -> float | None:
    rc,out,err = run_text([
        ffprobe,"-v","error","-show_entries","format=duration",
        "-of","default=nw=1:nk=1",str(p)
    ], 30)
    if rc != 0:
        return None
    try:
        return float(out.strip().splitlines()[0])
    except Exception:
        return None

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest().upper()

def sig(frame: bytes) -> tuple[int,int,int,float]:
    if len(frame) != FRAME_BYTES:
        raise ValueError("bad frame size")
    # Horizontal differences.
    hh=0; bit=0
    for y in range(H):
        o=y*W
        for x in range(W-1):
            if frame[o+x] > frame[o+x+1]:
                hh |= 1<<bit
            bit += 1
    # Vertical differences.
    vh=0; bit=0
    for y in range(H-1):
        a=y*W; b=(y+1)*W
        for x in range(W):
            if frame[a+x] > frame[b+x]:
                vh |= 1<<bit
            bit += 1
    mean=sum(frame)/FRAME_BYTES
    ah=0
    for i,v in enumerate(frame):
        if v > mean:
            ah |= 1<<i
    mad=sum(abs(v-mean) for v in frame)/FRAME_BYTES
    return hh,vh,ah,mad

TOTAL_BITS=(W-1)*H + W*(H-1) + W*H

def dist(a,b) -> float:
    return (
        (a[0]^b[0]).bit_count()
        +(a[1]^b[1]).bit_count()
        +(a[2]^b[2]).bit_count()
    ) / TOTAL_BITS

def fingerprint(ffmpeg: str, p: Path, vf: str, tag: str):
    CACHE.mkdir(parents=True,exist_ok=True)
    stat=p.stat()
    key=f"{stat.st_size}_{int(stat.st_mtime)}"
    safe=re.sub(r"[^A-Za-z0-9_.-]+","_",p.stem)
    c=CACHE/f"{tag}_{safe}_{key}.json"

    if c.exists():
        try:
            o=json.loads(c.read_text(encoding="utf-8"))
            if o.get("vf")==vf and o.get("fps")==FPS and o.get("w")==W and o.get("h")==H:
                return [
                    (int(x["h"],16),int(x["v"],16),int(x["a"],16),float(x["mad"]))
                    for x in o["frames"]
                ]
        except Exception:
            pass

    cmd=[
        ffmpeg,"-hide_banner","-loglevel","error","-i",str(p),
        "-an","-sn","-dn","-vf",vf,
        "-f","rawvideo","-pix_fmt","gray","-"
    ]
    q=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=900)
    if q.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fingerprint failed: {p}\n"
            +q.stderr.decode("utf-8","replace")[-1500:]
        )
    raw=q.stdout
    n=len(raw)//FRAME_BYTES
    out=[sig(raw[i*FRAME_BYTES:(i+1)*FRAME_BYTES]) for i in range(n)]
    c.write_text(json.dumps({
        "path":str(p),"vf":vf,"fps":FPS,"w":W,"h":H,
        "frames":[{"h":f"{x[0]:x}","v":f"{x[1]:x}","a":f"{x[2]:x}","mad":round(x[3],5)} for x in out]
    }),encoding="utf-8")
    return out

def sample_idx(frames, n=36):
    if not frames:
        return []
    pad=max(2,round(FPS*1.5))
    lo=min(pad,len(frames)-1)
    hi=max(lo,len(frames)-1-pad)
    if hi<=lo:
        xs=list(range(len(frames)))
    else:
        count=min(n*2,hi-lo+1)
        xs=[]
        for i in range(count):
            x=round(lo+(hi-lo)*(i/max(1,count-1)))
            if not xs or xs[-1]!=x:
                xs.append(x)
    good=[i for i in xs if frames[i][3]>=8.0]
    xs=good if len(good)>=max(5,min(10,n)) else xs
    if len(xs)<=n:
        return xs
    out=[]
    for i in range(n):
        j=round(i*(len(xs)-1)/(n-1))
        if not out or out[-1]!=xs[j]:
            out.append(xs[j])
    return out

def eval_offset(a_frames,b_frames,offset_sec: float,local_radius_sec=0.5):
    idx=sample_idx(a_frames,36)
    off=round(offset_sec*FPS)
    rad=max(0,round(local_radius_sec*FPS))
    vals=[]; drifts=[]
    for ai in idx:
        expected=ai+off
        lo=max(0,expected-rad)
        hi=min(len(b_frames)-1,expected+rad)
        if lo>hi:
            continue
        bd=9.0; bi=None
        for bj in range(lo,hi+1):
            d=dist(a_frames[ai],b_frames[bj])
            if d<bd:
                bd=d; bi=bj
        if bi is not None:
            vals.append(bd)
            drifts.append((bi-expected)/FPS)
    if not vals:
        return {"score":9.0,"median":9.0,"coverage":0.0,"drift":0.0,"n":0}
    s=sorted(vals)
    keep=max(3,math.ceil(len(s)*0.85))
    kept=s[:keep]
    return {
        "score":sum(kept)/len(kept),
        "median":statistics.median(vals),
        "coverage":sum(x<=0.18 for x in vals)/len(vals),
        "drift":statistics.median(drifts) if drifts else 0.0,
        "n":len(vals)
    }

def align_pair(a_frames,b_frames):
    # Counterparts should be extremely close in timing. Search +/-5 seconds at
    # 0.5s steps, then refine with local temporal drift.
    candidates=[]
    for step in range(-10,11):
        off=step/2.0
        ev=eval_offset(a_frames,b_frames,off,0.5)
        candidates.append((ev["score"],off,ev))
    candidates.sort(key=lambda x:(x[0],-x[2]["coverage"]))
    score,off,ev=candidates[0]
    refined=off+ev["drift"]
    ev2=eval_offset(a_frames,b_frames,refined,0.5)
    if ev2["score"]<=ev["score"]:
        off=refined; ev=ev2
    second=next((x for x in candidates[1:] if abs(x[1]-off)>=1.5),None)
    second_score=second[0] if second else 9.0
    return {
        "offset_sec":off,"score":ev["score"],"median":ev["median"],
        "coverage":ev["coverage"],"samples":ev["n"],
        "second_score":second_score,"margin":second_score-ev["score"]
    }

def classify(scene, durdiff):
    if scene is None:
        return "MISSING"
    s=scene["score"]; cov=scene["coverage"]; off=abs(scene["offset_sec"])
    if abs(durdiff)<=1.5 and off<=2.0 and s<=0.10 and cov>=0.80:
        return "SAME_VIDEO_HIGH"
    if abs(durdiff)<=3.0 and off<=5.0 and s<=0.20 and cov>=0.50:
        return "SAME_VIDEO_MEDIUM"
    if s<=0.28 and cov>=0.25:
        return "POSSIBLE"
    return "DIFFERENT_OR_UNRESOLVED"

def extract_frame(ffmpeg: str, src: Path, t: float, out: Path):
    out.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([
        ffmpeg,"-y","-hide_banner","-loglevel","error",
        "-ss",f"{max(0,t):.3f}","-i",str(src),"-frames:v","1",
        "-vf","scale=480:-2:flags=area","-q:v","5",str(out)
    ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)

def load_candidates():
    rows=[]
    if INVENTORY.exists():
        with INVENTORY.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                n=r.get("filename","")
                if not n.lower().endswith(".pmf") or n.lower() in LOGOS:
                    continue
                if r.get("subtitle_candidate","YES")!="YES":
                    continue
                rows.append(n)
    else:
        rows=[p.name for p in sorted(KR_DIR.glob("*.pmf")) if p.name.lower() not in LOGOS]
    return rows

def write_table(p: Path, rows, delim):
    if not rows:
        return
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()),delimiter=delim)
        w.writeheader();w.writerows(rows)

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    VERIFY.mkdir(parents=True,exist_ok=True)
    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"ffmpeg/ffprobe required: {ffmpeg} / {ffprobe}")
    if not KR_DIR.exists() or not US_DIR.exists():
        raise RuntimeError(f"KR/US movie folders missing: {KR_DIR} / {US_DIR}")

    log("========================================================================")
    log(" Naruto PSP MOV02 - KR PMF <-> US localized PMF pairing")
    log("========================================================================")
    log(f"ffmpeg : {ffmpeg}")
    log(f"ffprobe: {ffprobe}")

    names=load_candidates()
    log(f"\n[1/5] Candidate PMFs: {len(names)}")

    rows=[]; verify=[]
    for i,name in enumerate(names,1):
        kr=KR_DIR/name
        stem=kr.stem
        same=US_DIR/name
        ep=US_DIR/(stem+"e.pmf")

        log(f"\n[{i:02d}/{len(names):02d}] {name}")
        if not kr.exists():
            raise RuntimeError(f"KR PMF missing: {kr}")

        krdur=duration(ffprobe,kr)
        krhash=sha256(kr)

        kr_scene=fingerprint(ffmpeg,kr,VF_SCENE,f"scene_kr_{stem}")
        kr_full=fingerprint(ffmpeg,kr,VF_FULL,f"full_kr_{stem}")

        def inspect(label,p):
            if not p.exists():
                return None
            d=duration(ffprobe,p)
            h=sha256(p)
            scene=fingerprint(ffmpeg,p,VF_SCENE,f"scene_{label}_{p.stem}")
            full=fingerprint(ffmpeg,p,VF_FULL,f"full_{label}_{p.stem}")
            al=align_pair(kr_scene,scene)
            al_full=eval_offset(kr_full,full,al["offset_sec"],0.5)
            dd=(d-krdur) if (d is not None and krdur is not None) else 9999.0
            return {
                "path":p,"duration":d,"sha256":h,"scene":al,"full":al_full,
                "duration_diff":dd,"classification":classify(al,dd)
            }

        same_r=inspect("same",same)
        e_r=inspect("e",ep)

        def val(r,k,default=""):
            if r is None:
                return default
            return r.get(k,default)

        row={
            "kr_filename":name,
            "kr_duration_sec":round(krdur,3) if krdur is not None else "",
            "kr_bytes":kr.stat().st_size,
            "kr_sha256":krhash,
            "us_same_exists":"YES" if same_r else "NO",
            "us_same_duration_sec":round(same_r["duration"],3) if same_r and same_r["duration"] is not None else "",
            "us_same_duration_diff_sec":round(same_r["duration_diff"],3) if same_r else "",
            "us_same_byte_identical":"YES" if same_r and same_r["sha256"]==krhash else "NO",
            "us_same_scene_score":round(same_r["scene"]["score"],6) if same_r else "",
            "us_same_scene_coverage":round(same_r["scene"]["coverage"],4) if same_r else "",
            "us_same_offset_sec":round(same_r["scene"]["offset_sec"],3) if same_r else "",
            "us_same_full_score":round(same_r["full"]["score"],6) if same_r else "",
            "us_same_classification":same_r["classification"] if same_r else "MISSING",
            "us_e_filename":ep.name,
            "us_e_exists":"YES" if e_r else "NO",
            "us_e_duration_sec":round(e_r["duration"],3) if e_r and e_r["duration"] is not None else "",
            "us_e_duration_diff_sec":round(e_r["duration_diff"],3) if e_r else "",
            "us_e_byte_identical":"YES" if e_r and e_r["sha256"]==krhash else "NO",
            "us_e_scene_score":round(e_r["scene"]["score"],6) if e_r else "",
            "us_e_scene_coverage":round(e_r["scene"]["coverage"],4) if e_r else "",
            "us_e_offset_sec":round(e_r["scene"]["offset_sec"],3) if e_r else "",
            "us_e_full_score":round(e_r["full"]["score"],6) if e_r else "",
            "us_e_classification":e_r["classification"] if e_r else "MISSING",
        }
        rows.append(row)

        log(
            "  same: "
            +(f"{same_r['classification']} durΔ={same_r['duration_diff']:.3f}s "
              f"offset={same_r['scene']['offset_sec']:.3f}s score={same_r['scene']['score']:.4f} "
              f"cov={same_r['scene']['coverage']:.2f}"
              if same_r else "MISSING")
        )
        log(
            "  *e  : "
            +(f"{e_r['classification']} durΔ={e_r['duration_diff']:.3f}s "
              f"offset={e_r['scene']['offset_sec']:.3f}s score={e_r['scene']['score']:.4f} "
              f"cov={e_r['scene']['coverage']:.2f}"
              if e_r else "MISSING")
        )

        # Verification: full frames at five positions, KR vs US-e.
        if e_r and krdur:
            off=e_r["scene"]["offset_sec"]
            edur=e_r["duration"] or krdur
            for label,ratio in [("p10",.10),("p30",.30),("p50",.50),("p70",.70),("p90",.90)]:
                kt=max(.25,min(krdur-.25,krdur*ratio))
                et=max(.25,min(edur-.25,kt+off))
                a=VERIFY/f"{stem}_{label}_kr.jpg"
                b=VERIFY/f"{stem}_{label}_us_e.jpg"
                extract_frame(ffmpeg,kr,kt,a)
                extract_frame(ffmpeg,ep,et,b)
                verify.append({
                    "filename":name,"point":label,
                    "kr_sec":round(kt,3),"us_e_sec":round(et,3),
                    "classification":e_r["classification"],
                    "kr_image":a.name,"us_e_image":b.name
                })

    write_table(STAGE/"kr_us_pmf_pairing.tsv",rows,"\t")
    write_table(STAGE/"kr_us_pmf_pairing.csv",rows,",")
    write_table(STAGE/"verification_manifest.tsv",verify,"\t")

    log("\n[2/5] Summary statistics")
    ecounts={}
    scounts={}
    for r in rows:
        ecounts[r["us_e_classification"]]=ecounts.get(r["us_e_classification"],0)+1
        scounts[r["us_same_classification"]]=scounts.get(r["us_same_classification"],0)+1
    for k,v in sorted(ecounts.items()):
        log(f"  US *e {k}: {v}")
    for k,v in sorted(scounts.items()):
        log(f"  US same-name {k}: {v}")

    log("\n[3/5] Decide subtitle-timing source")
    usable=[
        r for r in rows
        if r["us_e_classification"] in ("SAME_VIDEO_HIGH","SAME_VIDEO_MEDIUM")
    ]
    log(f"  US *e usable counterparts: {len(usable)}/{len(rows)}")

    log("\n[4/5] Verification images")
    log(f"  {VERIFY}")
    log(f"  pairs={len(verify)}")

    log("\n[5/5] Save summary")
    summary=[
        "Naruto PSP MOV02 - KR PMF <-> US localized PMF pairing",
        "="*76,"",
        f"Candidates={len(rows)}",
        f"US *e usable SAME_VIDEO_HIGH/MEDIUM={len(usable)}/{len(rows)}",
        "US *e classification: "+", ".join(f"{k}={v}" for k,v in sorted(ecounts.items())),
        "US same-name classification: "+", ".join(f"{k}={v}" for k,v in sorted(scounts.items())),
        "",
        "Interpretation:",
        "- scene_score is computed with the bottom subtitle band removed.",
        "- full_score includes subtitles and may be worse when localized text differs.",
        "- SAME_VIDEO_HIGH/MEDIUM means the localized PMF can provide direct subtitle timing.",
        "",
        "Next gate:",
        "- Visually review KR vs US-e verification images.",
        "- If US-e counterparts are the same movie, stop trying to map DM to YouTube.",
        "- Next step becomes subtitle-event extraction from the localized PMFs, then Korean burn-in on KR PMFs.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    log("\n".join(summary))
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print("\nMOV02 FAILED:",e,file=sys.stderr,flush=True)
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
