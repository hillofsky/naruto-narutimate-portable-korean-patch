#!/usr/bin/env python3
# Naruto PSP MOV03Q - dm001 Korean subtitle video smoke test
#
# Final target architecture:
#   Visual source : US dm001e.pmf (clean, subtitle-free)
#   Subtitle time : MOV03N FIX5 KR timeline
#   Subtitle text : MOV03P Korean translation
#   Final audio   : KR dm001 original Japanese ATRAC3+ (NOT US English audio)
#
# This stage validates the VIDEO side only:
#   US clean PMF
#      -> burn Korean ASS subtitles using KR timing
#      -> lossless FFV1 intermediate
#      -> oMPSComposer video-only (- audio)
#      -> Mps2Pmf
#      -> PSP video-only PMF
#
# A PC preview is also created with the recovered KR Japanese audio.
# No at3tool.exe is required for this stage.
#
# The video-only PMF's padding/sector layout is inventoried for the next
# lossless KR ATRAC3+ mux stage.

from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, struct, subprocess, sys, traceback
from collections import Counter
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov03q_dm001_subtitle_video"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

ASSET_SRT = ROOT / "mov03q_dm001_ko.srt"

LOGICAL_AU = 752
ATRAC_FRAME = 744
EA3_HEADER_SIZE = 96
SRATE_INDEX = 1
CHANNEL_ID_STEREO = 2

def run(cmd, logname, timeout=1800, cwd=None):
    cp = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    txt = "COMMANLOCAL_PATH" + " ".join(('"%s"' % str(x) if " " in str(x) else str(x)) for x in cmd)
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout
    txt += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(txt, encoding="utf-8-sig")
    return cp

def write_tsv(path, rows, fields=None):
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def probe(path, name):
    cp = run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        name, 120
    )
    if cp.returncode != 0:
        return None
    try:
        return json.loads(cp.stdout)
    except Exception:
        return None

def duration(info):
    if not info:
        return None
    for s in info.get("streams", []):
        try:
            d = s.get("duration")
            if d not in (None, "", "N/A"):
                return float(d)
        except Exception:
            pass
    try:
        return float(info.get("format", {}).get("duration"))
    except Exception:
        return None

def video_stream(info):
    if not info:
        return None
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None

def find_exe(name):
    preferred = [
        ROOT / name,
        ROOT / "tools" / name,
        ROOT / "pmftools-plus" / name,
        ROOT / "tools" / "pmftools-plus" / name,
    ]
    for p in preferred:
        if p.exists():
            return p
    for base, dirs, files in os.walk(ROOT):
        rel = str(Path(base).relative_to(ROOT)).lower()
        if any(x in rel for x in [r"logs\old", r"analysis\stage37\video"]):
            dirs[:] = []
            continue
        for f in files:
            if f.lower() == name.lower():
                return Path(base) / f
    return None

def choose_font():
    cands = [
        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH"),
    ]
    for p in cands:
        if p.exists():
            dst = FONTD / p.name
            shutil.copy2(p, dst)
            return p, dst
    raise RuntimeError("Korean Windows font not found (malgun/gulim/batang)")

def parse_srt_time(t):
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def ass_time(sec):
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def wrap_ko(text, target=27):
    # ASS can auto-wrap, but explicit word-boundary wrapping gives predictable
    # 480px output and prevents extremely long one-line captions.
    text = text.strip()
    if len(text) <= target:
        return text
    words = text.split(" ")
    if len(words) == 1:
        cut = len(text)//2
        return text[:cut] + r"\N" + text[cut:]
    lines = []
    cur = ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if len(cand) <= target or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        # Rebalance to two lines for the 40px subtitle band.
        joined = " ".join(words)
        mid = len(joined)//2
        split = joined.rfind(" ", 0, mid+3)
        if split < max(1, mid-8):
            split = joined.find(" ", mid)
        if split > 0:
            lines = [joined[:split], joined[split+1:]]
    return r"\N".join(lines[:2])

def srt_to_ass(srt_path, ass_path):
    txt = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\r?\n+", txt.strip())
    events = []
    for b in blocks:
        ls = b.splitlines()
        if len(ls) < 3:
            continue
        times = ls[1].strip()
        if " --> " not in times:
            continue
        a, z = times.split(" --> ", 1)
        start = parse_srt_time(a.strip())
        end = parse_srt_time(z.strip())
        text = " ".join(x.strip() for x in ls[2:] if x.strip())
        text = text.replace("{", r"\{").replace("}", r"\}")
        text = wrap_ko(text)
        events.append((start, end, text))

    header = r"""[Script Info]
Title: Naruto MOV03Q dm001 Korean subtitles
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
    lines = [header.rstrip()]
    for st, en, text in events:
        lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Default,,0,0,0,,{text}")
    Path(ass_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return events

def parse_psmf(path):
    data = Path(path).read_bytes()
    if len(data) < 0x800 or data[:4] != b"PSMF":
        raise RuntimeError(f"{Path(path).name}: not PSMF")
    off = struct.unpack_from(">I", data, 8)[0]
    pos = off
    n = len(data)
    counts = Counter()
    audio = []
    video = []
    while pos + 6 <= n:
        if data[pos:pos+3] != b"\x00\x00\x01":
            nxt = data.find(b"\x00\x00\x01", pos+1)
            if nxt < 0:
                break
            pos = nxt
            continue
        sid = data[pos+3]
        counts[sid] += 1
        if sid == 0xBA:
            if pos + 14 > n:
                break
            pos += 14 + (data[pos+13] & 7)
            continue
        if sid == 0xB9:
            pos += 4
            continue
        plen = (data[pos+4] << 8) | data[pos+5]
        if plen == 0:
            nxt = data.find(b"\x00\x00\x01\xBA", pos+6)
            if nxt < 0:
                break
            pos = nxt
            continue
        end = pos + 6 + plen
        if end > n:
            break
        if 0xE0 <= sid <= 0xEF:
            video.append((pos, end))
        elif sid == 0xBD:
            p = pos + 6
            if p + 3 <= end and (data[p] & 0xC0) == 0x80:
                payload = p + 3 + data[p+2]
            else:
                payload = p
            audio.append((pos, end, payload))
        pos = end
    return dict(data=data, data_offset=off, counts=counts, audio=audio, video=video)

def recover_kr_audio_wav(kr_pmf, wav_out):
    parsed = parse_psmf(kr_pmf)
    logical = bytearray()
    for start, end, payload in parsed["audio"]:
        private = parsed["data"][payload:end]
        if len(private) >= 4 and private[0] < 0x10:
            logical += private[4:]
    if not logical or len(logical) % LOGICAL_AU:
        raise RuntimeError(f"KR embedded audio structural length invalid: {len(logical)}")
    frames = bytearray()
    for i in range(0, len(logical), LOGICAL_AU):
        frames += logical[i+8:i+LOGICAL_AU]
    if len(frames) % ATRAC_FRAME:
        raise RuntimeError("KR ATRAC3+ frame bytes invalid")

    size_code = ATRAC_FRAME // 8 - 1
    params = (SRATE_INDEX << 13) | (CHANNEL_ID_STEREO << 10) | size_code
    def syncsafe28(n):
        return bytes([(n>>21)&0x7F, (n>>14)&0x7F, (n>>7)&0x7F, n&0x7F])

    oma = WORK / "dm001_kr_audio.oma"
    out = bytearray()
    out += b"ea3" + bytes([3,0,0]) + syncsafe28(0)
    ea3 = bytearray(EA3_HEADER_SIZE)
    ea3[0:4] = b"EA3\x00"
    ea3[4] = EA3_HEADER_SIZE >> 7
    ea3[5] = EA3_HEADER_SIZE & 0x7F
    ea3[6:8] = struct.pack("<H", 0xFFFF)
    ea3[32:36] = struct.pack(">I", (1 << 24) | params)
    out += ea3
    out += frames
    oma.write_bytes(out)

    cp = run(
        [FFMPEG, "-y", "-v", "warning", "-f", "oma", "-i", oma,
         "-c:a", "pcm_s16le", wav_out],
        "03_decode_kr_japanese_audio.log", 300
    )
    if cp.returncode != 0 or not Path(wav_out).exists() or Path(wav_out).stat().st_size <= 44:
        raise RuntimeError("KR Japanese audio decode failed")
    return len(frames) // ATRAC_FRAME

def count_sector_layout(path):
    data = Path(path).read_bytes()
    if data[:4] != b"PSMF":
        return {}
    off = struct.unpack_from(">I", data, 8)[0]
    sectors = []
    sid_counts = Counter()
    for si, s in enumerate(range(off, len(data) - 2047, 2048)):
        sec = data[s:s+2048]
        if sec[:4] != b"\x00\x00\x01\xBA":
            sectors.append(dict(index=si, sid="NO_PACK"))
            sid_counts["NO_PACK"] += 1
            continue
        ph = 14 + (sec[13] & 7)
        sid = None
        if ph + 4 <= len(sec) and sec[ph:ph+3] == b"\x00\x00\x01":
            sid = sec[ph+3]
        label = f"0x{sid:02X}" if sid is not None else "NONE"
        sid_counts[label] += 1
        sectors.append(dict(index=si, sid=label))
    return dict(total=len(sectors), counts=sid_counts, rows=sectors)

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("LOCAL_PATH / ffprobe.exe missing")
    if not ASSET_SRT.exists():
        raise RuntimeError(f"Bundled Korean SRT missing: {ASSET_SRT}")

    us = US_MOV / "dm001e.pmf"
    if not us.exists():
        us = US_MOV / "dm001.pmf"
    kr = KR_MOV / "dm001.pmf"
    if not us.exists() or not kr.exists():
        raise RuntimeError("US/KR dm001 source PMF missing")

    composer = find_exe("oMPSComposer.exe")
    mps2pmf = find_exe("Mps2Pmf.exe")
    if composer is None:
        raise RuntimeError("oMPSComposer.exe not found under project root")
    if mps2pmf is None:
        raise RuntimeError("Mps2Pmf.exe not found under project root")

    print("="*80, flush=True)
    print(" Naruto PSP MOV03Q - dm001 Korean subtitle VIDEO smoke test", flush=True)
    print("="*80, flush=True)
    print(f"US clean video : {us}", flush=True)
    print(f"KR JP audio    : {kr}", flush=True)
    print("Subtitle timing: MOV03N FIX5 KR timeline", flush=True)

    _, font_copy = choose_font()
    ass = WORK / "dm001_ko.ass"
    events = srt_to_ass(ASSET_SRT, ass)
    if len(events) != 16:
        raise RuntimeError(f"Expected 16 dm001 subtitles, got {len(events)}")

    # Estimate original clean US video elementary-stream bitrate.
    raw264 = WORK / "dm001_us_source.264"
    if raw264.exists():
        raw264.unlink()
    cp = run(
        [FFMPEG, "-y", "-v", "warning", "-i", us,
         "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "h264", raw264],
        "01_extract_source_h264.log", 300
    )
    if cp.returncode != 0 or not raw264.exists():
        raise RuntimeError("Could not extract US source H264")

    us_info = probe(us, "02_probe_us_source.log")
    us_dur = duration(us_info)
    if us_dur is None or us_dur <= 0:
        raise RuntimeError("Could not determine US movie duration")

    source_kbps = raw264.stat().st_size * 8 / us_dur / 1000.0
    avg = int(round(source_kbps / 50.0) * 50)
    avg = max(500, min(3500, avg))
    maxbr = int(round(max(avg + 500, avg * 1.55) / 50.0) * 50)
    maxbr = min(4700, maxbr)
    if maxbr <= avg:
        maxbr = min(4700, avg + 500)

    # Burn ASS onto clean US visual into a lossless FFV1 intermediate.
    burned_avi = WORK / "dm001_USclean_KOsub_lossless.avi"
    if burned_avi.exists():
        burned_avi.unlink()

    # Use STAGE cwd so libass paths contain no Windows drive-colon escaping.
    rel_ass = os.path.relpath(ass, STAGE).replace("\\", "/")
    rel_fonts = os.path.relpath(FONTD, STAGE).replace("\\", "/")
    vf = (
        "setpts=PTS-STARTPTS,"
        f"ass=filename='{rel_ass}':fontsdir='{rel_fonts}'"
    )
    cp = run(
        [FFMPEG, "-y", "-v", "warning", "-i", us, "-an",
         "-vf", vf,
         "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p",
         "-fps_mode", "cfr", burned_avi],
        "04_burn_korean_subtitles_lossless.log", 900, cwd=STAGE
    )
    if cp.returncode != 0 or not burned_avi.exists():
        raise RuntimeError("Korean subtitle burn-in failed")

    burn_info = probe(burned_avi, "05_probe_burned_avi.log")
    burn_dur = duration(burn_info)
    if burn_dur is None:
        raise RuntimeError("Burned AVI probe failed")

    # Recover original KR Japanese audio (no US audio is used).
    wav = WORK / "dm001_KR_JP_audio.wav"
    existing_wav = ROOT / "analysis" / "mov" / "mov03k_embedded_audio" / "audio" / "dm001_strip_head8.wav"
    if existing_wav.exists():
        shutil.copy2(existing_wav, wav)
        atrac_frames = ""
    else:
        atrac_frames = recover_kr_audio_wav(kr, wav)

    # PC preview: Korean subtitles + KR Japanese audio.
    preview = OUT / "dm001_KOsub_KR-JP-audio_preview.mp4"
    if preview.exists():
        preview.unlink()
    cp = run(
        [FFMPEG, "-y", "-v", "warning",
         "-i", burned_avi, "-i", wav,
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", preview],
        "06_build_japanese_audio_preview.log", 900
    )
    if cp.returncode != 0 or not preview.exists():
        raise RuntimeError("PC preview build failed")

    # oMPSComposer v2 supports no-audio: second positional argument '-'.
    # It still requires ffmpeg.exe beside the executable.
    cdir = composer.parent
    local_ffmpeg = cdir / "ffmpeg.exe"
    temp_ffmpeg = False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG, local_ffmpeg)
        temp_ffmpeg = True

    mps = WORK / "dm001_KOsub_video_only.mps"
    pmf = OUT / "dm001_KOsub_video_only.pmf"
    for p in (mps, pmf):
        if p.exists():
            p.unlink()

    try:
        cp = run(
            [composer, burned_avi, "-", mps,
             "--avg-bitrate", str(avg),
             "--max-bitrate", str(maxbr),
             "--encode-mode", "2pass",
             "--idr-duration", "2000",
             "--m-frames", "1"],
            "07_oMPSComposer_video_only.log", 2400, cwd=cdir
        )
        if cp.returncode != 0 or not mps.exists():
            raise RuntimeError(
                "oMPSComposer video-only build failed. "
                "If this executable predates pmftools-plus v2.0, update it."
            )
    finally:
        if temp_ffmpeg:
            try:
                local_ffmpeg.unlink()
            except Exception:
                pass

    whole = int(math.ceil(burn_dur))
    mins, secs = divmod(whole, 60)
    cp = run(
        [mps2pmf, "-i", mps, "-o", pmf, "-m", str(mins), "-s", str(secs)],
        "08_Mps2Pmf_video_only.log", 300, cwd=mps2pmf.parent
    )
    if cp.returncode != 0 or not pmf.exists():
        raise RuntimeError("Mps2Pmf failed")

    pmf_info = probe(pmf, "09_probe_video_only_pmf.log")
    vs = video_stream(pmf_info)
    parsed = parse_psmf(pmf)

    # Review frame during subtitle #10.
    review = OUT / "dm001_KOsub_review_27s.jpg"
    cp = run(
        [FFMPEG, "-y", "-v", "error", "-i", pmf,
         "-ss", "27.000", "-frames:v", "1", "-q:v", "2", review],
        "10_extract_review_frame.log", 180
    )

    # Inventory 2048-byte sectors for next original-ATRAC mux stage.
    new_layout = count_sector_layout(pmf)
    kr_layout = count_sector_layout(kr)
    us_layout = count_sector_layout(us)

    layout_rows = []
    for label, lay in [("KR_original", kr_layout), ("US_clean", us_layout), ("KO_video_only", new_layout)]:
        counts = lay.get("counts", Counter())
        layout_rows.append(dict(
            source=label,
            total_sectors=lay.get("total", 0),
            video_sectors=sum(v for k,v in counts.items() if k.startswith("0xE")),
            audio_sectors=counts.get("0xBD", 0),
            padding_sectors=counts.get("0xBE", 0),
            private2_sectors=counts.get("0xBF", 0),
            no_pack=counts.get("NO_PACK", 0),
        ))
    write_tsv(STAGE / "sector_layout.tsv", layout_rows)

    result = [dict(
        movie="dm001",
        subtitle_count=len(events),
        timing_basis="MOV03N FIX5 KR",
        visual_source=str(us),
        audio_target="KR dm001 original Japanese ATRAC3+",
        font=str(font_copy),
        source_video_kbps=f"{source_kbps:.3f}",
        encode_avg_kbps=avg,
        encode_max_kbps=maxbr,
        source_duration=f"{us_dur:.6f}",
        burned_duration=f"{burn_dur:.6f}",
        video_only_pmf=str(pmf),
        video_only_pmf_bytes=pmf.stat().st_size,
        pmf_codec=vs.get("codec_name","") if vs else "",
        pmf_width=vs.get("width","") if vs else "",
        pmf_height=vs.get("height","") if vs else "",
        pmf_video_pes=sum(v for k,v in parsed["counts"].items() if 0xE0 <= k <= 0xEF),
        pmf_audio_pes=parsed["counts"].get(0xBD,0),
        preview=str(preview),
        review_frame=str(review) if review.exists() else "",
        status=("PASS" if vs and parsed["counts"].get(0xBD,0)==0 else "FAIL"),
    )]
    write_tsv(STAGE / "smoke_result.tsv", result)

    ok = bool(vs and vs.get("codec_name") == "h264" and
              int(vs.get("width",0)) == 480 and int(vs.get("height",0)) == 272 and
              parsed["counts"].get(0xBD,0) == 0 and preview.exists())

    summary = [
        "Naruto PSP MOV03Q - dm001 Korean subtitle VIDEO smoke test",
        "="*80, "",
        f"Subtitle count={len(events)}",
        "Subtitle timing=MOV03N FIX5 KR timeline",
        "Visual source=US dm001e clean video",
        "Preview audio=KR original Japanese audio",
        f"Source video bitrate~{source_kbps:.1f} kbps",
        f"PSP encode avg/max={avg}/{maxbr} kbps",
        f"Video-only PMF={'PASS' if ok else 'FAIL'}",
        f"PMF H264={vs.get('width','?')}x{vs.get('height','?')}" if vs else "PMF H264=not detected",
        f"PMF audio PES={parsed['counts'].get(0xBD,0)} (expected 0 in MOV03Q)",
        "",
        "Local outputs:",
        f"  Preview    : {preview}",
        f"  Video PMF  : {pmf}",
        f"  Review JPG : {review}",
        "",
        "Next:",
        "  Use sector_layout.tsv + KR original 0xBD stream to build the",
        "  final subtitle-video + original Japanese ATRAC3+ PMF mux.",
    ]
    (STAGE / "SUMMARY.txt").write_text("\n".join(summary)+"\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if ok else 2

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        (STAGE / "FAILURE.txt").write_text(tb, encoding="utf-8-sig")
        print(tb, file=sys.stderr, flush=True)
        raise SystemExit(1)
