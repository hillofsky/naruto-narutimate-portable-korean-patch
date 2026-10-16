#!/usr/bin/env python3
# Naruto PSP MOV04B - exact subtitle timing for remaining real-text movies
#
# Visual review of MOV04A candidates established real Japanese text in:
#   da101, da201, dk101, dk102, dk202
#
# Bottom subtitle band:
#   KR-only exact detector, 10 fps, crop x=24 y=232 w=432 h=40
#
# Special centered overlay in dk202:
#   locally aligned KR-vs-US ROI difference, 10 fps
#
# Outputs:
#   subtitle_segments_exact.tsv
#   movie_summary.tsv
#   representatives\*_kr_sub.png
#   representatives\*_kr_full.jpg
#   representatives\*_us_full.jpg (centered-overlay review)
#
# No PMF/ISO modification.

from __future__ import annotations
import csv, math, os, shutil, statistics, subprocess, sys, traceback, zlib, binascii, struct
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov04b_exact_subtitle_timing"
REP = STAGE / "representatives"
LOGD = STAGE / "logs"
WORK = STAGE / "work"
for p in (STAGE, REP, LOGD, WORK):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")

FPS = 10.0

TARGETS = ["da101", "da201", "dk101", "dk102", "dk202"]

# Proven black subtitle band geometry from DM and MOV04A visual review.
BX, BY, BW, BH = 24, 232, 432, 40
BFRAME = BW * BH
LUMA_THRESHOLD = 96
MIN_BRIGHT_PIXELS = 20
TEXT_CHANGE_JACCARD = 0.34
MIN_SEGMENT_FRAMES = 2

# dk202 centered narrative overlay.
CX, CY, CW, CH = 60, 96, 360, 96
CLW, CLH = 90, 24
CFRAME = CLW * CLH

# Scene fingerprint outside centered text, used for local time alignment.
SX, SY, SW, SH = 24, 0, 432, 76
SLW, SLH = 36, 8
SFRAME = SLW * SLH
CENTER_SEARCH_RADIUS = 15  # +/-1.5 sec

def run(cmd, logname, timeout=1200):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout
    )
    txt = "COMMANLOCAL_PATH" + " ".join(
        ('"%s"' % str(x) if " " in str(x) else str(x)) for x in cmd
    )
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout
    txt += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(txt, encoding="utf-8-sig")
    return cp

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def us_source(name):
    for p in [US_MOV / f"{name}e.pmf", US_MOV / f"{name}.pmf"]:
        if p.exists():
            return p
    return None

def decode_gray(path, vf, frame_bytes, tag):
    cmd = [
        str(FFMPEG), "-v", "error", "-i", str(path),
        "-vf", vf,
        "-pix_fmt", "gray", "-f", "rawvideo", "-"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    assert p.stdout is not None
    while True:
        b = p.stdout.read(frame_bytes)
        if not b:
            break
        if len(b) != frame_bytes:
            break
        frames.append(b)
    err = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
    rc = p.wait()
    (LOGD / f"{tag}.log").write_text(
        "COMMANLOCAL_PATH" + " ".join(cmd) +
        "\n\nRETURN CODLOCAL_PATH" + str(rc) +
        "\n\nSTDERLOCAL_PATH" + err + "\n",
        encoding="utf-8-sig"
    )
    if rc != 0:
        raise RuntimeError(f"{tag}: ffmpeg raw decode failed")
    return frames

def bottom_frames(path, tag):
    vf = f"fps={FPS},crop={BW}:{BH}:{BX}:{BY},format=gray"
    return decode_gray(path, vf, BFRAME, tag + "_bottom")

def center_frames(path, tag):
    vf = f"fps={FPS},crop={CW}:{CH}:{CX}:{CY},scale={CLW}:{CLH}:flags=area,format=gray"
    return decode_gray(path, vf, CFRAME, tag + "_center")

def scene_frames(path, tag):
    vf = f"fps={FPS},crop={SW}:{SH}:{SX}:{SY},scale={SLW}:{SLH}:flags=area,format=gray"
    return decode_gray(path, vf, SFRAME, tag + "_scene")

def mask_from_gray(frame):
    return bytearray(1 if b >= LUMA_THRESHOLD else 0 for b in frame)

def jaccard(a, b):
    inter = 0
    union = 0
    for x, y in zip(a, b):
        if x or y:
            union += 1
            if x and y:
                inter += 1
    return inter / union if union else 1.0

def bottom_segments(frames):
    masks = []
    counts = []
    active = []

    for fr in frames:
        m = mask_from_gray(fr)
        c = sum(m)
        masks.append(m)
        counts.append(c)
        active.append(c >= MIN_BRIGHT_PIXELS)

    raw = []
    start = None
    prev = None

    for i, on in enumerate(active):
        if not on:
            if start is not None:
                raw.append((start, i-1))
                start = None
            prev = None
            continue

        if start is None:
            start = i
            prev = i
            continue

        jac = jaccard(masks[prev], masks[i]) if prev is not None else 1.0
        stable_a = counts[prev] >= 60
        stable_b = counts[i] >= 60
        if stable_a and stable_b and jac < TEXT_CHANGE_JACCARD:
            raw.append((start, i-1))
            start = i

        prev = i

    if start is not None:
        raw.append((start, len(frames)-1))

    raw = [(a,b) for a,b in raw if b-a+1 >= MIN_SEGMENT_FRAMES]

    # Repair one blank-frame dropout only when the glyph mask is the same.
    merged = []
    for a,b in raw:
        if not merged:
            merged.append((a,b))
            continue
        pa,pb = merged[-1]
        if a-pb-1 == 1:
            pi = max(range(pa,pb+1), key=lambda k: counts[k])
            ni = max(range(a,b+1), key=lambda k: counts[k])
            if jaccard(masks[pi], masks[ni]) >= 0.78:
                merged[-1] = (pa,b)
                continue
        merged.append((a,b))

    return merged, masks, counts, active

def mad(a,b):
    return sum(abs(x-y) for x,y in zip(a,b)) / len(a)

def percentile(vals,q):
    if not vals:
        return 0.0
    s=sorted(vals)
    if len(s)==1:return float(s[0])
    x=(len(s)-1)*q
    lo=int(math.floor(x));hi=int(math.ceil(x))
    if lo==hi:return float(s[lo])
    f=x-lo
    return s[lo]*(1-f)+s[hi]*f

def align_scene(kr_scene, us_scene):
    ratio = ((len(us_scene)-1)/(len(kr_scene)-1)) if len(kr_scene)>1 else 1.0
    mapping=[]
    prev=0
    for i,kf in enumerate(kr_scene):
        exp=int(round(i*ratio))
        lo=max(prev,exp-CENTER_SEARCH_RADIUS)
        hi=min(len(us_scene)-1,exp+CENTER_SEARCH_RADIUS)
        if lo>hi:
            lo=hi=min(len(us_scene)-1,max(0,exp))
        bestj=lo;bests=None
        for j in range(lo,hi+1):
            s=mad(kf,us_scene[j])
            if bests is None or s<bests:
                bests=s;bestj=j
        mapping.append((bestj,bests if bests is not None else 999.0))
        prev=bestj
    return mapping

def center_segments_dk202(kr,us):
    ks=scene_frames(kr,"dk202_kr")
    uss=scene_frames(us,"dk202_us")
    kc=center_frames(kr,"dk202_kr")
    uc=center_frames(us,"dk202_us")

    n=min(len(ks),len(kc))
    ks=ks[:n];kc=kc[:n]
    mapping=align_scene(ks,uss)

    scores=[]
    for i,(uj,_) in enumerate(mapping):
        if uj < len(uc):
            scores.append(mad(kc[i],uc[uj]))
        else:
            scores.append(0.0)

    # Baseline from most of the movie; centered narrative overlay is a large,
    # sustained outlier. Use robust threshold plus a hard floor.
    med=statistics.median(scores)
    dev=statistics.median([abs(x-med) for x in scores])
    thr=max(6.0, med+6.0*max(dev,0.5), percentile(scores,0.92)+1.5)

    active=[x>=thr for x in scores]

    # Remove isolated one-frame noise, fill one-frame holes.
    for i in range(1,len(active)-1):
        if not active[i] and active[i-1] and active[i+1]:
            active[i]=True

    segs=[]
    start=None
    for i,on in enumerate(active):
        if on and start is None:
            start=i
        if not on and start is not None:
            if i-start>=2:
                segs.append((start,i-1))
            start=None
    if start is not None and len(active)-start>=2:
        segs.append((start,len(active)-1))

    # MOV04A visual review already established the true centered text near
    # 91..97 sec. Limit this special ROI detector to that vicinity to reject
    # unrelated scene/localization differences.
    segs=[(a,b) for a,b in segs if (b/FPS)>=89.0 and (a/FPS)<=99.0]

    return segs, scores, mapping, kc, thr

def png_chunk(kind,data):
    body=kind+data
    return struct.pack(">I",len(data))+body+struct.pack(">I",binascii.crc32(body)&0xFFFFFFFF)

def write_gray_png(frame,w,h,out_path,scale=2):
    if len(frame)!=w*h:
        raise ValueError("gray frame size mismatch")
    ow,oh=w*scale,h*scale
    rows=[]
    for y in range(h):
        src=frame[y*w:(y+1)*w]
        expanded=bytes(v for b in src for v in [b]*scale)
        row=b"\x00"+expanded
        for _ in range(scale):
            rows.append(row)
    raw=b"".join(rows)
    png=bytearray(b"\x89PNG\r\n\x1a\n")
    png+=png_chunk(b"IHDR",struct.pack(">IIBBBBB",ow,oh,8,0,0,0,0))
    png+=png_chunk(b"IDAT",zlib.compress(raw,9))
    png+=png_chunk(b"IEND",b"")
    Path(out_path).write_bytes(png)

def exact_full_frames(src, indices, name, side):
    unique=sorted(set(int(x) for x in indices))
    if not unique:
        return {}
    tmp=WORK/f"_{name}_{side}_full"
    shutil.rmtree(tmp,ignore_errors=True)
    tmp.mkdir(parents=True,exist_ok=True)

    expr="+".join(f"eq(n\\,{i})" for i in unique)
    pat=tmp/"f_%04d.jpg"
    cp=run(
        [FFMPEG,"-y","-v","error","-i",src,
         "-vf",f"fps={FPS},select={expr},scale=480:272",
         "-fps_mode","vfr","-q:v","3",pat],
        f"{name}_{side}_full_extract.log",900
    )
    gen=sorted(tmp.glob("*.jpg"))
    result={}
    if cp.returncode==0 and len(gen)==len(unique):
        for idx,g in zip(unique,gen):
            out=REP/f"{name}_{side}_f{idx:05d}_full.jpg"
            shutil.move(str(g),str(out))
            result[idx]=str(out)
    shutil.rmtree(tmp,ignore_errors=True)
    return result

def main():
    if not FFMPEG.exists():
        raise RuntimeError("LOCAL_PATH missing")

    failure=STAGE/"FAILURE.txt"
    if failure.exists():failure.unlink()

    for p in REP.glob("*"):
        if p.is_file():p.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV04B - exact remaining subtitle timing",flush=True)
    print("="*80,flush=True)

    rows=[]
    summaries=[]

    for mi,name in enumerate(TARGETS,1):
        kr=KR_MOV/f"{name}.pmf"
        if not kr.exists():
            summaries.append(dict(movie=name,status="MISSING_KR"))
            continue

        print(f"[{mi:02d}/05] {name}",flush=True)

        frames=bottom_frames(kr,name+"_kr")
        segs,masks,counts,active=bottom_segments(frames)

        movie_start=len(rows)
        rep_indices=[]

        for si,(a,b) in enumerate(segs,1):
            peak=max(counts[a:b+1])
            candidates=[i for i in range(a,b+1) if counts[i]==peak]
            mid=(a+b)/2.0
            ri=min(candidates,key=lambda x:abs(x-mid))
            rep_indices.append(ri)

            sub=REP/f"{name}_bottom_seg{si:03d}_f{ri:05d}_kr_sub.png"
            write_gray_png(frames[ri],BW,BH,sub,scale=2)

            rows.append(dict(
                movie=name,
                region="bottom",
                segment=si,
                start_sec=f"{a/FPS:.3f}",
                end_sec=f"{(b+1)/FPS:.3f}",
                duration_sec=f"{(b-a+1)/FPS:.3f}",
                representative_frame=ri,
                representative_sec=f"{ri/FPS:.3f}",
                peak_bright_pixels=peak,
                detection_score="",
                kr_sub_image=str(sub),
                kr_full_image="",
                us_full_image="",
                ocr_japanese="",
                korean_translation="",
                review_status="PENDING",
            ))

        fulls=exact_full_frames(kr,rep_indices,name,"KR")
        for r in rows[movie_start:]:
            ri=int(r["representative_frame"])
            r["kr_full_image"]=fulls.get(ri,"")

        # Special centered narrative text in dk202.
        center_count=0
        if name=="dk202":
            us=us_source(name)
            if us is None:
                raise RuntimeError("dk202 US counterpart missing for center text alignment")

            csegs,scores,mapping,cframes,cthr=center_segments_dk202(kr,us)
            center_reps=[]
            center_rows_start=len(rows)

            for ci,(a,b) in enumerate(csegs,1):
                ri=max(range(a,b+1),key=lambda k:scores[k])
                uj=mapping[ri][0]
                center_reps.append((ri,uj))

                sub=REP/f"{name}_center_seg{ci:03d}_f{ri:05d}_kr_sub.png"
                write_gray_png(cframes[ri],CLW,CLH,sub,scale=4)

                rows.append(dict(
                    movie=name,
                    region="center",
                    segment=ci,
                    start_sec=f"{a/FPS:.3f}",
                    end_sec=f"{(b+1)/FPS:.3f}",
                    duration_sec=f"{(b-a+1)/FPS:.3f}",
                    representative_frame=ri,
                    representative_sec=f"{ri/FPS:.3f}",
                    peak_bright_pixels="",
                    detection_score=f"{scores[ri]:.6f}",
                    kr_sub_image=str(sub),
                    kr_full_image="",
                    us_full_image="",
                    ocr_japanese="",
                    korean_translation="",
                    review_status="PENDING",
                ))

            krfs=exact_full_frames(kr,[x[0] for x in center_reps],name,"KR_CENTER")
            usfs=exact_full_frames(us,[x[1] for x in center_reps],name,"US_CENTER")

            for r,(ri,uj) in zip(rows[center_rows_start:],center_reps):
                r["kr_full_image"]=krfs.get(ri,"")
                r["us_full_image"]=usfs.get(uj,"")

            center_count=len(csegs)

        summaries.append(dict(
            movie=name,
            status="OK",
            frames_analyzed=len(frames),
            bottom_segments=len(segs),
            center_segments=center_count,
            total_segments=len(segs)+center_count,
            max_bright_pixels=max(counts) if counts else 0,
        ))

        print(
            f"  bottom={len(segs)} center={center_count} "
            f"maxBright={max(counts) if counts else 0}",
            flush=True
        )

    write_tsv(STAGE/"subtitle_segments_exact.tsv",rows)
    write_tsv(STAGE/"movie_summary.tsv",summaries)

    total=sum(int(r.get("total_segments",0)) for r in summaries if r.get("status")=="OK")
    summary=[
        "Naruto PSP MOV04B - exact remaining subtitle timing",
        "="*80,"",
        f"Movies processed={sum(1 for r in summaries if r.get('status')=='OK')}/5",
        f"Exact subtitle/text segments={total}",
        "",
        "Targets established by MOV04A visual review:",
        "  da101 da201 dk101 dk102 dk202",
        "",
        "Detection:",
        "  bottom: KR-only exact 432x40 black-band glyph detector at 10 fps",
        "  dk202 center: locally aligned KR-vs-US ROI difference at 10 fps",
        "",
        "Next:",
        "  transcribe Japanese representative PNGs and translate to Korean.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
