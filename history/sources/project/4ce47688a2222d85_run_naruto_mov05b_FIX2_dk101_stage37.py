#!/usr/bin/env python3
# Naruto PSP MOV05B FIX2
# Robust long-window late alignment + piecewise Stage37 dk101 reconstruction.

from __future__ import annotations
import array, csv, importlib.util, math, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05b_proven_movie_core.py"
KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"
BASE_ISO=ROOT/"analysis"/"mov"/"mov03t_iso_install"/"output"/"Naruto_KR_MOV03S_KoreanMovies.iso"

STAGE=ROOT/"analysis"/"mov"/"mov05b_fix2_dk101_stage37_piecewise"
WORK=STAGE/"work"; OUT=STAGE/"output"; LOGD=STAGE/"logs"; FONTD=STAGE/"fonts"
for p in (STAGE,WORK,OUT,LOGD,FONTD): p.mkdir(parents=True,exist_ok=True)

FINAL_PMF=OUT/"dk101_stage37_KOvideo_KRJPaudio_piecewise.pmf"
SMOKE_ISO=OUT/"Naruto_KR_MOV05B_FIX2_dk101_stage37_smoketest.iso"
FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

RATE=8000
ENV_HZ=20.0
WIN=int(RATE/ENV_HZ)
SECTOR=2048
TARGET=["PSP_GAME","USRDIR","movie","dk101.pmf"]

def load_core():
    spec=importlib.util.spec_from_file_location("mov05b_core",CORE_PATH)
    if spec is None or spec.loader is None: raise RuntimeError("Cannot load proven core")
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.STAGE=STAGE; m.WORK=WORK; m.OUT=OUT; m.LOGD=LOGD; m.FONTD=FONTD
    return m

def run(cmd,logname,timeout=3000,cwd=None):
    cp=subprocess.run([str(x) for x in cmd],cwd=str(cwd) if cwd else None,
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                      text=True,encoding="utf-8",errors="replace",timeout=timeout)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
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

def decode_pcm(src,out,tag,is_oma=False):
    cmd=[FFMPEG,"-y","-v","warning"]
    if is_oma: cmd+=["-f","oma"]
    cmd+=["-i",src,"-vn","-ac","1","-ar",str(RATE),"-f","s16le","-c:a","pcm_s16le",out]
    cp=run(cmd,tag)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(p):
    a=array.array("h")
    with Path(p).open("rb") as f: a.fromfile(f,Path(p).stat().st_size//2)
    if sys.byteorder!="little": a.byteswap()
    return a

def envelope(pcm):
    n=(len(pcm)//WIN)*WIN; out=[]
    for i in range(0,n,WIN):
        ss=0.0
        for v in pcm[i:i+WIN]:
            x=float(v)/32768.0; ss+=x*x
        out.append(math.log1p(math.sqrt(ss/WIN+1e-12)*20.0))
    return out

def corr(a,b):
    if len(a)!=len(b) or len(a)<8: return -2.0
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    va=sum((x-ma)*(x-ma) for x in a); vb=sum((y-mb)*(y-mb) for y in b)
    if va<=1e-12 or vb<=1e-12: return -2.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)

def median(v):
    s=sorted(v); n=len(s)
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2

def scan_anchor(qenv,senv,center,window,off_lo,off_hi):
    half=int(round(window*ENV_HZ/2))
    qc=int(round(center*ENV_HZ))
    qa=qc-half; qb=qc+half
    if qa<0 or qb>len(qenv): return None
    q=qenv[qa:qb]
    best=(-2.0,None)
    lo=int(round(off_lo*ENV_HZ)); hi=int(round(off_hi*ENV_HZ))
    for oi in range(lo,hi+1):
        sc=qc+oi; sa=sc-half; sb=sc+half
        if sa<0 or sb>len(senv): continue
        c=corr(q,senv[sa:sb])
        if c>best[0]: best=(c,oi/ENV_HZ)
    return best

def alignment(qenv,senv,qdur):
    rows=[]

    # Early region: already shown by two independent runs to be +0.700 sec.
    for t in range(10,67,4):
        r=scan_anchor(qenv,senv,float(t),8.0,0.45,0.95)
        if r:
            c,o=r
            rows.append(dict(region="early",center_sec=t,window_sec=8,
                             offset_sec=f"{o:.3f}",correlation=f"{c:.6f}"))

    early_good=[r for r in rows if r["region"]=="early" and float(r["correlation"])>=0.85]
    if len(early_good)<8: raise RuntimeError(f"Early alignment unexpectedly weak: {len(early_good)}")
    early_off=median([float(r["offset_sec"]) for r in early_good])

    # Late region: use longer windows. The failed 4-sec scan was too ambiguous
    # around music/credits. Search near the +0.25 sec offset observed by MOV05B.
    late_rows=[]
    for t in (84,86,88,90,92,94,96,98):
        for w in (8.0,12.0):
            r=scan_anchor(qenv,senv,float(t),w,-0.35,0.85)
            if r:
                c,o=r
                rr=dict(region="late",center_sec=t,window_sec=int(w),
                        offset_sec=f"{o:.3f}",correlation=f"{c:.6f}")
                rows.append(rr); late_rows.append(rr)

    # Keep only reasonably strong long-window matches, then find the densest
    # offset cluster within +/-0.10 sec.
    usable=[r for r in late_rows if float(r["correlation"])>=0.50]
    if len(usable)<2:
        raise RuntimeError(f"Not enough long-window late matches: {len(usable)}")

    best_cluster=[]
    for r in usable:
        o=float(r["offset_sec"])
        cl=[x for x in usable if abs(float(x["offset_sec"])-o)<=0.10]
        if len(cl)>len(best_cluster):
            best_cluster=cl
        elif len(cl)==len(best_cluster) and cl:
            if sum(float(x["correlation"]) for x in cl)>sum(float(x["correlation"]) for x in best_cluster):
                best_cluster=cl

    if len(best_cluster)<2:
        raise RuntimeError("Late long-window matches did not form a consistent cluster")

    late_off=median([float(r["offset_sec"]) for r in best_cluster])

    # Require it to differ materially from the early mapping.
    if abs(late_off-early_off)<0.20:
        raise RuntimeError(f"No meaningful timeline shift detected: early={early_off}, late={late_off}")

    # Transition bounds:
    # early +0.7 is rock-solid through KR 66 sec; 4-sec dense scan first fails at 68.
    # Start correction at 68 sec.
    q1=68.0

    # Each accepted late window proves its entire window. Earliest start of the
    # strongest late cluster is the first point we can safely treat as post-edit.
    late_starts=[float(r["center_sec"])-float(r["window_sec"])/2.0 for r in best_cluster]
    q2=max(q1+6.0,min(late_starts))
    q2=min(q2,92.0)

    s1=q1+early_off
    s2=q2+late_off
    desired=q2-q1
    actual=s2-s1
    scale=desired/actual
    if not (0.94<=scale<=1.06):
        raise RuntimeError(
            f"Transition correction too large: early={early_off:.3f}, late={late_off:.3f}, "
            f"q1={q1:.3f}, q2={q2:.3f}, scale={scale:.6f}"
        )

    for r in best_cluster: r["selected_cluster"]="YES"
    for r in rows:
        r.setdefault("selected_cluster","NO")

    return rows,dict(early_offset=early_off,late_offset=late_off,q1=q1,q2=q2,
                     transition_scale=scale,late_cluster_count=len(best_cluster))

def probe_duration(p,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",p],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def build_piecewise(m,qdur,out):
    eo=m["early_offset"]; lo=m["late_offset"]; q1=m["q1"]; q2=m["q2"]
    s0=eo; s1=q1+eo; s2=q2+lo; s3=qdur+lo
    d0=q1; d1=q2-q1; d2=qdur-q2
    a0=s1-s0; a1=s2-s1; a2=s3-s2
    k0=d0/a0; k1=d1/a1; k2=d2/a2
    filt=(
      f"[0:v]trim=start={s0:.6f}:end={s1:.6f},setpts=(PTS-STARTPTS)*{k0:.12f}[v0];"
      f"[0:v]trim=start={s1:.6f}:end={s2:.6f},setpts=(PTS-STARTPTS)*{k1:.12f}[v1];"
      f"[0:v]trim=start={s2:.6f}:end={s3:.6f},setpts=(PTS-STARTPTS)*{k2:.12f}[v2];"
      f"[v0][v1][v2]concat=n=3:v=1:a=0,"
      f"scale=480:272:flags=lanczos,fps=30000/1001,format=yuv420p[v]"
    )
    cp=run([FFMPEG,"-y","-v","warning","-i",SRC_VIDEO,
            "-filter_complex",filt,"-map","[v]","-an",
            "-c:v","ffv1","-level","3","-pix_fmt","yuv420p","-fps_mode","cfr",out],
           "05_piecewise_lossless.log")
    if cp.returncode!=0 or not Path(out).exists(): raise RuntimeError("Piecewise video build failed")

def iso_norm(raw):
    s=raw.decode("ascii",errors="replace")
    if ";" in s:s=s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("ISO PVD missing")
    r=p[156:];r=r[:r[0]]
    return struct.unpack_from("<I",r,2)[0],struct.unpack_from("<I",r,10)[0]

def read_dir(f,ext,size):
    base=ext*SECTOR;f.seek(base);data=f.read(size);out=[];pos=0
    while pos<len(data):
        rl=data[pos]
        if rl==0:pos=((pos//SECTOR)+1)*SECTOR;continue
        rec=data[pos:pos+rl]
        ex=struct.unpack_from("<I",rec,2)[0];sz=struct.unpack_from("<I",rec,10)[0]
        flags=rec[25];nl=rec[32];raw=rec[33:33+nl]
        name="." if raw==b"\0" else ".." if raw==b"\1" else iso_norm(raw)
        out.append(dict(name=name,extent=ex,size=sz,is_dir=bool(flags&2),record_offset=base+pos))
        pos+=rl
    return out

def find_entry(f,parts):
    ext,sz=pvd_root(f);e=None
    for i,p in enumerate(parts):
        ms=[x for x in read_dir(f,ext,sz) if x["name"]==p.lower()]
        if not ms:raise FileNotFoundError("/"+"/".join(parts[:i+1]))
        e=ms[0]
        if i<len(parts)-1:ext,sz=e["extent"],e["size"]
    return e

def patch_size(f,off,new):
    f.seek(off+10);f.write(struct.pack("<I",new));f.write(struct.pack(">I",new))

def sha_file(p):
    import hashlib
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def sha_region(f,off,size):
    import hashlib
    h=hashlib.sha256();f.seek(off);remain=size
    while remain:
        b=f.read(min(remain,1024*1024))
        if not b:break
        h.update(b);remain-=len(b)
    if remain:raise RuntimeError("EOF hashing ISO")
    return h.hexdigest()

def main():
    core=load_core()
    for p in (CORE_PATH,KR_PMF,SRC_VIDEO,BASE_ISO,FFMPEG,FFPROBE):
        if not p.exists():raise RuntimeError(f"Missing input/tool: {p}")

    print("="*80,flush=True)
    print(" Naruto PSP MOV05B FIX2 - robust piecewise Stage37 dk101",flush=True)
    print("="*80,flush=True)

    krp=core.parse_pmf(KR_PMF); kra=core.recover_audio(krp)
    if kra["bad_headers"]:raise RuntimeError("KR AU headers invalid")
    oma=WORK/"kr.oma";core.build_oma(kra["frames"],oma)

    kp=WORK/"kr.s16";sp=WORK/"src.s16"
    decode_pcm(oma,kp,"01_decode_kr.log",True)
    decode_pcm(SRC_VIDEO,sp,"02_decode_src.log",False)
    qpcm=load_pcm(kp);spcm=load_pcm(sp)
    qenv=envelope(qpcm);senv=envelope(spcm);qdur=len(qpcm)/RATE

    rows,m=alignment(qenv,senv,qdur)
    write_tsv(STAGE/"robust_audio_anchors.tsv",rows)
    print(f"Mapping: early={m['early_offset']:+.3f}s late={m['late_offset']:+.3f}s "
          f"transition={m['q1']:.3f}..{m['q2']:.3f}s scale={m['transition_scale']:.6f}",
          flush=True)

    qvideo=probe_duration(KR_PMF,"03_kr_duration.log")
    if qvideo is None or not (1<qvideo<300):qvideo=qdur

    lossless=WORK/"piecewise.avi"
    build_piecewise(m,qvideo,lossless)
    outdur=probe_duration(lossless,"04_piecewise_duration.log")
    if outdur is None or abs(outdur-qvideo)>0.20:
        raise RuntimeError(f"Output duration mismatch: {outdur} vs {qvideo}")

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05b_FIX2_raw_mux.ps1"
    if composer is None or mps2pmf is None or not helper.exists():raise RuntimeError("PMF tools/helper missing")

    with BASE_ISO.open("rb") as f:
        base_entry=find_entry(f,TARGET);allocation=math.ceil(base_entry["size"]/SECTOR)*SECTOR

    cdir=composer.parent;lf=cdir/"ffmpeg.exe";temp=False
    if not lf.exists():shutil.copy2(FFMPEG,lf);temp=True
    chosen=None
    try:
        riff=WORK/"kr_frames.at3";core.build_riff(kra["frames"],riff)
        for idx,(avg,maxbr) in enumerate([(1000,1550),(975,1500),(950,1450),(925,1400),(900,1350)],1):
            tag=f"try{idx}_{avg}"
            print(f"Encode {idx}: avg={avg} max={maxbr}",flush=True)
            vmps=WORK/f"{tag}_v.mps"
            cp=run([composer,lossless,"-",vmps,"--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
                    "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"],
                   f"06_{tag}_video.log",cwd=cdir)
            if cp.returncode!=0 or not vmps.exists():continue
            vpmf=WORK/f"{tag}_v.pmf";whole=int(math.ceil(qvideo));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
                   f"07_{tag}_vpmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not vpmf.exists():continue
            h264=WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"08_{tag}_h264.log"):continue
            vsha=core.sha_file(h264)
            fmps=WORK/f"{tag}_final.mps"
            cp=run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",helper,
                    "-Composer",composer,"-H264",h264,"-AtracRiff",riff,"-OutputMps",fmps],
                   f"09_{tag}_mux.log",1200)
            if cp.returncode!=0 or not fmps.exists():continue
            core.patch_mps_audio_pts_exact(fmps,krp)
            cand=WORK/f"{tag}_final.pmf"
            total=max(qvideo,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
            whole=int(math.ceil(total));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",fmps,"-o",cand,"-m",str(mins),"-s",str(secs)],
                   f"10_{tag}_final.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not cand.exists():continue

            fp=core.parse_pmf(cand);fa=core.recover_audio(fp)
            f264=WORK/f"{tag}_final.264"
            if not core.extract_h264(cand,f264,f"11_{tag}_extract.log"):continue
            video_ok=core.sha_file(f264)==vsha
            logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
            frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
            pes_ok=len(fp["audio"])==len(krp["audio"])
            pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]
            oma2=WORK/f"{tag}.oma";core.build_oma(fa["frames"],oma2)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
                   f"12_{tag}_decode.log",600)
            decode_ok=cp.returncode==0
            info=core.probe(cand,f"13_{tag}_probe.log");vs=core.get_video(info)
            format_ok=bool(vs and vs.get("codec_name")=="h264" and int(vs.get("width",0))==480 and int(vs.get("height",0))==272)
            strict=all([video_ok,logical_ok,frames_ok,pes_ok,pts_ok,decode_ok,format_ok])
            fits=cand.stat().st_size<=allocation
            print(f"  size={cand.stat().st_size} strict={strict} fit={fits}",flush=True)
            if strict and fits:
                shutil.copy2(cand,FINAL_PMF)
                chosen=dict(avg=avg,maxbr=maxbr,size=cand.stat().st_size,
                            logical_ok=logical_ok,frames_ok=frames_ok,pes_ok=pes_ok,
                            pts_ok=pts_ok,decode_ok=decode_ok,format_ok=format_ok)
                break
    finally:
        if temp:
            try:lf.unlink()
            except:pass
    if chosen is None:raise RuntimeError("No strict-valid PMF fit the original dk101 allocation")

    for t in (8.0,35.0,m["q1"]-1,(m["q1"]+m["q2"])/2,m["q2"]+1,90.0,max(1,qvideo-8)):
        if not (0<=t<qvideo):continue
        out=OUT/f"review_{t:07.3f}.jpg"
        run([FFMPEG,"-y","-v","error","-ss",f"{t:.3f}","-i",FINAL_PMF,
             "-frames:v","1","-q:v","2",out],f"14_review_{t:.3f}.log",180)

    if SMOKE_ISO.exists():SMOKE_ISO.unlink()
    shutil.copyfile(BASE_ISO,SMOKE_ISO);payload=FINAL_PMF.read_bytes()
    with SMOKE_ISO.open("r+b") as f:
        e=find_entry(f,TARGET);f.seek(e["extent"]*SECTOR);f.write(payload)
        remain=allocation-len(payload);blk=b"\0"*min(32768,max(1,remain))
        while remain>0:
            n=min(remain,len(blk));f.write(blk[:n]);remain-=n
        patch_size(f,e["record_offset"],len(payload))
    expected=sha_file(FINAL_PMF)
    with SMOKE_ISO.open("rb") as f:
        e=find_entry(f,TARGET);actual=sha_region(f,e["extent"]*SECTOR,e["size"])
        iso_ok=e["extent"]==base_entry["extent"] and e["size"]==len(payload) and actual==expected
    if not iso_ok:raise RuntimeError("Smoke ISO verification failed")

    result=[dict(
        early_offset_sec=f"{m['early_offset']:.6f}",
        late_offset_sec=f"{m['late_offset']:.6f}",
        transition_start_sec=f"{m['q1']:.6f}",
        transition_end_sec=f"{m['q2']:.6f}",
        transition_scale=f"{m['transition_scale']:.9f}",
        late_cluster_count=m["late_cluster_count"],
        encoded_avg_kbps=chosen["avg"],encoded_max_kbps=chosen["maxbr"],
        final_pmf_bytes=chosen["size"],allocation_bytes=allocation,spare_bytes=allocation-chosen["size"],
        logical_752_equal_kr="YES" if chosen["logical_ok"] else "NO",
        frames_744_equal_kr="YES" if chosen["frames_ok"] else "NO",
        audio_pes_equal_kr="YES" if chosen["pes_ok"] else "NO",
        audio_pts_equal_kr="YES" if chosen["pts_ok"] else "NO",
        atrac_decode="PASS" if chosen["decode_ok"] else "FAIL",
        video_format="PASS" if chosen["format_ok"] else "FAIL",
        watermark_policy="PRESERVED",iso_sha_match="YES",status="PASS"
    )]
    write_tsv(STAGE/"mov05b_fix2_result.tsv",result)
    summary=[
        "Naruto PSP MOV05B FIX2 - Stage37 dk101 piecewise reconstruction","="*80,"",
        "RESULT=PASS","",
        f"Early offset={m['early_offset']:+.3f}s",
        f"Late offset={m['late_offset']:+.3f}s",
        f"Transition={m['q1']:.3f}..{m['q2']:.3f}s",
        f"Transition correction={m['transition_scale']:.6f}x","",
        "Video=Stage37 Koreanized visual (watermark preserved for sample)",
        "Audio=exact KR Japanese ATRAC3+",
        "PTS=exact KR audio PTS","",
        f"Final PMF={FINAL_PMF}",f"Smoke ISO={SMOKE_ISO}",
        "Wrapper auto-launches PPSSPP."
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
