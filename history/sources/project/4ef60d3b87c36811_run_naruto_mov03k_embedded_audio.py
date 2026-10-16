#!/usr/bin/env python3
# Naruto PSP MOV03K - Extract embedded PMF audio with FFmpeg
#
# MOV03J proved dm001..dm010 all contain MPEG private_stream_1 (0xBD).
# Modern FFmpeg supports ATRAC3+ audio carried in Sony PSMF/MPS private stream.
#
# This stage:
#  - ffprobes KR dm001..dm010 and US counterparts
#  - extracts KR first audio stream to PCM WAV
#  - attempts bit-exact ATRAC3+ copy to OMA when FFmpeg's OMA muxer supports it
#  - validates duration against PMF duration
#  - keeps extracted audio locally but excludes it from upload ZIP
#
# No patching.

from __future__ import annotations
import csv, json, subprocess, sys, traceback, hashlib
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"
STAGE = ROOT / "analysis" / "mov" / "mov03k_embedded_audio"
AUDIO_DIR = STAGE / "audio"
LOG_DIR = STAGE / "logs"
STAGE.mkdir(parents=True,exist_ok=True)
AUDIO_DIR.mkdir(parents=True,exist_ok=True)
LOG_DIR.mkdir(parents=True,exist_ok=True)

DM = [f"dm{i:03d}" for i in range(1,11)]

KNOWN_DURATION = {
    "dm001":53.620,
    "dm002":36.770,
    "dm003":66.600,
    "dm004":72.039,
    "dm005":66.366,
    "dm006":58.358,
    "dm007":59.826,
    "dm008":49.550,
    "dm009":59.960,
    "dm010":119.486,
}

def write_tsv(path, rows, fields=None):
    path=Path(path)
    if fields is None:
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def find_tool(name):
    cands=[
        Path(r"LOCAL_PATH") / (name+".exe"),
        Path(r"LOCAL_PATH") / (name+".EXE"),
    ]
    for p in cands:
        if p.exists():
            return p
    try:
        cp=subprocess.run(["where.exe",name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding="utf-8",errors="replace",timeout=10)
        for line in cp.stdout.splitlines():
            p=Path(line.strip())
            if p.exists():
                return p
    except Exception:
        pass
    return None

def run(cmd, logname, timeout=180):
    cp=subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding="utf-8",errors="replace",
        timeout=timeout
    )
    text="COMMANLOCAL_PATH"+" ".join('"%s"'%str(x) if " " in str(x) else str(x) for x in cmd)+"\n\n"
    text+="STDOULOCAL_PATH"+cp.stdout+"\n\nSTDERLOCAL_PATH"+cp.stderr+"\n"
    (LOG_DIR/logname).write_text(text,encoding="utf-8-sig")
    return cp

def ffprobe_json(ffprobe, path, logname):
    cp=run([
        ffprobe,"-v","error",
        "-show_streams","-show_format",
        "-of","json",path
    ],logname,120)
    if cp.returncode!=0:
        return None
    try:
        return json.loads(cp.stdout)
    except Exception:
        return None

def first_stream(info, codec_type):
    if not info:
        return None
    for s in info.get("streams",[]):
        if s.get("codec_type")==codec_type:
            return s
    return None

def tofloat(x):
    try:return float(x)
    except:return None

def stream_duration(stream, info):
    if stream:
        d=tofloat(stream.get("duration"))
        if d is not None:return d
        tb=stream.get("time_base")
        dur_ts=stream.get("duration_ts")
        if tb and dur_ts not in (None,"N/A"):
            try:
                a,b=tb.split("/")
                return float(dur_ts)*float(a)/float(b)
            except:pass
    if info:
        return tofloat(info.get("format",{}).get("duration"))
    return None

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def us_candidates(name):
    out=[]
    for fn in (name+"e.pmf",name+".pmf"):
        p=US_MOV/fn
        if p.exists():
            out.append(p)
    return out

def main():
    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg:
        raise RuntimeError("ffmpeg.exe not found. Expected LOCAL_PATH")
    if not ffprobe:
        raise RuntimeError("ffprobe.exe not found. Expected LOCAL_PATH")

    print("="*80,flush=True)
    print(" Naruto PSP MOV03K - Embedded PMF audio extraction",flush=True)
    print("="*80,flush=True)
    print(f"ffmpeg : {ffmpeg}",flush=True)
    print(f"ffprobe: {ffprobe}",flush=True)

    rows=[]
    usrows=[]
    extracted=0
    oma_ok=0
    exactish=0

    for idx,name in enumerate(DM,1):
        src=KR_MOV/(name+".pmf")
        if not src.exists():
            rows.append(dict(movie=name,status="MISSING_KR_PMF"))
            continue

        print(f"[{idx:02d}/10] {name}",flush=True)

        info=ffprobe_json(ffprobe,src,f"{name}_kr_ffprobe.log")
        a=first_stream(info,"audio")
        v=first_stream(info,"video")
        if a is None:
            rows.append(dict(
                movie=name,status="NO_AUDIO_STREAM",
                kr_pmf=str(src),kr_bytes=src.stat().st_size,
                video_codec=v.get("codec_name","") if v else "",
            ))
            continue

        adur=stream_duration(a,info)
        vdur=stream_duration(v,info)
        known=KNOWN_DURATION[name]

        wav=AUDIO_DIR/(name+"_kr.wav")
        oma=AUDIO_DIR/(name+"_kr.oma")
        for p in (wav,oma):
            if p.exists():
                p.unlink()

        # PCM extraction - independent of OMA muxing support.
        cp=run([
            ffmpeg,"-y","-v","warning",
            "-i",src,
            "-map","0:a:0",
            "-vn",
            "-c:a","pcm_s16le",
            wav
        ],f"{name}_extract_wav.log",300)

        wav_info=ffprobe_json(ffprobe,wav,f"{name}_wav_ffprobe.log") if wav.exists() else None
        wav_a=first_stream(wav_info,"audio")
        wav_dur=stream_duration(wav_a,wav_info)

        wav_success=(cp.returncode==0 and wav.exists() and wav.stat().st_size>44 and wav_a is not None)
        if wav_success:
            extracted+=1

        # Bitstream-preserving ATRAC3+ extraction if OMA muxer supports this.
        ocp=run([
            ffmpeg,"-y","-v","warning",
            "-i",src,
            "-map","0:a:0",
            "-vn",
            "-c:a","copy",
            oma
        ],f"{name}_extract_oma.log",300)

        oma_info=ffprobe_json(ffprobe,oma,f"{name}_oma_ffprobe.log") if oma.exists() else None
        oma_a=first_stream(oma_info,"audio")
        oma_dur=stream_duration(oma_a,oma_info)
        oma_success=(ocp.returncode==0 and oma.exists() and oma.stat().st_size>0 and oma_a is not None)
        if oma_success:
            oma_ok+=1

        compare_dur=wav_dur if wav_dur is not None else adur
        delta=(compare_dur-known) if compare_dur is not None else None
        if delta is not None and abs(delta)<=0.5:
            exactish+=1

        row=dict(
            movie=name,status="OK" if wav_success else "WAV_EXTRACT_FAILED",
            kr_pmf=str(src),kr_pmf_bytes=src.stat().st_size,
            video_codec=v.get("codec_name","") if v else "",
            video_width=v.get("width","") if v else "",
            video_height=v.get("height","") if v else "",
            video_duration=f"{vdur:.6f}" if vdur is not None else "",
            audio_codec=a.get("codec_name",""),
            audio_codec_long=a.get("codec_long_name",""),
            audio_sample_rate=a.get("sample_rate",""),
            audio_channels=a.get("channels",""),
            audio_channel_layout=a.get("channel_layout",""),
            audio_bit_rate=a.get("bit_rate",""),
            audio_duration=f"{adur:.6f}" if adur is not None else "",
            known_pmf_duration=f"{known:.6f}",
            wav_path=str(wav) if wav_success else "",
            wav_bytes=wav.stat().st_size if wav_success else "",
            wav_duration=f"{wav_dur:.6f}" if wav_dur is not None else "",
            duration_delta_vs_known=f"{delta:+.6f}" if delta is not None else "",
            duration_match_le_0_5s="YES" if delta is not None and abs(delta)<=0.5 else "NO",
            oma_copy_success="YES" if oma_success else "NO",
            oma_path=str(oma) if oma_success else "",
            oma_bytes=oma.stat().st_size if oma_success else "",
            oma_duration=f"{oma_dur:.6f}" if oma_dur is not None else "",
            oma_codec=oma_a.get("codec_name","") if oma_a else "",
            wav_sha256=sha256(wav) if wav_success else "",
            oma_sha256=sha256(oma) if oma_success else "",
        )
        rows.append(row)

        print(
            f"  PMF audio={row['audio_codec']} "
            f"{row['audio_sample_rate']}Hz ch={row['audio_channels']} "
            f"dur={row['audio_duration']} | WAV={'OK' if wav_success else 'FAIL'} "
            f"| OMA={'OK' if oma_success else 'FAIL'}",
            flush=True
        )

        # Probe US clean/localized counterpart(s), but do not extract them.
        for up in us_candidates(name):
            ui=ffprobe_json(ffprobe,up,f"{up.stem}_us_ffprobe.log")
            ua=first_stream(ui,"audio");uv=first_stream(ui,"video")
            uad=stream_duration(ua,ui);uvd=stream_duration(uv,ui)
            usrows.append(dict(
                movie=name,us_file=up.name,us_path=str(up),us_bytes=up.stat().st_size,
                video_codec=uv.get("codec_name","") if uv else "",
                video_duration=f"{uvd:.6f}" if uvd is not None else "",
                audio_present="YES" if ua else "NO",
                audio_codec=ua.get("codec_name","") if ua else "",
                audio_sample_rate=ua.get("sample_rate","") if ua else "",
                audio_channels=ua.get("channels","") if ua else "",
                audio_duration=f"{uad:.6f}" if uad is not None else "",
                duration_delta_vs_kr=f"{(uad-adur):+.6f}" if (uad is not None and adur is not None) else "",
            ))

    write_tsv(STAGE/"kr_dm_embedded_audio.tsv",rows)
    write_tsv(STAGE/"us_dm_counterpart_streams.tsv",usrows)

    # Simple codec/layout consistency.
    okrows=[r for r in rows if r.get("status")=="OK"]
    codecs=sorted(set(r.get("audio_codec","") for r in okrows))
    rates=sorted(set(str(r.get("audio_sample_rate","")) for r in okrows))
    channels=sorted(set(str(r.get("audio_channels","")) for r in okrows))

    summary=[
        "Naruto PSP MOV03K - Embedded PMF audio extraction",
        "="*80,"",
        f"KR DM PMFs with successful PCM WAV extraction={extracted}/10",
        f"KR DM PMFs with successful bitstream OMA extraction={oma_ok}/10",
        f"Audio durations matching known PMF duration within 0.5 sec={exactish}/10",
        f"Detected audio codecs={','.join(codecs) if codecs else '(none)'}",
        f"Detected sample rates={','.join(rates) if rates else '(none)'}",
        f"Detected channel counts={','.join(channels) if channels else '(none)'}",
        f"US counterpart stream rows={len(usrows)}",
        "",
        "Interpretation:",
        "- Successful WAV extraction proves usable embedded audio independently of psmfdump.",
        "- Successful OMA copy preserves the encoded ATRAC stream for later remuxing.",
        "- Extracted WAV/OMA files remain under analysis\\mov\\mov03k_embedded_audio\\audio",
        "  and are intentionally excluded from the compact upload ZIP.",
        "- If OMA copy fails but WAV succeeds, the final PMF rebuild can re-encode WAV",
        "  to ATRAC3+ during muxing.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary),flush=True)

    # Require all 10 to produce WAV. OMA is optional.
    return 0 if extracted==10 else 2

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
