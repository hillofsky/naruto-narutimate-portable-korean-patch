#!/usr/bin/env python3
# Naruto PSP MOV03K FIX5
# Detect/strip per-AU wrapper inside 752-byte PSMF ATRAC logical units.
#
# Evidence:
# - Correct PSMF private PES demux yields a global stream divisible by 752.
# - OMA wraps it as atrac3p/44100/2ch successfully.
# - Decoder then reports "Frame data doesn't match channel configuration!",
#   meaning packet bytes do not begin at the ATRAC3+ frame bitstream start.
# - 752 = 744 (0x2E8, common ATRAC3+ frame size) + 8.
#
# FIX5 splits the corrected stream into 752-byte logical AUs and tests:
#   A) raw 752
#   B) strip first 8 bytes  -> 744
#   C) strip last 8 bytes   -> 744
#   D) strip first 4 + last 4 -> 744
#   E) strip first 16 bytes -> 736
#
# It scores each candidate using FFmpeg ATRAC3+ frame-start semantics:
#   start bit must be 0
#   next 2 bits for stereo must be CH_UNIT_STEREO (1)
# => top 3 bits of first compressed byte should be binary 001.
#
# Then it builds exact OMA/EA3 headers for each block size and tries decoding.
#
# Logging convention:
# - success transcript: logs\naruto_...FIX5_<timestamp>.log
# - failure transcript: logs\fail_naruto_...FIX5_<timestamp>.log
# - failure ZIP:        logs\fail_naruto_...FIX5_upload.zip
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
    p.mkdir(parents=True, exist_ok=True)

DM = [f"dm{i:03d}" for i in range(1, 11)]

SAMPLE_RATE = 44100
SAMPLES_PER_FRAME = 2048
LOGICAL_AU = 752

# OMA: 1=ATRAC3+
OMA_CODEC_ATRAC3P = 1
SRATE_INDEX = 1       # 44100
CHANNEL_ID_STEREO = 2 # FFmpeg OMA table resolves this to 2 channels
EA3_HEADER_SIZE = 96

TRANSFORMS = [
    ("raw752", 0, 0),
    ("strip_head8", 8, 0),
    ("strip_tail8", 0, 8),
    ("strip_head4_tail4", 4, 4),
    ("strip_head16", 16, 0),
]

def write_tsv(path, rows, fields=None):
    path = Path(path)
    if fields is None:
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def find_tool(name):
    for p in [Path(r"LOCAL_PATH")/(name+".exe"), Path(r"LOCAL_PATH")/(name+".EXE")]:
        if p.exists():
            return p
    try:
        cp = subprocess.run(["where.exe", name], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", timeout=10)
        for line in cp.stdout.splitlines():
            p = Path(line.strip())
            if p.exists():
                return p
    except Exception:
        pass
    return None

def run(cmd, logname, timeout=300):
    cp = subprocess.run([str(x) for x in cmd],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace", timeout=timeout)
    txt = "COMMANLOCAL_PATH" + " ".join(('"%s"' % x if " " in str(x) else str(x)) for x in cmd)
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout + "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOG_DIR/logname).write_text(txt, encoding="utf-8-sig")
    return cp

def ffprobe_json(ffprobe, path, logname, force_oma=False):
    cmd = [ffprobe, "-v", "error"]
    if force_oma:
        cmd += ["-f", "oma"]
    cmd += ["-show_streams", "-show_format", "-of", "json", path]
    cp = run(cmd, logname, 120)
    if cp.returncode != 0:
        return None, cp
    try:
        return json.loads(cp.stdout), cp
    except Exception:
        return None, cp

def first_audio(info):
    if not info:
        return None
    for s in info.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    return None

def info_duration(info):
    if not info:
        return None
    a = first_audio(info)
    for x in [a.get("duration") if a else None, info.get("format", {}).get("duration")]:
        try:
            if x not in (None, "", "N/A"):
                return float(x)
        except Exception:
            pass
    return None

def short(s, n=500):
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()[:n]

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def parse_pts5(b):
    if len(b) < 5:
        return None
    return ((b[0] & 0x0E) << 29) | (b[1] << 22) | ((b[2] & 0xFE) << 14) | (b[3] << 7) | ((b[4] & 0xFE) >> 1)

def parse_pmf_private(path):
    data = path.read_bytes()
    if len(data) < 0x800 or data[:4] != b"PSMF":
        raise RuntimeError(f"{path.name}: not PSMF")
    data_offset = struct.unpack_from(">I", data, 8)[0]
    if data_offset <= 0 or data_offset >= len(data):
        raise RuntimeError(f"{path.name}: invalid PSMF data offset")

    pos = data_offset
    n = len(data)
    payloads = defaultdict(bytearray)
    pts = defaultdict(list)
    locs = defaultdict(list)
    sizes = defaultdict(list)
    counts = Counter()

    while pos + 6 <= n:
        if data[pos:pos+3] != b"\x00\x00\x01":
            nxt = data.find(b"\x00\x00\x01", pos + 1)
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
            nxt = data.find(b"\x00\x00\x01\xBA", pos + 6)
            if nxt < 0:
                break
            pos = nxt
            continue

        end = pos + 6 + plen
        if end > n:
            break

        if sid == 0xBD:
            p = pos + 6
            payload = p
            pes_pts = None

            if p + 3 <= end and (data[p] & 0xC0) == 0x80:
                flags2 = data[p+1]
                hlen = data[p+2]
                if (flags2 & 0x80) and p + 8 <= end:
                    pes_pts = parse_pts5(data[p+3:p+8])
                payload = p + 3 + hlen
            else:
                q = p
                while q < end and data[q] == 0xFF:
                    q += 1
                if q + 2 <= end and (data[q] & 0xC0) == 0x40:
                    q += 2
                if q < end and (data[q] & 0xF0) in (0x20, 0x30):
                    pes_pts = parse_pts5(data[q:q+5])
                    q += 5 if (data[q] & 0xF0) == 0x20 else 10
                elif q < end and data[q] == 0x0F:
                    q += 1
                payload = q

            # Sony private header: id + reserved + AU locator BE16.
            if payload + 4 <= end:
                subid = data[payload]
                locator = struct.unpack_from(">H", data, payload+2)[0]
                es = data[payload+4:end]
                payloads[subid].extend(es)
                locs[subid].append(locator)
                sizes[subid].append(len(es))
                if pes_pts is not None:
                    pts[subid].append(pes_pts)

        pos = end

    return dict(counts=counts, payloads=payloads, pts=pts, locs=locs, sizes=sizes)

def syncsafe28(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])

def build_oma(raw, block_align, path):
    if block_align <= 0 or block_align % 8:
        raise ValueError(f"OMA block_align must be divisible by 8, got {block_align}")

    size_code = block_align // 8 - 1
    if not (0 <= size_code <= 0x3FF):
        raise ValueError(size_code)

    codec_params = (SRATE_INDEX << 13) | (CHANNEL_ID_STEREO << 10) | size_code

    out = bytearray()
    # minimal ea3 ID3v2.3 header
    out += b"ea3" + bytes([3, 0, 0]) + syncsafe28(0)

    ea3 = bytearray(EA3_HEADER_SIZE)
    ea3[0:4] = b"EA3\x00"
    ea3[4] = EA3_HEADER_SIZE >> 7
    ea3[5] = EA3_HEADER_SIZE & 0x7F
    ea3[6:8] = struct.pack("<H", 0xFFFF)
    word = (OMA_CODEC_ATRAC3P << 24) | codec_params
    ea3[32:36] = struct.pack(">I", word)
    out += ea3
    out += raw
    path.write_bytes(out)
    return codec_params

def transform_aus(raw752, head_strip, tail_strip):
    if len(raw752) % LOGICAL_AU:
        raise RuntimeError("logical stream not divisible by 752")
    frame_size = LOGICAL_AU - head_strip - tail_strip
    if frame_size <= 0:
        raise ValueError(frame_size)

    out = bytearray()
    heads = []
    for i in range(0, len(raw752), LOGICAL_AU):
        au = raw752[i:i+LOGICAL_AU]
        body = au[head_strip:LOGICAL_AU-tail_strip if tail_strip else LOGICAL_AU]
        if len(body) != frame_size:
            raise AssertionError()
        out += body
        heads.append(body[:16])
    return bytes(out), frame_size, heads

def stereo_start_score(heads):
    # FFmpeg decoder expects:
    # bit0 start bit = 0
    # next 2 bits CH_UNIT_STEREO = 1
    # Top 3 bits therefore 001b.
    ok = 0
    valid = 0
    hist = Counter()
    examples = []
    for h in heads:
        if not h:
            continue
        b = h[0]
        top3 = (b >> 5) & 7
        hist[top3] += 1
        valid += 1
        if top3 == 1:
            ok += 1
        if len(examples) < 8:
            examples.append(h.hex(" "))
    ratio = ok / valid if valid else 0.0
    return ok, valid, ratio, hist, examples

def main():
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found")

    print("="*80, flush=True)
    print(" Naruto PSP MOV03K FIX5 - Per-AU 8-byte header detection", flush=True)
    print("="*80, flush=True)

    results = []
    trials = []
    diagnostics = []
    success_count = 0

    for idx, name in enumerate(DM, 1):
        print(f"[{idx:02d}/10] {name}", flush=True)
        src = KR_MOV / (name + ".pmf")
        if not src.exists():
            results.append(dict(movie=name, status="MISSING_PMF"))
            continue

        r = parse_pmf_private(src)
        cands = [s for s in r["payloads"] if s < 0x10]
        if not cands:
            results.append(dict(movie=name, status="NO_ATRAC_SUBSTREAM"))
            continue

        sub = max(cands, key=lambda s: len(r["payloads"][s]))
        raw752 = bytes(r["payloads"][sub])

        if len(raw752) % LOGICAL_AU:
            results.append(dict(movie=name, status="RAW_NOT_DIVISIBLE_752", raw_bytes=len(raw752)))
            continue

        logical_frames = len(raw752) // LOGICAL_AU
        pvals = r["pts"][sub]
        pts_span = (pvals[-1] - pvals[0]) / 90000.0 if len(pvals) >= 2 else None

        selected = None

        for tname, hs, ts in TRANSFORMS:
            transformed, block_align, heads = transform_aus(raw752, hs, ts)
            ok, valid, ratio, hist, examples = stereo_start_score(heads)

            diagnostics.append(dict(
                movie=name, transform=tname,
                logical_au_count=logical_frames,
                head_strip=hs, tail_strip=ts,
                block_align=block_align,
                stereo_start_ok=ok,
                frame_count_checked=valid,
                stereo_start_ratio=f"{ratio:.6f}",
                top3_histogram=";".join(f"{k}:{v}" for k,v in sorted(hist.items())),
                first_frame_heads=" | ".join(examples),
            ))

            # OMA size formula requires multiple of 8.
            if block_align % 8:
                trials.append(dict(movie=name, transform=tname, status="BLOCK_ALIGN_NOT_MULTIPLE_8",
                                   block_align=block_align, stereo_start_ratio=f"{ratio:.6f}"))
                continue

            oma = AUDIO_DIR / f"{name}_{tname}.oma"
            wav = AUDIO_DIR / f"{name}_{tname}.wav"
            for p in (oma, wav):
                if p.exists():
                    p.unlink()

            codec_params = build_oma(transformed, block_align, oma)

            ai, ap = ffprobe_json(ffprobe, oma, f"{name}_{tname}_fix5_probe.log", True)
            aa = first_audio(ai)

            cp = run([
                ffmpeg, "-y", "-v", "warning", "-f", "oma", "-i", oma,
                "-map", "0:a:0", "-c:a", "pcm_s16le", wav
            ], f"{name}_{tname}_fix5_decode.log", 300)

            wi, wp = ffprobe_json(ffprobe, wav, f"{name}_{tname}_fix5_wavprobe.log", False) if wav.exists() else (None, None)
            wa = first_audio(wi)
            wdur = info_duration(wi)

            decode_ok = cp.returncode == 0 and wav.exists() and wav.stat().st_size > 44 and wa is not None
            theoretical = logical_frames * SAMPLES_PER_FRAME / SAMPLE_RATE
            delta_pts = (wdur - pts_span) if (wdur is not None and pts_span is not None) else None
            full_ok = decode_ok and delta_pts is not None and abs(delta_pts) <= 0.50

            trials.append(dict(
                movie=name, transform=tname,
                head_strip=hs, tail_strip=ts,
                block_align=block_align,
                codec_params=f"0x{codec_params:06X}",
                stereo_start_ratio=f"{ratio:.6f}",
                ffprobe_audio="YES" if aa else "NO",
                ffprobe_codec=aa.get("codec_name","") if aa else "",
                sample_rate=aa.get("sample_rate","") if aa else "",
                channels=aa.get("channels","") if aa else "",
                ffmpeg_returncode=cp.returncode,
                ffmpeg_stderr=short(cp.stderr),
                wav_exists="YES" if wav.exists() else "NO",
                wav_bytes=wav.stat().st_size if wav.exists() else "",
                wav_duration=f"{wdur:.6f}" if wdur is not None else "",
                pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
                theoretical_duration=f"{theoretical:.6f}",
                wav_vs_pts=f"{delta_pts:+.6f}" if delta_pts is not None else "",
                status="FULL_OK" if full_ok else ("DECODE_OK_BAD_DURATION" if decode_ok else "DECODE_FAILED"),
            ))

            if full_ok and selected is None:
                selected = dict(
                    transform=tname, block_align=block_align, codec_params=codec_params,
                    stereo_start_ratio=ratio, oma=oma, wav=wav, wdur=wdur,
                    theoretical=theoretical
                )
                break

        if selected:
            success_count += 1
            status = "OK"
            print(
                f"  selected={selected['transform']} block={selected['block_align']} "
                f"start_score={selected['stereo_start_ratio']:.3f} "
                f"PTS={pts_span:.3f}s WAV={selected['wdur']:.3f}s => OK",
                flush=True
            )
        else:
            status = "NO_TRANSFORM_DECODED"
            # choose best structural score for console.
            thisdiag = [d for d in diagnostics if d["movie"] == name]
            best = max(thisdiag, key=lambda d: float(d["stereo_start_ratio"])) if thisdiag else None
            print(
                f"  best_structural={(best['transform'] if best else 'none')} "
                f"score={(best['stereo_start_ratio'] if best else 'N/A')} "
                f"PTS={(f'{pts_span:.3f}' if pts_span is not None else 'N/A')}s "
                f"=> {status}",
                flush=True
            )

        results.append(dict(
            movie=name, status=status,
            substream_id=f"0x{sub:02X}",
            private_stream_packets=r["counts"].get(0xBD,0),
            corrected_logical_bytes=len(raw752),
            logical_au_size=LOGICAL_AU,
            logical_au_count=logical_frames,
            pts_span=f"{pts_span:.6f}" if pts_span is not None else "",
            selected_transform=selected["transform"] if selected else "",
            selected_block_align=selected["block_align"] if selected else "",
            selected_codec_params=f"0x{selected['codec_params']:06X}" if selected else "",
            selected_stereo_start_ratio=f"{selected['stereo_start_ratio']:.6f}" if selected else "",
            wav_duration=f"{selected['wdur']:.6f}" if selected else "",
            oma_path=str(selected["oma"]) if selected else "",
            wav_path=str(selected["wav"]) if selected else "",
        ))

    write_tsv(STAGE/"fix5_results.tsv", results)
    write_tsv(STAGE/"fix5_transform_trials.tsv", trials)
    write_tsv(STAGE/"fix5_frame_start_diagnostics.tsv", diagnostics)

    # Summarize which transform wins structurally even if decode fails.
    agg = defaultdict(list)
    for d in diagnostics:
        agg[d["transform"]].append(float(d["stereo_start_ratio"]))
    avg_scores = sorted(
        ((sum(v)/len(v), k) for k,v in agg.items()),
        reverse=True
    )

    summary = [
        "Naruto PSP MOV03K FIX5 - Per-AU 8-byte header detection",
        "="*80, "",
        f"Validated full-duration WAV={success_count}/10",
        "",
        "Average ATRAC3+ stereo frame-start score by transform:",
        *[f"  {name}: {score:.6f}" for score,name in avg_scores],
        "",
        "Interpretation:",
        "- FFmpeg's ATRAC3+ decoder requires start bit 0 then channel-unit id.",
        "- Stereo frames should begin with top 3 bits 001.",
        "- If strip_head8 scores ~1.0 and decodes, each 752-byte PSMF AU is:",
        "    8-byte PSMF/MPEG AU header + 744-byte ATRAC3+ frame.",
        "- If another transform scores/decodes instead, its exact offsets are retained.",
        "",
        "Main files:",
        "  fix5_frame_start_diagnostics.tsv",
        "  fix5_transform_trials.tsv",
        "  fix5_results.tsv",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if success_count == 10 else 2

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True, exist_ok=True)
        tb = traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb, encoding="utf-8-sig")
        print(tb, file=sys.stderr, flush=True)
        raise SystemExit(1)
