#!/usr/bin/env python3
# Naruto PSP MOV03S FIX1 - FINAL batch dm001..dm010
#
# Final target for each DM movie:
#   video    = US dmXXXe.pmf clean visual + Korean burned subtitles
#   timing   = MOV03N FIX5 KR timeline
#   audio    = KR dmXXX original Japanese ATRAC3+ frames
#   audio PTS= KR original PTS restored packet-by-packet
#
# No US/English audio is used.
# No ATRAC re-encoding.
# No at3tool.
#
# Pipeline:
#   US clean video -> burn Korean ASS -> lossless FFV1
#   -> oMPSComposer video-only -> Mps2Pmf -> extract PSP H264
#   KR PMF -> exact 744-byte ATRAC3+ frames
#   -> oMPSComposer internal AtracReader + MpsMuxer via reflection
#   -> patch generated audio PES PTS bytes to KR original exact PTS bytes
#   -> Mps2Pmf -> FINAL PMF
#
# Strict per-movie validation:
#   final H264 SHA256 == subtitle-video H264 SHA256
#   final 752-byte logical AU SHA256 == KR
#   final 744-byte ATRAC frame SHA256 == KR
#   final audio PTS sequence == KR exactly
#   final audio PES count == KR
#   ATRAC decode test == PASS
#   480x272 H.264 video present

from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

SCRIPT_VERSION = "MOV04C_REMAINING5_FINAL_BUILDER"

ROOT = Path(r"D:\narutimate portable")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"
ASS_DIR = ROOT / "mov04c_ass"

STAGE = ROOT / "analysis" / "mov" / "mov04c_final_batch"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"C:\ffmpeg1\ffmpeg.exe")
FFPROBE = Path(r"C:\ffmpeg1\ffprobe.exe")

DM = ["da101","da201","dk101","dk102","dk202"]

LOGICAL_AU = 752
ATRAC_FRAME = 744
AU_HEADER = bytes.fromhex("0FD0285C00000000")
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 2048
EA3_HEADER_SIZE = 96

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def run(cmd,logname,timeout=2400,cwd=None):
    cp=subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",
        timeout=timeout
    )
    txt="COMMAND:\n"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODE:\n"+str(cp.returncode)
    txt+="\n\nSTDOUT:\n"+cp.stdout+"\n\nSTDERR:\n"+cp.stderr+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def find_exe(name):
    preferred=[
        ROOT/name,
        ROOT/"tools"/name,
        ROOT/"tools"/"pmftools-plus"/"release"/"tools"/name,
        ROOT/"pmftools-plus"/name,
    ]
    for p in preferred:
        if p.exists():return p
    for base,dirs,files in os.walk(ROOT):
        rel=str(Path(base).relative_to(ROOT)).lower()
        if any(x in rel for x in [r"logs\old",r"analysis\stage37\video"]):
            dirs[:]=[]
            continue
        for f in files:
            if f.lower()==name.lower():
                return Path(base)/f
    return None

def choose_font():
    cands=[
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path(r"C:\Windows\Fonts\malgunbd.ttf"),
        Path(r"C:\Windows\Fonts\gulim.ttc"),
        Path(r"C:\Windows\Fonts\batang.ttc"),
    ]
    for p in cands:
        if p.exists():
            dst=FONTD/p.name
            shutil.copy2(p,dst)
            return p,dst
    raise RuntimeError("Korean font not found")

def us_source(name):
    e=US_MOV/(name+"e.pmf")
    if e.exists():return e
    p=US_MOV/(name+".pmf")
    return p if p.exists() else None

def parse_srt_time(t):
    h,m,rest=t.split(":")
    s,ms=rest.split(",")
    return int(h)*3600+int(m)*60+int(s)+int(ms)/1000.0

def ass_time(sec):
    cs=int(round(sec*100))
    h,rem=divmod(cs,360000)
    m,rem=divmod(rem,6000)
    s,cs=divmod(rem,100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def wrap_ko(text,target=27):
    text=text.strip()
    if len(text)<=target:return text
    words=text.split(" ")
    if len(words)==1:
        cut=len(text)//2
        return text[:cut]+r"\N"+text[cut:]
    lines=[];cur=""
    for w in words:
        cand=w if not cur else cur+" "+w
        if len(cand)<=target or not cur:
            cur=cand
        else:
            lines.append(cur);cur=w
    if cur:lines.append(cur)
    if len(lines)>2:
        joined=" ".join(words)
        mid=len(joined)//2
        split=joined.rfind(" ",0,mid+3)
        if split<max(1,mid-8):
            split=joined.find(" ",mid)
        if split>0:lines=[joined[:split],joined[split+1:]]
    return r"\N".join(lines[:2])

def srt_to_ass(srt_path,ass_path):
    txt=Path(srt_path).read_text(encoding="utf-8-sig",errors="replace")
    blocks=re.split(r"\r?\n\r?\n+",txt.strip())
    events=[]
    for b in blocks:
        ls=b.splitlines()
        if len(ls)<3 or " --> " not in ls[1]:continue
        a,z=ls[1].split(" --> ",1)
        st=parse_srt_time(a.strip());en=parse_srt_time(z.strip())
        text=" ".join(x.strip() for x in ls[2:] if x.strip())
        text=text.replace("{",r"\{").replace("}",r"\}")
        text=wrap_ko(text)
        events.append((st,en,text))

    header=r"""[Script Info]
Title: Naruto Korean DM subtitle
ScriptType: v4.00+
PlayResX: 480
PlayResY: 272
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Malgun Gothic,16,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1.4,0,2,16,16,3,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines=[header.rstrip()]
    for st,en,text in events:
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Default,,0,0,0,,{text}")
    Path(ass_path).write_text("\n".join(lines)+"\n",encoding="utf-8-sig")
    return events

def parse_pts5(b):
    if len(b)<5:return None
    return ((b[0]&0x0E)<<29)|(b[1]<<22)|((b[2]&0xFE)<<14)|(b[3]<<7)|((b[4]&0xFE)>>1)

def parse_ps_stream(data,start_offset=0):
    pos=start_offset;n=len(data)
    audio=[];video=[];counts=Counter()
    while pos+6<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0:break
            pos=nxt;continue

        sid=data[pos+3];counts[sid]+=1

        if sid==0xBA:
            if pos+14>n:break
            pos += 14+(data[pos+13]&7)
            continue
        if sid==0xB9:
            pos+=4;continue

        plen=(data[pos+4]<<8)|data[pos+5]
        if plen==0:
            nxt=data.find(b"\x00\x00\x01\xBA",pos+6)
            if nxt<0:break
            pos=nxt;continue
        end=pos+6+plen
        if end>n:break

        if 0xE0<=sid<=0xEF:
            video.append(dict(start=pos,end=end,sid=sid))

        if sid==0xBD:
            p=pos+6;payload=p;pts=None;pts_off=None;pts_bytes=None
            if p+3<=end and (data[p]&0xC0)==0x80:
                flags2=data[p+1];hlen=data[p+2]
                if (flags2&0x80) and p+8<=end:
                    pts_off=p+3
                    pts_bytes=data[p+3:p+8]
                    pts=parse_pts5(pts_bytes)
                payload=p+3+hlen
            else:
                q=p
                while q<end and data[q]==0xFF:q+=1
                if q+2<=end and (data[q]&0xC0)==0x40:q+=2
                if q<end and (data[q]&0xF0) in (0x20,0x30):
                    pts_off=q
                    pts_bytes=data[q:q+5]
                    pts=parse_pts5(pts_bytes)
                    q+=5 if (data[q]&0xF0)==0x20 else 10
                elif q<end and data[q]==0x0F:q+=1
                payload=q

            subid=data[payload] if payload<end else None
            locator=struct.unpack_from(">H",data,payload+2)[0] if payload+4<=end else None
            audio.append(dict(
                start=pos,end=end,payload=payload,payload_len=end-payload,
                pts=pts,pts_off=pts_off,pts_bytes=pts_bytes,
                subid=subid,locator=locator
            ))
        pos=end
    return dict(audio=audio,video=video,counts=counts)

def parse_pmf(path):
    data=Path(path).read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError(f"{Path(path).name}: not PSMF")
    off=struct.unpack_from(">I",data,8)[0]
    ps=parse_ps_stream(data,off)
    ps.update(data=data,off=off,path=Path(path))
    return ps

def recover_audio(parsed):
    logical=bytearray()
    for p in parsed["audio"]:
        private=parsed["data"][p["payload"]:p["end"]]
        if len(private)>=4 and private[0]<0x10:
            logical+=private[4:]
    logical=bytes(logical)
    if len(logical)%LOGICAL_AU:
        raise RuntimeError(f"logical audio size {len(logical)} not divisible by 752")
    frames=bytearray();bad=0
    for i in range(0,len(logical),LOGICAL_AU):
        au=logical[i:i+LOGICAL_AU]
        if au[:8]!=AU_HEADER:bad+=1
        frames+=au[8:]
    frames=bytes(frames)
    if len(frames)%ATRAC_FRAME:
        raise RuntimeError("ATRAC frame bytes not divisible by 744")
    return dict(logical=logical,frames=frames,
                frame_count=len(frames)//ATRAC_FRAME,bad_headers=bad)

def build_riff(frames,path):
    channels=2
    seconds=(len(frames)//ATRAC_FRAME)*SAMPLES_PER_FRAME/SAMPLE_RATE
    avg_bps=int(len(frames)/seconds) if seconds>0 else 0
    fmt=struct.pack("<HHIIHHH",0xFFFE,channels,SAMPLE_RATE,avg_bps,ATRAC_FRAME,0,0)
    fact=struct.pack("<I",(len(frames)//ATRAC_FRAME)*SAMPLES_PER_FRAME)
    def chunk(tag,body):
        return tag+struct.pack("<I",len(body))+body+(b"\x00" if len(body)&1 else b"")
    body=b"WAVE"+chunk(b"fmt ",fmt)+chunk(b"fact",fact)+chunk(b"data",frames)
    Path(path).write_bytes(b"RIFF"+struct.pack("<I",len(body))+body)

def build_oma(frames,path):
    size_code=ATRAC_FRAME//8-1
    params=(1<<13)|(2<<10)|size_code
    def syncsafe(n):
        return bytes([(n>>21)&0x7F,(n>>14)&0x7F,(n>>7)&0x7F,n&0x7F])
    out=bytearray()
    out+=b"ea3"+bytes([3,0,0])+syncsafe(0)
    ea3=bytearray(EA3_HEADER_SIZE)
    ea3[0:4]=b"EA3\x00";ea3[5]=EA3_HEADER_SIZE
    ea3[6:8]=struct.pack("<H",0xFFFF)
    ea3[32:36]=struct.pack(">I",(1<<24)|params)
    out+=ea3;out+=frames
    Path(path).write_bytes(out)

def patch_mps_audio_pts_exact(mps_path,kr_parsed):
    """
    Restore the generated MPS audio PTS sequence to the KR original exactly.

    Normal case:
      generated PTS exists + KR PTS exists
        -> copy the exact 5 encoded PTS bytes from KR.

    Tail-PES case seen in dm003/dm004/dm006/dm010:
      generated PTS exists + KR PTS is absent
        -> keep PES/header length and payload offset unchanged
        -> clear MPEG-2 PTS_DTS_flags
        -> turn the former PTS/DTS bytes into 0xFF header stuffing

    This preserves packet size and ATRAC payload bytes while making the parsed
    PTS value exactly None, matching the KR original tail packet.
    """
    data=bytearray(Path(mps_path).read_bytes())
    gen=parse_ps_stream(data,0)
    ka=kr_parsed["audio"];ga=gen["audio"]

    if len(ga)!=len(ka):
        raise RuntimeError(
            f"generated/KR audio PES count mismatch {len(ga)}/{len(ka)}"
        )

    patched=0
    removed=0

    for i,(g,k) in enumerate(zip(ga,ka)):
        # KR has an explicit PTS: generated packet must also have room for one.
        if k["pts_bytes"] is not None:
            if g["pts_off"] is None:
                raise RuntimeError(
                    f"PES {i}: KR has PTS but generated PES has no PTS field"
                )
            data[g["pts_off"]:g["pts_off"]+5]=k["pts_bytes"]
            patched+=1
            continue

        # KR has no PTS and generated also has no PTS: already exact.
        if g["pts_off"] is None:
            continue

        # KR has no PTS but generated MpsMuxer emitted one.
        # MpsMuxer output is MPEG-2 PES. Remove only the timestamp semantic,
        # not any bytes, so the audio payload starts at exactly the same offset.
        p=g["start"]+6
        if p+3>len(data) or (data[p]&0xC0)!=0x80:
            raise RuntimeError(
                f"PES {i}: cannot safely remove generated PTS "
                f"(not MPEG-2 PES header)"
            )

        flags2=data[p+1]
        pts_dts_flags=flags2&0xC0
        hlen=data[p+2]

        if pts_dts_flags==0x80:
            stuff_len=5
        elif pts_dts_flags==0xC0:
            stuff_len=10
        else:
            raise RuntimeError(
                f"PES {i}: parser reported PTS but PTS_DTS_flags="
                f"0x{pts_dts_flags:02X}"
            )

        if hlen<stuff_len or p+3+stuff_len>g["end"]:
            raise RuntimeError(
                f"PES {i}: invalid generated PES header length "
                f"hlen={hlen}, need={stuff_len}"
            )

        # Clear PTS_DTS_flags while preserving all unrelated PES flags.
        data[p+1]=flags2&0x3F

        # MPEG-2 PES header stuffing bytes are 0xFF. Header-data-length remains
        # unchanged, therefore payload offset and packet length are unchanged.
        data[p+3:p+3+stuff_len]=b"\xFF"*stuff_len
        removed+=1

    Path(mps_path).write_bytes(data)

    verify=parse_ps_stream(bytes(data),0)
    vp=[x["pts"] for x in verify["audio"]]
    kp=[x["pts"] for x in ka]

    if len(vp)!=len(kp):
        raise RuntimeError(
            f"PTS verify count mismatch {len(vp)}/{len(kp)}"
        )
    if vp!=kp:
        diffs=[i for i,(a,b) in enumerate(zip(vp,kp)) if a!=b]
        raise RuntimeError(
            f"PTS patch verify failed at {diffs[:10]}"
        )

    return patched+removed

def extract_h264(src,out,log):
    if Path(out).exists():Path(out).unlink()
    cp=run([FFMPEG,"-y","-v","warning","-i",src,
            "-map","0:v:0","-an","-c:v","copy","-f","h264",out],log,300)
    return cp.returncode==0 and Path(out).exists() and Path(out).stat().st_size>0

def probe(path,name):
    cp=run([FFPROBE,"-v","error","-show_streams","-show_format","-of","json",path],name,120)
    if cp.returncode!=0:return None
    try:return json.loads(cp.stdout)
    except:return None

def get_duration(info):
    if not info:return None
    for s in info.get("streams",[]):
        try:
            if s.get("duration") not in (None,"","N/A"):
                return float(s["duration"])
        except:pass
    try:return float(info.get("format",{}).get("duration"))
    except:return None

def get_video(info):
    if not info:return None
    for s in info.get("streams",[]):
        if s.get("codec_type")=="video":return s
    return None

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("ffmpeg/ffprobe missing")

    composer=find_exe("oMPSComposer.exe")
    mps2pmf=find_exe("Mps2Pmf.exe")
    if composer is None or mps2pmf is None:
        raise RuntimeError("oMPSComposer.exe / Mps2Pmf.exe not found")

    helper=ROOT/"invoke_naruto_mov04c_raw_mux.ps1"
    if not helper.exists():
        raise RuntimeError("MOV04C reflection helper missing")

    _,font_copy=choose_font()

    # oMPSComposer video-only needs ffmpeg beside it.
    cdir=composer.parent
    local_ffmpeg=cdir/"ffmpeg.exe"
    temp_ffmpeg=False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG,local_ffmpeg)
        temp_ffmpeg=True

    print("="*80,flush=True)
    print(" Naruto PSP MOV04C - FINAL batch DA/DK translated movies",flush=True)
    print(f" Script version: {SCRIPT_VERSION}",flush=True)
    print("="*80,flush=True)
    print("Audio: KR original Japanese ATRAC3+ only",flush=True)
    print("Audio PTS: restored to KR exact values",flush=True)

    results=[]
    all_ok=True

    try:
        for num,name in enumerate(DM,1):
            print(f"[{num:02d}/05] {name}",flush=True)
            row=dict(movie=name)
            movie_work=WORK/name
            shutil.rmtree(movie_work,ignore_errors=True)
            movie_work.mkdir(parents=True,exist_ok=True)

            try:
                kr=KR_MOV/(name+".pmf")
                us=us_source(name)
                ass_src=ASS_DIR/(name+"_ko.ass")
                if not kr.exists():raise RuntimeError("KR PMF missing")
                if us is None:raise RuntimeError("US clean PMF missing")
                if not ass_src.exists():raise RuntimeError("Korean ASS missing")

                krp=parse_pmf(kr)
                kra=recover_audio(krp)
                if kra["bad_headers"]:
                    raise RuntimeError(f"unexpected KR AU headers: {kra['bad_headers']}")

                ass=movie_work/(name+".ass")
                shutil.copy2(ass_src,ass)
                events=[
                    ln for ln in ass.read_text(encoding="utf-8-sig",errors="replace").splitlines()
                    if ln.startswith("Dialogue:")
                ]

                # Measure clean source video bitrate.
                us264=movie_work/(name+"_us.264")
                if not extract_h264(us,us264,f"{name}_01_extract_us_h264.log"):
                    raise RuntimeError("US H264 extraction failed")
                ui=probe(us,f"{name}_02_probe_us.log")
                ud=get_duration(ui)
                if not ud:raise RuntimeError("US duration unavailable")
                kbps=us264.stat().st_size*8/ud/1000.0
                avg=max(500,min(3500,int(round(kbps/50.0)*50)))
                maxbr=min(4700,int(round(max(avg+500,avg*1.55)/50.0)*50))
                if maxbr<=avg:maxbr=min(4700,avg+500)

                # Burn subtitles losslessly.
                burned=movie_work/(name+"_burned.avi")
                rel_ass=os.path.relpath(ass,STAGE).replace("\\","/")
                rel_fonts=os.path.relpath(FONTD,STAGE).replace("\\","/")
                vf=f"setpts=PTS-STARTPTS,ass=filename='{rel_ass}':fontsdir='{rel_fonts}'"
                cp=run([FFMPEG,"-y","-v","warning","-i",us,"-an",
                        "-vf",vf,"-c:v","ffv1","-level","3","-pix_fmt","yuv420p",
                        "-fps_mode","cfr",burned],
                       f"{name}_03_burn.log",1800,cwd=STAGE)
                if cp.returncode!=0 or not burned.exists():
                    raise RuntimeError("subtitle burn failed")

                bi=probe(burned,f"{name}_04_probe_burned.log")
                bd=get_duration(bi)
                if not bd:raise RuntimeError("burned duration unavailable")

                # Video-only PSP MPS then PMF (proven MOV03Q route).
                v_mps=movie_work/(name+"_video.mps")
                cp=run([composer,burned,"-",v_mps,
                        "--avg-bitrate",str(avg),"--max-bitrate",str(maxbr),
                        "--encode-mode","2pass","--idr-duration","2000","--m-frames","1"],
                       f"{name}_05_oMPSComposer_video.log",3000,cwd=cdir)
                if cp.returncode!=0 or not v_mps.exists():
                    raise RuntimeError("oMPSComposer video-only failed")

                v_pmf=movie_work/(name+"_video_only.pmf")
                whole=int(math.ceil(bd));mins,secs=divmod(whole,60)
                cp=run([mps2pmf,"-i",v_mps,"-o",v_pmf,"-m",str(mins),"-s",str(secs)],
                       f"{name}_06_Mps2Pmf_video.log",300,cwd=mps2pmf.parent)
                if cp.returncode!=0 or not v_pmf.exists():
                    raise RuntimeError("video-only Mps2Pmf failed")

                sub264=movie_work/(name+"_KOsub.264")
                if not extract_h264(v_pmf,sub264,f"{name}_07_extract_sub_h264.log"):
                    raise RuntimeError("subtitle H264 extraction failed")
                sub_sha=sha_file(sub264)

                # Original KR ATRAC frames -> AtracReader RIFF.
                riff=movie_work/(name+"_KR_frames.at3")
                build_riff(kra["frames"],riff)

                final_mps=movie_work/(name+"_final.mps")
                cp=run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
                        "-File",helper,
                        "-Composer",composer,
                        "-H264",sub264,
                        "-AtracRiff",riff,
                        "-OutputMps",final_mps],
                       f"{name}_08_reflection_mux.log",1200)
                if cp.returncode!=0 or not final_mps.exists():
                    raise RuntimeError("raw ATRAC reflection mux failed")

                # Restore exact KR audio PTS before PMF conversion.
                patched_pts=patch_mps_audio_pts_exact(final_mps,krp)

                final=OUT/(name+".pmf")
                if final.exists():final.unlink()
                total_sec=max(
                    bd,
                    kra["frame_count"]*SAMPLES_PER_FRAME/SAMPLE_RATE
                )
                whole=int(math.ceil(total_sec));mins,secs=divmod(whole,60)
                cp=run([mps2pmf,"-i",final_mps,"-o",final,"-m",str(mins),"-s",str(secs)],
                       f"{name}_09_Mps2Pmf_final.log",300,cwd=mps2pmf.parent)
                if cp.returncode!=0 or not final.exists():
                    raise RuntimeError("final Mps2Pmf failed")

                fp=parse_pmf(final)
                fa=recover_audio(fp)

                # Strict binary validation.
                final264=movie_work/(name+"_final.264")
                if not extract_h264(final,final264,f"{name}_10_extract_final_h264.log"):
                    raise RuntimeError("final H264 extraction failed")

                video_ok=(sha_file(final264)==sub_sha)
                logical_ok=(sha_bytes(fa["logical"])==sha_bytes(kra["logical"]))
                frames_ok=(sha_bytes(fa["frames"])==sha_bytes(kra["frames"]))
                pes_count_ok=(len(fp["audio"])==len(krp["audio"]))
                kr_pts=[x["pts"] for x in krp["audio"]]
                fi_pts=[x["pts"] for x in fp["audio"]]
                pts_ok=(kr_pts==fi_pts)

                # Decoder check without storing WAV.
                oma=movie_work/(name+".oma")
                build_oma(fa["frames"],oma)
                cp=run([FFMPEG,"-v","warning","-f","oma","-i",oma,"-f","null","-"],
                       f"{name}_11_decode_audio.log",600)
                decode_ok=(cp.returncode==0)

                info=probe(final,f"{name}_12_probe_final.log")
                vs=get_video(info)
                video_format_ok=bool(
                    vs and vs.get("codec_name")=="h264" and
                    int(vs.get("width",0))==480 and int(vs.get("height",0))==272
                )

                ok=all([video_ok,logical_ok,frames_ok,pes_count_ok,pts_ok,decode_ok,video_format_ok])

                row.update(
                    subtitle_count=len(events),
                    us_source=str(us),
                    kr_source=str(kr),
                    final_pmf=str(final),
                    final_bytes=final.stat().st_size,
                    source_video_kbps=f"{kbps:.3f}",
                    encode_avg_kbps=avg,
                    encode_max_kbps=maxbr,
                    kr_audio_pes=len(krp["audio"]),
                    final_audio_pes=len(fp["audio"]),
                    audio_pes_count_equal="YES" if pes_count_ok else "NO",
                    kr_atrac_frames=kra["frame_count"],
                    final_atrac_frames=fa["frame_count"],
                    h264_equal_subtitle_video="YES" if video_ok else "NO",
                    logical_752_equal_kr="YES" if logical_ok else "NO",
                    frames_744_equal_kr="YES" if frames_ok else "NO",
                    audio_pts_equal_kr="YES" if pts_ok else "NO",
                    pts_fields_patched=patched_pts,
                    atrac_decode="PASS" if decode_ok else "FAIL",
                    video_format="PASS" if video_format_ok else "FAIL",
                    status="PASS" if ok else "FAIL",
                )
                results.append(row)

                print(
                    f"  subs={len(events)} audioPES={len(fp['audio'])} "
                    f"frames={fa['frame_count']} "
                    f"video={'OK' if video_ok else 'BAD'} "
                    f"audio={'OK' if frames_ok else 'BAD'} "
                    f"PTS={'EXACT' if pts_ok else 'BAD'} "
                    f"=> {'PASS' if ok else 'FAIL'}",
                    flush=True
                )

                if not ok:
                    all_ok=False

            except Exception as e:
                all_ok=False
                row["status"]="FAIL"
                row["error"]=str(e)
                results.append(row)
                print(f"  FAIL: {e}",flush=True)

            finally:
                # Keep only compact diagnostics and final PMF.
                shutil.rmtree(movie_work,ignore_errors=True)

    finally:
        if temp_ffmpeg:
            try:local_ffmpeg.unlink()
            except:pass

    write_tsv(STAGE/"final_batch_results.tsv",results)

    passed=sum(1 for r in results if r.get("status")=="PASS")
    failed=sum(1 for r in results if r.get("status")=="FAIL")
    exact_pts=sum(1 for r in results if r.get("audio_pts_equal_kr")=="YES")

    summary=[
        "Naruto PSP MOV04C - FINAL batch DA/DK translated movies",
        "="*80,"",
        f"PASS={passed}/5",
        f"FAIL={failed}/5",
        f"Exact KR audio PTS={exact_pts}/5",
        "",
        "Final architecture:",
        "  visual = US localized clean movie + Korean burned subtitle",
        "  subtitle timing = MOV04B reviewed KR timeline",
        "  audio = KR original Japanese ATRAC3+ frames",
        "  audio PTS = KR original exact values",
        "",
        "Validation required per movie:",
        "  final H264 == generated Korean-subtitle PSP H264",
        "  final 752-byte AU stream == KR",
        "  final 744-byte ATRAC3+ frames == KR",
        "  final audio PES count == KR",
        "  final audio PTS sequence == KR",
        "  ATRAC decode PASS",
        "  H264 480x272 PASS",
        "",
        f"FINAL BATCH RESULT={'PASS' if passed==5 and failed==0 else 'FAIL'}",
        f"Output folder: {OUT}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0 if passed==5 and failed==0 else 2

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
