#!/usr/bin/env python3
# Naruto PSP MOV03L FIX2 - whole audio PES transplant
#
# FIX1 finding:
# - KR/US dm001 both have exactly 432 private_stream_1 audio PES packets.
# - Corresponding PES TOTAL sizes match 432/432.
# - 22 packets only differ in OPTIONAL PES-header length by +/-3 bytes,
#   so private payload offsets differ although the complete PES size is equal.
# - 431/432 PTS are identical.
# - one packet differs by exactly ~1 ATRAC frame (~46.44 ms), so preserving
#   KR's whole PES header/PTS is preferable.
#
# FIX2:
#   Replace each entire US 0xBD PES packet with the corresponding KR 0xBD PES
#   packet, byte-for-byte, while leaving every non-audio byte in the US PMF
#   untouched.
#
# Validation:
#   - all corresponding audio PES lengths equal
#   - hybrid file size == US file size
#   - concatenated hybrid audio PES SHA256 == KR
#   - recovered hybrid ATRAC3+ frames SHA256 == KR
#   - extracted hybrid H.264 SHA256 == US
#   - hybrid ATRAC3+ decodes to WAV
#   - preview MP4 generated
#
# No at3tool. No oMPSComposer. No re-encoding inside the PMF.

from __future__ import annotations
import csv, hashlib, json, statistics, struct, subprocess, sys, traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov03l_hybrid_pmf_smoke"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, OUT, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

LOGICAL_AU = 752
ATRAC_FRAME = 744
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 2048
SRATE_INDEX = 1
CHANNEL_ID_STEREO = 2
EA3_HEADER_SIZE = 96

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields: fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

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

def run(cmd,logname,timeout=600):
    cp=subprocess.run([str(x) for x in cmd],
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                      text=True,encoding="utf-8",errors="replace",timeout=timeout)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%x if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOGD/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def probe(path,logname):
    cp=run([FFPROBE,"-v","error","-show_streams","-show_format","-of","json",path],logname,120)
    if cp.returncode!=0:return None
    try:return json.loads(cp.stdout)
    except:return None

def duration(info):
    if not info:return None
    for s in info.get("streams",[]):
        try:
            d=s.get("duration")
            if d not in (None,"","N/A"):return float(d)
        except:pass
    try:return float(info.get("format",{}).get("duration"))
    except:return None

def parse_pts5(b):
    if len(b)<5:return None
    return ((b[0]&0x0E)<<29)|(b[1]<<22)|((b[2]&0xFE)<<14)|(b[3]<<7)|((b[4]&0xFE)>>1)

def parse_pmf(path):
    data=Path(path).read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError(f"{Path(path).name}: not PSMF")
    data_offset=struct.unpack_from(">I",data,8)[0]
    if data_offset<=0 or data_offset>=len(data):
        raise RuntimeError(f"{Path(path).name}: bad data offset")

    pos=data_offset;n=len(data)
    audio=[];video=[];counts=Counter()

    while pos+6<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0:break
            pos=nxt;continue

        sid=data[pos+3];counts[sid]+=1
        if sid==0xBA:
            if pos+14>n:break
            pos+=14+(data[pos+13]&7);continue
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
            video.append(dict(start=pos,end=end,sid=sid,pes_total=end-pos))

        if sid==0xBD:
            p=pos+6;payload=p;pts=None;style=""
            if p+3<=end and (data[p]&0xC0)==0x80:
                style="MPEG2"
                flags2=data[p+1];hlen=data[p+2]
                if (flags2&0x80) and p+8<=end:
                    pts=parse_pts5(data[p+3:p+8])
                payload=p+3+hlen
            else:
                style="MPEG1"
                q=p
                while q<end and data[q]==0xFF:q+=1
                if q+2<=end and (data[q]&0xC0)==0x40:q+=2
                if q<end and (data[q]&0xF0) in (0x20,0x30):
                    pts=parse_pts5(data[q:q+5])
                    q+=5 if (data[q]&0xF0)==0x20 else 10
                elif q<end and data[q]==0x0F:q+=1
                payload=q

            subid=data[payload] if payload<end else None
            reserved=data[payload+1] if payload+1<end else None
            locator=struct.unpack_from(">H",data,payload+2)[0] if payload+4<=end else None
            audio.append(dict(
                start=pos,end=end,pes_total=end-pos,
                payload=payload,payload_len=end-payload,
                pts=pts,style=style,
                subid=subid,reserved=reserved,locator=locator,
            ))
        pos=end

    return dict(path=Path(path),data=data,data_offset=data_offset,
                audio=audio,video=video,counts=counts)

def concat_audio_pes(p):
    return b"".join(p["data"][x["start"]:x["end"]] for x in p["audio"])

def recover_frames(p):
    logical=bytearray()
    for x in p["audio"]:
        private=p["data"][x["payload"]:x["end"]]
        if len(private)>=4 and private[0]<0x10:
            logical += private[4:]
    logical=bytes(logical)
    if len(logical)%LOGICAL_AU:
        raise RuntimeError(f"{p['path'].name}: logical audio {len(logical)} not divisible by {LOGICAL_AU}")
    frames=bytearray()
    headers=Counter()
    for i in range(0,len(logical),LOGICAL_AU):
        au=logical[i:i+LOGICAL_AU]
        headers[au[:8]]+=1
        frames+=au[8:]
    if len(frames)%ATRAC_FRAME:
        raise RuntimeError(f"{p['path'].name}: ATRAC bytes {len(frames)} not divisible by {ATRAC_FRAME}")
    return dict(logical=logical,frames=bytes(frames),
                au_count=len(logical)//LOGICAL_AU,
                frame_count=len(frames)//ATRAC_FRAME,
                headers=headers)

def syncsafe28(n):
    return bytes([(n>>21)&0x7F,(n>>14)&0x7F,(n>>7)&0x7F,n&0x7F])

def build_oma(frames,path):
    size_code=ATRAC_FRAME//8-1
    params=(SRATE_INDEX<<13)|(CHANNEL_ID_STEREO<<10)|size_code
    out=bytearray()
    out+=b"ea3"+bytes([3,0,0])+syncsafe28(0)
    ea3=bytearray(EA3_HEADER_SIZE)
    ea3[0:4]=b"EA3\x00"
    ea3[4]=EA3_HEADER_SIZE>>7
    ea3[5]=EA3_HEADER_SIZE&0x7F
    ea3[6:8]=struct.pack("<H",0xFFFF)
    ea3[32:36]=struct.pack(">I",(1<<24)|params)
    out+=ea3
    out+=frames
    Path(path).write_bytes(out)

def extract_h264(pmf,out,logname):
    cp=run([FFMPEG,"-y","-v","warning","-i",pmf,
            "-map","0:v:0","-an","-c:v","copy","-f","h264",out],logname,300)
    return cp.returncode==0 and Path(out).exists() and Path(out).stat().st_size>0

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("ffmpeg/ffprobe missing")

    kr_path=KR_MOV/"dm001.pmf"
    us_path=US_MOV/"dm001e.pmf"
    if not us_path.exists():us_path=US_MOV/"dm001.pmf"
    if not kr_path.exists() or not us_path.exists():
        raise RuntimeError("KR/US dm001 PMF missing")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03L FIX2 - Whole audio PES transplant",flush=True)
    print("="*80,flush=True)

    kr=parse_pmf(kr_path)
    us=parse_pmf(us_path)

    if len(kr["audio"])!=len(us["audio"]) or not kr["audio"]:
        raise RuntimeError(f"Audio PES count mismatch KR={len(kr['audio'])} US={len(us['audio'])}")

    cmp=[]
    totals_equal=True
    pts_equal=0
    pts_diffs=[]
    payload_offset_diffs=0

    for i,(k,u) in enumerate(zip(kr["audio"],us["audio"])):
        same_total=k["pes_total"]==u["pes_total"]
        totals_equal &= same_total
        same_pts=k["pts"]==u["pts"]
        pts_equal+=int(same_pts)
        if k["pts"] is not None and u["pts"] is not None:
            pts_diffs.append((u["pts"]-k["pts"])/90000.0)
        if k["payload_len"]!=u["payload_len"]:
            payload_offset_diffs+=1

        cmp.append(dict(
            index=i,
            kr_pes_total=k["pes_total"],us_pes_total=u["pes_total"],
            total_equal="YES" if same_total else "NO",
            kr_payload_len=k["payload_len"],us_payload_len=u["payload_len"],
            payload_len_equal="YES" if k["payload_len"]==u["payload_len"] else "NO",
            kr_style=k["style"],us_style=u["style"],
            kr_pts=k["pts"] if k["pts"] is not None else "",
            us_pts=u["pts"] if u["pts"] is not None else "",
            pts_equal="YES" if same_pts else "NO",
            pts_delta_sec=(f"{(u['pts']-k['pts'])/90000.0:+.6f}"
                           if k["pts"] is not None and u["pts"] is not None else ""),
            kr_locator=k["locator"] if k["locator"] is not None else "",
            us_locator=u["locator"] if u["locator"] is not None else "",
        ))
    write_tsv(STAGE/"dm001_audio_pes_compare_FIX2.tsv",cmp)

    if not totals_equal:
        raise RuntimeError("Corresponding whole audio PES sizes are not all equal.")

    # Whole-PES transplant.
    hybrid=bytearray(us["data"])
    for k,u in zip(kr["audio"],us["audio"]):
        donor=kr["data"][k["start"]:k["end"]]
        if len(donor)!=(u["end"]-u["start"]):
            raise RuntimeError("Internal PES length mismatch")
        hybrid[u["start"]:u["end"]]=donor

    hybrid_path=OUT/"dm001_USvideo_KRaudio_lossless.pmf"
    hybrid_path.write_bytes(hybrid)

    hy=parse_pmf(hybrid_path)

    # Exact audio PES equality.
    kr_pes_sha=sha_bytes(concat_audio_pes(kr))
    hy_pes_sha=sha_bytes(concat_audio_pes(hy))
    audio_pes_match=kr_pes_sha==hy_pes_sha

    # Exact ATRAC frame equality.
    kr_a=recover_frames(kr)
    hy_a=recover_frames(hy)
    kr_atrac_sha=sha_bytes(kr_a["frames"])
    hy_atrac_sha=sha_bytes(hy_a["frames"])
    atrac_match=kr_atrac_sha==hy_atrac_sha

    # US video must be unchanged.
    us264=WORK/"dm001_us_FIX2.264"
    hy264=WORK/"dm001_hybrid_FIX2.264"
    for p in (us264,hy264):
        if p.exists():p.unlink()
    if not extract_h264(us_path,us264,"01_FIX2_extract_us_h264.log"):
        raise RuntimeError("US H264 extraction failed")
    if not extract_h264(hybrid_path,hy264,"02_FIX2_extract_hybrid_h264.log"):
        raise RuntimeError("Hybrid H264 extraction failed")
    us_vsha=sha_file(us264)
    hy_vsha=sha_file(hy264)
    video_match=us_vsha==hy_vsha

    # Decode hybrid audio.
    oma=WORK/"dm001_hybrid_FIX2.oma"
    wav=OUT/"dm001_hybrid_audio.wav"
    for p in (oma,wav):
        if p.exists():p.unlink()
    build_oma(hy_a["frames"],oma)
    cp=run([FFMPEG,"-y","-v","warning","-f","oma","-i",oma,
            "-c:a","pcm_s16le",wav],"03_FIX2_decode_hybrid_audio.log",300)
    wav_ok=cp.returncode==0 and wav.exists() and wav.stat().st_size>44
    wi=probe(wav,"04_FIX2_probe_wav.log") if wav_ok else None
    wdur=duration(wi)

    # Preview.
    preview=OUT/"dm001_USvideo_KRaudio_preview.mp4"
    if preview.exists():preview.unlink()
    cp=run([FFMPEG,"-y","-v","warning",
            "-i",hybrid_path,"-i",wav,
            "-map","0:v:0","-map","1:a:0",
            "-c:v","copy","-c:a","aac","-b:a","192k",
            "-shortest",preview],"05_FIX2_preview.log",300) if wav_ok else None
    preview_ok=bool(cp and cp.returncode==0 and preview.exists())

    same_size=hybrid_path.stat().st_size==us_path.stat().st_size
    ptd_mean=statistics.mean(pts_diffs) if pts_diffs else None
    ptd_min=min(pts_diffs) if pts_diffs else None
    ptd_max=max(pts_diffs) if pts_diffs else None

    final=all([same_size,audio_pes_match,atrac_match,video_match,wav_ok,preview_ok])

    result=[dict(
        movie="dm001",
        kr_audio_pes_count=len(kr["audio"]),
        us_audio_pes_count=len(us["audio"]),
        all_whole_pes_sizes_equal="YES" if totals_equal else "NO",
        packets_with_different_private_payload_len=payload_offset_diffs,
        pts_equal_packets=f"{pts_equal}/{len(kr['audio'])}",
        pts_delta_mean_sec=f"{ptd_mean:+.6f}" if ptd_mean is not None else "",
        pts_delta_min_sec=f"{ptd_min:+.6f}" if ptd_min is not None else "",
        pts_delta_max_sec=f"{ptd_max:+.6f}" if ptd_max is not None else "",
        us_pmf_bytes=us_path.stat().st_size,
        hybrid_pmf_bytes=hybrid_path.stat().st_size,
        hybrid_size_equals_us="YES" if same_size else "NO",
        kr_audio_pes_sha256=kr_pes_sha,
        hybrid_audio_pes_sha256=hy_pes_sha,
        hybrid_audio_pes_equals_kr="YES" if audio_pes_match else "NO",
        kr_atrac_sha256=kr_atrac_sha,
        hybrid_atrac_sha256=hy_atrac_sha,
        hybrid_atrac_equals_kr="YES" if atrac_match else "NO",
        us_h264_sha256=us_vsha,
        hybrid_h264_sha256=hy_vsha,
        hybrid_h264_equals_us="YES" if video_match else "NO",
        hybrid_wav_duration=f"{wdur:.6f}" if wdur is not None else "",
        hybrid_wav_ok="YES" if wav_ok else "NO",
        preview_ok="YES" if preview_ok else "NO",
        hybrid_pmf=str(hybrid_path),
        preview=str(preview),
        static_result="PASS" if final else "FAIL",
    )]
    write_tsv(STAGE/"smoke_result.tsv",result)

    summary=[
        "Naruto PSP MOV03L FIX2 - Whole audio PES transplant",
        "="*80,"",
        f"KR/US audio PES count={len(kr['audio'])}/{len(us['audio'])}",
        f"Whole PES lengths equal={'YES' if totals_equal else 'NO'}",
        f"Packets whose private payload offset/length differs={payload_offset_diffs}",
        f"PTS exactly equal={pts_equal}/{len(kr['audio'])}",
        f"Hybrid file size equals US={'YES' if same_size else 'NO'}",
        f"Hybrid whole-audio-PES SHA equals KR={'YES' if audio_pes_match else 'NO'}",
        f"Hybrid ATRAC3+ SHA equals KR={'YES' if atrac_match else 'NO'}",
        f"Hybrid H264 SHA equals US={'YES' if video_match else 'NO'}",
        f"Hybrid WAV decode={'OK' if wav_ok else 'FAIL'}",
        f"Hybrid WAV duration={(f'{wdur:.6f}s' if wdur is not None else 'N/A')}",
        f"Preview={'OK' if preview_ok else 'FAIL'}",
        f"LOSSLESS HYBRID RESULT={'PASS' if final else 'FAIL'}",
        "",
        "Outputs:",
        f"  {hybrid_path}",
        f"  {wav}",
        f"  {preview}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)
    return 0 if final else 2

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
