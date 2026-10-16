#!/usr/bin/env python3
# Naruto PSP MOV03 - Burned JP subtitle segment extraction
#
# Input:
#   KR PMFs: Japanese subtitles burned into the black bottom band.
#   MOV02 mapping: verifies corresponding US *e PMFs are the same visual movie.
#
# Output:
#   subtitle_segments.tsv/csv
#   per_frame_metrics/*.tsv
#   crops/<movie>/<segment>_{kr_full,kr_sub,us_e_full,us_e_sub}.jpg
#   shared handoff TSV for the SUB chat
#
# Method:
#   - 10 fps analysis (~0.1 sec timing)
#   - crop the bottom 18% black subtitle band
#   - grayscale + downscale to 240x24
#   - detect white/light subtitle glyph pixels
#   - split on blank gaps and large binary-mask changes
#   - merge tiny transition fragments
#
# Credits-heavy movies dk102/dk202 are excluded from automatic dialogue subtitle
# segmentation and marked SPECIAL_CREDITS.

from __future__ import annotations
import csv, json, math, os, re, shutil, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
ANALYSIS = ROOT / "analysis"
MOV02 = ANALYSIS / "mov" / "mov02_us_pmf_pairing"
STAGE = ANALYSIS / "mov" / "mov03_subtitle_segments"
METRIC_DIR = STAGE / "per_frame_metrics"
CROP_DIR = STAGE / "crops"
SHARED = ANALYSIS / "shared"

PAIRING = MOV02 / "kr_us_pmf_pairing.csv"
KR_DIR = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_DIR = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

SPECIAL_CREDITS = {"dk102.pmf", "dk202.pmf"}
ANALYSIS_FPS = 10.0
W = 240
H = 24
FRAME_BYTES = W * H

# Dynamic bottom 18% crop, then normalize to a tiny grayscale strip.
VF_BOTTOM = (
    "crop=iw:trunc(ih*0.18/2)*2:0:ih-trunc(ih*0.18/2)*2,"
    f"fps={ANALYSIS_FPS:g},scale={W}:{H}:flags=area,format=gray"
)

# Detection thresholds.  The PMF subtitle band is black; Japanese glyphs are
# white/light.  Two thresholds make compression noise less likely to trigger.
BRIGHT_HI = 185
BRIGHT_LO = 145
MIN_HI_PIXELS = 22
MIN_LO_PIXELS = 55

# Segmentation behavior.
MIN_SEGMENT_SEC = 0.25
MERGE_BLANK_GAP_SEC = 0.22
MIN_CHANGE_SPLIT_SEC = 0.28
MASK_CHANGE_THRESHOLD = 0.52

def log(*a):
    print(*a, flush=True)

def find_tool(name: str) -> str | None:
    x=shutil.which(name)
    if x:
        return x
    for base in [
        ROOT/"tools", ROOT/"ffmpeg", Path(r"LOCAL_PATH"), Path(r"LOCAL_PATH"),
        ANALYSIS
    ]:
        if not base.exists():
            continue
        for en in ([name+".exe",name] if os.name=="nt" else [name]):
            for p in base.rglob(en):
                if p.is_file():
                    return str(p)
    return None

def probe_duration(ffprobe: str, p: Path) -> float | None:
    q=subprocess.run([
        ffprobe,"-v","error","-show_entries","format=duration",
        "-of","default=nw=1:nk=1",str(p)
    ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
      encoding="utf-8",errors="replace",timeout=30)
    if q.returncode!=0:
        return None
    try:
        return float(q.stdout.strip().splitlines()[0])
    except Exception:
        return None

def decode_bottom(ffmpeg: str, p: Path) -> list[bytes]:
    cmd=[
        ffmpeg,"-hide_banner","-loglevel","error","-i",str(p),
        "-an","-sn","-dn","-vf",VF_BOTTOM,
        "-f","rawvideo","-pix_fmt","gray","-"
    ]
    q=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1200)
    if q.returncode!=0:
        raise RuntimeError(
            f"ffmpeg subtitle-band decode failed: {p}\n"
            +q.stderr.decode("utf-8","replace")[-1800:]
        )
    raw=q.stdout
    n=len(raw)//FRAME_BYTES
    return [raw[i*FRAME_BYTES:(i+1)*FRAME_BYTES] for i in range(n)]

def metric(frame: bytes):
    hi=0; lo=0; mask=0; bit=0
    for v in frame:
        if v>=BRIGHT_LO:
            lo+=1
            mask |= 1<<bit
        if v>=BRIGHT_HI:
            hi+=1
        bit+=1
    active=(hi>=MIN_HI_PIXELS and lo>=MIN_LO_PIXELS)
    return hi,lo,mask,active

def mask_change(a:int,b:int) -> float:
    u=(a|b).bit_count()
    if u==0:
        return 0.0
    return (a^b).bit_count()/u

def raw_runs(rows):
    # First pass: active/blank runs.
    runs=[]
    start=None
    for i,r in enumerate(rows):
        if r["active"] and start is None:
            start=i
        if (not r["active"]) and start is not None:
            runs.append([start,i-1])
            start=None
    if start is not None:
        runs.append([start,len(rows)-1])
    return runs

def merge_short_gaps(runs):
    if not runs:
        return []
    max_gap=round(MERGE_BLANK_GAP_SEC*ANALYSIS_FPS)
    out=[runs[0][:]]
    for s,e in runs[1:]:
        prev=out[-1]
        gap=s-prev[1]-1
        if gap<=max_gap:
            prev[1]=e
        else:
            out.append([s,e])
    return out

def split_text_changes(rows,runs):
    out=[]
    min_frames=max(2,round(MIN_CHANGE_SPLIT_SEC*ANALYSIS_FPS))
    for s,e in runs:
        seg_start=s
        ref_mask=rows[s]["mask"]
        last_change=s
        # Require a high change that persists for at least 2 frames.
        i=s+1
        while i<=e:
            ch=mask_change(ref_mask,rows[i]["mask"])
            if ch>=MASK_CHANGE_THRESHOLD and (i-seg_start)>=min_frames:
                # Confirm next frame looks more like the new mask than old mask.
                if i<e:
                    newm=rows[i]["mask"]
                    next_to_new=mask_change(newm,rows[i+1]["mask"])
                    next_to_old=mask_change(ref_mask,rows[i+1]["mask"])
                    confirmed=(next_to_new < next_to_old)
                else:
                    confirmed=True
                if confirmed:
                    out.append([seg_start,i-1])
                    seg_start=i
                    ref_mask=rows[i]["mask"]
                    last_change=i
                    i+=1
                    continue
            # Slowly update reference only when the current mask is close, to
            # tolerate anti-aliasing/compression shimmer without chasing changes.
            if ch<0.20:
                ref_mask=rows[i]["mask"]
            i+=1
        out.append([seg_start,e])
    return out

def clean_segments(rows,segs):
    min_frames=max(1,round(MIN_SEGMENT_SEC*ANALYSIS_FPS))
    # Drop very short fragments.
    segs=[x for x in segs if x[1]-x[0]+1>=min_frames]
    if not segs:
        return []

    # Merge adjacent fragments separated by <=0.2 sec if their representative
    # masks remain similar.
    max_gap=round(MERGE_BLANK_GAP_SEC*ANALYSIS_FPS)
    out=[segs[0][:]]
    for s,e in segs[1:]:
        ps,pe=out[-1]
        gap=s-pe-1
        pm=rows[(ps+pe)//2]["mask"]
        cm=rows[(s+e)//2]["mask"]
        if gap<=max_gap and mask_change(pm,cm)<0.30:
            out[-1][1]=e
        else:
            out.append([s,e])
    return out

def pick_representative(rows,s,e):
    # Choose active frame with maximum high-threshold glyph pixels, but avoid
    # extreme edge frames where text may still be fading.
    pad=min(2,max(0,(e-s)//4))
    lo=s+pad; hi=e-pad
    if hi<lo:
        lo,hi=s,e
    best=max(range(lo,hi+1),key=lambda i:(rows[i]["hi"],rows[i]["lo"]))
    return best

def extract_jpg(ffmpeg: str, src: Path, t: float, out: Path, crop_bottom=False):
    out.parent.mkdir(parents=True,exist_ok=True)
    vf="scale=480:-2:flags=area"
    if crop_bottom:
        vf="crop=iw:trunc(ih*0.18/2)*2:0:ih-trunc(ih*0.18/2)*2,scale=480:-2:flags=area"
    q=subprocess.run([
        ffmpeg,"-y","-hide_banner","-loglevel","error",
        "-ss",f"{max(0,t):.3f}","-i",str(src),
        "-frames:v","1","-vf",vf,"-q:v","4",str(out)
    ],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
    return q.returncode==0 and out.exists()

def sample_bottom_metric(ffmpeg: str, src: Path, t: float):
    # Decode a single bottom-band grayscale frame and apply the same detector.
    cmd=[
        ffmpeg,"-hide_banner","-loglevel","error","-ss",f"{max(0,t):.3f}",
        "-i",str(src),"-an","-sn","-dn","-frames:v","1",
        "-vf",f"crop=iw:trunc(ih*0.18/2)*2:0:ih-trunc(ih*0.18/2)*2,scale={W}:{H}:flags=area,format=gray",
        "-f","rawvideo","-pix_fmt","gray","-"
    ]
    q=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    if q.returncode!=0 or len(q.stdout)<FRAME_BYTES:
        return None
    hi,lo,mask,active=metric(q.stdout[:FRAME_BYTES])
    return {"hi":hi,"lo":lo,"active":active}

def write_table(p:Path,rows,delim):
    if not rows:
        p.write_text("",encoding="utf-8-sig")
        return
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()),delimiter=delim)
        w.writeheader();w.writerows(rows)

def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    METRIC_DIR.mkdir(parents=True,exist_ok=True)
    CROP_DIR.mkdir(parents=True,exist_ok=True)
    SHARED.mkdir(parents=True,exist_ok=True)

    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"ffmpeg/ffprobe required: {ffmpeg}/{ffprobe}")
    if not PAIRING.exists():
        raise RuntimeError(f"MOV02 pairing missing: {PAIRING}")

    with PAIRING.open("r",encoding="utf-8-sig",newline="") as f:
        pair=list(csv.DictReader(f))

    log("========================================================================")
    log(" Naruto PSP MOV03 - Burned Japanese subtitle segment extraction")
    log("========================================================================")
    log(f"Analysis FPS : {ANALYSIS_FPS:g}")
    log(f"Bottom crop  : 18%")
    log(f"Movies       : {len(pair)}")

    all_segments=[]
    movie_summary=[]

    for mi,r in enumerate(pair,1):
        name=r["kr_filename"]
        kr=KR_DIR/name
        ue=US_DIR/r["us_e_filename"]
        cls=r["us_e_classification"]

        log(f"\n[{mi:02d}/{len(pair):02d}] {name}  US-e={cls}")

        if name.lower() in SPECIAL_CREDITS:
            log("  SPECIAL_CREDITS -> automatic dialogue segmentation skipped")
            movie_summary.append({
                "filename":name,"status":"SPECIAL_CREDITS","segments":0,
                "us_e_classification":cls,"note":"credits/localized staff roll"
            })
            continue

        if cls not in ("SAME_VIDEO_HIGH","SAME_VIDEO_MEDIUM"):
            log("  SKIP -> US-e counterpart not sufficiently verified")
            movie_summary.append({
                "filename":name,"status":"PAIR_UNRESOLVED","segments":0,
                "us_e_classification":cls,"note":"MOV02 pairing not high/medium"
            })
            continue

        if not kr.exists() or not ue.exists():
            raise RuntimeError(f"Missing PMF: KR={kr.exists()} US-e={ue.exists()} {name}")

        frames=decode_bottom(ffmpeg,kr)
        rows=[]
        for i,fr in enumerate(frames):
            hi,lo,mask,active=metric(fr)
            rows.append({
                "frame_index":i,
                "time_sec":round(i/ANALYSIS_FPS,3),
                "bright_hi":hi,
                "bright_lo":lo,
                "active":1 if active else 0,
                "mask":mask,
            })

        runs=raw_runs(rows)
        runs=merge_short_gaps(runs)
        segs=split_text_changes(rows,runs)
        segs=clean_segments(rows,segs)

        metric_rows=[{
            "frame_index":x["frame_index"],"time_sec":x["time_sec"],
            "bright_hi":x["bright_hi"],"bright_lo":x["bright_lo"],
            "active":x["active"]
        } for x in rows]
        write_table(METRIC_DIR/f"{Path(name).stem}_metrics.tsv",metric_rows,"\t")

        # MOV02 coarse alignment is 0 / +/-0.5 sec.  Use it for clean US-e
        # crop sampling only; subtitle timing remains KR-local and exact.
        try:
            us_off=float(r.get("us_e_offset_sec") or 0.0)
        except Exception:
            us_off=0.0

        movie_crop=CROP_DIR/Path(name).stem
        movie_crop.mkdir(parents=True,exist_ok=True)

        for si,(s,e) in enumerate(segs,1):
            rep=pick_representative(rows,s,e)
            start=s/ANALYSIS_FPS
            # Use end of last active analysis frame.
            end=(e+1)/ANALYSIS_FPS
            rep_t=rep/ANALYSIS_FPS
            peak_hi=max(rows[j]["hi"] for j in range(s,e+1))
            peak_lo=max(rows[j]["lo"] for j in range(s,e+1))

            ident=f"{Path(name).stem}_{si:03d}"
            kr_full=movie_crop/f"{ident}_kr_full.jpg"
            kr_sub=movie_crop/f"{ident}_kr_sub.jpg"
            ue_full=movie_crop/f"{ident}_us_e_full.jpg"
            ue_sub=movie_crop/f"{ident}_us_e_sub.jpg"

            extract_jpg(ffmpeg,kr,rep_t,kr_full,False)
            extract_jpg(ffmpeg,kr,rep_t,kr_sub,True)
            extract_jpg(ffmpeg,ue,max(0,rep_t+us_off),ue_full,False)
            extract_jpg(ffmpeg,ue,max(0,rep_t+us_off),ue_sub,True)

            clean_metric=sample_bottom_metric(ffmpeg,ue,max(0,rep_t+us_off))
            clean_state="UNKNOWN"
            if clean_metric is not None:
                clean_state="CLEAN" if not clean_metric["active"] else "TEXT_PRESENT"

            all_segments.append({
                "segment_id":ident,
                "filename":name,
                "segment_index":si,
                "start_sec":round(start,3),
                "end_sec":round(end,3),
                "duration_sec":round(end-start,3),
                "representative_sec":round(rep_t,3),
                "peak_bright_hi":peak_hi,
                "peak_bright_lo":peak_lo,
                "us_e_filename":r["us_e_filename"],
                "us_e_offset_sec":round(us_off,3),
                "us_e_bottom_state":clean_state,
                "us_e_bottom_hi":clean_metric["hi"] if clean_metric else "",
                "us_e_bottom_lo":clean_metric["lo"] if clean_metric else "",
                "kr_full_image":str(kr_full.relative_to(STAGE)),
                "kr_sub_image":str(kr_sub.relative_to(STAGE)),
                "us_e_full_image":str(ue_full.relative_to(STAGE)),
                "us_e_sub_image":str(ue_sub.relative_to(STAGE)),
                "ocr_text":"",
                "korean_text":"",
                "review_status":"",
            })

        clean_n=sum(1 for x in all_segments if x["filename"]==name and x["us_e_bottom_state"]=="CLEAN")
        text_n=sum(1 for x in all_segments if x["filename"]==name and x["us_e_bottom_state"]=="TEXT_PRESENT")

        log(f"  frames={len(frames)} raw_runs={len(runs)} final_segments={len(segs)}")
        log(f"  US-e bottom check: CLEAN={clean_n} TEXT_PRESENT={text_n}")

        movie_summary.append({
            "filename":name,"status":"OK","segments":len(segs),
            "us_e_classification":cls,
            "note":f"US-e CLEAN={clean_n} TEXT_PRESENT={text_n}"
        })

    log("\n[Final] Save MOV03 outputs")

    write_table(STAGE/"subtitle_segments.tsv",all_segments,"\t")
    write_table(STAGE/"subtitle_segments.csv",all_segments,",")
    write_table(STAGE/"movie_summary.tsv",movie_summary,"\t")

    # Shared handoff intentionally contains only the compact data needed by
    # the SUB track; images remain in MOV03 and are referenced by relative path.
    write_table(SHARED/"mov_subtitle_segments.tsv",all_segments,"\t")

    total=len(all_segments)
    clean=sum(1 for x in all_segments if x["us_e_bottom_state"]=="CLEAN")
    textp=sum(1 for x in all_segments if x["us_e_bottom_state"]=="TEXT_PRESENT")
    special=sum(1 for x in movie_summary if x["status"]=="SPECIAL_CREDITS")
    unresolved=sum(1 for x in movie_summary if x["status"]=="PAIR_UNRESOLVED")

    summary=[
        "Naruto PSP MOV03 - Burned Japanese subtitle segment extraction",
        "="*76,"",
        f"Analysis FPS={ANALYSIS_FPS:g}",
        f"Movies in MOV02 pairing={len(pair)}",
        f"Automatic subtitle segments={total}",
        f"US-e representative subtitle bands CLEAN={clean}",
        f"US-e representative subtitle bands TEXT_PRESENT={textp}",
        f"SPECIAL_CREDITS movies={special}",
        f"Pair unresolved movies skipped={unresolved}",
        "",
        "Special credits skipped: "+", ".join(sorted(SPECIAL_CREDITS)),
        "",
        "Handoff:",
        str(SHARED/"mov_subtitle_segments.tsv"),
        "",
        "Next:",
        "1) Review segment crops / false splits.",
        "2) SUB track OCR/translates kr_sub_image -> korean_text.",
        "3) MOV track burns korean_text onto the clean US-e visual stream.",
        "4) Final stage restores/uses the KR audio stream while building PSP PMF.",
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
        print("\nMOV03 FAILED:",e,file=sys.stderr,flush=True)
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
