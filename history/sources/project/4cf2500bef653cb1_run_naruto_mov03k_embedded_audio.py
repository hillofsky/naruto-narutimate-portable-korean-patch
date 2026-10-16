#!/usr/bin/env python3
# Naruto PSP MOV03K FIX3
# Robust corrected PSMF ATRAC3+ demux + multiple RIFF/AT3 wrapper trials.
#
# Key corrections preserved from FIX2:
#   private_stream_1 private header = 4 bytes:
#     stream_id(1) + reserved(1) + AU_locator_be16(2)
#   corrected raw frame size = 0x2F0 (752)
#
# FIX3 changes:
# - never crashes when ffprobe/ffmpeg returns no duration
# - processes all 10 DM files regardless of individual decode failure
# - tries multiple standards-compatible ATRAC3+ WAVEFORMATEXTENSIBLE headers
# - records ffprobe codec and ffmpeg stderr excerpt for every variant
# - selects the first full-duration successful decode
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
CHANNELS=2
CHANNEL_MASK=3
FRAME_SIZE=0x2F0

ATRAC3P_GUID = bytes.fromhex(
    "bf aa 23 e9 58 cb 71 44 a1 19 ff fa 01 e4 ce 62"
)

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
    txt+="\n\nSTDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOG_DIR/logname).write_text(txt,encoding="utf-8-sig")
    return cp

def ffprobe_json(ffprobe,path,logname):
    cp=run([ffprobe,"-v","error","-show_streams","-show_format","-of","json",path],logname,120)
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
    candidates=[]
    if a:candidates.append(a.get("duration"))
    candidates.append(info.get("format",{}).get("duration"))
    for x in candidates:
        try:
            if x not in (None,"N/A",""):
                return float(x)
        except:pass
    return None

def stderr_excerpt(s,limit=400):
    if not s:return ""
    s=re.sub(r"\s+"," ",s).strip()
    return s[:limit]

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
    declared_data_size=struct.unpack_from(">I",data,12)[0]
    if data_offset<=0 or data_offset>=len(data):
        raise RuntimeError(f"{path.name}: invalid data offset")

    pos=data_offset;n=len(data)
    payloads=defaultdict(bytearray)
    pts=defaultdict(list)
    locators=defaultdict(list)
    sizes=defaultdict(list)
    counts=Counter()
    private_rows=[]

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
                reserved=data[payload+1]
                locator=struct.unpack_from(">H",data,payload+2)[0]
                es=data[payload+4:end]
                payloads[subid].extend(es)
                locators[subid].append(locator)
                sizes[subid].append(len(es))
                if pes_pts is not None:pts[subid].append(pes_pts)
                private_rows.append(dict(
                    pes_file_offset=f"0x{pos:X}",
                    substream_id=f"0x{subid:02X}",
                    reserved=f"0x{reserved:02X}",
                    au_locator=locator,
                    es_bytes=len(es),
                    pts=pes_pts if pes_pts is not None else "",
                    es_head=es[:32].hex(" "),
                ))
        pos=end

    return dict(
        data_offset=data_offset,declared_data_size=declared_data_size,
        counts=counts,payloads=payloads,pts=pts,locators=locators,
        sizes=sizes,private_rows=private_rows
    )

def locator_recurrence(locs,sizes):
    good=0;total=0
    for i in range(min(len(locs)-1,len(sizes)-1)):
        # packet payload starts at arbitrary position within current frame.
        # After consuming current packet payload, next locator should restore
        # frame phase. This expression must be frame-aligned.
        value=sizes[i]-locs[i]+locs[i+1]
        if value % FRAME_SIZE==0:good+=1
        total+=1
    return good,total

def build_fmt(cb_size, samples_field, extra12):
    avg_bps=round(FRAME_SIZE*SAMPLE_RATE/SAMPLES_PER_FRAME)
    fmt=bytearray()
    fmt += struct.pack("<H",0xFFFE)       # WAVE_FORMAT_EXTENSIBLE
    fmt += struct.pack("<H",CHANNELS)
    fmt += struct.pack("<I",SAMPLE_RATE)
    fmt += struct.pack("<I",avg_bps)
    fmt += struct.pack("<H",FRAME_SIZE)
    fmt += struct.pack("<H",0)            # bits/sample
    fmt += struct.pack("<H",cb_size)
    fmt += struct.pack("<H",samples_field)
    fmt += struct.pack("<I",CHANNEL_MASK)
    fmt += ATRAC3P_GUID
    if extra12:
        fmt += b"\x00"*12
    return bytes(fmt)

def write_wave_variant(raw,out_path,variant,frames):
    samples=frames*SAMPLES_PER_FRAME

    if variant=="ext22_s0_fact4":
        fmt=build_fmt(0x16,0,False)
        fact=struct.pack("<I",samples)
    elif variant=="ext22_s2048_fact4":
        fmt=build_fmt(0x16,SAMPLES_PER_FRAME,False)
        fact=struct.pack("<I",samples)
    elif variant=="ext34_s0_fact4":
        fmt=build_fmt(0x22,0,True)
        fact=struct.pack("<I",samples)
    elif variant=="ext34_s2048_fact4":
        fmt=build_fmt(0x22,SAMPLES_PER_FRAME,True)
        fact=struct.pack("<I",samples)
    elif variant=="ext34_s2048_fact8":
        fmt=build_fmt(0x22,SAMPLES_PER_FRAME,True)
        fact=struct.pack("<Q",samples)
    elif variant=="ext22_s0_nofact":
        fmt=build_fmt(0x16,0,False)
        fact=None
    else:
        raise ValueError(variant)

    body=bytearray()
    body += b"fmt " + struct.pack("<I",len(fmt)) + fmt
    if fact is not None:
        body += b"fact" + struct.pack("<I",len(fact)) + fact
        if len(fact)&1:body+=b"\x00"
    body += b"data" + struct.pack("<I",len(raw)) + raw
    if len(raw)&1:body+=b"\x00"

    riff=b"WAVE"+bytes(body)
    out_path.write_bytes(b"RIFF"+struct.pack("<I",len(riff))+riff)

VARIANTS=[
    "ext22_s0_fact4",
    "ext22_s2048_fact4",
    "ext34_s0_fact4",
    "ext34_s2048_fact4",
    "ext34_s2048_fact8",
    "ext22_s0_nofact",
]

def main():
    ffmpeg=find_tool("ffmpeg");ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03K FIX3 - Robust ATRAC3+ wrapper trials",flush=True)
    print("="*80,flush=True)

    results=[];trials=[];packet_rows=[]
    all_raw=[]
    decoded_full=0

    # Demux all first, verify global 0x2F0 evidence.
    parsed={}
    for name in DM:
        src=KR_MOV/(name+".pmf")
        if not src.exists():
            parsed[name]=None;continue
        r=parse_pmf_private(src)
        cands=[s for s in r["payloads"] if s<0x10]
        if not cands:
            parsed[name]=(r,None,b"");continue
        chosen=max(cands,key=lambda s:len(r["payloads"][s]))
        raw=bytes(r["payloads"][chosen])
        parsed[name]=(r,chosen,raw)
        all_raw.append(len(raw))
        for rr in r["private_rows"]:
            packet_rows.append(dict(movie=name,**rr))

    g=0
    for x in all_raw:g=math.gcd(g,x)

    for idx,name in enumerate(DM,1):
        print(f"[{idx:02d}/10] {name}",flush=True)
        item=parsed.get(name)
        if item is None:
            results.append(dict(movie=name,status="MISSING_PMF"))
            continue
        r,chosen,raw=item
        if chosen is None:
            results.append(dict(movie=name,status="NO_SONY_PRIVATE_STREAM"))
            continue

        raw_path=RAW_DIR/f"{name}_sub{chosen:02X}_fix3.raw"
        raw_path.write_bytes(raw)

        divisible=(len(raw)%FRAME_SIZE==0)
        frames=len(raw)//FRAME_SIZE if divisible else 0
        theoretical=frames*SAMPLES_PER_FRAME/SAMPLE_RATE if frames else None
        pvals=r["pts"][chosen]
        pts_span=(pvals[-1]-pvals[0])/90000.0 if len(pvals)>=2 else None
        good,total=locator_recurrence(r["locators"][chosen],r["sizes"][chosen])

        chosen_variant=""
        chosen_at3=""
        chosen_wav=""
        chosen_codec=""
        chosen_wdur=None
        best_status="NO_VARIANT_DECODED"

        for v in VARIANTS:
            at3=AUDIO_DIR/f"{name}_{v}.at3"
            wav=AUDIO_DIR/f"{name}_{v}.wav"
            for p in (at3,wav):
                if p.exists():p.unlink()

            if not divisible:
                trials.append(dict(movie=name,variant=v,status="RAW_NOT_DIVISIBLE"))
                continue

            write_wave_variant(raw,at3,v,frames)

            ainfo,aprobe=ffprobe_json(ffprobe,at3,f"{name}_{v}_probe.log")
            aa=first_audio(ainfo)
            codec=aa.get("codec_name","") if aa else ""
            probe_duration=info_duration(ainfo)

            cp=run([ffmpeg,"-y","-v","warning","-i",at3,
                    "-map","0:a:0","-c:a","pcm_s16le",wav],
                   f"{name}_{v}_decode.log",300)

            winfo,wprobe=ffprobe_json(ffprobe,wav,f"{name}_{v}_wav_probe.log") if wav.exists() else (None,None)
            wa=first_audio(winfo)
            wdur=info_duration(winfo)
            decode_ok=(cp.returncode==0 and wav.exists() and wav.stat().st_size>44 and wa is not None)
            duration_delta=(wdur-pts_span) if (wdur is not None and pts_span is not None) else None
            full_ok=(decode_ok and duration_delta is not None and abs(duration_delta)<=0.50)

            status="FULL_OK" if full_ok else ("DECODE_OK_BAD_DURATION" if decode_ok else "DECODE_FAILED")
            trials.append(dict(
                movie=name,variant=v,status=status,
                at3_bytes=at3.stat().st_size if at3.exists() else "",
                ffprobe_audio="YES" if aa else "NO",
                ffprobe_codec=codec,
                ffprobe_duration=f"{probe_duration:.6f}" if probe_duration is not None else "",
                ffprobe_stderr=stderr_excerpt(aprobe.stderr if aprobe else ""),
                ffmpeg_returncode=cp.returncode,
                ffmpeg_stderr=stderr_excerpt(cp.stderr),
                wav_exists="YES" if wav.exists() else "NO",
                wav_bytes=wav.stat().st_size if wav.exists() else "",
                wav_duration=f"{wdur:.6f}" if wdur is not None else "",
                pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
                wav_vs_pts=f"{duration_delta:+.6f}" if duration_delta is not None else "",
            ))

            if full_ok and not chosen_variant:
                chosen_variant=v
                chosen_at3=str(at3)
                chosen_wav=str(wav)
                chosen_codec=codec
                chosen_wdur=wdur
                best_status="OK"
                decoded_full+=1
                # We already found a validated wrapper; no need to test later variants.
                break

        wdur_text=f"{chosen_wdur:.3f}" if chosen_wdur is not None else "N/A"
        pts_text=f"{pts_span:.3f}" if pts_span is not None else "N/A"
        theo_text=f"{theoretical:.3f}" if theoretical is not None else "N/A"

        results.append(dict(
            movie=name,status=best_status,
            substream_id=f"0x{chosen:02X}",
            private_stream_packets=r["counts"].get(0xBD,0),
            raw_bytes=len(raw),
            raw_gcd_global=g,
            frame_size=FRAME_SIZE,
            frame_size_hex=f"0x{FRAME_SIZE:X}",
            raw_divisible="YES" if divisible else "NO",
            frame_count=frames,
            theoretical_duration=f"{theoretical:.6f}" if theoretical is not None else "",
            pts_count=len(pvals),
            pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
            locator_recurrence=f"{good}/{total}",
            selected_variant=chosen_variant,
            selected_codec=chosen_codec,
            wav_duration=f"{chosen_wdur:.6f}" if chosen_wdur is not None else "",
            at3_path=chosen_at3,
            wav_path=chosen_wav,
            raw_path=str(raw_path),
            raw_sha256=sha256(raw_path),
        ))

        print(
            f"  raw={len(raw)} divisible={'YES' if divisible else 'NO'} "
            f"frames={frames} PTS={pts_text}s theoretical={theo_text}s "
            f"variant={chosen_variant or '(none)'} WAV={wdur_text}s "
            f"=> {best_status}",
            flush=True
        )

    write_tsv(STAGE/"fix3_extract_results.tsv",results)
    write_tsv(STAGE/"fix3_wrapper_trials.tsv",trials)
    write_tsv(STAGE/"fix3_private_packet_headers.tsv",packet_rows)

    summary=[
        "Naruto PSP MOV03K FIX3 - Robust ATRAC3+ wrapper trials",
        "="*80,"",
        f"Corrected raw-length GCD={g} (0x{g:X})",
        f"Expected frame size={FRAME_SIZE} (0x{FRAME_SIZE:X})",
        f"DM files with validated full-duration WAV={decoded_full}/10",
        "",
        "Wrapper variants tried:",
        *[f"  {v}" for v in VARIANTS],
        "",
        "FIX3 specifically fixes the prior crash:",
        "- None durations are printed as N/A, never formatted with :.3f.",
        "- A failed decoder does not stop the remaining DM files.",
        "- Every ffprobe/ffmpeg result and stderr excerpt is captured.",
        "",
        "If 0/10 still decode:",
        "- the demux/frame evidence remains preserved separately from RIFF wrapper success;",
        "- fix3_wrapper_trials.tsv will show whether FFmpeg recognizes the ATRAC3+ GUID",
        "  and the exact decoder error for each header variant.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0 if decoded_full==10 else 2

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
