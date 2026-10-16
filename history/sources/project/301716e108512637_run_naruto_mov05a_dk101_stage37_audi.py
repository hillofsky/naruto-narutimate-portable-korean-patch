#!/usr/bin/env python3
# Naruto PSP MOV05A
# Locate KR dk101 inside existing Stage37 local YouTube/playthrough videos
# using the KR PMF's original Japanese audio as the primary fingerprint.
#
# Inputs:
#   PROJECT_ROOT\analysis\stage37\video\source_video.mp4
#   PROJECT_ROOT\analysis\stage37\video\part2.mp4
#   PROJECT_ROOT\kr_extracted\PSP_GAME\USRDIR\movie\dk101.pmf
#
# No YouTube download.
# No ISO modification.
# No OCR used for alignment.
#
# Outputs include top audio matches and paired KR/Stage37 review frames.

from __future__ import annotations
import csv, hashlib, math, os, struct, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
STAGE37 = ROOT / "analysis" / "stage37"
VIDEO_DIR = STAGE37 / "video"
SOURCES = [
    VIDEO_DIR / "source_video.mp4",
    VIDEO_DIR / "part2.mp4",
]
KR_PMF = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie" / "dk101.pmf"

STAGE = ROOT / "analysis" / "mov" / "mov05a_dk101_stage37_audio_match"
WORK = STAGE / "work"
REP = STAGE / "representatives"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, REP, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

SECTOR = 2048
LOGICAL_AU = 752
ATRAC_FRAME = 744
AU_HEADER = bytes.fromhex("0FD0285C00000000")
SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 2048
EA3_HEADER_SIZE = 96

# Audio matching:
DECODE_RATE = 8000
ENV_HZ = 20.0
WIN_SAMPLES = int(DECODE_RATE / ENV_HZ)  # 400 = 50 ms
TOP_N = 8
MIN_SEPARATION_SEC = 20.0

def run(cmd, logname, timeout=1800):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout
    )
    txt = "COMMANLOCAL_PATH" + " ".join(('"%s"' % str(x) if " " in str(x) else str(x)) for x in cmd)
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout
    txt += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(txt, encoding="utf-8-sig")
    return cp

def write_tsv(path, rows):
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def parse_ps_stream(data,start_offset=0):
    pos=start_offset;n=len(data)
    audio=[]
    while pos+6<=n:
        if data[pos:pos+3]!=b"\x00\x00\x01":
            nxt=data.find(b"\x00\x00\x01",pos+1)
            if nxt<0: break
            pos=nxt; continue

        sid=data[pos+3]

        if sid==0xBA:
            if pos+14>n:break
            pos += 14 + (data[pos+13] & 7)
            continue
        if sid==0xB9:
            pos += 4
            continue

        plen=(data[pos+4]<<8)|data[pos+5]
        if plen==0:
            nxt=data.find(b"\x00\x00\x01\xBA",pos+6)
            if nxt<0:break
            pos=nxt;continue
        end=pos+6+plen
        if end>n:break

        if sid==0xBD:
            p=pos+6;payload=p
            if p+3<=end and (data[p]&0xC0)==0x80:
                hlen=data[p+2]
                payload=p+3+hlen
            else:
                q=p
                while q<end and data[q]==0xFF:q+=1
                if q+2<=end and (data[q]&0xC0)==0x40:q+=2
                if q<end and (data[q]&0xF0) in (0x20,0x30):
                    q+=5 if (data[q]&0xF0)==0x20 else 10
                elif q<end and data[q]==0x0F:q+=1
                payload=q
            audio.append(dict(start=pos,end=end,payload=payload))
        pos=end
    return audio

def recover_kr_atrac(path):
    data=Path(path).read_bytes()
    if len(data)<0x800 or data[:4]!=b"PSMF":
        raise RuntimeError("dk101 is not a PSMF/PMF file")
    off=struct.unpack_from(">I",data,8)[0]
    pes=parse_ps_stream(data,off)

    logical=bytearray()
    for p in pes:
        private=data[p["payload"]:p["end"]]
        # This is the same KR private-audio extraction rule already proven in MOV03S/MOV04C.
        if len(private)>=4 and private[0]<0x10:
            logical += private[4:]

    logical=bytes(logical)
    if not logical or len(logical)%LOGICAL_AU:
        raise RuntimeError(f"Recovered logical audio length invalid: {len(logical)}")

    frames=bytearray()
    bad=0
    for i in range(0,len(logical),LOGICAL_AU):
        au=logical[i:i+LOGICAL_AU]
        if au[:8]!=AU_HEADER:
            bad+=1
        frames += au[8:]
    if bad:
        raise RuntimeError(f"Unexpected AU header count: {bad}")
    if len(frames)%ATRAC_FRAME:
        raise RuntimeError("Recovered ATRAC payload not divisible by 744")

    return bytes(frames), len(frames)//ATRAC_FRAME, len(pes)

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

def decode_pcm(source,out_pcm,tag,is_oma=False):
    cmd=[FFMPEG,"-y","-v","warning"]
    if is_oma:
        cmd += ["-f","oma"]
    cmd += ["-i",source,"-vn","-ac","1","-ar",str(DECODE_RATE),"-f","s16le","-c:a","pcm_s16le",out_pcm]
    cp=run(cmd,tag,2400)
    if cp.returncode!=0 or not Path(out_pcm).exists() or Path(out_pcm).stat().st_size<1000:
        raise RuntimeError(f"PCM decode failed: {source}")

def load_pcm_np(path):
    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError("NumPy is required for MOV05A audio matching: "+str(e))
    return np.fromfile(path,dtype="<i2").astype(np.float32)/32768.0

def envelope(x):
    import numpy as np
    n=(len(x)//WIN_SAMPLES)*WIN_SAMPLES
    if n<=0: return np.zeros(0,dtype=np.float32)
    y=x[:n].reshape(-1,WIN_SAMPLES)
    # RMS -> log envelope. Remove DC-related near-silence instability.
    rms=np.sqrt(np.mean(y*y,axis=1)+1e-10)
    return np.log1p(rms*20.0).astype(np.float32)

def resample_vector(x,factor):
    import numpy as np
    if abs(factor-1.0)<1e-9:
        return x.copy()
    n=max(8,int(round(len(x)*factor)))
    old=np.linspace(0.0,1.0,len(x),endpoint=True)
    new=np.linspace(0.0,1.0,n,endpoint=True)
    return np.interp(new,old,x).astype(np.float32)

def nextpow2(n):
    return 1<<(int(n-1).bit_length())

def norm_xcorr_valid(source,query):
    """
    Normalized sliding correlation, valid positions only.
    query is z-normalized. local source mean/variance handled analytically.
    """
    import numpy as np
    m=len(query); n=len(source)
    if m<10 or n<m:
        return np.zeros(0,dtype=np.float32)

    q=query.astype(np.float64)
    q=q-np.mean(q)
    qnorm=np.sqrt(np.sum(q*q))
    if qnorm<1e-9:
        raise RuntimeError("Query envelope variance too small")

    x=source.astype(np.float64)

    # FFT convolution x * reversed(q)
    L=nextpow2(n+m-1)
    X=np.fft.rfft(x,L)
    Q=np.fft.rfft(q[::-1],L)
    conv=np.fft.irfft(X*Q,L)
    numer=conv[m-1:n]

    # Rolling local variance of source.
    cs=np.concatenate(([0.0],np.cumsum(x)))
    cs2=np.concatenate(([0.0],np.cumsum(x*x)))
    sx=cs[m:]-cs[:-m]
    sx2=cs2[m:]-cs2[:-m]
    var=np.maximum(sx2-(sx*sx)/m,1e-12)
    denom=np.sqrt(var)*qnorm

    corr=numer/denom
    return np.clip(corr,-1.0,1.0).astype(np.float32)

def select_peaks(corr,top_n=TOP_N):
    import numpy as np
    if len(corr)==0:return []
    order=np.argsort(corr)[::-1]
    chosen=[]
    sep=int(round(MIN_SEPARATION_SEC*ENV_HZ))
    for idx in order:
        idx=int(idx)
        if all(abs(idx-j)>=sep for j,_ in chosen):
            chosen.append((idx,float(corr[idx])))
            if len(chosen)>=top_n:break
    return chosen

def probe_duration(path,tag):
    cp=run([FFPROBE,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path],tag,120)
    if cp.returncode!=0:return None
    try:return float(cp.stdout.strip())
    except:return None

def extract_frame(src,sec,out,tag):
    cp=run(
        [FFMPEG,"-y","-v","error","-ss",f"{sec:.3f}","-i",src,
         "-frames:v","1","-q:v","2",out],
        tag,180
    )
    return cp.returncode==0 and Path(out).exists()

def inventory_stage37():
    rows=[]
    if not STAGE37.exists():
        return rows
    exts={".csv",".tsv",".json",".txt",".log",".md",".srt",".ass"}
    for p in STAGE37.rglob("*"):
        if not p.is_file():continue
        if p.suffix.lower() not in exts:continue
        try:
            rel=str(p.relative_to(ROOT))
            rows.append(dict(
                path=rel,
                bytes=p.stat().st_size,
                modified=str(p.stat().st_mtime),
            ))
        except Exception:
            pass
    rows.sort(key=lambda r:r["path"].lower())
    return rows

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("LOCAL_PATH / ffprobe.exe missing")
    if not KR_PMF.exists():
        raise RuntimeError(f"KR dk101 missing: {KR_PMF}")
    for s in SOURCES:
        if not s.exists():
            raise RuntimeError(f"Stage37 source video missing: {s}")

    failure=STAGE/"FAILURE.txt"
    if failure.exists():failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV05A - dk101 Stage37 audio locator",flush=True)
    print("="*80,flush=True)

    # Inventory prior Stage37 analysis records before doing any new matching.
    inv=inventory_stage37()
    write_tsv(STAGE/"stage37_existing_analysis_inventory.tsv",inv)
    print(f"Existing Stage37 text/log artifacts indexed: {len(inv)}",flush=True)

    # Recover exact KR Japanese audio.
    frames,frame_count,pes_count=recover_kr_atrac(KR_PMF)
    oma=WORK/"dk101_kr.oma"
    build_oma(frames,oma)
    kr_pcm=WORK/"dk101_kr_8k_mono.s16"
    decode_pcm(oma,kr_pcm,"01_decode_kr_dk101.log",is_oma=True)

    q_pcm=load_pcm_np(kr_pcm)
    q_env=envelope(q_pcm)
    q_duration=len(q_pcm)/DECODE_RATE

    print(
        f"KR dk101: ATRAC frames={frame_count}, audio PES={pes_count}, "
        f"decoded duration={q_duration:.3f}s, envelope={len(q_env)}",
        flush=True
    )

    candidates=[]
    source_info=[]

    # Small scale grid handles 29.97/30 conversion or upload resampling drift.
    scales=[0.997,1.000,1.003]

    for si,src in enumerate(SOURCES,1):
        tag=src.stem
        print(f"[{si:02d}/02] scanning {src.name}",flush=True)
        dur=probe_duration(src,f"02_{tag}_probe_duration.log")

        pcm=WORK/f"{tag}_8k_mono.s16"
        decode_pcm(src,pcm,f"03_{tag}_decode_audio.log",is_oma=False)
        x_pcm=load_pcm_np(pcm)
        x_env=envelope(x_pcm)

        best_for_source=[]
        for scale in scales:
            q=resample_vector(q_env,scale)
            corr=norm_xcorr_valid(x_env,q)
            peaks=select_peaks(corr,TOP_N)
            for idx,score in peaks:
                offset=idx/ENV_HZ
                best_for_source.append(dict(
                    source=src.name,
                    source_path=str(src),
                    scale=f"{scale:.3f}",
                    offset_sec=f"{offset:.3f}",
                    correlation=f"{score:.6f}",
                    query_duration_sec=f"{q_duration:.3f}",
                    source_duration_sec=f"{dur:.3f}" if dur is not None else "",
                    envelope_index=idx,
                ))

        best_for_source.sort(key=lambda r:float(r["correlation"]),reverse=True)

        # De-duplicate close offsets across scale hypotheses.
        dedup=[]
        for r in best_for_source:
            off=float(r["offset_sec"])
            if all(abs(off-float(x["offset_sec"]))>=5.0 for x in dedup):
                dedup.append(r)
            if len(dedup)>=TOP_N:break

        candidates.extend(dedup)
        source_info.append(dict(
            source=src.name,
            duration_sec=f"{dur:.3f}" if dur is not None else "",
            pcm_samples=len(x_pcm),
            envelope_frames=len(x_env),
            best_correlation=dedup[0]["correlation"] if dedup else "",
            best_offset_sec=dedup[0]["offset_sec"] if dedup else "",
            best_scale=dedup[0]["scale"] if dedup else "",
        ))

        if dedup:
            print(
                f"  best offset={dedup[0]['offset_sec']}s "
                f"corr={dedup[0]['correlation']} scale={dedup[0]['scale']}",
                flush=True
            )

    candidates.sort(key=lambda r:float(r["correlation"]),reverse=True)
    for i,r in enumerate(candidates,1):
        r["global_rank"]=i

    write_tsv(STAGE/"audio_match_candidates.tsv",candidates)
    write_tsv(STAGE/"source_summary.tsv",source_info)

    if not candidates:
        raise RuntimeError("No audio match candidates produced")

    # Generate review frames for global top 4 candidates.
    review=[]
    rel_times=[8.0, 30.0, 60.0, min(100.0,max(8.0,q_duration-8.0))]
    top=candidates[:4]

    for rank,c in enumerate(top,1):
        src=Path(c["source_path"])
        off=float(c["offset_sec"])
        scale=float(c["scale"])

        for k,qt in enumerate(rel_times,1):
            # If query envelope was stretched, source progression is scaled similarly.
            src_t=off + qt*scale
            kr_t=qt

            s_img=REP/f"rank{rank:02d}_{src.stem}_src_t{src_t:09.3f}_q{qt:06.3f}.jpg"
            k_img=REP/f"rank{rank:02d}_KR_dk101_t{kr_t:06.3f}.jpg"

            sok=extract_frame(src,src_t,s_img,f"04_rank{rank}_{k}_source_frame.log")
            kok=extract_frame(KR_PMF,kr_t,k_img,f"05_rank{rank}_{k}_kr_frame.log")

            review.append(dict(
                rank=rank,
                source=src.name,
                correlation=c["correlation"],
                scale=c["scale"],
                source_offset_sec=c["offset_sec"],
                query_time_sec=f"{qt:.3f}",
                source_time_sec=f"{src_t:.3f}",
                source_frame=str(s_img) if sok else "",
                kr_frame=str(k_img) if kok else "",
            ))

    write_tsv(STAGE/"review_frames.tsv",review)

    best=candidates[0]
    best_corr=float(best["correlation"])
    # Do not hard-claim a match solely from audio; confidence labels are diagnostic.
    if best_corr>=0.80:
        confidence="VERY_HIGH"
    elif best_corr>=0.60:
        confidence="HIGH"
    elif best_corr>=0.40:
        confidence="POSSIBLE"
    else:
        confidence="WEAK"

    summary=[
        "Naruto PSP MOV05A - dk101 Stage37 audio locator",
        "="*80,"",
        "Existing local Stage37 sources:",
        f"  {SOURCES[0]}",
        f"  {SOURCES[1]}",
        "",
        f"KR dk101 decoded audio duration={q_duration:.3f}s",
        f"KR ATRAC frames={frame_count}",
        f"KR audio PES={pes_count}",
        "",
        "Best candidate:",
        f"  source={best['source']}",
        f"  offset={best['offset_sec']} sec",
        f"  audio correlation={best['correlation']}",
        f"  scale={best['scale']}",
        f"  diagnostic confidence={confidence}",
        "",
        "Review paired source/KR frames in representatives/.",
        "If the same scene is confirmed, MOV05B can crop/retime that exact",
        "Stage37 interval and rebuild dk101 with KR original ATRAC/PTS.",
        "",
        f"Prior Stage37 text/log artifacts indexed={len(inv)}",
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
