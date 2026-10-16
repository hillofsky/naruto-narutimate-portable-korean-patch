#!/usr/bin/env python3
# Naruto PSP MOV03K FIX4 - Exact FFmpeg-compatible OMA/EA3 wrapper
#
# Grounded facts:
# - PSMF private_stream_1 contains Sony ATRAC3+.
# - private header is 4 bytes: id + reserved + AU locator BE16.
# - corrected raw stream frame size is exactly 0x2F0 (752) for all 10 DMs.
# - 44100 Hz, stereo, 2048 samples per ATRAC3+ frame.
#
# FFmpeg OMA decoder formula:
#   framesize = ((codec_params & 0x3FF) * 8) + 8
#   sample rate index = (codec_params >> 13) & 7
#   channel id       = (codec_params >> 10) & 7
#
# For 752-byte stereo 44.1 kHz ATRAC3+:
#   srate_index = 1
#   channel_id  = 2
#   size_code   = 752/8 - 1 = 93 = 0x5D
#   codec_params = (1<<13) | (2<<10) | 0x5D = 0x285D
#
# OMA byte 32 = codec id 1 (ATRAC3+)
# bytes 33..35 = 00 28 5D
#
# No patching.

from __future__ import annotations
import csv, json, math, statistics, struct, subprocess, sys, traceback, hashlib, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
STAGE = ROOT / "analysis" / "mov" / "mov03k_embedded_audio"
AUDIO_DIR = STAGE / "audio"
RAW_DIR = STAGE / "raw"
LOG_DIR = STAGE / "logs"
for p in (STAGE,AUDIO_DIR,RAW_DIR,LOG_DIR):
    p.mkdir(parents=True,exist_ok=True)

DM=[f"dm{i:03d}" for i in range(1,11)]

SAMPLE_RATE=44100
SAMPLES_PER_FRAME=2048
CHANNEL_ID=2
FRAME_SIZE=0x2F0
SRATE_INDEX=1
SIZE_CODE=FRAME_SIZE//8 - 1
CODEC_PARAMS=(SRATE_INDEX<<13)|(CHANNEL_ID<<10)|SIZE_CODE
OMA_CODEC_ATRAC3P=1
EA3_HEADER_SIZE=96

def write_tsv(path,rows,fields=None):
    path=Path(path)
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields:fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def find_tool(name):
    for p in [Path(r"LOCAL_PATH")/(name+".exe"),Path(r"LOCAL_PATH")/(name+".EXE")]:
        if p.exists():return p
    try:
        cp=subprocess.run(["where.exe",name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding="utf-8",errors="replace",timeout=10)
        for line in cp.stdout.splitlines():
            p=Path(line.strip())
            if p.exists():return p
    except Exception:pass
    return None

def run(cmd,logname,timeout=300):
    cp=subprocess.run([str(x) for x in cmd],
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                      text=True,encoding="utf-8",errors="replace",timeout=timeout)
    txt="COMMANLOCAL_PATH"+" ".join(('"%s"'%x if " " in str(x) else str(x)) for x in cmd)
    txt+="\n\nRETURN CODLOCAL_PATH"+str(cp.returncode)
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOG_DIR/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def ffprobe_json(ffprobe,path,logname,force_oma=False):
    cmd=[ffprobe,"-v","error"]
    if force_oma:cmd += ["-f","oma"]
    cmd += ["-show_streams","-show_format","-of","json",path]
    cp=run(cmd,logname,120)
    if cp.returncode!=0:return None,cp
    try:return json.loads(cp.stdout),cp
    except:return None,cp

def first_audio(info):
    if not info:return None
    for s in info.get("streams",[]):
        if s.get("codec_type")=="audio":return s
    return None

def info_duration(info):
    if not info:return None
    a=first_audio(info)
    for x in [a.get("duration") if a else None,info.get("format",{}).get("duration")]:
        try:
            if x not in (None,"N/A",""):
                return float(x)
        except:pass
    return None

def short(s,n=500):
    if not s:return ""
    return re.sub(r"\s+"," ",s).strip()[:n]

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def parse_pts5(b):
    if len(b)<5:return None
    return ((b[0]&0x0E)<<29) | (b[1]<<22) | ((b[2]&0xFE)<<14) | (b[3]<<7) | ((b[4]&0xFE)>>1)

def parse_pmf_private(path):
    data=path.read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError(f"{path.name}: not PSMF")
    data_offset=struct.unpack_from(">I",data,8)[0]
    if data_offset<=0 or data_offset>=len(data):
        raise RuntimeError(f"{path.name}: bad PSMF data offset")

    pos=data_offset;n=len(data)
    payloads=defaultdict(bytearray)
    pts=defaultdict(list)
    locs=defaultdict(list)
    sizes=defaultdict(list)
    counts=Counter()

    while pos+6<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0:break
            pos=nxt;continue
        sid=data[pos+3];counts[sid]+=1

        if sid==0xBA:
            if pos+14>n:break
            pos += 14+(data[pos+13]&7);continue
        if sid==0xB9:
            pos+=4;continue

        plen=(data[pos+4]<<8)|data[pos+5]
        if plen==0:
            nxt=data.find(b"\x00\x00\x01\xBA",pos+6)
            if nxt<0:break
            pos=nxt;continue
        end=pos+6+plen
        if end>n:break

        if sid==0xBD:
            p=pos+6;payload=p;pes_pts=None

            if p+3<=end and (data[p]&0xC0)==0x80:
                flags2=data[p+1];hlen=data[p+2]
                if (flags2&0x80) and p+8<=end:
                    pes_pts=parse_pts5(data[p+3:p+8])
                payload=p+3+hlen
            else:
                q=p
                while q<end and data[q]==0xFF:q+=1
                if q+2<=end and (data[q]&0xC0)==0x40:q+=2
                if q<end and (data[q]&0xF0) in (0x20,0x30):
                    pes_pts=parse_pts5(data[q:q+5])
                    q += 5 if (data[q]&0xF0)==0x20 else 10
                elif q<end and data[q]==0x0F:q+=1
                payload=q

            if payload+4<=end:
                subid=data[payload]
                locator=struct.unpack_from(">H",data,payload+2)[0]
                es=data[payload+4:end]
                payloads[subid].extend(es)
                locs[subid].append(locator)
                sizes[subid].append(len(es))
                if pes_pts is not None:pts[subid].append(pes_pts)

        pos=end

    return dict(counts=counts,payloads=payloads,pts=pts,locs=locs,sizes=sizes)

def locator_check(locs,sizes):
    good=0;total=0
    for i in range(min(len(locs)-1,len(sizes)-1)):
        v=sizes[i]-locs[i]+locs[i+1]
        good += int(v%FRAME_SIZE==0)
        total += 1
    return good,total

def syncsafe28(n):
    if not (0<=n<0x10000000):raise ValueError(n)
    return bytes([(n>>21)&0x7F,(n>>14)&0x7F,(n>>7)&0x7F,n&0x7F])

def build_oma(raw:bytes,path:Path,with_empty_id3=True):
    out=bytearray()

    # Minimal ID3v2.3-style header with Sony 'ea3' magic, payload size 0.
    # FFmpeg's OMA demuxer calls ff_id3v2_read(..., "ea3", ...) first.
    if with_empty_id3:
        out += b"ea3"
        out += bytes([3,0,0])
        out += syncsafe28(0)

    ea3=bytearray(EA3_HEADER_SIZE)
    ea3[0:4]=b"EA3\x00"
    ea3[4]=EA3_HEADER_SIZE>>7
    ea3[5]=EA3_HEADER_SIZE&0x7F
    ea3[6:8]=struct.pack("<H",0xFFFF)  # not encrypted
    # 8..31 zeros: DRM/padding
    word=(OMA_CODEC_ATRAC3P<<24)|CODEC_PARAMS
    ea3[32:36]=struct.pack(">I",word)
    # 36..95 zero padding
    out += ea3
    out += raw
    path.write_bytes(out)

def main():
    ffmpeg=find_tool("ffmpeg");ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03K FIX4 - Exact OMA/EA3 ATRAC3+ wrapper",flush=True)
    print("="*80,flush=True)
    print(f"Frame size      : {FRAME_SIZE} (0x{FRAME_SIZE:X})",flush=True)
    print(f"OMA codec params: 0x{CODEC_PARAMS:06X}",flush=True)

    version=run([ffmpeg,"-version"],"fix4_ffmpeg_version.log",30)

    rows=[];trials=[]
    ok_count=0
    raw_lens=[]

    for idx,name in enumerate(DM,1):
        print(f"[{idx:02d}/10] {name}",flush=True)
        src=KR_MOV/(name+".pmf")
        if not src.exists():
            rows.append(dict(movie=name,status="MISSING_PMF"));continue

        r=parse_pmf_private(src)
        cands=[s for s in r["payloads"] if s<0x10]
        if not cands:
            rows.append(dict(movie=name,status="NO_ATRAC_SUBSTREAM"));continue
        sub=max(cands,key=lambda x:len(r["payloads"][x]))
        raw=bytes(r["payloads"][sub])
        raw_lens.append(len(raw))

        raw_path=RAW_DIR/f"{name}_fix4.raw"
        raw_path.write_bytes(raw)

        divisible=(len(raw)%FRAME_SIZE==0)
        frames=len(raw)//FRAME_SIZE if divisible else 0
        theoretical=frames*SAMPLES_PER_FRAME/SAMPLE_RATE if frames else None

        pvals=r["pts"][sub]
        pts_span=(pvals[-1]-pvals[0])/90000.0 if len(pvals)>=2 else None
        good,total=locator_check(r["locs"][sub],r["sizes"][sub])

        selected=""
        selected_oma=""
        selected_wav=""
        selected_wdur=None
        selected_codec=""
        status="NO_OMA_VARIANT_OK"

        for variant,with_id3 in [("oma_ea3_id3",True),("oma_ea3_noid3",False)]:
            oma=AUDIO_DIR/f"{name}_{variant}.oma"
            wav=AUDIO_DIR/f"{name}_{variant}.wav"
            for p in (oma,wav):
                if p.exists():p.unlink()

            if not divisible:
                trials.append(dict(movie=name,variant=variant,status="RAW_NOT_DIVISIBLE"))
                continue

            build_oma(raw,oma,with_id3)

            # First normal auto-probe, then forced oma probe.
            ai,acp=ffprobe_json(ffprobe,oma,f"{name}_{variant}_autoprobe.log",False)
            aa=first_audio(ai)
            fi,fcp=ffprobe_json(ffprobe,oma,f"{name}_{variant}_forceprobe.log",True)
            fa=first_audio(fi)

            probe=fi if fa else ai
            pa=fa if fa else aa
            codec=pa.get("codec_name","") if pa else ""
            sr=pa.get("sample_rate","") if pa else ""
            ch=pa.get("channels","") if pa else ""
            ba=pa.get("block_align","") if pa else ""

            # Decode forced as OMA, avoiding extension/probe ambiguity.
            cp=run([ffmpeg,"-y","-v","warning","-f","oma","-i",oma,
                    "-map","0:a:0","-c:a","pcm_s16le",wav],
                   f"{name}_{variant}_decode.log",300)

            wi,wcp=ffprobe_json(ffprobe,wav,f"{name}_{variant}_wavprobe.log",False) if wav.exists() else (None,None)
            wa=first_audio(wi)
            wdur=info_duration(wi)
            decode_ok=(cp.returncode==0 and wav.exists() and wav.stat().st_size>44 and wa is not None)
            delta=(wdur-pts_span) if (wdur is not None and pts_span is not None) else None
            duration_ok=decode_ok and delta is not None and abs(delta)<=0.50
            full_ok=bool(duration_ok)

            trials.append(dict(
                movie=name,variant=variant,
                status="FULL_OK" if full_ok else ("DECODE_OK_BAD_DURATION" if decode_ok else "DECODE_FAILED"),
                oma_bytes=oma.stat().st_size if oma.exists() else "",
                auto_probe_audio="YES" if aa else "NO",
                auto_probe_stderr=short(acp.stderr if acp else ""),
                forced_probe_audio="YES" if fa else "NO",
                forced_probe_stderr=short(fcp.stderr if fcp else ""),
                codec=codec,sample_rate=sr,channels=ch,block_align=ba,
                ffmpeg_returncode=cp.returncode,
                ffmpeg_stderr=short(cp.stderr),
                wav_exists="YES" if wav.exists() else "NO",
                wav_bytes=wav.stat().st_size if wav.exists() else "",
                wav_duration=f"{wdur:.6f}" if wdur is not None else "",
                pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
                wav_vs_pts=f"{delta:+.6f}" if delta is not None else "",
            ))

            if full_ok:
                selected=variant
                selected_oma=str(oma)
                selected_wav=str(wav)
                selected_wdur=wdur
                selected_codec=codec
                status="OK"
                ok_count+=1
                break

        print(
            f"  raw={len(raw)} frames={frames} "
            f"PTS={pts_span:.3f}s theoretical={theoretical:.3f}s "
            f"locator={good}/{total} "
            f"variant={selected or '(none)'} "
            f"WAV={(f'{selected_wdur:.3f}s' if selected_wdur is not None else 'N/A')} "
            f"=> {status}",
            flush=True
        )

        rows.append(dict(
            movie=name,status=status,
            substream_id=f"0x{sub:02X}",
            private_stream_packets=r["counts"].get(0xBD,0),
            raw_bytes=len(raw),
            frame_size=FRAME_SIZE,
            frame_size_hex=f"0x{FRAME_SIZE:X}",
            raw_divisible="YES" if divisible else "NO",
            frame_count=frames,
            theoretical_duration=f"{theoretical:.6f}" if theoretical is not None else "",
            pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
            locator_recurrence=f"{good}/{total}",
            oma_codec_params=f"0x{CODEC_PARAMS:06X}",
            selected_variant=selected,
            selected_codec=selected_codec,
            wav_duration=f"{selected_wdur:.6f}" if selected_wdur is not None else "",
            raw_path=str(raw_path),
            oma_path=selected_oma,
            wav_path=selected_wav,
            raw_sha256=sha256(raw_path),
        ))

    g=0
    for x in raw_lens:g=math.gcd(g,x)

    write_tsv(STAGE/"fix4_oma_results.tsv",rows)
    write_tsv(STAGE/"fix4_oma_trials.tsv",trials)

    summary=[
        "Naruto PSP MOV03K FIX4 - Exact OMA/EA3 ATRAC3+ wrapper",
        "="*80,"",
        f"Corrected raw-length GCD={g} (0x{g:X})",
        f"ATRAC3+ frame size={FRAME_SIZE} (0x{FRAME_SIZE:X})",
        f"OMA codec params=0x{CODEC_PARAMS:06X}",
        f"Validated full-duration WAV={ok_count}/10",
        "",
        "OMA construction:",
        "  ea3 ID3v2.3 header (empty metadata)",
        "  EA3 header size = 96",
        "  codec id = 1 (ATRAC3+)",
        f"  sample rate index = {SRATE_INDEX} (44100 Hz)",
        f"  channel id = {CHANNEL_ID} (stereo)",
        f"  size code = {SIZE_CODE} (frame = size_code*8+8 = {FRAME_SIZE})",
        "",
        "Two variants are tested:",
        "  oma_ea3_id3    : normal OMA with minimal ea3 ID3 header",
        "  oma_ea3_noid3  : diagnostic EA3-only form",
        "",
        "FFmpeg is invoked with -f oma for decoding.",
        "See fix4_oma_trials.tsv for exact codec recognition and stderr.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0 if ok_count==10 else 2

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
