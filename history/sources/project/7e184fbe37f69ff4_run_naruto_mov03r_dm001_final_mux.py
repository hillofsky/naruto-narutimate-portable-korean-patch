#!/usr/bin/env python3
# Naruto PSP MOV03R - dm001 FINAL PMF raw-ATRAC mux smoke test
#
# Inputs:
#   Video : MOV03Q dm001_KOsub_video_only.pmf
#   Audio : KR dm001.pmf original embedded ATRAC3+ frames
#
# No at3tool.
# No audio re-encoding.
#
# Strategy:
#   1) Extract PSP H.264 from MOV03Q video-only PMF
#   2) Recover exact 744-byte ATRAC3+ frames from KR dm001
#   3) Wrap those frames in a minimal RIFF container that AtracReader.Open()
#      accepts; AtracReader itself reinserts the 8-byte PSP AU header
#   4) Load oMPSComposer.exe as a .NET assembly and invoke its internal:
#        AtracReader.Open()
#        MpsMuxer.Mux()
#      via PowerShell reflection
#   5) Mps2Pmf converts the resulting audio+video MPS to PMF
#
# Validation:
#   - final H264 elementary stream == MOV03Q H264 SHA256
#   - final recovered 744-byte ATRAC frames == KR SHA256
#   - final recovered 752-byte logical AU stream == KR SHA256
#   - ATRAC decode passes
#   - audio PTS sequence compared to KR
#   - final PMF has both video and 0xBD audio PES
#
# Final audio remains Japanese (KR edition original).

from __future__ import annotations
import csv, hashlib, json, math, os, shutil, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"

Q_STAGE = ROOT / "analysis" / "mov" / "mov03q_dm001_subtitle_video"
VIDEO_ONLY_PMF = Q_STAGE / "output" / "dm001_KOsub_video_only.pmf"

STAGE = ROOT / "analysis" / "mov" / "mov03r_dm001_final_mux"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, OUT, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

LOGICAL_AU = 752
ATRAC_FRAME = 744
AU_HEADER = bytes.fromhex("0FD0285C00000000")
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 2048

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

def run(cmd,logname,timeout=1800,cwd=None,env=None):
    cp=subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",
        timeout=timeout
    )
    text="COMMANLOCAL_PATH"+" ".join(('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd)
    text+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    text+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOGD/logname).write_text(text,encoding="utf-8-sig")
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

def parse_pts5(b):
    if len(b)<5:return None
    return ((b[0]&0x0E)<<29)|(b[1]<<22)|((b[2]&0xFE)<<14)|(b[3]<<7)|((b[4]&0xFE)>>1)

def parse_pmf(path):
    data=Path(path).read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError(f"{Path(path).name}: not PSMF")
    off=struct.unpack_from(">I",data,8)[0]
    pos=off;n=len(data)
    audio=[];video=[];counts=Counter()

    while pos+6<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0:break
            pos=nxt;continue

        sid=data[pos+3]
        counts[sid]+=1

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
            video.append(dict(start=pos,end=end))

        if sid==0xBD:
            p=pos+6
            payload=p
            pts=None
            if p+3<=end and (data[p]&0xC0)==0x80:
                flags2=data[p+1]
                hlen=data[p+2]
                if (flags2&0x80) and p+8<=end:
                    pts=parse_pts5(data[p+3:p+8])
                payload=p+3+hlen
            else:
                q=p
                while q<end and data[q]==0xFF:q+=1
                if q+2<=end and (data[q]&0xC0)==0x40:q+=2
                if q<end and (data[q]&0xF0) in (0x20,0x30):
                    pts=parse_pts5(data[q:q+5])
                    q+=5 if (data[q]&0xF0)==0x20 else 10
                elif q<end and data[q]==0x0F:
                    q+=1
                payload=q

            subid=data[payload] if payload<end else None
            locator=struct.unpack_from(">H",data,payload+2)[0] if payload+4<=end else None
            audio.append(dict(
                start=pos,end=end,payload=payload,
                payload_len=end-payload,pts=pts,
                subid=subid,locator=locator
            ))
        pos=end

    return dict(path=Path(path),data=data,off=off,audio=audio,video=video,counts=counts)

def recover_audio(parsed):
    logical=bytearray()
    for p in parsed["audio"]:
        private=parsed["data"][p["payload"]:p["end"]]
        if len(private)>=4 and private[0]<0x10:
            logical += private[4:]

    logical=bytes(logical)
    if len(logical)%LOGICAL_AU:
        raise RuntimeError(
            f"{parsed['path'].name}: logical audio length {len(logical)} "
            f"not divisible by {LOGICAL_AU}"
        )

    frames=bytearray()
    bad_headers=0
    for i in range(0,len(logical),LOGICAL_AU):
        au=logical[i:i+LOGICAL_AU]
        if au[:8]!=AU_HEADER:
            bad_headers+=1
        frames += au[8:]

    frames=bytes(frames)
    if len(frames)%ATRAC_FRAME:
        raise RuntimeError("ATRAC frame byte length not divisible by 744")

    return dict(
        logical=logical,
        frames=frames,
        frame_count=len(frames)//ATRAC_FRAME,
        bad_au_headers=bad_headers
    )

def build_riff_for_atrac_reader(frames,path):
    """
    AtracReader.Open() only needs:
      RIFF/WAVE
      fmt chunk with sampleRate at +4 and blockAlign at +12
      fact chunk (marks this as standard ATRAC3+ data)
      data chunk with raw 744-byte frames

    AtracReader then inserts the canonical 8-byte PSP AU header itself.
    """
    channels=2
    avg_bps=int(len(frames) / max(1, (len(frames)//ATRAC_FRAME)*SAMPLES_PER_FRAME/SAMPLE_RATE))

    fmt=struct.pack(
        "<HHIIHHH",
        0xFFFE,       # extensible-ish tag; parser does not require a specific tag
        channels,
        SAMPLE_RATE,
        avg_bps,
        ATRAC_FRAME,
        0,
        0
    )
    fact=struct.pack("<I",(len(frames)//ATRAC_FRAME)*SAMPLES_PER_FRAME)

    def chunk(tag,body):
        pad=b"\x00" if len(body)&1 else b""
        return tag+struct.pack("<I",len(body))+body+pad

    body=b"WAVE"+chunk(b"fmt ",fmt)+chunk(b"fact",fact)+chunk(b"data",frames)
    riff=b"RIFF"+struct.pack("<I",len(body))+body
    Path(path).write_bytes(riff)

def build_oma(frames,path):
    # Same proven MOV03K wrapper for decode verification.
    size_code=ATRAC_FRAME//8-1
    params=(1<<13)|(2<<10)|size_code
    def syncsafe(n):
        return bytes([(n>>21)&0x7F,(n>>14)&0x7F,(n>>7)&0x7F,n&0x7F])
    out=bytearray()
    out+=b"ea3"+bytes([3,0,0])+syncsafe(0)
    ea3=bytearray(96)
    ea3[0:4]=b"EA3\x00"
    ea3[4]=0
    ea3[5]=96
    ea3[6:8]=struct.pack("<H",0xFFFF)
    ea3[32:36]=struct.pack(">I",(1<<24)|params)
    out+=ea3
    out+=frames
    Path(path).write_bytes(out)

def extract_h264(pmf,out,log):
    if Path(out).exists():Path(out).unlink()
    cp=run(
        [FFMPEG,"-y","-v","warning","-i",pmf,
         "-map","0:v:0","-an","-c:v","copy","-f","h264",out],
        log,300
    )
    return cp.returncode==0 and Path(out).exists() and Path(out).stat().st_size>0

def probe(path,name):
    cp=run([FFPROBE,"-v","error","-show_streams","-show_format","-of","json",path],name,120)
    if cp.returncode!=0:return None
    try:return json.loads(cp.stdout)
    except:return None

def stream(info,kind):
    if not info:return None
    for s in info.get("streams",[]):
        if s.get("codec_type")==kind:return s
    return None

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("ffmpeg/ffprobe missing")
    if not VIDEO_ONLY_PMF.exists():
        raise RuntimeError(
            f"MOV03Q video-only PMF missing: {VIDEO_ONLY_PMF}\n"
            "Run MOV03Q successfully first."
        )

    kr=KR_MOV/"dm001.pmf"
    if not kr.exists():
        raise RuntimeError("KR dm001.pmf missing")

    composer=find_exe("oMPSComposer.exe")
    mps2pmf=find_exe("Mps2Pmf.exe")
    if composer is None:
        raise RuntimeError("oMPSComposer.exe not found")
    if mps2pmf is None:
        raise RuntimeError("Mps2Pmf.exe not found")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03R - dm001 FINAL raw-ATRAC mux smoke test",flush=True)
    print("="*80,flush=True)
    print("Video : MOV03Q Korean-subtitle PSP H.264",flush=True)
    print("Audio : KR original Japanese ATRAC3+ frames",flush=True)
    print("at3tool: NOT USED",flush=True)

    krp=parse_pmf(kr)
    kra=recover_audio(krp)
    if kra["bad_au_headers"]:
        raise RuntimeError(f"KR audio has {kra['bad_au_headers']} unexpected AU headers")

    raw_riff=WORK/"dm001_KR_original_frames_for_AtracReader.at3"
    build_riff_for_atrac_reader(kra["frames"],raw_riff)

    # PSP H264 from the subtitle-burned video-only PMF.
    h264=WORK/"dm001_KOsub.264"
    if not extract_h264(VIDEO_ONLY_PMF,h264,"01_extract_MOV03Q_h264.log"):
        raise RuntimeError("MOV03Q H264 extraction failed")
    source_h264_sha=sha_file(h264)

    # Reflection helper packaged with the stage.
    helper=ROOT/"invoke_naruto_mov03r_raw_mux.ps1"
    if not helper.exists():
        raise RuntimeError(f"Reflection helper missing: {helper}")

    mps=WORK/"dm001_KOsub_KR-JP-original.mps"
    if mps.exists():mps.unlink()

    cp=run(
        [
            "powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
            "-File",helper,
            "-Composer",composer,
            "-H264",h264,
            "-AtracRiff",raw_riff,
            "-OutputMps",mps
        ],
        "02_reflection_MpsMuxer.log",900
    )
    if cp.returncode!=0 or not mps.exists():
        raise RuntimeError("Reflection MpsMuxer failed")

    # Convert MPS with audio to PMF.
    # Use 54 sec to cover the 53.7s audio tail/header duration.
    final_pmf=OUT/"dm001_KOsub_KR-JP-original_FINAL_TEST.pmf"
    if final_pmf.exists():final_pmf.unlink()
    cp=run(
        [mps2pmf,"-i",mps,"-o",final_pmf,"-m","0","-s","54"],
        "03_Mps2Pmf_final.log",300,cwd=mps2pmf.parent
    )
    if cp.returncode!=0 or not final_pmf.exists():
        raise RuntimeError("Mps2Pmf final conversion failed")

    fp=parse_pmf(final_pmf)
    fa=recover_audio(fp)

    # Final video elementary stream must equal MOV03Q video stream.
    final264=WORK/"dm001_final.264"
    if not extract_h264(final_pmf,final264,"04_extract_final_h264.log"):
        raise RuntimeError("Final H264 extraction failed")
    final_h264_sha=sha_file(final264)

    # Audio bit-exact validations.
    kr_logical_sha=sha_bytes(kra["logical"])
    final_logical_sha=sha_bytes(fa["logical"])
    kr_frame_sha=sha_bytes(kra["frames"])
    final_frame_sha=sha_bytes(fa["frames"])

    h264_ok=(source_h264_sha==final_h264_sha)
    logical_ok=(kr_logical_sha==final_logical_sha)
    frames_ok=(kr_frame_sha==final_frame_sha)

    # Audio PTS comparison.
    kr_pts=[p["pts"] for p in krp["audio"] if p["pts"] is not None]
    final_pts=[p["pts"] for p in fp["audio"] if p["pts"] is not None]
    pts_rows=[]
    max_abs_delta=None
    equal_pts=0
    for i in range(max(len(kr_pts),len(final_pts))):
        a=kr_pts[i] if i<len(kr_pts) else None
        b=final_pts[i] if i<len(final_pts) else None
        d=(b-a) if a is not None and b is not None else None
        if d==0:equal_pts+=1
        pts_rows.append(dict(
            index=i,
            kr_pts=a if a is not None else "",
            final_pts=b if b is not None else "",
            delta_ticks=d if d is not None else "",
            delta_sec=f"{d/90000.0:+.6f}" if d is not None else ""
        ))
    ds=[abs(int(r["delta_ticks"])) for r in pts_rows if r["delta_ticks"]!=""]
    if ds:max_abs_delta=max(ds)
    write_tsv(STAGE/"audio_pts_compare.tsv",pts_rows)

    # Verify ATRAC decode.
    oma=WORK/"dm001_final_audio.oma"
    wav=WORK/"dm001_final_audio.wav"
    build_oma(fa["frames"],oma)
    cp=run(
        [FFMPEG,"-y","-v","warning","-f","oma","-i",oma,
         "-c:a","pcm_s16le",wav],
        "05_decode_final_audio.log",300
    )
    decode_ok=(cp.returncode==0 and wav.exists() and wav.stat().st_size>44)

    # PC preview using the FINAL PMF video + decoded FINAL Japanese audio.
    preview=OUT/"dm001_FINAL_KOsub_KR-JP-audio_preview.mp4"
    if preview.exists():preview.unlink()
    if decode_ok:
        cp=run(
            [FFMPEG,"-y","-v","warning",
             "-i",final_pmf,"-i",wav,
             "-map","0:v:0","-map","1:a:0",
             "-c:v","copy","-c:a","aac","-b:a","192k",
             "-shortest",preview],
            "06_build_final_preview.log",300
        )
        preview_ok=(cp.returncode==0 and preview.exists())
    else:
        preview_ok=False

    info=probe(final_pmf,"07_probe_final_pmf.log")
    vs=stream(info,"video")

    result=[dict(
        movie="dm001",
        final_pmf=str(final_pmf),
        final_pmf_bytes=final_pmf.stat().st_size,
        final_video_codec=vs.get("codec_name","") if vs else "",
        final_width=vs.get("width","") if vs else "",
        final_height=vs.get("height","") if vs else "",
        final_video_pes=sum(v for k,v in fp["counts"].items() if 0xE0<=k<=0xEF),
        final_audio_pes=fp["counts"].get(0xBD,0),
        kr_audio_pes=krp["counts"].get(0xBD,0),
        kr_atrac_frames=kra["frame_count"],
        final_atrac_frames=fa["frame_count"],
        h264_sha_MOV03Q=source_h264_sha,
        h264_sha_final=final_h264_sha,
        final_h264_equals_MOV03Q="YES" if h264_ok else "NO",
        kr_logical_au_sha256=kr_logical_sha,
        final_logical_au_sha256=final_logical_sha,
        final_logical_au_equals_kr="YES" if logical_ok else "NO",
        kr_744_frame_sha256=kr_frame_sha,
        final_744_frame_sha256=final_frame_sha,
        final_744_frames_equal_kr="YES" if frames_ok else "NO",
        kr_pts_count=len(kr_pts),
        final_pts_count=len(final_pts),
        pts_equal_same_index=f"{equal_pts}/{min(len(kr_pts),len(final_pts))}",
        pts_max_abs_delta_ticks=max_abs_delta if max_abs_delta is not None else "",
        pts_max_abs_delta_sec=f"{max_abs_delta/90000.0:.6f}" if max_abs_delta is not None else "",
        atrac_decode="PASS" if decode_ok else "FAIL",
        preview="PASS" if preview_ok else "FAIL",
    )]

    ok=all([
        vs is not None,
        vs.get("codec_name")=="h264",
        int(vs.get("width",0))==480,
        int(vs.get("height",0))==272,
        fp["counts"].get(0xBD,0)>0,
        h264_ok,logical_ok,frames_ok,decode_ok,preview_ok
    ])

    result[0]["status"]="PASS" if ok else "FAIL"
    write_tsv(STAGE/"final_mux_result.tsv",result)

    summary=[
        "Naruto PSP MOV03R - dm001 FINAL raw-ATRAC mux smoke test",
        "="*80,"",
        f"Final PMF={'PASS' if ok else 'FAIL'}",
        f"Final H264 == MOV03Q Korean-subtitle H264: {'YES' if h264_ok else 'NO'}",
        f"Final logical 752-byte AU stream == KR: {'YES' if logical_ok else 'NO'}",
        f"Final 744-byte ATRAC3+ frames == KR: {'YES' if frames_ok else 'NO'}",
        f"KR/final ATRAC frame count={kra['frame_count']}/{fa['frame_count']}",
        f"KR/final audio PES count={krp['counts'].get(0xBD,0)}/{fp['counts'].get(0xBD,0)}",
        f"Audio PTS entries KR/final={len(kr_pts)}/{len(final_pts)}",
        f"Same-index exact PTS={equal_pts}/{min(len(kr_pts),len(final_pts))}",
        f"Max same-index PTS delta={(f'{max_abs_delta/90000.0:.6f}s' if max_abs_delta is not None else 'N/A')}",
        f"ATRAC decode={'PASS' if decode_ok else 'FAIL'}",
        f"Preview={'PASS' if preview_ok else 'FAIL'}",
        "",
        "No at3tool was used.",
        "No ATRAC frame was re-encoded.",
        "",
        "Outputs:",
        f"  Final PMF : {final_pmf}",
        f"  Preview   : {preview}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0 if ok else 2

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
