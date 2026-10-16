#!/usr/bin/env python3
# Naruto PSP MOV05C FIX1
# Independent visual segment matcher for dk101.
#
# Purpose:
#   Correct short/silent segments that can false-match by audio.
#
# Method:
#   - reuse KR internal segment boundaries discovered by MOV05C
#   - decode a central "clean" crop from KR dk101 and Stage37
#   - exclude bottom subtitle area and outer edges / top-right watermark
#   - create low-resolution binary visual fingerprints at 4 fps
#   - search EVERY KR segment independently over the first 180 sec of Stage37
#   - score multiple frames across each segment, not a single still
#   - output top visual candidates and representative pairs
#
# Analysis only. No PMF/ISO modification.

from __future__ import annotations
import csv, math, re, subprocess, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"

PREV=ROOT/"analysis"/"mov"/"mov05c_dk101_independent_segments"
PREV_MAP=PREV/"segment_map.tsv"
PREV_BLACK=PREV/"kr_black_intervals.tsv"

STAGE=ROOT/"analysis"/"mov"/"mov05c_fix1_dk101_visual_segments"
WORK=STAGE/"work"
REVIEW=STAGE/"review"
LOGD=STAGE/"logs"
for p in (STAGE,WORK,REVIEW,LOGD):p.mkdir(parents=True,exist_ok=True)

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

FPS=4.0
W=32
H=18
FRAME_BYTES=W*H
SEARCH_LIMIT=180.0
SEARCH_STEP=0.25
TOPK=8
MIN_SEPARATION=1.5

# Keep only the central image content:
# - remove lower subtitle region
# - remove top/right channel watermark
# - remove edge/letterbox noise
FILTER=(
    "crop="
    "trunc(iw*0.78/2)*2:"
    "trunc(ih*0.58/2)*2:"
    "trunc(iw*0.08/2)*2:"
    "trunc(ih*0.14/2)*2,"
    f"scale={W}:{H}:flags=area,"
    "format=gray,"
    f"fps={FPS:g}"
)

def run(cmd,logname,timeout=2400):
    cp=subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=timeout
    )
    def dec(b):
        return b.decode("utf-8",errors="replace") if isinstance(b,(bytes,bytearray)) else str(b)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+dec(cp.stdout)
    txt+="\n\nSTDERLOCAL_PATH"+dec(cp.stderr)+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def write_tsv(path,rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def read_tsv(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.decode("utf-8",errors="replace").strip())
    except:return None

def decode_visual_raw(src,out,tag,limit=None):
    cmd=[FFMPEG,"-y","-v","warning"]
    if limit is not None:
        cmd+=["-t",f"{limit:.3f}"]
    cmd+=["-i",src,"-an","-vf",FILTER,
          "-f","rawvideo","-pix_fmt","gray",out]
    cp=run(cmd,tag,3000)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<FRAME_BYTES:
        raise RuntimeError(f"Visual raw decode failed: {src}")

def load_raw_frames(path):
    data=Path(path).read_bytes()
    n=len(data)//FRAME_BYTES
    return [data[i*FRAME_BYTES:(i+1)*FRAME_BYTES] for i in range(n)]

def signature(frame):
    # Binary mean-threshold fingerprint + detail score.
    vals=frame
    mean=sum(vals)/len(vals)
    variance=sum((x-mean)*(x-mean) for x in vals)/len(vals)
    std=math.sqrt(max(0.0,variance))

    bits=0
    for i,x in enumerate(vals):
        if x>=mean:
            bits|=(1<<i)
    return bits,mean,std

def sig_similarity(a,b):
    # 1.0 identical, 0.0 inverted.
    return 1.0-((a^b).bit_count()/FRAME_BYTES)

def build_signatures(frames):
    return [signature(f) for f in frames]

def frame_index(t,n):
    i=int(round(t*FPS))
    return max(0,min(n-1,i))

def choose_query_rel_times(duration,qsigs,start_abs):
    # Use frames spread across the segment, excluding transition edges.
    edge=min(0.75,max(0.20,duration*0.10))
    if duration<2.0:
        rels=[duration/2]
    elif duration<6.0:
        rels=[edge,duration*0.30,duration*0.50,duration*0.70,duration-edge]
    elif duration<15.0:
        rels=[edge,duration*0.18,duration*0.36,duration*0.54,duration*0.72,duration-edge]
    else:
        rels=[edge]+[duration*x for x in (0.12,0.25,0.38,0.52,0.65,0.78,0.90)]+[duration-edge]

    # Prefer detailed frames; black frames are poor discriminators.
    scored=[]
    for r in rels:
        idx=frame_index(start_abs+r,len(qsigs))
        _,mean,std=qsigs[idx]
        scored.append((std,r,mean))

    detailed=[x for x in scored if x[0]>=12.0]
    use=detailed if len(detailed)>=3 else sorted(scored,reverse=True)[:max(2,min(5,len(scored)))]
    relout=sorted(set(round(x[1],3) for x in use))

    # Limit expensive comparisons but keep coverage.
    if len(relout)>8:
        picks=[]
        for i in range(8):
            j=round(i*(len(relout)-1)/7)
            picks.append(relout[j])
        relout=sorted(set(picks))
    return relout

def score_candidate(qsigs,ssigs,kr_start,src_start,rels):
    vals=[]
    for r in rels:
        qi=frame_index(kr_start+r,len(qsigs))
        si=frame_index(src_start+r,len(ssigs))
        qsig,qmean,qstd=qsigs[qi]
        ssig,smean,sstd=ssigs[si]

        # Ignore completely featureless pair if possible.
        sim=sig_similarity(qsig,ssig)

        # Small penalty for very different global lightness, but localized
        # subtitles/text should not dominate because of the crop + binary sig.
        light_pen=min(0.08,abs(qmean-smean)/255.0*0.08)
        vals.append(sim-light_pen)

    if not vals:return -1.0,0.0,0.0
    vals_sorted=sorted(vals)
    avg=sum(vals)/len(vals)
    worst=vals_sorted[0]
    # Lower quartile stabilizes against one misleading matching still.
    lowq=vals_sorted[max(0,len(vals_sorted)//4-1)]
    score=0.64*avg+0.20*lowq+0.16*worst
    return score,avg,worst

def search_segment(qsigs,ssigs,seg):
    kr_start=float(seg["kr_start_sec"])
    kr_end=float(seg["kr_end_sec"])
    duration=kr_end-kr_start
    rels=choose_query_rel_times(duration,qsigs,kr_start)

    max_start=min(SEARCH_LIMIT,duration/FPS+len(ssigs)/FPS)-duration
    max_start=min(max_start,(len(ssigs)-1)/FPS-duration)
    if max_start<0:raise RuntimeError("Stage37 visual search range too short")

    candidates=[]
    steps=int(math.floor(max_start/SEARCH_STEP))
    for i in range(steps+1):
        s=i*SEARCH_STEP
        score,avg,worst=score_candidate(qsigs,ssigs,kr_start,s,rels)
        candidates.append((score,avg,worst,s))

    picked=[]
    for item in sorted(candidates,reverse=True):
        if all(abs(item[3]-x[3])>=MIN_SEPARATION for x in picked):
            picked.append(item)
            if len(picked)>=TOPK:break

    rows=[]
    for rank,(score,avg,worst,s) in enumerate(picked,1):
        rows.append(dict(
            segment=int(seg["segment"]),
            rank=rank,
            kr_start_sec=f"{kr_start:.3f}",
            kr_end_sec=f"{kr_end:.3f}",
            duration_sec=f"{duration:.3f}",
            source_start_sec=f"{s:.3f}",
            source_end_sec=f"{s+duration:.3f}",
            source_offset_sec=f"{s-kr_start:.3f}",
            visual_score=f"{score:.6f}",
            visual_avg=f"{avg:.6f}",
            visual_worst=f"{worst:.6f}",
            sample_rel_sec=",".join(f"{x:.3f}" for x in rels),
        ))
    return rows,rels

def extract_frame(src,t,out,tag):
    cp=run([FFMPEG,"-y","-v","error","-ss",f"{max(0,t):.3f}","-i",src,
            "-frames:v","1","-q:v","2",out],tag,180)
    return cp.returncode==0 and Path(out).exists()

def main():
    for p in (KR_PMF,SRC_VIDEO,FFMPEG,FFPROBE,PREV_MAP):
        if not p.exists():raise RuntimeError(f"Missing input: {p}")

    print("="*80,flush=True)
    print(" Naruto PSP MOV05C FIX1 - independent VISUAL segment matcher",flush=True)
    print("="*80,flush=True)

    segments=read_tsv(PREV_MAP)
    qdur=probe_duration(KR_PMF,"00_kr_duration.log")
    sdur=probe_duration(SRC_VIDEO,"00_source_duration.log")
    if qdur is None or sdur is None:raise RuntimeError("Duration probe failed")

    krraw=WORK/"kr_visual.raw"
    srcraw=WORK/"source_visual.raw"
    decode_visual_raw(KR_PMF,krraw,"01_decode_kr_visual.log")
    decode_visual_raw(SRC_VIDEO,srcraw,"02_decode_source_visual.log",min(SEARCH_LIMIT,sdur))

    qframes=load_raw_frames(krraw)
    sframes=load_raw_frames(srcraw)
    qsigs=build_signatures(qframes)
    ssigs=build_signatures(sframes)

    allrows=[]
    final=[]
    for seg in segments:
        sid=int(seg["segment"])
        rows,rels=search_segment(qsigs,ssigs,seg)
        allrows.extend(rows)

        best=rows[0]
        audio_off=seg.get("source_offset_sec","")
        audio_start=seg.get("source_predicted_start_sec","")
        visual_start=float(best["source_start_sec"])
        audio_start_f=float(audio_start) if audio_start not in ("",None) else None
        diff=(visual_start-audio_start_f) if audio_start_f is not None else None

        confidence="HIGH"
        if float(best["visual_score"])<0.72:
            confidence="MEDIUM"
        if float(best["visual_score"])<0.64:
            confidence="LOW"

        final.append(dict(
            segment=sid,
            kr_start_sec=best["kr_start_sec"],
            kr_end_sec=best["kr_end_sec"],
            duration_sec=best["duration_sec"],
            visual_source_start_sec=best["source_start_sec"],
            visual_source_end_sec=best["source_end_sec"],
            visual_offset_sec=best["source_offset_sec"],
            visual_score=best["visual_score"],
            visual_worst=best["visual_worst"],
            previous_audio_source_start_sec=audio_start or "",
            previous_audio_offset_sec=audio_off or "",
            visual_minus_audio_start_sec=f"{diff:.3f}" if diff is not None else "",
            confidence=confidence,
            sample_rel_sec=best["sample_rel_sec"],
        ))

        # Top 3 paired review sets. Use segment-relative middle and late image.
        kr_start=float(best["kr_start_sec"])
        duration=float(best["duration_sec"])
        review_rels=sorted(set([
            min(max(0.25,duration*0.25),max(0.25,duration-0.25)),
            min(max(0.25,duration*0.60),max(0.25,duration-0.25)),
            min(max(0.25,duration-0.35),max(0.25,duration-0.25)),
        ]))

        for cand in rows[:3]:
            rank=int(cand["rank"])
            ss=float(cand["source_start_sec"])
            for j,r in enumerate(review_rels,1):
                qout=REVIEW/f"seg{sid:02d}_rank{rank}_pair{j}_KR_{kr_start+r:08.3f}.jpg"
                sout=REVIEW/f"seg{sid:02d}_rank{rank}_pair{j}_SRC_{ss+r:08.3f}.jpg"
                extract_frame(KR_PMF,kr_start+r,qout,f"frame_s{sid}_r{rank}_p{j}_kr.log")
                extract_frame(SRC_VIDEO,ss+r,sout,f"frame_s{sid}_r{rank}_p{j}_src.log")

        print(
            f"segment {sid}: KR {best['kr_start_sec']}..{best['kr_end_sec']} "
            f"VIS source {best['source_start_sec']}..{best['source_end_sec']} "
            f"score={best['visual_score']} previous_audio_start={audio_start}",
            flush=True
        )

    write_tsv(STAGE/"visual_segment_candidates.tsv",allrows)
    write_tsv(STAGE/"visual_segment_map.tsv",final)

    # Flag substantial disagreement between audio-only and visual mapping.
    disagreements=[]
    for r in final:
        if r["visual_minus_audio_start_sec"]!="":
            d=abs(float(r["visual_minus_audio_start_sec"]))
            if d>=1.0:
                disagreements.append((int(r["segment"]),d))

    summary=[
        "Naruto PSP MOV05C FIX1 - independent visual segment matcher",
        "="*80,"",
        f"KR duration: {qdur:.3f} sec",
        f"Stage37 visual search: first {min(SEARCH_LIMIT,sdur):.1f} sec",
        f"Segments: {len(final)}",
        "",
        "The search ignores most subtitle/watermark pixels and compares multiple",
        "central scene frames across each segment.",
        "",
        f"Audio-vs-visual mapping disagreements >=1 sec: {len(disagreements)}",
    ]
    for sid,d in disagreements:
        summary.append(f"  segment {sid}: disagreement {d:.3f} sec")

    summary += [
        "",
        "Use visual_segment_map.tsv to verify short/silent segments that were",
        "unsafe to locate from Japanese audio alone.",
        "",
        "No PMF or ISO was modified."
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0

if __name__=="__main__":
    try:raise SystemExit(main())
    except SystemExit:raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
