#!/usr/bin/env python3
from __future__ import annotations
import array,csv,importlib.util,math,subprocess,sys,traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov06a_proven_movie_core.py"
KR_MOVIE_DIR=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"
STAGE37_DIR=ROOT/"analysis"/"stage37"/"video"
SOURCES=[STAGE37_DIR/"source_video.mp4",STAGE37_DIR/"part2.mp4"]
TARGETS=["da101","da201","dk102","dk202"]

STAGE=ROOT/"analysis"/"mov"/"mov06a_remaining_stage37_locator"
WORK=STAGE/"work"; REVIEW=STAGE/"review"; LOGD=STAGE/"logs"
for p in (STAGE,WORK,REVIEW,LOGD): p.mkdir(parents=True,exist_ok=True)

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")
RATE=8000; COARSE_HZ=2.0; FINE_HZ=20.0
SCALES=[0.997,1.000,1.003]
COARSE_TOP=8; FINE_TOP=5; COARSE_SEP=8.0; CLUSTER_RADIUS=1.0

def load_core():
    spec=importlib.util.spec_from_file_location("mov06a_core",CORE_PATH)
    if spec is None or spec.loader is None: raise RuntimeError("Cannot load proven PMF core")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.STAGE=STAGE; m.WORK=WORK; m.OUT=STAGE; m.LOGD=LOGD
    return m

def run(cmd,logname,timeout=3600):
    cp=subprocess.run([str(x) for x in cmd],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",timeout=timeout)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)+"\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def write_tsv(path,rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def decode_pcm(src,out,tag,is_oma=False):
    cmd=[FFMPEG,"-y","-v","warning"]
    if is_oma:cmd+=["-f","oma"]
    cmd+=["-i",src,"-vn","-ac","1","-ar",str(RATE),"-f","s16le","-c:a","pcm_s16le",out]
    cp=run(cmd,tag)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(path):
    a=array.array("h")
    with Path(path).open("rb") as f:a.fromfile(f,Path(path).stat().st_size//2)
    if sys.byteorder!="little":a.byteswap()
    return a

def envelope(pcm,hz):
    win=max(1,int(round(RATE/hz))); n=(len(pcm)//win)*win; out=[]
    for i in range(0,n,win):
        ss=0.0
        for v in pcm[i:i+win]:
            x=float(v)/32768.0; ss+=x*x
        out.append(math.log1p(math.sqrt(ss/win+1e-12)*20.0))
    return out

def znormalize(v):
    m=sum(v)/len(v); var=sum((x-m)*(x-m) for x in v)/len(v); sd=math.sqrt(max(var,1e-12))
    return [(x-m)/sd for x in v]

def prefix(v):
    s=[0.0];s2=[0.0];a=b=0.0
    for x in v:a+=x;b+=x*x;s.append(a);s2.append(b)
    return s,s2

def corr_at(src,qz,pos,p,p2):
    m=len(qz)
    if pos<0 or pos+m>len(src):return -2.0
    sx=p[pos+m]-p[pos]; sx2=p2[pos+m]-p2[pos]; mean=sx/m; var=sx2/m-mean*mean
    if var<=1e-12:return -2.0
    sd=math.sqrt(var); dot=0.0
    for i,q in enumerate(qz):dot+=((src[pos+i]-mean)/sd)*q
    return dot/m

def resample(v,scale):
    if abs(scale-1)<1e-12:return list(v)
    n=max(8,int(round(len(v)*scale))); out=[]
    for j in range(n):
        x=j*(len(v)-1)/max(1,n-1); i=int(math.floor(x)); k=min(len(v)-1,i+1); f=x-i
        out.append(v[i]*(1-f)+v[k]*f)
    return out

def anchor_plan(d):
    if d>=70: win=18.0; centers=[d*.18,d*.42,d*.68,d*.86]
    elif d>=35: win=14.0; centers=[d*.20,d*.50,d*.80]
    elif d>=20: win=10.0; centers=[d*.25,d*.55,d*.78]
    else: win=max(6.0,d*.45); centers=[d*.35,d*.65]
    h=win/2; clean=[]
    for c in centers:
        c=max(h+.25,min(d-h-.25,c))
        if all(abs(c-x)>=win*.45 for x in clean):clean.append(c)
    return clean,win

def slice_env(env,center,window,hz):
    half=int(round(window*hz/2)); c=int(round(center*hz)); a=max(0,c-half); b=min(len(env),c+half)
    return env[a:b] if b-a>=max(8,int(window*hz*.7)) else None

def coarse_search(src,q):
    qz=znormalize(q);p,p2=prefix(src);m=len(q)
    vals=[(pos,corr_at(src,qz,pos,p,p2)) for pos in range(0,len(src)-m+1)]
    picked=[]; sep=int(round(COARSE_SEP*COARSE_HZ))
    for item in sorted(vals,key=lambda x:x[1],reverse=True):
        if all(abs(item[0]-x[0])>=sep for x in picked):
            picked.append(item)
            if len(picked)>=COARSE_TOP:break
    return picked

def fine_search(src,q,coarse_center):
    p,p2=prefix(src);center=int(round(coarse_center*FINE_HZ));rad=int(round(2.5*FINE_HZ));allv=[]
    for scale in SCALES:
        qq=resample(q,scale);qz=znormalize(qq)
        lo=max(0,center-rad);hi=min(len(src)-len(qq),center+rad)
        for pos in range(lo,hi+1):
            allv.append((corr_at(src,qz,pos,p,p2),pos/FINE_HZ,scale))
    picked=[]
    for x in sorted(allv,reverse=True):
        if all(abs(x[1]-y[1])>=.45 for y in picked):
            picked.append(x)
            if len(picked)>=FINE_TOP:break
    return picked

def cluster_offsets(rows):
    if not rows:return []
    cs=[]
    for seed in [float(r["offset_sec"]) for r in rows]:
        members=[r for r in rows if abs(float(r["offset_sec"])-seed)<=CLUSTER_RADIUS]
        by={}
        for r in members:
            a=int(r["anchor_index"])
            if a not in by or float(r["correlation"])>float(by[a]["correlation"]):by[a]=r
        mem=list(by.values())
        if not mem:continue
        n=len(mem); avg=sum(float(r["correlation"]) for r in mem)/n
        den=sum(max(.01,float(r["correlation"])) for r in mem)
        off=sum(float(r["offset_sec"])*max(.01,float(r["correlation"])) for r in mem)/den
        scale=sum(float(r["scale"]) for r in mem)/n
        cs.append(dict(distinct_anchors=n,avg_corr=avg,offset=off,scale=scale))
    out=[]
    for c in sorted(cs,key=lambda x:(x["distinct_anchors"],x["avg_corr"]),reverse=True):
        if all(abs(c["offset"]-x["offset"])>.75 for x in out):out.append(c)
        if len(out)>=5:break
    return out

def extract_frame(src,sec,out,tag):
    cp=run([FFMPEG,"-y","-v","error","-ss",f"{max(0,sec):.3f}","-i",src,"-frames:v","1","-q:v","2",out],tag,180)
    return cp.returncode==0 and Path(out).exists()

def main():
    core=load_core()
    for p in [CORE_PATH,FFMPEG,FFPROBE]+SOURCES:
        if not p.exists():raise RuntimeError(f"Missing input/tool: {p}")
    for t in TARGETS:
        if not (KR_MOVIE_DIR/f"{t}.pmf").exists():raise RuntimeError(f"Missing KR PMF: {t}")

    f=STAGE/"FAILURE.txt"
    if f.exists():f.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV06A - remaining Stage37 batch locator",flush=True)
    print("="*80,flush=True)

    source_data={};srcrows=[]
    for i,src in enumerate(SOURCES,1):
        dur=probe_duration(src,f"00_source{i}_duration.log")
        pcm_path=WORK/f"{src.stem}_8k_mono.s16"
        print(f"[source {i}/2] decode {src.name}",flush=True)
        decode_pcm(src,pcm_path,f"01_source{i}_decode.log")
        pcm=load_pcm(pcm_path)
        source_data[src.name]=dict(path=src,duration=dur,coarse=envelope(pcm,COARSE_HZ),fine=envelope(pcm,FINE_HZ))
        srcrows.append(dict(source=src.name,duration_sec=f"{dur:.3f}" if dur is not None else ""))
        del pcm
    write_tsv(STAGE/"stage37_sources.tsv",srcrows)

    matches=[];summaries=[];reviews=[]
    for ti,target in enumerate(TARGETS,1):
        print(f"\n[target {ti}/{len(TARGETS)}] {target}",flush=True)
        pmf=KR_MOVIE_DIR/f"{target}.pmf"
        parsed=core.parse_pmf(pmf);aud=core.recover_audio(parsed)
        if aud["bad_headers"]:raise RuntimeError(f"{target}: bad AU headers")
        oma=WORK/f"{target}.oma";core.build_oma(aud["frames"],oma)
        pcmp=WORK/f"{target}_8k_mono.s16";decode_pcm(oma,pcmp,f"02_{target}_decode.log",True)
        pcm=load_pcm(pcmp);qdur=len(pcm)/RATE;qcoarse=envelope(pcm,COARSE_HZ);qfine=envelope(pcm,FINE_HZ);del pcm
        centers,win=anchor_plan(qdur)
        target_rows=[]
        for ai,c in enumerate(centers,1):
            qc=slice_env(qcoarse,c,win,COARSE_HZ);qf=slice_env(qfine,c,win,FINE_HZ)
            if qc is None or qf is None:continue
            for sname,sd in source_data.items():
                fine=[]
                for pos,cs in coarse_search(sd["coarse"],qc):
                    center=pos/COARSE_HZ+(len(qc)/COARSE_HZ)/2
                    fine.extend(fine_search(sd["fine"],qf,center))
                picked=[]
                for item in sorted(fine,reverse=True):
                    if all(abs(item[1]-x[1])>=.45 for x in picked):picked.append(item)
                    if len(picked)>=FINE_TOP:break
                for rank,(score,sc,scale) in enumerate(picked,1):
                    row=dict(target=target,source=sname,anchor_index=ai,anchor_center_kr_sec=f"{c:.3f}",
                        anchor_window_sec=f"{win:.3f}",rank=rank,source_center_sec=f"{sc:.3f}",
                        offset_sec=f"{sc-c:.3f}",correlation=f"{score:.6f}",scale=f"{scale:.3f}")
                    matches.append(row);target_rows.append(row)

        clusters=[]
        for sname in source_data:
            rows=[r for r in target_rows if r["source"]==sname and int(r["rank"])<=3]
            for c in cluster_offsets(rows):c["source"]=sname;clusters.append(c)
        clusters.sort(key=lambda c:(c["distinct_anchors"],c["avg_corr"]),reverse=True)

        if clusters:
            b=clusters[0];conf="LOW"
            if b["distinct_anchors"]>=max(2,len(centers)-1) and b["avg_corr"]>=.72:conf="VERY_HIGH"
            elif b["distinct_anchors"]>=2 and b["avg_corr"]>=.60:conf="HIGH"
            elif b["distinct_anchors"]>=2 and b["avg_corr"]>=.45:conf="MEDIUM"
            start=b["offset"];end=start+qdur
            summaries.append(dict(target=target,kr_audio_duration_sec=f"{qdur:.3f}",anchor_count=len(centers),
                best_source=b["source"],best_start_sec=f"{start:.3f}",best_end_sec=f"{end:.3f}",
                matching_anchor_count=b["distinct_anchors"],avg_correlation=f"{b['avg_corr']:.6f}",
                scale=f"{b['scale']:.3f}",confidence=conf,kr_audio_pes=len(parsed["audio"]),kr_atrac_frames=aud["frame_count"]))
            print(f"  BEST {b['source']} start={start:.3f}s corr={b['avg_corr']:.4f} anchors={b['distinct_anchors']}/{len(centers)} {conf}",flush=True)
            srcp=source_data[b["source"]]["path"]
            for ri,rel in enumerate((qdur*.2,qdur*.5,qdur*.8),1):
                ko=REVIEW/f"{target}_pair{ri}_KR_{rel:08.3f}.jpg";so=REVIEW/f"{target}_pair{ri}_{srcp.stem}_{start+rel:09.3f}.jpg"
                extract_frame(pmf,rel,ko,f"frame_{target}_{ri}_kr.log");extract_frame(srcp,start+rel,so,f"frame_{target}_{ri}_src.log")
                reviews.append(dict(target=target,source=b["source"],relative_sec=f"{rel:.3f}",source_sec=f"{start+rel:.3f}",kr_frame=str(ko),source_frame=str(so)))
        else:
            summaries.append(dict(target=target,kr_audio_duration_sec=f"{qdur:.3f}",anchor_count=len(centers),best_source="",
                best_start_sec="",best_end_sec="",matching_anchor_count=0,avg_correlation="",scale="",confidence="NO_MATCH",
                kr_audio_pes=len(parsed["audio"]),kr_atrac_frames=aud["frame_count"]))

    write_tsv(STAGE/"anchor_matches.tsv",matches)
    write_tsv(STAGE/"target_summary.tsv",summaries)
    write_tsv(STAGE/"review_frames.tsv",reviews)

    lines=["Naruto PSP MOV06A - remaining Stage37 batch locator","="*80,"",
        "Targets: da101, da201, dk102, dk202","",
        "Analysis only. No PMF/ISO modification.","",
        "Accepted dk101 MOV05D note:",
        "  runtime accepted; ~2-3 Stage37/YouTube tail frames at the end of the",
        "  second internal video are intentionally tolerated.",""]
    for r in summaries:
        lines += [f"{r['target']}: source={r['best_source']} start={r['best_start_sec']} corr={r['avg_correlation']} anchors={r['matching_anchor_count']}/{r['anchor_count']} confidence={r['confidence']}"]
    (STAGE/"SUMMARY.txt").write_text("\n".join(lines)+"\n",encoding="utf-8-sig")

    mov05d=ROOT/"analysis"/"mov"/"mov05d_dk101_segmented_final";mov05d.mkdir(parents=True,exist_ok=True)
    (mov05d/"ACCEPTED_RUNTIME_NOTE.txt").write_text(
        "MOV05D dk101 accepted for continued work.\n"
        "A/V synchronization is acceptable.\n"
        "Known tolerated artifact: about 2-3 frames of Stage37/YouTube tail imagery\n"
        "at the end of the second internal video. No further fix requested.\n",
        encoding="utf-8-sig")
    print("\n".join(lines),flush=True)
    return 0

if __name__=="__main__":
    try:raise SystemExit(main())
    except SystemExit:raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc();(STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True);raise SystemExit(1)
