#!/usr/bin/env python3
# Naruto PSP MOV05B - build dk101 from Stage37 Koreanized video
#
# Video source:
#   analysis\stage37\video\source_video.mp4
#
# Alignment:
#   KR dk101 Japanese audio -> Stage37 audio
#   verify local anchors across the movie before encoding
#
# Final PMF:
#   video = Stage37 Koreanized dk101 visual
#   audio = exact KR original Japanese ATRAC3+ frames
#   PTS   = exact KR original audio PTS
#
# Then create a separate smoke-test ISO and verify embedded SHA256.
#
# Watermark policy for this sample:
#   preserve Stage37 pixels as-is. Do not delogo/inpaint yet.

from __future__ import annotations
import array, csv, importlib.util, math, os, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
CORE_PATH = ROOT / "mov05b_proven_movie_core.py"

KR_PMF = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie" / "dk101.pmf"
SRC_VIDEO = ROOT / "analysis" / "stage37" / "video" / "source_video.mp4"
BASE_ISO = ROOT / "analysis" / "mov" / "mov03t_iso_install" / "output" / "Naruto_KR_MOV03S_KoreanMovies.iso"

STAGE = ROOT / "analysis" / "mov" / "mov05b_dk101_stage37_final"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

FINAL_PMF = OUT / "dk101_stage37_KOvideo_KRJPaudio.pmf"
SMOKE_ISO = OUT / "Naruto_KR_MOV05B_dk101_stage37_smoketest.iso"

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

DECODE_RATE = 8000
ENV_HZ = 20.0
WIN_SAMPLES = int(DECODE_RATE / ENV_HZ)
INITIAL_OFFSET = 0.700
ANCHOR_WINDOW_SEC = 8.0
ANCHOR_SEARCH_SEC = 2.0
ANCHOR_STEP_SEC = 10.0

SECTOR = 2048
TARGET_PATH = ["PSP_GAME","USRDIR","movie","dk101.pmf"]

def load_core():
    if not CORE_PATH.exists():
        raise RuntimeError(f"Missing proven core: {CORE_PATH}")
    spec=importlib.util.spec_from_file_location("mov05b_core",CORE_PATH)
    mod=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.STAGE=STAGE; mod.WORK=WORK; mod.OUT=OUT; mod.LOGD=LOGD; mod.FONTD=FONTD
    return mod

def run(cmd,logname,timeout=2400,cwd=None):
    cp=subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",
        timeout=timeout
    )
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
        w.writeheader();w.writerows(rows)

def decode_pcm(src,out,tag,is_oma=False):
    cmd=[FFMPEG,"-y","-v","warning"]
    if is_oma:
        cmd += ["-f","oma"]
    cmd += ["-i",src,"-vn","-ac","1","-ar",str(DECODE_RATE),"-f","s16le","-c:a","pcm_s16le",out]
    cp=run(cmd,tag,3000)
    if cp.returncode!=0 or not Path(out).exists() or Path(out).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(path):
    a=array.array("h")
    with Path(path).open("rb") as f:
        a.fromfile(f,Path(path).stat().st_size//2)
    if sys.byteorder!="little":
        a.byteswap()
    return a

def envelope(pcm):
    out=[]
    n=(len(pcm)//WIN_SAMPLES)*WIN_SAMPLES
    for i in range(0,n,WIN_SAMPLES):
        ss=0.0
        for v in pcm[i:i+WIN_SAMPLES]:
            fv=float(v)/32768.0
            ss+=fv*fv
        out.append(math.log1p(math.sqrt(ss/WIN_SAMPLES+1e-12)*20.0))
    return out

def corr(a,b):
    if len(a)!=len(b) or len(a)<4:return -2.0
    ma=sum(a)/len(a);mb=sum(b)/len(b)
    va=sum((x-ma)*(x-ma) for x in a)
    vb=sum((x-mb)*(x-mb) for x in b)
    if va<=1e-12 or vb<=1e-12:return -2.0
    num=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    return num/math.sqrt(va*vb)

def verify_local_anchors(qenv,senv,q_duration):
    rows=[]
    w=max(8,int(round(ANCHOR_WINDOW_SEC*ENV_HZ)))
    radius=int(round(ANCHOR_SEARCH_SEC*ENV_HZ))
    half=w//2

    t=10.0
    while t <= q_duration-10.0:
        qc=int(round(t*ENV_HZ))
        qa=max(0,qc-half); qb=min(len(qenv),qa+w)
        qa=max(0,qb-w)
        q=qenv[qa:qb]

        expected=int(round((INITIAL_OFFSET+t)*ENV_HZ))
        best=None
        for sc in range(max(half,expected-radius),min(len(senv)-half,expected+radius)+1):
            sa=sc-half;sb=sa+len(q)
            if sa<0 or sb>len(senv):continue
            c=corr(q,senv[sa:sb])
            if best is None or c>best[0]:
                best=(c,sc)
        if best:
            c,sc=best
            source_center=sc/ENV_HZ
            off=source_center-t
            rows.append(dict(
                query_center_sec=f"{t:.3f}",
                source_center_sec=f"{source_center:.3f}",
                offset_sec=f"{off:.3f}",
                correlation=f"{c:.6f}",
            ))
        t += ANCHOR_STEP_SEC

    strong=[r for r in rows if float(r["correlation"])>=0.35]
    if not strong:
        raise RuntimeError("No strong local audio anchors")

    offsets=sorted(float(r["offset_sec"]) for r in strong)
    median=offsets[len(offsets)//2]
    devs=[abs(x-median) for x in offsets]
    maxdev=max(devs) if devs else 999.0
    span=max(float(r["query_center_sec"]) for r in strong)-min(float(r["query_center_sec"]) for r in strong)

    return rows,strong,median,maxdev,span

def probe_video(path,tag):
    cp=run([
        FFPROBE,"-v","error","-select_streams","v:0",
        "-show_entries","stream=width,height,r_frame_rate,duration,start_time,codec_name",
        "-of","default=nw=1",path
    ],tag,120)
    if cp.returncode!=0:
        raise RuntimeError(f"ffprobe failed: {path}")
    vals={}
    for line in cp.stdout.splitlines():
        if "=" in line:
            k,v=line.split("=",1);vals[k]=v
    return vals

def iso_norm(raw):
    s=raw.decode("ascii",errors="replace")
    if ";" in s:s=s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":
        raise RuntimeError("ISO9660 PVD not found")
    r=p[156:];r=r[:r[0]]
    return struct.unpack_from("<I",r,2)[0],struct.unpack_from("<I",r,10)[0]

def read_dir(f,extent,size):
    base=extent*SECTOR
    f.seek(base);data=f.read(size)
    out=[];pos=0
    while pos<len(data):
        rl=data[pos]
        if rl==0:
            pos=((pos//SECTOR)+1)*SECTOR;continue
        rec=data[pos:pos+rl]
        ext=struct.unpack_from("<I",rec,2)[0]
        sz=struct.unpack_from("<I",rec,10)[0]
        flags=rec[25];nl=rec[32];raw=rec[33:33+nl]
        name="." if raw==b"\0" else ".." if raw==b"\1" else iso_norm(raw)
        out.append(dict(name=name,extent=ext,size=sz,is_dir=bool(flags&2),record_offset=base+pos))
        pos+=rl
    return out

def find_entry(f,parts):
    ext,sz=pvd_root(f);e=None
    for i,p in enumerate(parts):
        m=[x for x in read_dir(f,ext,sz) if x["name"]==p.lower()]
        if not m:raise FileNotFoundError("/"+"/".join(parts[:i+1]))
        e=m[0]
        if i<len(parts)-1:
            ext,sz=e["extent"],e["size"]
    return e

def patch_size(f,record_offset,new_size):
    f.seek(record_offset+10)
    f.write(struct.pack("<I",new_size));f.write(struct.pack(">I",new_size))

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
    h=hashlib.sha256();f.seek(off);remain=size
    while remain:
        b=f.read(min(remain,1024*1024))
        if not b:break
        h.update(b);remain-=len(b)
    if remain:raise RuntimeError("EOF hashing ISO")
    return h.hexdigest()

def main():
    core=load_core()

    for p in (KR_PMF,SRC_VIDEO,BASE_ISO,FFMPEG,FFPROBE):
        if not p.exists():
            raise RuntimeError(f"Missing input/tool: {p}")

    failure=STAGE/"FAILURE.txt"
    if failure.exists():failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05B - Stage37 Koreanized dk101 -> PSP PMF",flush=True)
    print("="*80,flush=True)
    print("Watermark: preserved for this sample.",flush=True)

    # Recover the exact KR audio with the proven parser.
    krp=core.parse_pmf(KR_PMF)
    kra=core.recover_audio(krp)
    if kra["bad_headers"]:
        raise RuntimeError(f"KR audio header errors: {kra['bad_headers']}")

    oma=WORK/"dk101_kr.oma"
    core.build_oma(kra["frames"],oma)

    krpcm_path=WORK/"kr.s16"
    srcpcm_path=WORK/"stage37.s16"
    decode_pcm(oma,krpcm_path,"01_decode_kr_audio.log",True)
    decode_pcm(SRC_VIDEO,srcpcm_path,"02_decode_stage37_audio.log",False)

    krpcm=load_pcm(krpcm_path);srcpcm=load_pcm(srcpcm_path)
    qenv=envelope(krpcm);senv=envelope(srcpcm)
    qdur=len(krpcm)/DECODE_RATE

    anchors,strong,median_off,maxdev,span=verify_local_anchors(qenv,senv,qdur)
    write_tsv(STAGE/"local_audio_anchors.tsv",anchors)

    print(
        f"Local anchors: total={len(anchors)} strong={len(strong)} "
        f"median_offset={median_off:.3f}s maxdev={maxdev:.3f}s span={span:.1f}s",
        flush=True
    )

    # Require evidence across most of the cutscene; isolated music correlation is not enough.
    if len(strong)<5 or span<70.0 or maxdev>0.250:
        raise RuntimeError(
            f"Audio mapping not stable enough: strong={len(strong)}, "
            f"span={span:.1f}, maxdev={maxdev:.3f}"
        )

    # Use median local offset rather than the previous global 0.700 estimate.
    offset=median_off

    krinfo=probe_video(KR_PMF,"03_probe_kr_video.log")
    srcinfo=probe_video(SRC_VIDEO,"04_probe_stage37_video.log")

    try:
        video_dur=float(krinfo.get("duration",""))
    except:
        video_dur=qdur

    if not (1.0 < video_dur < 300.0):
        video_dur=qdur

    print(
        f"KR video duration={video_dur:.3f}s; "
        f"Stage37={srcinfo.get('width')}x{srcinfo.get('height')} "
        f"fps={srcinfo.get('r_frame_rate')}",
        flush=True
    )

    # Create lossless video intermediate. Stage37 is already Koreanized, so no
    # new subtitle rendering is done here.
    burned=WORK/"dk101_stage37_lossless.avi"
    vf="setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,fps=30000/1001,format=yuv420p"
    cp=run([
        FFMPEG,"-y","-v","warning",
        "-ss",f"{offset:.6f}","-i",SRC_VIDEO,
        "-t",f"{video_dur:.6f}",
        "-an","-vf",vf,
        "-c:v","ffv1","-level","3","-pix_fmt","yuv420p",
        "-fps_mode","cfr",burned
    ],"05_cut_scale_lossless.log",2400)
    if cp.returncode!=0 or not burned.exists():
        raise RuntimeError("Stage37 lossless cut failed")

    # Use the bitrate already proven for dk101 in MOV04C.
    avg=1000;maxbr=1550

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05b_raw_mux.ps1"
    if composer is None or mps2pmf is None or not helper.exists():
        raise RuntimeError("PMF tools/helper missing")

    cdir=composer.parent
    local_ffmpeg=cdir/"ffmpeg.exe"
    temp_ffmpeg=False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG,local_ffmpeg);temp_ffmpeg=True

    try:
        vmps=WORK/"video.mps"
        cp=run([
            composer,burned,"-",vmps,
            "--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
            "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"
        ],"06_oMPSComposer_video.log",3000,cwd=cdir)
        if cp.returncode!=0 or not vmps.exists():
            raise RuntimeError("video-only oMPSComposer failed")

        vpmf=WORK/"video_only.pmf"
        whole=int(math.ceil(video_dur));mins,secs=divmod(whole,60)
        cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
               "07_Mps2Pmf_video.log",300,cwd=mps2pmf.parent)
        if cp.returncode!=0 or not vpmf.exists():
            raise RuntimeError("video-only PMF conversion failed")

        h264=WORK/"stage37.264"
        if not core.extract_h264(vpmf,h264,"08_extract_stage37_h264.log"):
            raise RuntimeError("H264 extraction failed")
        expected_video_sha=core.sha_file(h264)

        riff=WORK/"kr_frames.at3"
        core.build_riff(kra["frames"],riff)

        fmps=WORK/"final.mps"
        cp=run([
            "powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
            "-File",helper,
            "-Composer",composer,
            "-H264",h264,
            "-AtracRiff",riff,
            "-OutputMps",fmps
        ],"09_reflection_mux.log",1200)
        if cp.returncode!=0 or not fmps.exists():
            raise RuntimeError("raw ATRAC mux failed")

        patched=core.patch_mps_audio_pts_exact(fmps,krp)

        total_sec=max(video_dur,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
        whole=int(math.ceil(total_sec));mins,secs=divmod(whole,60)
        if FINAL_PMF.exists():FINAL_PMF.unlink()
        cp=run([mps2pmf,"-i",fmps,"-o",FINAL_PMF,"-m",str(mins),"-s",str(secs)],
               "10_Mps2Pmf_final.log",300,cwd=mps2pmf.parent)
        if cp.returncode!=0 or not FINAL_PMF.exists():
            raise RuntimeError("final PMF conversion failed")
    finally:
        if temp_ffmpeg:
            try:local_ffmpeg.unlink()
            except:pass

    # Strict media validation.
    fp=core.parse_pmf(FINAL_PMF)
    fa=core.recover_audio(fp)

    final264=WORK/"final.264"
    if not core.extract_h264(FINAL_PMF,final264,"11_extract_final_h264.log"):
        raise RuntimeError("final H264 extraction failed")

    video_ok=core.sha_file(final264)==expected_video_sha
    logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
    frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
    pes_ok=len(fp["audio"])==len(krp["audio"])
    pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]

    oma2=WORK/"final.oma"
    core.build_oma(fa["frames"],oma2)
    cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
           "12_decode_final_audio.log",600)
    decode_ok=cp.returncode==0

    info=core.probe(FINAL_PMF,"13_probe_final.log")
    vs=core.get_video(info)
    format_ok=bool(vs and vs.get("codec_name")=="h264" and
                   int(vs.get("width",0))==480 and int(vs.get("height",0))==272)

    strict=all([video_ok,logical_ok,frames_ok,pes_ok,pts_ok,decode_ok,format_ok])
    if not strict:
        raise RuntimeError(
            f"Final PMF validation failed: video={video_ok} logical={logical_ok} "
            f"frames={frames_ok} pes={pes_ok} pts={pts_ok} decode={decode_ok} format={format_ok}"
        )

    # Build review frames from the encoded PMF itself.
    for rel in (8.0,35.0,70.0,max(8.0,video_dur-8.0)):
        out=OUT/f"review_dk101_{rel:06.3f}.jpg"
        run([FFMPEG,"-y","-v","error","-ss",f"{rel:.3f}","-i",FINAL_PMF,
             "-frames:v","1","-q:v","2",out],
            f"14_review_{rel:.3f}.log",180)

    # Smoke ISO: preserve original LBA.
    with BASE_ISO.open("rb") as f:
        e=find_entry(f,TARGET_PATH)
        alloc=math.ceil(e["size"]/SECTOR)*SECTOR

    if FINAL_PMF.stat().st_size>alloc:
        raise RuntimeError(
            f"Final Stage37 dk101 exceeds original allocation: "
            f"{FINAL_PMF.stat().st_size}>{alloc}"
        )

    if SMOKE_ISO.exists():SMOKE_ISO.unlink()
    shutil.copyfile(BASE_ISO,SMOKE_ISO)

    payload=FINAL_PMF.read_bytes()
    with SMOKE_ISO.open("r+b") as f:
        e2=find_entry(f,TARGET_PATH)
        f.seek(e2["extent"]*SECTOR);f.write(payload)
        remain=alloc-len(payload)
        block=b"\x00"*min(32768,max(1,remain))
        while remain>0:
            n=min(remain,len(block));f.write(block[:n]);remain-=n
        patch_size(f,e2["record_offset"],len(payload))

    expected_sha=sha_file(FINAL_PMF)
    with SMOKE_ISO.open("rb") as f:
        ve=find_entry(f,TARGET_PATH)
        embedded_sha=sha_region(f,ve["extent"]*SECTOR,ve["size"])

    iso_ok=(ve["extent"]==e["extent"] and ve["size"]==len(payload) and embedded_sha==expected_sha)
    if not iso_ok:
        raise RuntimeError("Smoke ISO verification failed")

    result=[dict(
        source=str(SRC_VIDEO),
        chosen_offset_sec=f"{offset:.6f}",
        strong_anchor_count=len(strong),
        anchor_span_sec=f"{span:.3f}",
        anchor_max_offset_deviation_sec=f"{maxdev:.6f}",
        kr_video_duration_sec=f"{video_dur:.6f}",
        final_pmf=str(FINAL_PMF),
        final_pmf_bytes=FINAL_PMF.stat().st_size,
        original_dk101_allocation_bytes=alloc,
        spare_bytes=alloc-FINAL_PMF.stat().st_size,
        h264_equal_encoded_video="YES" if video_ok else "NO",
        logical_752_equal_kr="YES" if logical_ok else "NO",
        frames_744_equal_kr="YES" if frames_ok else "NO",
        audio_pes_equal_kr="YES" if pes_ok else "NO",
        audio_pts_equal_kr="YES" if pts_ok else "NO",
        atrac_decode="PASS" if decode_ok else "FAIL",
        video_format="PASS" if format_ok else "FAIL",
        smoke_iso=str(SMOKE_ISO),
        iso_sha_match="YES" if iso_ok else "NO",
        watermark_policy="PRESERVED",
        status="PASS",
    )]
    write_tsv(STAGE/"mov05b_result.tsv",result)

    summary=[
        "Naruto PSP MOV05B - Stage37 Koreanized dk101 final sample",
        "="*80,"",
        "RESULT=PASS","",
        f"Stage37 source={SRC_VIDEO}",
        f"Chosen source offset={offset:.6f}s",
        f"Strong local anchors={len(strong)}",
        f"Anchor span={span:.3f}s",
        f"Max strong-anchor offset deviation={maxdev:.6f}s","",
        "Final media:",
        "  video = Stage37 Koreanized visual",
        "  audio = exact KR Japanese ATRAC3+",
        "  PTS   = exact KR audio PTS",
        "  watermark = preserved for this first runtime sample","",
        f"Final PMF={FINAL_PMF}",
        f"Smoke ISO={SMOKE_ISO}","",
        "After wrapper success, this ISO should be auto-launched in PPSSPP.",
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
