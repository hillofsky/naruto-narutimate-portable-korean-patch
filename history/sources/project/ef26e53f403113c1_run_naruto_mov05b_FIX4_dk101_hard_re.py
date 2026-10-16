#!/usr/bin/env python3
# Naruto PSP MOV05B FIX4
#
# FIX2 proved:
#   first section  : Stage37 = KR + 0.700 sec
#   later section  : Stage37 = KR + 0.250 sec
#
# FIX2 incorrectly stretched a whole 14-second section.
# FIX3 treats the 0.450-second offset change as a discrete edit between videos:
#
#   video 1: normal speed, +0.700 sec mapping
#   edit gap: 0.450 sec frame hold
#   video 2+: normal speed, +0.250 sec mapping
#
# The actual source scene cut is detected automatically and scored using
# Japanese-audio correlation immediately before and after the cut.
#
# Final audio remains exact KR Japanese ATRAC3+ with exact KR PTS.

from __future__ import annotations
import array, csv, importlib.util, math, re, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05b_proven_movie_core.py"
KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"
BASE_ISO=ROOT/"analysis"/"mov"/"mov03t_iso_install"/"output"/"Naruto_KR_MOV03S_KoreanMovies.iso"

STAGE=ROOT/"analysis"/"mov"/"mov05b_fix4_dk101_hard_reset"
WORK=STAGE/"work"; OUT=STAGE/"output"; LOGD=STAGE/"logs"; FONTD=STAGE/"fonts"
for p in (STAGE,WORK,OUT,LOGD,FONTD): p.mkdir(parents=True,exist_ok=True)

FINAL_PMF=OUT/"dk101_stage37_KOvideo_KRJPaudio_hardreset.pmf"
SMOKE_ISO=OUT/"Naruto_KR_MOV05B_FIX4_dk101_stage37_smoketest.iso"

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

RATE=8000
ENV_HZ=20.0
WIN=int(RATE/ENV_HZ)

EARLY_OFF=0.700
LATE_OFF=0.250
GAP=EARLY_OFF-LATE_OFF

SEARCH_SOURCE_START=64.0
SEARCH_SOURCE_END=86.0

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

def exact_corr(qenv,senv,qcenter,window,offset):
    half=int(round(window*ENV_HZ/2))
    qc=int(round(qcenter*ENV_HZ))
    sc=int(round((qcenter+offset)*ENV_HZ))
    qa=qc-half; qb=qc+half; sa=sc-half; sb=sc+half
    if qa<0 or qb>len(qenv) or sa<0 or sb>len(senv):return -2.0
    return corr(qenv[qa:qb],senv[sa:sb])

def detect_scene_candidates():
    start=SEARCH_SOURCE_START
    dur=SEARCH_SOURCE_END-SEARCH_SOURCE_START
    candidates=[]

    # Hard scene cuts.
    cp=run([
        FFMPEG,"-hide_banner","-v","info",
        "-ss",f"{start:.3f}","-t",f"{dur:.3f}","-i",SRC_VIDEO,
        "-an","-vf","select='gt(scene,0.10)',showinfo",
        "-f","null","-"
    ],"03_scene_detect.log",300)

    for line in cp.stderr.splitlines():
        m=re.search(r"pts_time:([0-9.]+)",line)
        if not m:continue
        t=float(m.group(1))
        # With input -ss ffmpeg normally reports relative timestamps here.
        if t < dur+3:
            t += start
        if SEARCH_SOURCE_START<=t<=SEARCH_SOURCE_END:
            candidates.append((round(t,3),"scene"))

    # Black transition boundaries are also useful candidates.
    cp=run([
        FFMPEG,"-hide_banner","-v","info",
        "-ss",f"{start:.3f}","-t",f"{dur:.3f}","-i",SRC_VIDEO,
        "-an","-vf","blackdetect=d=0.04:pix_th=0.10",
        "-f","null","-"
    ],"04_black_detect.log",300)
    for line in cp.stderr.splitlines():
        for key in ("black_start","black_end"):
            m=re.search(key+r":([0-9.]+)",line)
            if not m:continue
            t=float(m.group(1))
            if t < dur+3:t+=start
            if SEARCH_SOURCE_START<=t<=SEARCH_SOURCE_END:
                candidates.append((round(t,3),key))

    # De-duplicate nearby visual boundaries.
    candidates.sort()
    merged=[]
    for t,kind in candidates:
        if merged and abs(t-merged[-1][0])<=0.10:
            merged[-1]=(merged[-1][0],merged[-1][1]+"+"+kind)
        else:
            merged.append((t,kind))

    # Fallback: if scene detection returned nothing, use a coarse source grid.
    if not merged:
        t=SEARCH_SOURCE_START
        while t<=SEARCH_SOURCE_END:
            merged.append((round(t,3),"grid"))
            t+=0.25

    return merged

def score_cut_candidates(candidates,qenv,senv):
    """
    Score a candidate boundary using only stable audio far away from the
    edited/credit region.

    Before boundary:
      sample 12/16/20 sec earlier under EARLY_OFF (+0.700)

    After boundary:
      sample 10/14/18 sec later under LATE_OFF (+0.250)

    This intentionally ignores the several seconds immediately surrounding
    the visual boundary because Stage37 has localized/edited credits there.
    """
    rows=[]
    for source_cut,kind in candidates:
        q_before=source_cut-EARLY_OFF
        q_after=source_cut-LATE_OFF

        early_vals=[]
        for d in (12.0,16.0,20.0):
            early_vals.append(exact_corr(
                qenv,senv,q_before-d,4.0,EARLY_OFF
            ))

        late_vals=[]
        for d in (10.0,14.0,18.0):
            late_vals.append(exact_corr(
                qenv,senv,q_after+d,4.0,LATE_OFF
            ))

        # Drop invalid edge checks if any.
        early_valid=[x for x in early_vals if x>-1.5]
        late_valid=[x for x in late_vals if x>-1.5]
        if not early_valid or not late_valid:
            continue

        early=sum(early_valid)/len(early_valid)
        late=sum(late_valid)/len(late_valid)
        early_min=min(early_valid)
        late_min=min(late_valid)

        # Require both sides. Score also rewards a visually later boundary
        # when correlations are otherwise nearly tied, because the known
        # +0.250 late mapping becomes reliable around KR ~88-94 sec.
        minimum=min(early,late)
        combined=(
            minimum
            + 0.18*(early+late)
            + 0.08*(early_min+late_min)
            + 0.0015*(source_cut-SEARCH_SOURCE_START)
        )

        rows.append(dict(
            source_cut_sec=f"{source_cut:.3f}",
            kind=kind,
            kr_before_end_sec=f"{q_before:.3f}",
            kr_after_start_sec=f"{q_after:.3f}",
            inserted_hold_sec=f"{GAP:.3f}",
            early_corr=f"{early:.6f}",
            early_min_corr=f"{early_min:.6f}",
            late_corr=f"{late:.6f}",
            late_min_corr=f"{late_min:.6f}",
            score=f"{combined:.6f}",
        ))

    rows.sort(key=lambda r:float(r["score"]),reverse=True)
    if not rows:
        raise RuntimeError("No visual transition candidates could be scored")

    best=rows[0]

    if float(best["early_corr"])<0.70:
        raise RuntimeError(
            "No candidate has convincing stable early audio. "
            f"best={best}"
        )
    if float(best["late_corr"])<0.45:
        raise RuntimeError(
            "No candidate has convincing stable late audio. "
            f"best={best}"
        )

    return rows,best

def probe_duration(p,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",p],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def build_hardreset_lossless(source_cut,qdur,out):
    q_before=source_cut-EARLY_OFF
    q_after=source_cut-LATE_OFF
    source_end=qdur+LATE_OFF

    if q_before<=1 or q_after>=qdur-1:
        raise RuntimeError("Detected cut outside usable KR timeline")

    # No time stretching.
    #
    # First section maps with +0.700 sec.
    # Later section maps with +0.250 sec.
    # Therefore Stage37 is 0.450 sec shorter at the edit boundary.
    #
    # Extend the LAST FRAME of section 1 by exactly 0.450 sec. This is less
    # visually intrusive than inserting a new black frame and keeps the
    # second video's first frame at the exact late-audio position.
    filt=(
      f"[0:v]trim=start={EARLY_OFF:.6f}:end={source_cut:.6f},"
      f"setpts=PTS-STARTPTS,"
      f"scale=480:272:flags=lanczos,fps=30000/1001,setsar=1,"
      f"tpad=stop_mode=clone:stop_duration={GAP:.6f}[v0];"
      f"[0:v]trim=start={source_cut:.6f}:end={source_end:.6f},"
      f"setpts=PTS-STARTPTS,"
      f"scale=480:272:flags=lanczos,fps=30000/1001,setsar=1[v2];"
      f"[v0][v2]concat=n=2:v=1:a=0,format=yuv420p[v]"
    )

    cp=run([FFMPEG,"-y","-v","warning","-i",SRC_VIDEO,
            "-filter_complex",filt,"-map","[v]","-an",
            "-c:v","ffv1","-level","3","-pix_fmt","yuv420p",
            "-fps_mode","cfr",out],
           "05_hardreset_lossless.log")
    if cp.returncode!=0 or not Path(out).exists():
        raise RuntimeError("Hard-reset video reconstruction failed")

    return q_before,q_after

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

    failure=STAGE/"FAILURE.txt"
    if failure.exists():failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05B FIX4 - hard reset between Stage37 videos",flush=True)
    print("="*80,flush=True)
    print(f"Early offset={EARLY_OFF:+.3f}s  Late offset={LATE_OFF:+.3f}s  Gap={GAP:.3f}s",flush=True)

    krp=core.parse_pmf(KR_PMF);kra=core.recover_audio(krp)
    if kra["bad_headers"]:raise RuntimeError("KR AU header validation failed")

    oma=WORK/"kr.oma";core.build_oma(kra["frames"],oma)
    kp=WORK/"kr.s16";sp=WORK/"src.s16"
    decode_pcm(oma,kp,"01_decode_kr.log",True)
    decode_pcm(SRC_VIDEO,sp,"02_decode_stage37.log",False)
    qenv=envelope(load_pcm(kp));senv=envelope(load_pcm(sp))

    candidates=detect_scene_candidates()
    scored,best=score_cut_candidates(candidates,qenv,senv)
    write_tsv(STAGE/"scene_cut_candidates.tsv",scored)

    source_cut=float(best["source_cut_sec"])
    print(
        f"Chosen source cut={source_cut:.3f}s ({best['kind']}) "
        f"early_corr={best['early_corr']} late_corr={best['late_corr']}",
        flush=True
    )

    qvideo=probe_duration(KR_PMF,"06_kr_duration.log")
    if qvideo is None or not (1<qvideo<300):
        qvideo=len(qenv)/ENV_HZ

    lossless=WORK/"hardreset.avi"
    q_before,q_after=build_hardreset_lossless(source_cut,qvideo,lossless)

    outdur=probe_duration(lossless,"07_hardreset_duration.log")
    if outdur is None or abs(outdur-qvideo)>0.20:
        raise RuntimeError(f"Hard-reset output duration mismatch: {outdur} vs {qvideo}")

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05b_FIX4_raw_mux.ps1"
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
                   f"08_{tag}_video.log",cwd=cdir)
            if cp.returncode!=0 or not vmps.exists():continue

            vpmf=WORK/f"{tag}_v.pmf";whole=int(math.ceil(qvideo));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
                   f"09_{tag}_vpmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not vpmf.exists():continue

            h264=WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"10_{tag}_h264.log"):continue
            vsha=core.sha_file(h264)

            fmps=WORK/f"{tag}_final.mps"
            cp=run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",helper,
                    "-Composer",composer,"-H264",h264,"-AtracRiff",riff,"-OutputMps",fmps],
                   f"11_{tag}_mux.log",1200)
            if cp.returncode!=0 or not fmps.exists():continue

            core.patch_mps_audio_pts_exact(fmps,krp)

            cand=WORK/f"{tag}_final.pmf"
            total=max(qvideo,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
            whole=int(math.ceil(total));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",fmps,"-o",cand,"-m",str(mins),"-s",str(secs)],
                   f"12_{tag}_final.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not cand.exists():continue

            fp=core.parse_pmf(cand);fa=core.recover_audio(fp)
            f264=WORK/f"{tag}_final.264"
            if not core.extract_h264(cand,f264,f"13_{tag}_extract.log"):continue

            video_ok=core.sha_file(f264)==vsha
            logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
            frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
            pes_ok=len(fp["audio"])==len(krp["audio"])
            pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]

            oma2=WORK/f"{tag}.oma";core.build_oma(fa["frames"],oma2)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
                   f"14_{tag}_decode.log",600)
            decode_ok=cp.returncode==0

            info=core.probe(cand,f"15_{tag}_probe.log");vs=core.get_video(info)
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

    if chosen is None:raise RuntimeError("No strict-valid PMF fit original dk101 allocation")

    # Review around the actual reset point and later dialogue.
    review_times=[
        8.0,35.0,
        max(0,q_before-1.0),q_before+0.10,
        q_after-0.10,min(qvideo-1,q_after+1.0),
        90.0,max(1,qvideo-8)
    ]
    for t in sorted(set(round(x,3) for x in review_times if 0<=x<qvideo)):
        out=OUT/f"review_{t:07.3f}.jpg"
        run([FFMPEG,"-y","-v","error","-ss",f"{t:.3f}","-i",FINAL_PMF,
             "-frames:v","1","-q:v","2",out],f"16_review_{t:.3f}.log",180)

    # Smoke ISO
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
        early_offset_sec=f"{EARLY_OFF:.6f}",
        late_offset_sec=f"{LATE_OFF:.6f}",
        inserted_hold_sec=f"{GAP:.6f}",
        chosen_source_cut_sec=f"{source_cut:.6f}",
        kr_video1_end_sec=f"{q_before:.6f}",
        kr_video2_start_sec=f"{q_after:.6f}",
        chosen_cut_kind=best["kind"],
        cut_early_corr=best["early_corr"],
        cut_late_corr=best["late_corr"],
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
        status="PASS",
    )]
    write_tsv(STAGE/"mov05b_fix4_result.tsv",result)

    summary=[
        "Naruto PSP MOV05B FIX4 - hard reset between Stage37 videos","="*80,"",
        "RESULT=PASS","",
        f"Early mapping={EARLY_OFF:+.3f}s",
        f"Late mapping={LATE_OFF:+.3f}s",
        f"Detected source video boundary={source_cut:.3f}s ({best['kind']})",
        f"KR video1 ends={q_before:.3f}s",
        f"Inserted transition={GAP:.3f}s",
        f"KR video2 starts={q_after:.3f}s","",
        "No time stretching is used.",
        "The 0.450 sec timeline difference is inserted as a frame hold only at the detected video boundary.","",
        "Video=Stage37 Koreanized visual",
        "Audio=exact KR Japanese ATRAC3+",
        "PTS=exact KR audio PTS",
        "Watermark=preserved for this sample","",
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
