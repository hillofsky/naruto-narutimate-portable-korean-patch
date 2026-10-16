#!/usr/bin/env python3
# Naruto PSP MOV03K FIX2 - Correct PSMF ATRAC3+ AU-locator demux
#
# Proven from FIX1 diagnostics:
# - private_stream_1 substream id = 0x00 for all dm001..dm010
# - private header is:
#       [stream_id:1][reserved:1][AU_locator:2, big endian]
# - after removing ALL 4 private-header bytes from each PES packet,
#   every DM raw stream length is exactly divisible by 0x2F0 (752).
# - 0x2F0 * frame_count at 2048 samples / 44100 Hz matches audio PTS span.
#
# This pass performs the corrected extraction and validates decoded WAV duration.

from __future__ import annotations
import csv, json, math, statistics, struct, subprocess, sys, traceback, hashlib
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
EXPECTED_FRAME_SIZE=0x2F0

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
    if cp.returncode!=0:return None
    try:return json.loads(cp.stdout)
    except:return None

def first_audio(info):
    if not info:return None
    for s in info.get("streams",[]):
        if s.get("codec_type")=="audio":return s
    return None

def info_duration(info):
    if not info:return None
    a=first_audio(info)
    for x in [(a or {}).get("duration"),info.get("format",{}).get("duration")]:
        try:return float(x)
        except:pass
    return None

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
        raise RuntimeError(f"{path.name}: bad data offset")

    pos=data_offset
    n=len(data)
    payloads=defaultdict(bytearray)
    pts=defaultdict(list)
    locators=defaultdict(list)
    packet_data_sizes=defaultdict(list)
    packet_rows=[]
    counts=Counter()

    while pos+6<=n:
        if data[pos:pos+3] != b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0:break
            pos=nxt
            continue

        sid=data[pos+3]
        counts[sid]+=1

        if sid==0xBA:
            if pos+14>n:break
            pos+=14+(data[pos+13]&7)
            continue
        if sid==0xB9:
            pos+=4
            continue

        plen=(data[pos+4]<<8)|data[pos+5]
        if plen==0:
            nxt=data.find(b"\x00\x00\x01\xBA",pos+6)
            if nxt<0:break
            pos=nxt
            continue

        end=pos+6+plen
        if end>n:break

        if sid==0xBD:
            p=pos+6
            payload=p
            pes_pts=None

            if p+3<=end and (data[p]&0xC0)==0x80:
                flags2=data[p+1]
                hlen=data[p+2]
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
                elif q<end and data[q]==0x0F:
                    q+=1
                payload=q

            # Sony private header:
            #   0: private stream id
            #   1: reserved
            #   2..3: AU locator, big-endian
            if payload+4<=end:
                subid=data[payload]
                reserved=data[payload+1]
                locator=struct.unpack_from(">H",data,payload+2)[0]
                es=data[payload+4:end]

                payloads[subid].extend(es)
                locators[subid].append(locator)
                packet_data_sizes[subid].append(len(es))
                if pes_pts is not None:
                    pts[subid].append(pes_pts)

                packet_rows.append(dict(
                    pes_file_offset=f"0x{pos:X}",
                    substream_id=f"0x{subid:02X}",
                    reserved=f"0x{reserved:02X}",
                    au_locator=locator,
                    es_bytes=len(es),
                    pts=pes_pts if pes_pts is not None else "",
                    es_head=es[:24].hex(" "),
                ))

        pos=end

    return dict(
        data_offset=data_offset,
        declared_data_size=declared_data_size,
        counts=counts,payloads=payloads,pts=pts,
        locators=locators,packet_data_sizes=packet_data_sizes,
        packet_rows=packet_rows,
    )

def validate_locator_recurrence(locators,sizes,frame_size):
    # If L_i is bytes from packet payload start to next AU,
    # then (payload_i - L_i + L_{i+1}) should be an integer multiple of frame size.
    rows=[]
    good=0
    total=0
    for i in range(min(len(locators)-1,len(sizes)-1)):
        li=locators[i]
        ln=locators[i+1]
        plen=sizes[i]
        value=plen-li+ln
        rem=value%frame_size
        ok=(rem==0)
        total+=1
        good+=int(ok)
        rows.append((i,li,ln,plen,value,rem,ok))
    return rows,good,total

def make_at3_wave(raw,frame_size,out_path):
    frames=len(raw)//frame_size
    samples=frames*SAMPLES_PER_FRAME
    avg_bps=int(frame_size*SAMPLE_RATE/SAMPLES_PER_FRAME)

    fmt=bytearray()
    fmt += struct.pack("<H",0xFFFE)
    fmt += struct.pack("<H",CHANNELS)
    fmt += struct.pack("<I",SAMPLE_RATE)
    fmt += struct.pack("<I",avg_bps)
    fmt += struct.pack("<H",frame_size)
    fmt += struct.pack("<H",0)
    fmt += struct.pack("<H",0x22)
    fmt += struct.pack("<H",SAMPLES_PER_FRAME)
    fmt += struct.pack("<I",CHANNEL_MASK)
    fmt += ATRAC3P_GUID
    fmt += b"\x00"*12
    assert len(fmt)==52

    fact=struct.pack("<Q",samples)
    body=bytearray()
    body += b"fmt " + struct.pack("<I",len(fmt)) + fmt
    body += b"fact" + struct.pack("<I",len(fact)) + fact
    body += b"data" + struct.pack("<I",len(raw)) + raw

    riff=b"WAVE"+bytes(body)
    out_path.write_bytes(b"RIFF"+struct.pack("<I",len(riff))+riff)
    return frames,samples,avg_bps

def main():
    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03K FIX2 - Correct AU-locator ATRAC3+ demux",flush=True)
    print("="*80,flush=True)

    all_raw_lens=[]
    parsed={}
    packet_rows=[]

    # First pass: corrected demux.
    for name in DM:
        src=KR_MOV/(name+".pmf")
        if not src.exists():
            raise RuntimeError(f"Missing {src}")
        r=parse_pmf_private(src)
        candidates=[sid for sid in r["payloads"] if sid<0x10]
        if not candidates:
            raise RuntimeError(f"{name}: no Sony ATRAC private substream")
        chosen=max(candidates,key=lambda sid:len(r["payloads"][sid]))
        raw=bytes(r["payloads"][chosen])

        parsed[name]=(r,chosen,raw)
        all_raw_lens.append(len(raw))
        for row in r["packet_rows"]:
            row=dict(movie=name,**row)
            packet_rows.append(row)

    # Strong global proof: gcd of all corrected raw lengths.
    g=0
    for x in all_raw_lens:
        g=math.gcd(g,x)

    if g != EXPECTED_FRAME_SIZE:
        raise RuntimeError(
            f"Corrected raw-length GCD is {g} (0x{g:X}), expected "
            f"{EXPECTED_FRAME_SIZE} (0x{EXPECTED_FRAME_SIZE:X})"
        )

    rows=[]
    locator_rows=[]
    wav_ok=0

    for i,name in enumerate(DM,1):
        r,chosen,raw=parsed[name]
        print(f"[{i:02d}/10] {name}",flush=True)

        raw_path=RAW_DIR/f"{name}_sub{chosen:02X}_correct.raw"
        at3=AUDIO_DIR/f"{name}_kr_correct.at3"
        wav=AUDIO_DIR/f"{name}_kr_correct.wav"

        for p in (raw_path,at3,wav):
            if p.exists():p.unlink()

        raw_path.write_bytes(raw)

        if len(raw)%EXPECTED_FRAME_SIZE:
            raise RuntimeError(f"{name}: corrected raw not divisible by 0x2F0")

        locs=r["locators"][chosen]
        sizes=r["packet_data_sizes"][chosen]
        lrows,good,total=validate_locator_recurrence(locs,sizes,EXPECTED_FRAME_SIZE)

        for ix,li,ln,plen,val,rem,ok in lrows:
            locator_rows.append(dict(
                movie=name,packet_index=ix,
                locator_current=li,locator_next=ln,
                payload_bytes=plen,
                recurrence_value=val,
                frame_size=EXPECTED_FRAME_SIZE,
                remainder=rem,
                recurrence_ok="YES" if ok else "NO",
            ))

        pvals=r["pts"][chosen]
        pts_span=(pvals[-1]-pvals[0])/90000.0 if len(pvals)>=2 else None
        pts_deltas=[b-a for a,b in zip(pvals,pvals[1:]) if b>=a]
        pts_median=statistics.median(pts_deltas) if pts_deltas else None

        frames,samples,avg=make_at3_wave(raw,EXPECTED_FRAME_SIZE,at3)
        theoretical=frames*SAMPLES_PER_FRAME/SAMPLE_RATE

        ainfo=ffprobe_json(ffprobe,at3,f"{name}_fix2_at3_probe.log")
        aa=first_audio(ainfo)

        cp=run([
            ffmpeg,"-y","-v","warning",
            "-i",at3,
            "-map","0:a:0",
            "-c:a","pcm_s16le",
            wav
        ],f"{name}_fix2_decode.log",300)

        winfo=ffprobe_json(ffprobe,wav,f"{name}_fix2_wav_probe.log") if wav.exists() else None
        wa=first_audio(winfo)
        wdur=info_duration(winfo)

        decode_ok=(cp.returncode==0 and wav.exists() and wav.stat().st_size>44 and wa is not None)
        duration_ok=(
            decode_ok and pts_span is not None and wdur is not None
            and abs(wdur-pts_span)<=0.25
        )
        success=decode_ok and duration_ok

        if success:wav_ok+=1

        rows.append(dict(
            movie=name,
            status="OK" if success else ("DECODE_OK_DURATION_BAD" if decode_ok else "DECODE_FAILED"),
            substream_id=f"0x{chosen:02X}",
            private_stream_packets=r["counts"].get(0xBD,0),
            corrected_raw_bytes=len(raw),
            frame_size=EXPECTED_FRAME_SIZE,
            frame_size_hex=f"0x{EXPECTED_FRAME_SIZE:X}",
            frame_remainder=len(raw)%EXPECTED_FRAME_SIZE,
            frame_count=frames,
            theoretical_duration=f"{theoretical:.6f}",
            pts_count=len(pvals),
            pts_span_sec=f"{pts_span:.6f}" if pts_span is not None else "",
            median_pts_delta=f"{pts_median:.3f}" if pts_median is not None else "",
            locator_recurrence_ok=f"{good}/{total}",
            at3_ffprobe_audio="YES" if aa else "NO",
            at3_codec=aa.get("codec_name","") if aa else "",
            wav_decode_success="YES" if decode_ok else "NO",
            wav_duration=f"{wdur:.6f}" if wdur is not None else "",
            wav_vs_pts_delta=f"{(wdur-pts_span):+.6f}" if (wdur is not None and pts_span is not None) else "",
            wav_duration_validation="PASS" if duration_ok else "FAIL",
            raw_path=str(raw_path),
            at3_path=str(at3),
            wav_path=str(wav) if wav.exists() else "",
            raw_sha256=sha256(raw_path),
            at3_sha256=sha256(at3),
            wav_sha256=sha256(wav) if wav.exists() else "",
        ))

        print(
            f"  raw={len(raw)} /0x2F0={frames} frames "
            f"PTS={pts_span:.3f}s theoretical={theoretical:.3f}s "
            f"WAV={wdur:.3f}s "
            f"locator={good}/{total} "
            f"=> {'OK' if success else 'FAIL'}",
            flush=True
        )

    write_tsv(STAGE/"fix2_extract_results.tsv",rows)
    write_tsv(STAGE/"fix2_au_locator_recurrence.tsv",locator_rows)
    write_tsv(STAGE/"fix2_private_packet_headers.tsv",packet_rows)

    summary=[
        "Naruto PSP MOV03K FIX2 - Correct AU-locator ATRAC3+ demux",
        "="*80,"",
        f"Corrected raw-length GCD across dm001..dm010={g} (0x{g:X})",
        f"Expected/validated ATRAC3+ frame size={EXPECTED_FRAME_SIZE} (0x{EXPECTED_FRAME_SIZE:X})",
        f"DM files with validated full-length PCM WAV={wav_ok}/10",
        "",
        "Correct private_stream_1 layout:",
        "  byte 0  : Sony private stream id (0x00 here)",
        "  byte 1  : reserved",
        "  byte 2-3: big-endian AU locator",
        "  byte 4+ : ATRAC3+ elementary payload",
        "",
        "Validation:",
        "- all corrected raw streams must divide exactly by 0x2F0",
        "- AU-locator recurrence is checked packet-to-packet",
        "- decoded WAV duration must be within 0.25 sec of PES PTS span",
        "",
        "Local outputs:",
        f"  {RAW_DIR}",
        f"  {AUDIO_DIR}",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    return 0 if wav_ok==10 else 2

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
