#!/usr/bin/env python3
# Naruto PSP MOV05B FIX5
#
# Correct model:
#   early: Stage37 source time = KR time + early_offset (~+0.700)
#   late : Stage37 source time = KR time + late_offset  (~+0.250)
#
# Therefore the Stage37 source must jump BACK by about 0.450 sec at the edit.
# No stretching, no inserted black, no frame hold.
#
# Stage37 already contains a 2.3 sec black interval near the edit. FIX5 places
# the 0.45 sec source overlap entirely inside that black interval, so the
# repeated source frames are visually invisible while the second video starts
# on its own independent audio mapping.
#
# Final audio remains exact KR ATRAC3+ and exact KR audio PTS.

from __future__ import annotations
import array, csv, importlib.util, math, re, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05b_proven_movie_core.py"
KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"
BASE_ISO=ROOT/"analysis"/"mov"/"mov03t_iso_install"/"output"/"Naruto_KR_MOV03S_KoreanMovies.iso"

STAGE=ROOT/"analysis"/"mov"/"mov05b_fix5_dk101_overlap_reset"
WORK=STAGE/"work"; OUT=STAGE/"output"; LOGD=STAGE/"logs"; FONTD=STAGE/"fonts"
for p in (STAGE,WORK,OUT,LOGD,FONTD): p.mkdir(parents=True,exist_ok=True)

FINAL_PMF=OUT/"dk101_stage37_KOvideo_KRJPaudio_overlapreset.pmf"
SMOKE_ISO=OUT/"Naruto_KR_MOV05B_FIX5_dk101_stage37_smoketest.iso"

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
    if len(a)!=len(b) or len(a)<8:return -2.0
    ma=sum(a)/len(a); mb=sum(b)/len(b)
    va=sum((x-ma)*(x-ma) for x in a); vb=sum((y-mb)*(y-mb) for y in b)
    if va<=1e-12 or vb<=1e-12:return -2.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)

def best_offset(qenv,senv,center,window,lo,hi,step=0.05):
    half=int(round(window*ENV_HZ/2))
    qc=int(round(center*ENV_HZ))
    qa=qc-half; qb=qc+half
    if qa<0 or qb>len(qenv):return None
    q=qenv[qa:qb]
    best=(-2.0,None)
    n=int(round((hi-lo)/step))
    for i in range(n+1):
        off=lo+i*step
        sc=int(round((center+off)*ENV_HZ))
        sa=sc-half; sb=sc+half
        if sa<0 or sb>len(senv):continue
        c=corr(q,senv[sa:sb])
        if c>best[0]:best=(c,off)
    return best

def median(vals):
    s=sorted(vals); n=len(s)
    if not s:raise RuntimeError("empty median")
    return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0

def estimate_offsets(qenv,senv):
    rows=[]

    early=[]
    for t in (10,20,30,40,50,60):
        r=best_offset(qenv,senv,float(t),8.0,0.45,0.95)
        if r:
            c,o=r
            rows.append(dict(region="early",center_sec=t,window_sec=8,
                             best_offset_sec=f"{o:.3f}",correlation=f"{c:.6f}"))
            if c>=0.85:early.append((o,c,t))
    if len(early)<5:
        raise RuntimeError(f"Early mapping not stable enough: {early}")
    early_off=median([x[0] for x in early])

    # Long late windows around the region already shown to re-lock.
    late=[]
    for t in (86,88,90,92,94,96):
        for w in (8.0,12.0):
            r=best_offset(qenv,senv,float(t),w,-0.10,0.60)
            if r:
                c,o=r
                rows.append(dict(region="late",center_sec=t,window_sec=int(w),
                                 best_offset_sec=f"{o:.3f}",correlation=f"{c:.6f}"))
                if c>=0.48:late.append((o,c,t,w))

    if not late:
        raise RuntimeError("No convincing late audio anchors")

    # Densest 0.10-sec cluster.
    best_cluster=[]
    for x in late:
        cl=[y for y in late if abs(y[0]-x[0])<=0.10]
        if len(cl)>len(best_cluster):
            best_cluster=cl
        elif len(cl)==len(best_cluster) and cl:
            if sum(y[1] for y in cl)>sum(y[1] for y in best_cluster):
                best_cluster=cl

    if not best_cluster:
        raise RuntimeError("Late offset cluster not found")
    late_off=median([x[0] for x in best_cluster])

    # Sanity: must represent the observed edit.
    gap=early_off-late_off
    if not (0.25<=gap<=0.70):
        raise RuntimeError(f"Unexpected offset jump: early={early_off:.3f} late={late_off:.3f} gap={gap:.3f}")

    for r in rows:
        r["selected_late_cluster"]="NO"
    for o,c,t,w in best_cluster:
        for r in rows:
            if (r["region"]=="late" and float(r["center_sec"])==float(t)
                and float(r["window_sec"])==float(w)
                and abs(float(r["best_offset_sec"])-o)<0.001):
                r["selected_late_cluster"]="YES"

    return rows,early_off,late_off,gap

def detect_black_intervals():
    start=64.0; dur=16.0
    cp=run([FFMPEG,"-hide_banner","-v","info","-ss",f"{start:.3f}","-t",f"{dur:.3f}",
            "-i",SRC_VIDEO,"-an","-vf","blackdetect=d=0.10:pix_th=0.10","-f","null","-"],
           "03_black_detect.log",300)
    intervals=[]
    for line in cp.stderr.splitlines():
        m=re.search(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)",line)
        if not m:continue
        bs=float(m.group(1));be=float(m.group(2));bd=float(m.group(3))
        if bs<dur+3:
            bs+=start;be+=start
        intervals.append((bs,be,bd))
    return intervals

def choose_reset(black_intervals,early_off,late_off,gap):
    # Need a black interval that can fully contain the source overlap.
    usable=[x for x in black_intervals if x[2]>=gap+0.10]
    if not usable:
        raise RuntimeError(f"No black interval long enough for {gap:.3f}s source overlap: {black_intervals}")

    # Prefer interval nearest the known edit area and with longest duration.
    usable.sort(key=lambda x:(abs(((x[0]+x[1])/2)-69.0),-x[2]))
    bs,be,bd=usable[0]
    mid=(bs+be)/2.0

    # Source overlap is [qreset+late, qreset+early].
    # Center it in the black interval:
    # qreset + (early+late)/2 = black_mid
    qreset=mid-(early_off+late_off)/2.0
    overlap_start=qreset+late_off
    overlap_end=qreset+early_off

    if overlap_start<bs or overlap_end>be:
        raise RuntimeError("Computed source overlap does not fit black interval")

    return dict(
        black_start=bs,black_end=be,black_duration=bd,
        qreset=qreset,
        overlap_start=overlap_start,overlap_end=overlap_end
    )

def probe_duration(p,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",p],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def build_overlap_lossless(reset,early_off,late_off,qdur,out):
    q=reset["qreset"]
    first_start=early_off
    first_end=q+early_off
    second_start=q+late_off
    second_end=qdur+late_off

    # IMPORTANT:
    # first_end - second_start == early_off-late_off.
    # This intentionally repeats that amount of SOURCE footage inside an
    # already-black transition. Output time itself stays continuous and exact.
    filt=(
      f"[0:v]trim=start={first_start:.6f}:end={first_end:.6f},"
      f"setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,"
      f"fps=30000/1001,setsar=1[v0];"
      f"[0:v]trim=start={second_start:.6f}:end={second_end:.6f},"
      f"setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,"
      f"fps=30000/1001,setsar=1[v1];"
      f"[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]"
    )
    cp=run([FFMPEG,"-y","-v","warning","-i",SRC_VIDEO,
            "-filter_complex",filt,"-map","[v]","-an",
            "-c:v","ffv1","-level","3","-pix_fmt","yuv420p","-fps_mode","cfr",out],
           "04_overlap_lossless.log")
    if cp.returncode!=0 or not Path(out).exists():
        raise RuntimeError("Overlap-reset video reconstruction failed")

def iso_norm(raw):
    s=raw.decode("ascii",errors="replace")
    if ";" in s:s=s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("ISO PVD missing")
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

    fail=STAGE/"FAILURE.txt"
    if fail.exists():fail.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05B FIX5 - overlap reset inside black transition",flush=True)
    print("="*80,flush=True)

    krp=core.parse_pmf(KR_PMF);kra=core.recover_audio(krp)
    if kra["bad_headers"]:raise RuntimeError("KR AU header validation failed")

    oma=WORK/"kr.oma";core.build_oma(kra["frames"],oma)
    kp=WORK/"kr.s16";sp=WORK/"src.s16"
    decode_pcm(oma,kp,"01_decode_kr.log",True)
    decode_pcm(SRC_VIDEO,sp,"02_decode_stage37.log",False)

    qenv=envelope(load_pcm(kp));senv=envelope(load_pcm(sp))
    rows,early_off,late_off,gap=estimate_offsets(qenv,senv)
    write_tsv(STAGE/"audio_offset_anchors.tsv",rows)

    black=detect_black_intervals()
    reset=choose_reset(black,early_off,late_off,gap)

    print(
        f"Offsets: early={early_off:+.3f}s late={late_off:+.3f}s "
        f"source rewind={gap:.3f}s",
        flush=True
    )
    print(
        f"Black={reset['black_start']:.3f}..{reset['black_end']:.3f}s "
        f"reset KR={reset['qreset']:.3f}s "
        f"source overlap={reset['overlap_start']:.3f}..{reset['overlap_end']:.3f}s",
        flush=True
    )

    qvideo=probe_duration(KR_PMF,"05_kr_duration.log")
    if qvideo is None or not (1<qvideo<300):
        qvideo=len(qenv)/ENV_HZ

    lossless=WORK/"overlap_reset.avi"
    build_overlap_lossless(reset,early_off,late_off,qvideo,lossless)

    outdur=probe_duration(lossless,"06_overlap_duration.log")
    if outdur is None or abs(outdur-qvideo)>0.20:
        raise RuntimeError(f"Overlap output duration mismatch: {outdur} vs {qvideo}")

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05b_FIX5_raw_mux.ps1"
    if composer is None or mps2pmf is None or not helper.exists():
        raise RuntimeError("PMF tools/helper missing")

    with BASE_ISO.open("rb") as f:
        base_entry=find_entry(f,TARGET)
        allocation=math.ceil(base_entry["size"]/SECTOR)*SECTOR

    cdir=composer.parent;lf=cdir/"ffmpeg.exe";temp=False
    if not lf.exists():shutil.copy2(FFMPEG,lf);temp=True

    chosen=None
    try:
        riff=WORK/"kr_frames.at3";core.build_riff(kra["frames"],riff)

        for idx,(avg,maxbr) in enumerate([(1000,1550),(975,1500),(950,1450),(925,1400),(900,1350)],1):
            tag=f"try{idx}_{avg}"
            print(f"Encode {idx}: avg={avg} max={maxbr}",flush=True)

            vmps=WORK/f"{tag}_v.mps"
            cp=run([composer,lossless,"-",vmps,
                    "--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
                    "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"],
                   f"07_{tag}_video.log",cwd=cdir)
            if cp.returncode!=0 or not vmps.exists():continue

            vpmf=WORK/f"{tag}_v.pmf";whole=int(math.ceil(qvideo));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
                   f"08_{tag}_vpmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not vpmf.exists():continue

            h264=WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"09_{tag}_h264.log"):continue
            vsha=core.sha_file(h264)

            fmps=WORK/f"{tag}_final.mps"
            cp=run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",helper,
                    "-Composer",composer,"-H264",h264,"-AtracRiff",riff,"-OutputMps",fmps],
                   f"10_{tag}_mux.log",1200)
            if cp.returncode!=0 or not fmps.exists():continue

            core.patch_mps_audio_pts_exact(fmps,krp)

            cand=WORK/f"{tag}_final.pmf"
            total=max(qvideo,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
            whole=int(math.ceil(total));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",fmps,"-o",cand,"-m",str(mins),"-s",str(secs)],
                   f"11_{tag}_final.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not cand.exists():continue

            fp=core.parse_pmf(cand);fa=core.recover_audio(fp)
            f264=WORK/f"{tag}_final.264"
            if not core.extract_h264(cand,f264,f"12_{tag}_extract.log"):continue

            video_ok=core.sha_file(f264)==vsha
            logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
            frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
            pes_ok=len(fp["audio"])==len(krp["audio"])
            pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]

            oma2=WORK/f"{tag}.oma";core.build_oma(fa["frames"],oma2)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
                   f"13_{tag}_decode.log",600)
            decode_ok=cp.returncode==0

            info=core.probe(cand,f"14_{tag}_probe.log");vs=core.get_video(info)
            format_ok=bool(vs and vs.get("codec_name")=="h264" and
                           int(vs.get("width",0))==480 and int(vs.get("height",0))==272)

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

    if chosen is None:
        raise RuntimeError("No strict-valid PMF fit original dk101 allocation")

    # Review around reset and late dialogue.
    q=reset["qreset"]
    review=[8.0,35.0,max(0,q-1),q-0.1,q+0.1,min(qvideo-1,q+1),88.0,90.0,94.0,max(1,qvideo-8)]
    for t in sorted(set(round(x,3) for x in review if 0<=x<qvideo)):
        out=OUT/f"review_{t:07.3f}.jpg"
        run([FFMPEG,"-y","-v","error","-ss",f"{t:.3f}","-i",FINAL_PMF,
             "-frames:v","1","-q:v","2",out],f"15_review_{t:.3f}.log",180)

    # Smoke ISO.
    if SMOKE_ISO.exists():SMOKE_ISO.unlink()
    shutil.copyfile(BASE_ISO,SMOKE_ISO)
    payload=FINAL_PMF.read_bytes()
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
        early_offset_sec=f"{early_off:.6f}",
        late_offset_sec=f"{late_off:.6f}",
        source_rewind_sec=f"{gap:.6f}",
        black_start_sec=f"{reset['black_start']:.6f}",
        black_end_sec=f"{reset['black_end']:.6f}",
        reset_kr_sec=f"{reset['qreset']:.6f}",
        source_overlap_start_sec=f"{reset['overlap_start']:.6f}",
        source_overlap_end_sec=f"{reset['overlap_end']:.6f}",
        encoded_avg_kbps=chosen["avg"],
        encoded_max_kbps=chosen["maxbr"],
        final_pmf_bytes=chosen["size"],
        allocation_bytes=allocation,
        spare_bytes=allocation-chosen["size"],
        logical_752_equal_kr="YES" if chosen["logical_ok"] else "NO",
        frames_744_equal_kr="YES" if chosen["frames_ok"] else "NO",
        audio_pes_equal_kr="YES" if chosen["pes_ok"] else "NO",
        audio_pts_equal_kr="YES" if chosen["pts_ok"] else "NO",
        atrac_decode="PASS" if chosen["decode_ok"] else "FAIL",
        video_format="PASS" if chosen["format_ok"] else "FAIL",
        watermark_policy="PRESERVED",
        iso_sha_match="YES",
        status="PASS"
    )]
    write_tsv(STAGE/"mov05b_fix5_result.tsv",result)

    summary=[
        "Naruto PSP MOV05B FIX5 - overlap reset inside black transition","="*80,"",
        "RESULT=PASS","",
        f"Early mapping={early_off:+.3f}s",
        f"Late mapping={late_off:+.3f}s",
        f"Source rewind at edit={gap:.3f}s",
        f"Black interval={reset['black_start']:.3f}..{reset['black_end']:.3f}s",
        f"KR reset time={reset['qreset']:.3f}s",
        f"Repeated source interval={reset['overlap_start']:.3f}..{reset['overlap_end']:.3f}s","",
        "No video stretching.",
        "No inserted black frame.",
        "No frame hold.",
        "Only a short source overlap, completely inside the existing black transition.","",
        "Video=Stage37 Koreanized visual",
        "Audio=exact KR Japanese ATRAC3+",
        "PTS=exact KR audio PTS",
        "Watermark=preserved for sync test","",
        f"Final PMF={FINAL_PMF}",
        f"Smoke ISO={SMOKE_ISO}",
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
