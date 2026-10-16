#!/usr/bin/env python3
# Naruto PSP MOV05C
# dk101 independent internal-video segment mapper
#
# Analysis only. Does NOT build a PMF/ISO.
#
# Goal:
#   KR dk101 visual/audio timeline
#     -> detect internal black transitions
#     -> split into independent video segments
#     -> match EACH segment independently against Stage37 source_video.mp4
#     -> inspect predicted source start/end against Stage37 scene/black boundaries
#     -> flag likely YouTube/outro tail leakage
#
# This avoids assuming one global offset or one global piecewise edit.

from __future__ import annotations
import array, csv, importlib.util, math, re, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05c_proven_movie_core.py"

KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"

STAGE=ROOT/"analysis"/"mov"/"mov05c_dk101_independent_segments"
WORK=STAGE/"work"
OUT=STAGE/"review"
LOGD=STAGE/"logs"
for p in (STAGE,WORK,OUT,LOGD):p.mkdir(parents=True,exist_ok=True)

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

RATE=8000
ENV_HZ=20.0
ENV_WIN=int(RATE/ENV_HZ)
SOURCE_SEARCH_LIMIT=180.0
TOPK=6
TOP_SEPARATION_SEC=1.5
OFFSET_CLUSTER_RADIUS=0.35

def load_core():
    spec=importlib.util.spec_from_file_location("mov05c_core",CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load proven MOV04C/MOV05 core")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STAGE=STAGE
    m.WORK=WORK
    m.OUT=OUT
    m.LOGD=LOGD
    return m

def run(cmd,logname,timeout=2400):
    cp=subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",
        timeout=timeout
    )
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout
    txt+="\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def write_tsv(path,rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def decode_pcm(src,out,tag,is_oma=False,limit=None):
    cmd=[FFMPEG,"-y","-v","warning"]
    if is_oma:cmd+=["-f","oma"]
    cmd+=["-i",src]
    if limit is not None:
        cmd+=["-t",f"{limit:.3f}"]
    cmd+=["-vn","-ac","1","-ar",str(RATE),
          "-f","s16le","-c:a","pcm_s16le",out]
    cp=run(cmd,tag,3000)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(path):
    a=array.array("h")
    with Path(path).open("rb") as f:
        a.fromfile(f,Path(path).stat().st_size//2)
    if sys.byteorder!="little":a.byteswap()
    return a

def envelope(pcm):
    n=(len(pcm)//ENV_WIN)*ENV_WIN
    out=[]
    for i in range(0,n,ENV_WIN):
        ss=0.0
        for v in pcm[i:i+ENV_WIN]:
            x=float(v)/32768.0
            ss+=x*x
        out.append(math.log1p(math.sqrt(ss/ENV_WIN+1e-12)*20.0))
    return out

def corr(a,b):
    if len(a)!=len(b) or len(a)<8:return -2.0
    ma=sum(a)/len(a);mb=sum(b)/len(b)
    va=sum((x-ma)*(x-ma) for x in a)
    vb=sum((y-mb)*(y-mb) for y in b)
    if va<=1e-12 or vb<=1e-12:return -2.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)

def median(vals):
    s=sorted(vals)
    if not s:raise ValueError("empty median")
    n=len(s)
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0

def detect_black(path,tag,min_d=0.18):
    cp=run([FFMPEG,"-hide_banner","-v","info","-i",path,
            "-an","-vf",f"blackdetect=d={min_d}:pix_th=0.10","-f","null","-"],
           tag,600)
    rows=[]
    for line in cp.stderr.splitlines():
        m=re.search(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)",line)
        if m:
            a,b,d=map(float,m.groups())
            rows.append(dict(start_sec=a,end_sec=b,duration_sec=d,mid_sec=(a+b)/2.0))
    return rows

def detect_scene(path,tag,limit=None,threshold=0.34):
    cmd=[FFMPEG,"-hide_banner","-v","info"]
    if limit is not None:
        cmd+=["-t",f"{limit:.3f}"]
    cmd+=["-i",path,"-an","-vf",f"select='gt(scene,{threshold})',showinfo","-f","null","-"]
    cp=run(cmd,tag,900)
    vals=[]
    for line in cp.stderr.splitlines():
        m=re.search(r"pts_time:([0-9.]+)",line)
        if m:
            vals.append(float(m.group(1)))
    # dedupe
    out=[]
    for t in sorted(vals):
        if not out or abs(t-out[-1])>0.10:
            out.append(t)
    return out

def make_kr_segments(qdur,black_rows):
    # Long-enough black intervals are treated as internal video separators.
    candidates=[]
    for r in black_rows:
        d=float(r["duration_sec"])
        mid=float(r["mid_sec"])
        if d>=0.30 and 3.0<mid<qdur-3.0:
            candidates.append((mid,d))

    # Merge black separators less than 2 sec apart, keeping the longer.
    merged=[]
    for mid,d in sorted(candidates):
        if merged and abs(mid-merged[-1][0])<2.0:
            if d>merged[-1][1]:
                merged[-1]=(mid,d)
        else:
            merged.append((mid,d))

    boundaries=[0.0]+[x[0] for x in merged]+[qdur]

    # Avoid pathological tiny segments by removing the less useful boundary.
    changed=True
    while changed and len(boundaries)>2:
        changed=False
        for i in range(len(boundaries)-1):
            if boundaries[i+1]-boundaries[i]<4.0:
                if i==0:
                    del boundaries[1]
                elif i+1==len(boundaries)-1:
                    del boundaries[-2]
                else:
                    # Remove boundary adjacent to the shorter neighbor.
                    left=boundaries[i]-boundaries[i-1]
                    right=boundaries[i+2]-boundaries[i+1]
                    if left<right:del boundaries[i]
                    else:del boundaries[i+1]
                changed=True
                break

    segs=[]
    for i,(a,b) in enumerate(zip(boundaries,boundaries[1:]),1):
        segs.append(dict(segment=i,kr_start=a,kr_end=b,duration=b-a))
    return segs,merged

def query_centers(seg):
    a=seg["kr_start"];b=seg["kr_end"];d=seg["duration"]
    if d>=28:
        vals=[a+7.0,(a+b)/2.0,b-7.0]
        win=10.0
    elif d>=16:
        vals=[a+4.5,(a+b)/2.0,b-4.5]
        win=7.0
    elif d>=8:
        vals=[a+3.0,b-3.0]
        win=5.0
    else:
        vals=[(a+b)/2.0]
        win=max(3.0,d*0.55)

    # unique + valid
    out=[]
    for x in vals:
        if x-win/2<0 or x+win/2>b+0.01 or x-win/2<a-0.01:
            continue
        if all(abs(x-y)>0.25 for y in out):
            out.append(x)
    if not out:
        out=[(a+b)/2]
        win=max(2.0,min(4.0,d*0.7))
    return out,win

def top_matches(qenv,senv,qcenter,window):
    half=int(round(window*ENV_HZ/2))
    qc=int(round(qcenter*ENV_HZ))
    qa=qc-half;qb=qc+half
    if qa<0 or qb>len(qenv):return []
    q=qenv[qa:qb]

    min_sc=half
    max_sc=min(len(senv)-half,int(round(SOURCE_SEARCH_LIMIT*ENV_HZ)))
    scores=[]
    for sc in range(min_sc,max_sc+1):
        sa=sc-half;sb=sa+len(q)
        if sb>len(senv):break
        c=corr(q,senv[sa:sb])
        scores.append((c,sc/ENV_HZ))

    selected=[]
    sep=TOP_SEPARATION_SEC
    for c,t in sorted(scores,reverse=True):
        if all(abs(t-x[1])>=sep for x in selected):
            selected.append((c,t))
            if len(selected)>=TOPK:break
    return selected

def choose_segment_mapping(seg,query_rows):
    own=[r for r in query_rows if r["segment"]==seg["segment"]]
    if not own:return None

    # Candidate offset values from all top matches.
    candidate_offsets=[]
    for r in own:
        candidate_offsets.append(float(r["offset_sec"]))

    best=None
    for off0 in candidate_offsets:
        chosen=[]
        by_q={}
        for r in own:
            off=float(r["offset_sec"])
            if abs(off-off0)<=OFFSET_CLUSTER_RADIUS:
                q=float(r["kr_query_center_sec"])
                c=float(r["correlation"])
                if q not in by_q or c>float(by_q[q]["correlation"]):
                    by_q[q]=r
        chosen=list(by_q.values())
        if not chosen:continue

        score=sum(max(0.0,float(r["correlation"])) for r in chosen)
        avg=score/len(chosen)
        rank=(len(chosen),avg,score)
        if best is None or rank>best[0]:
            best=(rank,chosen)

    if best is None:return None
    chosen=best[1]
    offs=[float(r["offset_sec"]) for r in chosen]
    cors=[float(r["correlation"]) for r in chosen]
    off=median(offs)
    avg=sum(cors)/len(cors)
    spread=max(offs)-min(offs) if len(offs)>1 else 0.0

    needed=2 if len(set(float(r["kr_query_center_sec"]) for r in own))>=2 else 1
    confidence=(
        "HIGH" if len(chosen)>=needed and avg>=0.62 and spread<=0.20
        else "MEDIUM" if len(chosen)>=needed and avg>=0.45 and spread<=0.40
        else "LOW"
    )

    return dict(
        offset=off,
        avg_corr=avg,
        spread=spread,
        matched_queries=len(chosen),
        confidence=confidence,
        chosen=chosen
    )

def build_source_boundaries(black_rows,scene_times):
    rows=[]
    for r in black_rows:
        rows.append(dict(time_sec=float(r["start_sec"]),kind="black_start"))
        rows.append(dict(time_sec=float(r["end_sec"]),kind="black_end"))
        rows.append(dict(time_sec=float(r["mid_sec"]),kind="black_mid"))
    for t in scene_times:
        rows.append(dict(time_sec=t,kind="scene"))
    rows.sort(key=lambda r:r["time_sec"])
    return rows

def nearest_boundary(boundaries,t,radius=5.0):
    c=[r for r in boundaries if abs(r["time_sec"]-t)<=radius]
    if not c:return None
    # prefer black boundaries when similarly close
    def key(r):
        kind_pen=0 if r["kind"].startswith("black") else 0.15
        return (abs(r["time_sec"]-t)+kind_pen)
    return min(c,key=key)

def extract_frame(src,t,out,tag):
    if t<0:t=0
    cp=run([FFMPEG,"-y","-v","error","-ss",f"{t:.3f}","-i",src,
            "-frames:v","1","-q:v","2",out],tag,180)
    return cp.returncode==0 and Path(out).exists()

def main():
    core=load_core()
    for p in (CORE_PATH,KR_PMF,SRC_VIDEO,FFMPEG,FFPROBE):
        if not p.exists():raise RuntimeError(f"Missing input/tool: {p}")

    fail=STAGE/"FAILURE.txt"
    if fail.exists():fail.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05C - dk101 independent internal-video mapping",flush=True)
    print("="*80,flush=True)

    qdur=probe_duration(KR_PMF,"00_kr_duration.log")
    sdur=probe_duration(SRC_VIDEO,"00_source_duration.log")
    if qdur is None:raise RuntimeError("Cannot probe KR dk101 duration")
    if sdur is None:raise RuntimeError("Cannot probe Stage37 source duration")

    # Exact KR audio.
    krp=core.parse_pmf(KR_PMF)
    kra=core.recover_audio(krp)
    if kra["bad_headers"]:raise RuntimeError("KR ATRAC headers invalid")

    oma=WORK/"kr.oma"
    core.build_oma(kra["frames"],oma)
    kp=WORK/"kr.s16"
    sp=WORK/"source_first180.s16"
    decode_pcm(oma,kp,"01_decode_kr.log",True)
    decode_pcm(SRC_VIDEO,sp,"02_decode_source.log",False,min(SOURCE_SEARCH_LIMIT,sdur))

    qenv=envelope(load_pcm(kp))
    senv=envelope(load_pcm(sp))

    # Visual boundaries.
    kr_black=detect_black(KR_PMF,"03_kr_blackdetect.log",0.18)
    src_black=detect_black(SRC_VIDEO,"04_source_blackdetect.log",0.18)
    # Restrict source boundary rows to search horizon.
    src_black=[r for r in src_black if float(r["start_sec"])<=SOURCE_SEARCH_LIMIT+5]

    kr_scenes=detect_scene(KR_PMF,"05_kr_scene_detect.log",None,0.36)
    src_scenes=detect_scene(SRC_VIDEO,"06_source_scene_detect.log",SOURCE_SEARCH_LIMIT,0.38)

    segments,used_black=make_kr_segments(qdur,kr_black)

    write_tsv(STAGE/"kr_black_intervals.tsv",[
        dict(start_sec=f"{float(r['start_sec']):.3f}",
             end_sec=f"{float(r['end_sec']):.3f}",
             duration_sec=f"{float(r['duration_sec']):.3f}",
             mid_sec=f"{float(r['mid_sec']):.3f}")
        for r in kr_black
    ])

    source_boundaries=build_source_boundaries(src_black,src_scenes)
    write_tsv(STAGE/"source_boundaries.tsv",[
        dict(time_sec=f"{r['time_sec']:.3f}",kind=r["kind"]) for r in source_boundaries
    ])

    query_rows=[]
    print(f"KR duration={qdur:.3f}s; internal segments={len(segments)}",flush=True)

    for seg in segments:
        centers,window=query_centers(seg)
        print(
            f"[segment {seg['segment']}/{len(segments)}] "
            f"KR {seg['kr_start']:.3f}..{seg['kr_end']:.3f}s "
            f"queries={len(centers)} window={window:.1f}s",
            flush=True
        )
        for qi,qcenter in enumerate(centers,1):
            matches=top_matches(qenv,senv,qcenter,window)
            for rank,(c,st) in enumerate(matches,1):
                query_rows.append(dict(
                    segment=seg["segment"],
                    query_index=qi,
                    rank=rank,
                    kr_query_center_sec=f"{qcenter:.3f}",
                    window_sec=f"{window:.3f}",
                    source_center_sec=f"{st:.3f}",
                    offset_sec=f"{st-qcenter:.3f}",
                    correlation=f"{c:.6f}",
                ))

    write_tsv(STAGE/"query_matches.tsv",query_rows)

    segment_rows=[]
    low=0

    for seg in segments:
        m=choose_segment_mapping(seg,query_rows)

        if m is None:
            row=dict(
                segment=seg["segment"],
                kr_start_sec=f"{seg['kr_start']:.3f}",
                kr_end_sec=f"{seg['kr_end']:.3f}",
                kr_duration_sec=f"{seg['duration']:.3f}",
                status="NO_MATCH",
                confidence="LOW"
            )
            segment_rows.append(row);low+=1
            continue

        source_start=seg["kr_start"]+m["offset"]
        source_end=seg["kr_end"]+m["offset"]

        sb=nearest_boundary(source_boundaries,source_start,5.0)
        eb=nearest_boundary(source_boundaries,source_end,5.0)

        start_delta=(sb["time_sec"]-source_start) if sb else None
        end_delta=(eb["time_sec"]-source_end) if eb else None

        # Strong tail risk: Stage37 visibly transitions to another scene/outro
        # 0.5..4.5 sec BEFORE the exact audio-mapped KR segment end.
        tail_risk="NO"
        recommended_end=source_end
        end_note=""
        if eb and -4.5<=end_delta<=-0.50:
            tail_risk="YES"
            recommended_end=eb["time_sec"]
            end_note="Stage37 visual boundary occurs before audio-mapped end; likely outro/tail leakage."
        elif eb and abs(end_delta)<=0.50:
            end_note="Stage37 visual boundary agrees with mapped end."
        elif eb:
            end_note="Nearest Stage37 visual boundary differs from mapped end."
        else:
            end_note="No Stage37 visual boundary within +/-5 sec."

        row=dict(
            segment=seg["segment"],
            kr_start_sec=f"{seg['kr_start']:.3f}",
            kr_end_sec=f"{seg['kr_end']:.3f}",
            kr_duration_sec=f"{seg['duration']:.3f}",
            matched_query_count=m["matched_queries"],
            avg_correlation=f"{m['avg_corr']:.6f}",
            offset_spread_sec=f"{m['spread']:.3f}",
            source_offset_sec=f"{m['offset']:.3f}",
            source_predicted_start_sec=f"{source_start:.3f}",
            source_predicted_end_sec=f"{source_end:.3f}",
            nearest_source_start_boundary_sec=f"{sb['time_sec']:.3f}" if sb else "",
            nearest_source_start_boundary_kind=sb["kind"] if sb else "",
            start_boundary_delta_sec=f"{start_delta:.3f}" if start_delta is not None else "",
            nearest_source_end_boundary_sec=f"{eb['time_sec']:.3f}" if eb else "",
            nearest_source_end_boundary_kind=eb["kind"] if eb else "",
            end_boundary_delta_sec=f"{end_delta:.3f}" if end_delta is not None else "",
            recommended_source_end_sec=f"{recommended_end:.3f}",
            tail_risk=tail_risk,
            confidence=m["confidence"],
            status="PASS" if m["confidence"]!="LOW" else "REVIEW",
            note=end_note,
        )
        segment_rows.append(row)
        if m["confidence"]=="LOW":low+=1

        # Representative images.
        rid=int(seg["segment"])
        times=[
            ("kr_start",KR_PMF,seg["kr_start"]+0.25),
            ("kr_end",KR_PMF,max(seg["kr_start"],seg["kr_end"]-0.25)),
            ("src_start",SRC_VIDEO,max(0,source_start+0.25)),
            ("src_pred_end",SRC_VIDEO,max(0,source_end-0.25)),
        ]
        if eb:
            times += [
                ("src_boundary_before",SRC_VIDEO,max(0,eb["time_sec"]-0.25)),
                ("src_boundary_after",SRC_VIDEO,max(0,eb["time_sec"]+0.25)),
            ]

        for label,src,t in times:
            out=OUT/f"seg{rid:02d}_{label}_{t:08.3f}.jpg"
            extract_frame(src,t,out,f"frame_seg{rid:02d}_{label}.log")

    write_tsv(STAGE/"segment_map.tsv",segment_rows)

    tail_count=sum(1 for r in segment_rows if r.get("tail_risk")=="YES")
    high=sum(1 for r in segment_rows if r.get("confidence")=="HIGH")
    med=sum(1 for r in segment_rows if r.get("confidence")=="MEDIUM")

    summary=[
        "Naruto PSP MOV05C - dk101 independent internal-video mapper",
        "="*80,"",
        f"KR dk101 duration: {qdur:.3f} sec",
        f"Stage37 search source: {SRC_VIDEO}",
        f"Stage37 search horizon: first {min(SOURCE_SEARCH_LIMIT,sdur):.1f} sec",
        f"Detected KR internal segments: {len(segments)}",
        f"HIGH mappings: {high}",
        f"MEDIUM mappings: {med}",
        f"LOW/failed mappings: {low}",
        f"Segments with likely Stage37 tail/outro leakage: {tail_count}","",
        "Important:",
        "  Every segment was matched independently.",
        "  No global +0.700/+0.250 timeline assumption is used.",
        "  predicted source end is compared against real Stage37 scene/black boundaries.",
        "  tail_risk=YES means the Stage37 clip appears to end before the KR segment does.",
        "",
        "Next build should use segment_map.tsv and never copy pixels beyond each",
        "segment's approved source end. Any unmatched remainder can fall back to",
        "the KR original visual rather than exposing YouTube outro/tail frames.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    # Analysis succeeds even if a segment needs review; the report is the product.
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
