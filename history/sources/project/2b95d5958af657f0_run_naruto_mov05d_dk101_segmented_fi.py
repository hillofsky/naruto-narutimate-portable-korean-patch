#!/usr/bin/env python3
# Naruto PSP MOV05D
#
# Final dk101 segmented reconstruction.
#
# MOV05C/MOV05C FIX1 established:
#
# KR segment 1: 0.000 .. 6.990
#   Stage37 audio match start = 0.705
#
# KR segment 2: 6.990 .. 67.951
#   Stage37 audio match start = 7.689
#
# KR segment 3: 67.951 .. 72.539
#   duration = 4.588 sec
#   Japanese production credits on black.
#   Stage37 has NO trustworthy equivalent segment.
#   -> generate a Korean localized production-credit card at exact KR duration.
#
# KR segment 4: 72.539 .. 116.249
#   Stage37 audio match start = 69.545
#
# Key rule:
#   each Stage37 segment is trimmed independently to the exact KR segment duration.
#   No pixels beyond that segment's approved end are ever copied.
#
# Final audio:
#   exact KR Japanese ATRAC3+ frames and exact KR PTS.

from __future__ import annotations
import csv, importlib.util, math, os, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(r"PROJECT_ROOT")
CORE_PATH=ROOT/"mov05d_proven_movie_core.py"

KR_PMF=ROOT/"kr_extracted"/"PSP_GAME"/"USRDIR"/"movie"/"dk101.pmf"
SRC_VIDEO=ROOT/"analysis"/"stage37"/"video"/"source_video.mp4"

BASE_ISO=ROOT/"analysis"/"mov"/"mov03t_iso_install"/"output"/"Naruto_KR_MOV03S_KoreanMovies.iso"
if not BASE_ISO.exists():
    BASE_ISO=ROOT/"kr"/"Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"

STAGE=ROOT/"analysis"/"mov"/"mov05d_dk101_segmented_final"
WORK=STAGE/"work"
OUT=STAGE/"output"
LOGD=STAGE/"logs"
FONTD=STAGE/"fonts"
for p in (STAGE,WORK,OUT,LOGD,FONTD):
    p.mkdir(parents=True,exist_ok=True)

FINAL_PMF=OUT/"dk101_stage37_segmented_KOvideo_KRJPaudio.pmf"
SMOKE_ISO=OUT/"Naruto_KR_MOV05D_dk101_segmented_smoketest.iso"

FFMPEG=Path(r"LOCAL_PATH")
FFPROBE=Path(r"LOCAL_PATH")

SECTOR=2048
TARGET=["PSP_GAME","USRDIR","movie","dk101.pmf"]

SEGMENTS=[
    dict(id=1,kind="stage37",kr_start=0.000,kr_end=6.990,src_start=0.705),
    dict(id=2,kind="stage37",kr_start=6.990,kr_end=67.951,src_start=7.689),
    dict(id=3,kind="generated",kr_start=67.951,kr_end=72.539,src_start=None),
    dict(id=4,kind="stage37",kr_start=72.539,kr_end=116.249,src_start=69.545),
]

def load_core():
    spec=importlib.util.spec_from_file_location("mov05d_core",CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load proven PMF core")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STAGE=STAGE;m.WORK=WORK;m.OUT=OUT;m.LOGD=LOGD;m.FONTD=FONTD
    return m

def run(cmd,logname,timeout=3000,cwd=None):
    cp=subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
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
        w.writeheader();w.writerows(rows)

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration",
            "-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def make_credit_ass(path,duration):
    # Black-card production credits corresponding to KR segment 3:
    # 制作: CyberConnect2 / ARTDINK
    # 製作: BANDAI
    #
    # Keep a simple centered credit style. Fade matches the original card's
    # observed fade-in/fade-out behavior without relying on YouTube pixels.
    end=max(0.5,duration-0.12)
    def ass_time(sec):
        h=int(sec//3600);sec-=h*3600
        m=int(sec//60);sec-=m*60
        return f"{h}:{m:02d}:{sec:05.2f}"
    txt=f"""[Script Info]
ScriptType: v4.00+
PlayResX: 480
PlayResY: 272
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Credit,Malgun Gothic,17,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0.8,0,5,20,20,18,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,{ass_time(0.12)},{ass_time(end)},Credit,,0,0,0,,{{\\fad(420,520)}}－ 제작 －\\N주식회사 사이버커넥트2\\N주식회사 아트딩크\\N\\N－ 제작 －\\N주식회사 반다이
"""
    Path(path).write_text(txt,encoding="utf-8-sig")

def build_segment3(duration,out):
    ass=WORK/"segment3_ko.ass"
    make_credit_ass(ass,duration)

    # Use relative paths so libass handles the project path more reliably.
    rel_ass=os.path.relpath(ass,STAGE).replace("\\","/")
    vf=f"ass=filename='{rel_ass}'"
    cp=run([
        FFMPEG,"-y","-v","warning",
        "-f","lavfi","-i",f"color=c=black:s=480x272:r=30000/1001:d={duration:.6f}",
        "-an","-vf",vf,
        "-c:v","ffv1","-level","3","-pix_fmt","yuv420p",
        "-fps_mode","cfr",out
    ],"01_build_segment3_credits.log",600,cwd=STAGE)
    if cp.returncode!=0 or not Path(out).exists():
        raise RuntimeError("Korean production-credit segment generation failed")
    return ass

def build_segmented_lossless(seg3,out):
    s1=SEGMENTS[0];s2=SEGMENTS[1];s4=SEGMENTS[3]
    d1=s1["kr_end"]-s1["kr_start"]
    d2=s2["kr_end"]-s2["kr_start"]
    d4=s4["kr_end"]-s4["kr_start"]

    e1=s1["src_start"]+d1
    e2=s2["src_start"]+d2
    e4=s4["src_start"]+d4

    # Independent trims are the critical change.
    # No Stage37 pixels between 68.650 and 69.545 are used.
    # No Stage37 pixels after 113.255 are used.
    filt=(
      f"[0:v]trim=start={s1['src_start']:.6f}:end={e1:.6f},"
      f"setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,fps=30000/1001,setsar=1[v1];"
      f"[0:v]trim=start={s2['src_start']:.6f}:end={e2:.6f},"
      f"setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,fps=30000/1001,setsar=1[v2];"
      f"[1:v]setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,fps=30000/1001,setsar=1[v3];"
      f"[0:v]trim=start={s4['src_start']:.6f}:end={e4:.6f},"
      f"setpts=PTS-STARTPTS,scale=480:272:flags=lanczos,fps=30000/1001,setsar=1[v4];"
      f"[v1][v2][v3][v4]concat=n=4:v=1:a=0,format=yuv420p[v]"
    )

    cp=run([
        FFMPEG,"-y","-v","warning",
        "-i",SRC_VIDEO,
        "-i",seg3,
        "-filter_complex",filt,
        "-map","[v]","-an",
        "-c:v","ffv1","-level","3","-pix_fmt","yuv420p",
        "-fps_mode","cfr",out
    ],"02_build_segmented_lossless.log",3000)
    if cp.returncode!=0 or not Path(out).exists():
        raise RuntimeError("Segmented Stage37 video build failed")

    rows=[]
    for s in SEGMENTS:
        d=s["kr_end"]-s["kr_start"]
        row=dict(
            segment=s["id"],kind=s["kind"],
            kr_start_sec=f"{s['kr_start']:.3f}",
            kr_end_sec=f"{s['kr_end']:.3f}",
            duration_sec=f"{d:.3f}",
        )
        if s["src_start"] is not None:
            row["source_start_sec"]=f"{s['src_start']:.3f}"
            row["source_end_sec"]=f"{s['src_start']+d:.3f}"
        else:
            row["source_start_sec"]="GENERATED"
            row["source_end_sec"]="GENERATED"
        rows.append(row)
    write_tsv(STAGE/"segment_recipe.tsv",rows)

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

def read_dir(f,ext,size):
    base=ext*SECTOR;f.seek(base);data=f.read(size);out=[];pos=0
    while pos<len(data):
        rl=data[pos]
        if rl==0:
            pos=((pos//SECTOR)+1)*SECTOR
            continue
        rec=data[pos:pos+rl]
        ex=struct.unpack_from("<I",rec,2)[0]
        sz=struct.unpack_from("<I",rec,10)[0]
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
        if i<len(parts)-1:
            ext,sz=e["extent"],e["size"]
    return e

def patch_size(f,off,new):
    f.seek(off+10)
    f.write(struct.pack("<I",new))
    f.write(struct.pack(">I",new))

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
    if remain:raise RuntimeError("EOF while hashing ISO")
    return h.hexdigest()

def extract_review(pmf,t,label):
    out=OUT/f"review_{label}_{t:08.3f}.jpg"
    run([FFMPEG,"-y","-v","error","-ss",f"{max(0,t):.3f}","-i",pmf,
         "-frames:v","1","-q:v","2",out],
        f"review_{label}.log",180)

def main():
    core=load_core()

    for p in (CORE_PATH,KR_PMF,SRC_VIDEO,BASE_ISO,FFMPEG,FFPROBE):
        if not p.exists():
            raise RuntimeError(f"Missing input/tool: {p}")

    fail=STAGE/"FAILURE.txt"
    if fail.exists():fail.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05D - dk101 segmented final reconstruction",flush=True)
    print("="*80,flush=True)
    print("No global timeline. Each internal video is cut independently.",flush=True)

    # Exact KR audio recovery.
    krp=core.parse_pmf(KR_PMF)
    kra=core.recover_audio(krp)
    if kra["bad_headers"]:
        raise RuntimeError(f"KR AU header validation failed: {kra['bad_headers']}")

    # Segment 3 generated locally at exact KR duration.
    seg3dur=SEGMENTS[2]["kr_end"]-SEGMENTS[2]["kr_start"]
    seg3=WORK/"segment3_korean_credits.avi"
    ass=build_segment3(seg3dur,seg3)

    # Four independent visual pieces.
    lossless=WORK/"dk101_segmented_lossless.avi"
    build_segmented_lossless(seg3,lossless)

    target_dur=SEGMENTS[-1]["kr_end"]
    actual_dur=probe_duration(lossless,"03_segmented_duration.log")
    print(f"Visual duration target={target_dur:.3f}s actual={actual_dur}",flush=True)
    if actual_dur is None or abs(actual_dur-target_dur)>0.20:
        raise RuntimeError(f"Segmented video duration mismatch: {actual_dur} vs {target_dur}")

    composer=core.find_exe("oMPSComposer.exe")
    mps2pmf=core.find_exe("Mps2Pmf.exe")
    helper=ROOT/"invoke_naruto_mov05d_raw_mux.ps1"
    if composer is None or mps2pmf is None or not helper.exists():
        raise RuntimeError("PMF tools/helper missing")

    # Use original MOV03T dk101 entry to retain its original allocation.
    with BASE_ISO.open("rb") as f:
        base_entry=find_entry(f,TARGET)
        allocation=math.ceil(base_entry["size"]/SECTOR)*SECTOR

    cdir=composer.parent
    local_ffmpeg=cdir/"ffmpeg.exe"
    temp_ffmpeg=False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG,local_ffmpeg)
        temp_ffmpeg=True

    chosen=None
    try:
        riff=WORK/"kr_frames.at3"
        core.build_riff(kra["frames"],riff)

        # Highest quality first.
        attempts=[(1000,1550),(975,1500),(950,1450),(925,1400),(900,1350)]
        for idx,(avg,maxbr) in enumerate(attempts,1):
            tag=f"try{idx}_{avg}"
            print(f"[encode {idx}/{len(attempts)}] avg={avg} max={maxbr}",flush=True)

            vmps=WORK/f"{tag}_video.mps"
            cp=run([
                composer,lossless,"-",vmps,
                "--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
                "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"
            ],f"04_{tag}_video.log",3000,cwd=cdir)
            if cp.returncode!=0 or not vmps.exists():
                continue

            vpmf=WORK/f"{tag}_video.pmf"
            whole=int(math.ceil(target_dur));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",vmps,"-o",vpmf,"-m",str(mins),"-s",str(secs)],
                   f"05_{tag}_vpmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not vpmf.exists():
                continue

            h264=WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"06_{tag}_extract_h264.log"):
                continue
            expected_vsha=core.sha_file(h264)

            fmps=WORK/f"{tag}_final.mps"
            cp=run([
                "powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
                "-File",helper,
                "-Composer",composer,
                "-H264",h264,
                "-AtracRiff",riff,
                "-OutputMps",fmps
            ],f"07_{tag}_mux.log",1200)
            if cp.returncode!=0 or not fmps.exists():
                continue

            core.patch_mps_audio_pts_exact(fmps,krp)

            cand=WORK/f"{tag}_final.pmf"
            total=max(target_dur,kra["frame_count"]*core.SAMPLES_PER_FRAME/core.SAMPLE_RATE)
            whole=int(math.ceil(total));mins,secs=divmod(whole,60)
            cp=run([mps2pmf,"-i",fmps,"-o",cand,"-m",str(mins),"-s",str(secs)],
                   f"08_{tag}_final_pmf.log",300,cwd=mps2pmf.parent)
            if cp.returncode!=0 or not cand.exists():
                continue

            # Strict validation.
            fp=core.parse_pmf(cand)
            fa=core.recover_audio(fp)
            f264=WORK/f"{tag}_final.264"
            if not core.extract_h264(cand,f264,f"09_{tag}_final_h264.log"):
                continue

            video_ok=core.sha_file(f264)==expected_vsha
            logical_ok=core.sha_bytes(fa["logical"])==core.sha_bytes(kra["logical"])
            frames_ok=core.sha_bytes(fa["frames"])==core.sha_bytes(kra["frames"])
            pes_ok=len(fp["audio"])==len(krp["audio"])
            pts_ok=[x["pts"] for x in fp["audio"]]==[x["pts"] for x in krp["audio"]]

            oma2=WORK/f"{tag}.oma"
            core.build_oma(fa["frames"],oma2)
            cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma2,"-f","null","-"],
                   f"10_{tag}_audio_decode.log",600)
            decode_ok=cp.returncode==0

            info=core.probe(cand,f"11_{tag}_probe.log")
            vs=core.get_video(info)
            format_ok=bool(vs and vs.get("codec_name")=="h264" and
                           int(vs.get("width",0))==480 and int(vs.get("height",0))==272)

            strict=all([video_ok,logical_ok,frames_ok,pes_ok,pts_ok,decode_ok,format_ok])
            fits=cand.stat().st_size<=allocation
            print(
                f"  bytes={cand.stat().st_size} allocation={allocation} "
                f"strict={strict} fit={fits}",
                flush=True
            )

            if strict and fits:
                shutil.copy2(cand,FINAL_PMF)
                chosen=dict(
                    avg=avg,maxbr=maxbr,size=cand.stat().st_size,
                    video_ok=video_ok,logical_ok=logical_ok,frames_ok=frames_ok,
                    pes_ok=pes_ok,pts_ok=pts_ok,decode_ok=decode_ok,format_ok=format_ok
                )
                break
    finally:
        if temp_ffmpeg:
            try:local_ffmpeg.unlink()
            except:pass

    if chosen is None:
        raise RuntimeError("No strict-valid segmented dk101 PMF fit original allocation")

    # Review: every independent boundary, plus late section.
    for t,label in [
        (2.0,"seg1"),
        (6.85,"seg1_end"),
        (7.20,"seg2_start"),
        (35.0,"seg2_mid"),
        (67.80,"seg2_end"),
        (68.50,"seg3_credit_start"),
        (70.20,"seg3_credit_mid"),
        (72.35,"seg3_credit_end"),
        (72.80,"seg4_start"),
        (88.0,"seg4_early"),
        (100.0,"seg4_mid"),
        (115.5,"seg4_end"),
    ]:
        extract_review(FINAL_PMF,t,label)

    # Build smoke ISO.
    if SMOKE_ISO.exists():
        SMOKE_ISO.unlink()
    shutil.copyfile(BASE_ISO,SMOKE_ISO)
    payload=FINAL_PMF.read_bytes()

    with SMOKE_ISO.open("r+b") as f:
        e=find_entry(f,TARGET)
        f.seek(e["extent"]*SECTOR)
        f.write(payload)
        remain=allocation-len(payload)
        block=b"\0"*min(32768,max(1,remain))
        while remain>0:
            n=min(remain,len(block))
            f.write(block[:n])
            remain-=n
        patch_size(f,e["record_offset"],len(payload))

    expected=sha_file(FINAL_PMF)
    with SMOKE_ISO.open("rb") as f:
        e=find_entry(f,TARGET)
        actual=sha_region(f,e["extent"]*SECTOR,e["size"])
        iso_ok=(
            e["extent"]==base_entry["extent"]
            and e["size"]==len(payload)
            and actual==expected
        )
    if not iso_ok:
        raise RuntimeError("Smoke ISO verification failed")

    result=[dict(
        source_model="INDEPENDENT_4_SEGMENTS",
        segment3_policy="GENERATED_KOREAN_PRODUCTION_CREDITS",
        encoded_avg_kbps=chosen["avg"],
        encoded_max_kbps=chosen["maxbr"],
        final_pmf_bytes=chosen["size"],
        allocation_bytes=allocation,
        spare_bytes=allocation-chosen["size"],
        h264_equal_encoded_video="YES" if chosen["video_ok"] else "NO",
        logical_752_equal_kr="YES" if chosen["logical_ok"] else "NO",
        frames_744_equal_kr="YES" if chosen["frames_ok"] else "NO",
        audio_pes_equal_kr="YES" if chosen["pes_ok"] else "NO",
        audio_pts_equal_kr="YES" if chosen["pts_ok"] else "NO",
        atrac_decode="PASS" if chosen["decode_ok"] else "FAIL",
        video_format="PASS" if chosen["format_ok"] else "FAIL",
        iso_sha_match="YES",
        final_pmf=str(FINAL_PMF),
        smoke_iso=str(SMOKE_ISO),
        status="PASS"
    )]
    write_tsv(STAGE/"mov05d_result.tsv",result)

    summary=[
        "Naruto PSP MOV05D - dk101 independently segmented final",
        "="*80,"",
        "RESULT=PASS","",
        "Visual recipe:",
        "  segment 1 KR 0.000..6.990     <- Stage37 0.705..7.695",
        "  segment 2 KR 6.990..67.951    <- Stage37 7.689..68.650",
        "  segment 3 KR 67.951..72.539   <- generated Korean production credits",
        "  segment 4 KR 72.539..116.249  <- Stage37 69.545..113.255","",
        "Critical behavior:",
        "  No global/piecewise offset interpolation.",
        "  No time stretching.",
        "  No Stage37 pixels after each approved segment end.",
        "  Stage37 transition/outro pixels between segment 2 and 4 are discarded.","",
        "Audio:",
        "  exact KR Japanese ATRAC3+ frames",
        "  exact KR audio PES count",
        "  exact KR PTS sequence","",
        f"Final PMF={FINAL_PMF}",
        f"Smoke ISO={SMOKE_ISO}",
        f"Final PMF bytes={chosen['size']}",
        f"Original allocation={allocation}",
        f"Spare bytes={allocation-chosen['size']}",
        "",
        "Wrapper will launch PPSSPP from the user's fixed PPSSPP folder."
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
