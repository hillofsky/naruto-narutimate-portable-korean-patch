#!/usr/bin/env python3
# Naruto PSP MOV05B FIX1 - piecewise Stage37 dk101 reconstruction

from __future__ import annotations
import array, csv, importlib.util, math, os, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05b_proven_movie_core.py"
KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"
BASE_ISO=ROOT/"analysis"/"mov"/"mov03t_iso_install"/"output"/"Naruto_KR_MOV03S_KoreanMovies.iso"

STAGE=ROOT/"analysis"/"mov"/"mov05b_fix1_dk101_stage37_piecewise"
WORK=STAGE/"work"; OUT=STAGE/"output"; LOGD=STAGE/"logs"; FONTD=STAGE/"fonts"
for p in (STAGE,WORK,OUT,LOGD,FONTD): p.mkdir(parents=True,exist_ok=True)

FINAL_PMF=OUT/"dk101_stage37_KOvideo_KRJPaudio_piecewise.pmf"
SMOKE_ISO=OUT/"Naruto_KR_MOV05B_FIX1_dk101_stage37_smoketest.iso"

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

DECODE_RATE=8000
ENV_HZ=20.0
WIN_SAMPLES=int(DECODE_RATE/ENV_HZ)
DENSE_STEP=2.0
DENSE_WIN=4.0
SEARCH_OFFSET_MIN=-2.0
SEARCH_OFFSET_MAX=1.5
STRONG_CORR=0.55
SECTOR=2048
TARGET_PATH=["PSP_GAME","USRDIR","movie","dk101.pmf"]

def load_core():
    spec=importlib.util.spec_from_file_location("mov05b_core",CORE_PATH)
    if spec is None or spec.loader is None: raise RuntimeError("Cannot load proven core")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod.STAGE=STAGE; mod.WORK=WORK; mod.OUT=OUT; mod.LOGD=LOGD; mod.FONTD=FONTD
    return mod

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
    cmd+=["-i",src,"-vn","-ac","1","-ar",str(DECODE_RATE),"-f","s16le","-c:a","pcm_s16le",out]
    cp=run(cmd,tag,3000)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(path):
    a=array.array("h")
    with Path(path).open("rb") as f: a.fromfile(f,Path(path).stat().st_size//2)
    if sys.byteorder!="little": a.byteswap()
    return a

def envelope(pcm):
    n=(len(pcm)//WIN_SAMPLES)*WIN_SAMPLES
    out=[]
    for i in range(0,n,WIN_SAMPLES):
        ss=0.0
        for v in pcm[i:i+WIN_SAMPLES]:
            x=float(v)/32768.0; ss+=x*x
        out.append(math.log1p(math.sqrt(ss/WIN_SAMPLES+1e-12)*20.0))
    return out

def corr(a,b):
    if len(a)!=len(b) or len(a)<8: return -2.0
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    va=sum((x-ma)*(x-ma) for x in a); vb=sum((y-mb)*(y-mb) for y in b)
    if va<=1e-12 or vb<=1e-12: return -2.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)

def median(vals):
    s=sorted(vals); n=len(s)
    if not s: raise ValueError("empty median")
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0

def dense_anchors(qenv,senv,qdur):
    rows=[]
    half=int(round(DENSE_WIN*ENV_HZ/2))
    off_min=int(round(SEARCH_OFFSET_MIN*ENV_HZ))
    off_max=int(round(SEARCH_OFFSET_MAX*ENV_HZ))
    t=6.0
    while t<=qdur-6.0:
        qc=int(round(t*ENV_HZ)); qa=qc-half; qb=qc+half
        if qa<0 or qb>len(qenv):
            t+=DENSE_STEP; continue
        q=qenv[qa:qb]
        best=(-2.0,None)
        for oi in range(off_min,off_max+1):
            sc=qc+oi; sa=sc-half; sb=sc+half
            if sa<0 or sb>len(senv): continue
            c=corr(q,senv[sa:sb])
            if c>best[0]: best=(c,sc)
        c,sc=best
        source=sc/ENV_HZ if sc is not None else -999
        off=source-t if sc is not None else -999
        rows.append(dict(query_center_sec=f"{t:.3f}",
                         source_center_sec=f"{source:.3f}" if sc is not None else "",
                         offset_sec=f"{off:.3f}" if sc is not None else "",
                         correlation=f"{c:.6f}",
                         strong="YES" if c>=STRONG_CORR else "NO"))
        t+=DENSE_STEP
    return rows

def derive_piecewise(rows):
    strong=[r for r in rows if r["strong"]=="YES"]
    if len(strong)<8: raise RuntimeError(f"Too few strong anchors: {len(strong)}")

    early=[r for r in strong if float(r["query_center_sec"])<=62 and float(r["correlation"])>=0.80]
    if len(early)<5: raise RuntimeError(f"Too few early stable anchors: {len(early)}")
    early_off=median([float(r["offset_sec"]) for r in early])

    late_raw=[r for r in strong if float(r["query_center_sec"])>=72 and
              abs(float(r["offset_sec"])-early_off)>=0.25]
    if not late_raw: raise RuntimeError("No post-edit strong offset cluster")

    late_sorted=sorted(late_raw,key=lambda r:float(r["correlation"]),reverse=True)
    late_seed=late_sorted[:max(1,min(5,len(late_sorted)))]
    late_off=median([float(r["offset_sec"]) for r in late_seed])

    early_cluster=[r for r in strong if abs(float(r["offset_sec"])-early_off)<=0.12]
    late_cluster=[r for r in strong if float(r["query_center_sec"])>=65 and
                  abs(float(r["offset_sec"])-late_off)<=0.15]
    if not late_cluster: raise RuntimeError("Late cluster not stable")

    first_late=min(late_cluster,key=lambda r:float(r["query_center_sec"]))
    q2=float(first_late["query_center_sec"])
    before=[r for r in early_cluster if float(r["query_center_sec"])<q2]
    if not before: raise RuntimeError("No early cluster before late cluster")
    last_early=max(before,key=lambda r:float(r["query_center_sec"]))
    q1=float(last_early["query_center_sec"])

    q1=min(q1+DENSE_WIN/2.0,q2-4.0)
    q2=max(q2-DENSE_WIN/2.0,q1+4.0)

    src1=q1+early_off
    src2=q2+late_off
    desired=q2-q1
    actual=src2-src1
    if actual<=1.0: raise RuntimeError("Invalid transition duration")
    stretch=desired/actual
    if not (0.95<=stretch<=1.05):
        raise RuntimeError(f"Transition correction too large: {stretch:.6f}")

    return dict(early_offset=early_off,late_offset=late_off,q1=q1,q2=q2,
                src1=src1,src2=src2,transition_scale=stretch,
                early_count=len(early_cluster),late_count=len(late_cluster))

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def build_piecewise_lossless(m,qdur,out):
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
           "05_piecewise_lossless.log",3000)
    if cp.returncode!=0 or not Path(out).exists(): raise RuntimeError("Piecewise reconstruction failed")

def iso_norm(raw):
    s=raw.decode("ascii",errors="replace")
    if ";" in s:s=s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("ISO PVD missing")
    r=p[156:]; r=r[:r[0]]
    return struct.unpack_from("<I",r,2)[0],struct.unpack_from("<I",r,10)[0]

def read_dir(f,extent,size):
    base=extent*SECTOR; f.seek(base); data=f.read(size); out=[]; pos=0
    while pos<len(data):
        rl=data[pos]
        if rl==0: pos=((pos//SECTOR)+1)*SECTOR; continue
        rec=data[pos:pos+rl]
        ext=struct.unpack_from("<I",rec,2)[0]; sz=struct.unpack_from("<I",rec,10)[0]
        flags=rec[25]; nl=rec[32]; raw=rec[33:33+nl]
        name="." if raw==b"\0" else ".." if raw==b"\1" else iso_norm(raw)
        out.append(dict(name=name,extent=ext,size=sz,is_dir=bool(flags&2),record_offset=base+pos))
        pos+=rl
    return out

def find_entry(f,parts):
    ext,sz=pvd_root(f); e=None
    for i,p in enumerate(parts):
        ms=[x for x in read_dir(f,ext,sz) if x["name"]==p.lower()]
        if not ms: raise FileNotFoundError("/"+"/".join(parts[:i+1]))
        e=ms[0]
        if i<len(parts)-1: ext,sz=e["extent"],e["size"]
    return e

def patch_size(f,record_offset,new_size):
    f.seek(record_offset+10); f.write(struct.pack("<I",new_size)); f.write(struct.pack(">I",new_size))

def sha_file(path):
    import hashlib
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def sha_region(f,off,size):
    import hashlib
    h=hashlib.sha256(); f.seek(off); remain=size
    while remain:
        b=f.read(min(remain,1024*1024))
        if not b:break
        h.update(b); remain-=len(b)
    if remain: raise RuntimeError("EOF hashing ISO")
    return h.hexdigest()

def main():
    core=load_core()
    for p in (CORE_PATH,KR_PMF,SRC_VIDEO,BASE_ISO,FFMPEG,FFPROBE):
        if not p.exists(): raise RuntimeError(f"Missing input/tool: {p}")

    failure=STAGE/"FAILURE.txt"
    if failure.exists(): failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05B FIX1 - piecewise Stage37 dk101",flush=True)
    print("="*80,flush=True)

    krp=core.parse_pmf(KR_PMF)
    kra=core.recover_audio(krp)
    if kra["bad_headers"]: raise RuntimeError("KR AU header validation failed")

    oma=WORK/"kr.oma"; core.build_oma(kra["frames"],oma)
    krpcm_path=WORK/"kr.s16"; srcpcm_path=WORK/"source.s16"
    decode_pcm(oma,krpcm_path,"01_decode_kr.log",True)
    decode_pcm(SRC_VIDEO,srcpcm_path,"02_decode_stage37.log",False)

    krpcm=load_pcm(krpcm_path); srcpcm=load_pcm(srcpcm_path)
    qenv=envelope(krpcm); senv=envelope(srcpcm)
    qdur=len(krpcm)/DECODE_RATE

    anchors=dense_anchors(qenv,senv,qdur)
    write_tsv(STAGE/"dense_audio_anchors.tsv",anchors)
    mapping=derive_piecewise(anchors)

    print(f"Mapping early={mapping['early_offset']:+.3f}s late={mapping['late_offset']:+.3f}s "
          f"transition={mapping['q1']:.3f}..{mapping['q2']:.3f}s "
          f"scale={mapping['transition_scale']:.6f}",flush=True)

    qvideo=probe_duration(KR_PMF,"03_kr_duration.log")
    if qvideo is None or not (1<qvideo<300): qvideo=qdur

    lossless=WORK/"piecewise.avi"
    build_piecewise_lossless(mapping,qvideo,lossless)
    outdur=probe_duration(lossless,"04_piecewise_duration.log")
    if outdur is None or abs(outdur-qvideo)>0.20:
        raise RuntimeError(f"Piecewise duration mismatch: {outdur} vs {qvideo}")

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05b_FIX1_raw_mux.ps1"
    if composer is None or mps2pmf is None or not helper.exists(): raise RuntimeError("PMF tools/helper missing")

    with BASE_ISO.open("rb") as f:
        iso_entry=find_entry(f,TARGET_PATH)
        allocation=math.ceil(iso_entry["size"]/SECTOR)*SECTOR

    cdir=composer.parent
    local_ffmpeg=cdir/"ffmpeg.exe"; temp_ffmpeg=False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG,local_ffmpeg); temp_ffmpeg=True

    chosen=None
    try:
        riff=WORK/"kr_frames.at3"; core.build_riff(kra["frames"],riff)
        for attempt,(avg,maxbr) in enumerate([(1000,1550),(975,1500),(950,1450),(925,1400),(900,1350)],1):
            tag=f"try{attempt}_{avg}"
            print(f"Encoding attempt {attempt}: avg={avg} max={maxbr}",flush=True)

            vmps=WORK/f"{tag}_video.mps"
            cp=run([composer,lossless,"-",vmps,"--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
                    "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"],
                   f"06_{tag}_video.log",3000,cwd=cdir)
            if cp.returncode!=0 or not vmps.exists(): continue

            vpmf=WORK/f"{tag}_video.pmf"
            whole=int(math.ceil(qvideo)); mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
                   f"07_{tag}_video_pmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not vpmf.exists(): continue

            h264=WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"08_{tag}_h264.log"): continue
            expected_h264=core.sha_file(h264)

            fmps=WORK/f"{tag}_final.mps"
            cp=run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",helper,
                    "-Composer",composer,"-H264",h264,"-AtracRiff",riff,"-OutputMps",fmps],
                   f"09_{tag}_mux.log",1200)
            if cp.returncode!=0 or not fmps.exists(): continue

            core.patch_mps_audio_pts_exact(fmps,krp)

            cand=WORK/f"{tag}_final.pmf"
            total=max(qvideo,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
            whole=int(math.ceil(total)); mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",fmps,"-o",cand,"-m",str(mins),"-s",str(secs)],
                   f"10_{tag}_final_pmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not cand.exists(): continue

            fp=core.parse_pmf(cand); fa=core.recover_audio(fp)
            final264=WORK/f"{tag}_final.264"
            if not core.extract_h264(cand,final264,f"11_{tag}_final_h264.log"): continue

            video_ok=core.sha_file(final264)==expected_h264
            logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
            frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
            pes_ok=len(fp["audio"])==len(krp["audio"])
            pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]

            oma2=WORK/f"{tag}.oma"; core.build_oma(fa["frames"],oma2)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
                   f"12_{tag}_decode.log",600)
            decode_ok=cp.returncode==0

            info=core.probe(cand,f"13_{tag}_probe.log"); vs=core.get_video(info)
            format_ok=bool(vs and vs.get("codec_name")=="h264" and int(vs.get("width",0))==480 and int(vs.get("height",0))==272)
            strict=all([video_ok,logical_ok,frames_ok,pes_ok,pts_ok,decode_ok,format_ok])
            fits=cand.stat().st_size<=allocation
            print(f"  size={cand.stat().st_size} fit={fits} strict={strict}",flush=True)

            if strict and fits:
                shutil.copy2(cand,FINAL_PMF)
                chosen=dict(avg=avg,maxbr=maxbr,size=cand.stat().st_size,
                            logical_ok=logical_ok,frames_ok=frames_ok,pes_ok=pes_ok,pts_ok=pts_ok,
                            decode_ok=decode_ok,format_ok=format_ok)
                break
    finally:
        if temp_ffmpeg:
            try: local_ffmpeg.unlink()
            except: pass

    if chosen is None: raise RuntimeError("No strict-valid PMF fit dk101 allocation")

    review_times=[8.0,35.0,max(0,mapping["q1"]-2),(mapping["q1"]+mapping["q2"])/2,
                  min(qvideo-1,mapping["q2"]+2),90.0,max(1,qvideo-8)]
    for t in sorted(set(round(x,3) for x in review_times if 0<=x<qvideo)):
        out=OUT/f"review_{t:07.3f}.jpg"
        run([FFMPEG,"-y","-v","error","-ss",f"{t:.3f}","-i",FINAL_PMF,
             "-frames:v","1","-q:v","2",out],f"14_review_{t:.3f}.log",180)

    if SMOKE_ISO.exists(): SMOKE_ISO.unlink()
    shutil.copyfile(BASE_ISO,SMOKE_ISO)
    payload=FINAL_PMF.read_bytes()
    with SMOKE_ISO.open("r+b") as f:
        e=find_entry(f,TARGET_PATH)
        f.seek(e["extent"]*SECTOR); f.write(payload)
        remain=allocation-len(payload)
        block=b"\0"*min(32768,max(1,remain))
        while remain>0:
            n=min(remain,len(block)); f.write(block[:n]); remain-=n
        patch_size(f,e["record_offset"],len(payload))

    expected=sha_file(FINAL_PMF)
    with SMOKE_ISO.open("rb") as f:
        e=find_entry(f,TARGET_PATH)
        actual=sha_region(f,e["extent"]*SECTOR,e["size"])
        iso_ok=(e["extent"]==iso_entry["extent"] and e["size"]==len(payload) and actual==expected)
    if not iso_ok: raise RuntimeError("Smoke ISO verification failed")

    result=[dict(
        early_offset_sec=f"{mapping['early_offset']:.6f}",
        late_offset_sec=f"{mapping['late_offset']:.6f}",
        transition_query_start_sec=f"{mapping['q1']:.6f}",
        transition_query_end_sec=f"{mapping['q2']:.6f}",
        transition_scale=f"{mapping['transition_scale']:.9f}",
        early_anchor_count=mapping["early_count"], late_anchor_count=mapping["late_count"],
        encoded_avg_kbps=chosen["avg"], encoded_max_kbps=chosen["maxbr"],
        final_pmf_bytes=chosen["size"], allocation_bytes=allocation,
        spare_bytes=allocation-chosen["size"],
        logical_752_equal_kr="YES" if chosen["logical_ok"] else "NO",
        frames_744_equal_kr="YES" if chosen["frames_ok"] else "NO",
        audio_pes_equal_kr="YES" if chosen["pes_ok"] else "NO",
        audio_pts_equal_kr="YES" if chosen["pts_ok"] else "NO",
        atrac_decode="PASS" if chosen["decode_ok"] else "FAIL",
        video_format="PASS" if chosen["format_ok"] else "FAIL",
        watermark_policy="PRESERVED", final_pmf=str(FINAL_PMF), smoke_iso=str(SMOKE_ISO),
        iso_sha_match="YES", status="PASS"
    )]
    write_tsv(STAGE/"mov05b_fix1_result.tsv",result)

    summary=[
        "Naruto PSP MOV05B FIX1 - Stage37 dk101 piecewise reconstruction",
        "="*80,"","RESULT=PASS","",
        f"Early offset={mapping['early_offset']:+.3f}s",
        f"Late offset={mapping['late_offset']:+.3f}s",
        f"Transition KR={mapping['q1']:.3f}..{mapping['q2']:.3f}s",
        f"Transition correction={mapping['transition_scale']:.6f}x","",
        "Final audio: exact KR Japanese ATRAC3+ / exact KR PTS",
        "Watermark: preserved for this sample","",
        f"Final PMF={FINAL_PMF}",f"Smoke ISO={SMOKE_ISO}",
        "Wrapper will auto-launch PPSSPP."
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except SystemExit: raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
