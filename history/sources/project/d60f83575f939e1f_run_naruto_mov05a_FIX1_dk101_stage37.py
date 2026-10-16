#!/usr/bin/env python3
# Naruto PSP MOV05A FIX1
#
# Fixes:
#  - use the exact MOV04C-proven PMF/ATRAC parser instead of a duplicated parser
#  - remove NumPy dependency entirely
#  - pure-Python coarse-to-fine audio-envelope matching
#  - always preserve Python traceback in FAILURE.txt
#
# Search target:
#   KR dk101 original Japanese audio
#
# Search sources:
#   analysis\stage37\video\source_video.mp4
#   analysis\stage37\video\part2.mp4

from __future__ import annotations
import array, csv, importlib.util, math, os, shutil, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
STAGE37 = ROOT / "analysis" / "stage37"
VIDEO_DIR = STAGE37 / "video"

SOURCES = [
    VIDEO_DIR / "source_video.mp4",
    VIDEO_DIR / "part2.mp4",
]
KR_PMF = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie" / "dk101.pmf"
CORE_PATH = ROOT / "mov05a_proven_movie_core.py"

STAGE = ROOT / "analysis" / "mov" / "mov05a_fix1_dk101_stage37_audio_match"
WORK = STAGE / "work"
REP = STAGE / "representatives"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, REP, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

DECODE_RATE = 8000

COARSE_HZ = 2.0
FINE_HZ = 20.0

TOP_COARSE = 10
TOP_FINAL = 8
COARSE_SEPARATION_SEC = 20.0
FINE_SEARCH_SEC = 4.0
SCALES = [0.997, 1.000, 1.003]

def load_core():
    if not CORE_PATH.exists():
        raise RuntimeError(f"Proven MOV04C core missing: {CORE_PATH}")
    spec = importlib.util.spec_from_file_location("mov05a_core", CORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

def run(cmd, logname, timeout=2400):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    txt = "COMMANLOCAL_PATH" + " ".join(
        ('"%s"' % str(x) if " " in str(x) else str(x)) for x in cmd
    )
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout
    txt += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(txt, encoding="utf-8-sig")
    return cp

def write_tsv(path, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def decode_pcm(source, out_pcm, tag, is_oma=False):
    cmd = [FFMPEG, "-y", "-v", "warning"]
    if is_oma:
        cmd += ["-f", "oma"]
    cmd += [
        "-i", source,
        "-vn", "-ac", "1", "-ar", str(DECODE_RATE),
        "-f", "s16le", "-c:a", "pcm_s16le",
        out_pcm,
    ]
    cp = run(cmd, tag, 3000)
    if cp.returncode != 0 or not Path(out_pcm).exists():
        raise RuntimeError(f"PCM decode failed: {source}")
    if Path(out_pcm).stat().st_size < 1000:
        raise RuntimeError(f"PCM output suspiciously small: {out_pcm}")

def load_pcm(path):
    a = array.array("h")
    with Path(path).open("rb") as f:
        a.fromfile(f, Path(path).stat().st_size // 2)
    if sys.byteorder != "little":
        a.byteswap()
    return a

def envelope(pcm, hz):
    win = max(1, int(round(DECODE_RATE / hz)))
    out = []
    n = len(pcm)
    i = 0
    while i + win <= n:
        ss = 0.0
        # RMS of integer PCM.
        for v in pcm[i:i+win]:
            fv = float(v) / 32768.0
            ss += fv * fv
        rms = math.sqrt(ss / win + 1e-12)
        out.append(math.log1p(rms * 20.0))
        i += win
    return out

def znormalize(v):
    if not v:
        return []
    mean = sum(v) / len(v)
    var = sum((x-mean)*(x-mean) for x in v) / len(v)
    sd = math.sqrt(max(var, 1e-12))
    return [(x-mean)/sd for x in v]

def prefix(v):
    s = [0.0]
    s2 = [0.0]
    a = 0.0
    b = 0.0
    for x in v:
        a += x
        b += x*x
        s.append(a)
        s2.append(b)
    return s, s2

def corr_at(source, qz, pos, pref, pref2):
    m = len(qz)
    if pos < 0 or pos + m > len(source):
        return -2.0
    sx = pref[pos+m] - pref[pos]
    sx2 = pref2[pos+m] - pref2[pos]
    mean = sx / m
    var = sx2 / m - mean*mean
    if var <= 1e-12:
        return -2.0
    sd = math.sqrt(var)

    dot = 0.0
    for i, q in enumerate(qz):
        dot += ((source[pos+i]-mean)/sd) * q
    return dot / m

def select_peaks(items, separation_sec, hz, topn):
    chosen = []
    sep = int(round(separation_sec * hz))
    for pos, score in sorted(items, key=lambda x:x[1], reverse=True):
        if all(abs(pos-p) >= sep for p,_ in chosen):
            chosen.append((pos, score))
            if len(chosen) >= topn:
                break
    return chosen

def coarse_search(source, query):
    qz = znormalize(query)
    pref, pref2 = prefix(source)
    m = len(query)
    if len(source) < m:
        return []
    scores = []
    for pos in range(0, len(source)-m+1):
        scores.append((pos, corr_at(source, qz, pos, pref, pref2)))
    return select_peaks(scores, COARSE_SEPARATION_SEC, COARSE_HZ, TOP_COARSE)

def resample_query(v, scale):
    if abs(scale-1.0) < 1e-9:
        return list(v)
    n = max(8, int(round(len(v)*scale)))
    if len(v) == 1:
        return [v[0]] * n
    out = []
    for j in range(n):
        x = j * (len(v)-1) / max(1, n-1)
        i = int(math.floor(x))
        k = min(len(v)-1, i+1)
        f = x-i
        out.append(v[i]*(1-f)+v[k]*f)
    return out

def fine_search(source, query, coarse_pos_sec):
    pref, pref2 = prefix(source)
    out = []
    center = int(round(coarse_pos_sec * FINE_HZ))
    radius = int(round(FINE_SEARCH_SEC * FINE_HZ))

    for scale in SCALES:
        q = resample_query(query, scale)
        qz = znormalize(q)
        for pos in range(max(0, center-radius), min(len(source)-len(q), center+radius)+1):
            score = corr_at(source, qz, pos, pref, pref2)
            out.append((pos, score, scale, len(q)))
    return out

def probe_duration(path, tag):
    cp = run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        tag, 120
    )
    if cp.returncode != 0:
        return None
    try:
        return float(cp.stdout.strip())
    except Exception:
        return None

def extract_frame(src, sec, out, tag):
    cp = run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{sec:.3f}", "-i", src,
         "-frames:v", "1", "-q:v", "2", out],
        tag, 180
    )
    return cp.returncode == 0 and Path(out).exists()

def inventory_stage37():
    rows = []
    exts = {".csv",".tsv",".json",".txt",".log",".md",".srt",".ass"}
    if not STAGE37.exists():
        return rows
    for p in STAGE37.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        rows.append(dict(
            path=str(p.relative_to(ROOT)),
            bytes=p.stat().st_size,
        ))
    rows.sort(key=lambda r:r["path"].lower())
    return rows

def main():
    print("="*80, flush=True)
    print(" Naruto PSP MOV05A FIX1 - dk101 Stage37 audio locator", flush=True)
    print("="*80, flush=True)
    print("Uses proven MOV04C PMF/ATRAC parser; NumPy not required.", flush=True)

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("ffmpeg/ffprobe missing")
    if not KR_PMF.exists():
        raise RuntimeError(f"KR dk101 missing: {KR_PMF}")
    for s in SOURCES:
        if not s.exists():
            raise RuntimeError(f"Stage37 video missing: {s}")

    inv = inventory_stage37()
    write_tsv(STAGE/"stage37_existing_analysis_inventory.tsv", inv)
    print(f"Existing Stage37 text/log artifacts indexed: {len(inv)}", flush=True)

    core = load_core()

    # Exact same parser/recovery functions used in MOV04C's successful dk101 build.
    krp = core.parse_pmf(KR_PMF)
    kra = core.recover_audio(krp)
    if kra["bad_headers"]:
        raise RuntimeError(f"KR dk101 bad AU headers: {kra['bad_headers']}")

    oma = WORK / "dk101_kr.oma"
    core.build_oma(kra["frames"], oma)

    kr_pcm_path = WORK / "dk101_kr_8k_mono.s16"
    decode_pcm(oma, kr_pcm_path, "01_decode_kr_dk101.log", True)
    kr_pcm = load_pcm(kr_pcm_path)

    q_coarse = envelope(kr_pcm, COARSE_HZ)
    q_fine = envelope(kr_pcm, FINE_HZ)
    q_duration = len(kr_pcm) / DECODE_RATE

    print(
        f"KR dk101 recovered: frames={kra['frame_count']} "
        f"PES={len(krp['audio'])} duration={q_duration:.3f}s",
        flush=True
    )

    candidates = []
    summaries = []

    for idx, src in enumerate(SOURCES, 1):
        print(f"[{idx:02d}/02] {src.name}", flush=True)
        dur = probe_duration(src, f"02_{src.stem}_duration.log")

        pcm_path = WORK / f"{src.stem}_8k_mono.s16"
        decode_pcm(src, pcm_path, f"03_{src.stem}_decode_audio.log", False)
        pcm = load_pcm(pcm_path)

        s_coarse = envelope(pcm, COARSE_HZ)
        s_fine = envelope(pcm, FINE_HZ)

        coarse = coarse_search(s_coarse, q_coarse)
        print(f"  coarse peaks={len(coarse)}", flush=True)

        fine_all = []
        for cpos, cscore in coarse:
            csec = cpos / COARSE_HZ
            fine_all.extend(fine_search(s_fine, q_fine, csec))

        # Sort and dedupe near-identical offsets across scales.
        fine_all.sort(key=lambda x:x[1], reverse=True)
        chosen = []
        for pos, score, scale, qlen in fine_all:
            sec = pos / FINE_HZ
            if all(abs(sec - x[0]/FINE_HZ) >= 5.0 for x in chosen):
                chosen.append((pos, score, scale, qlen))
            if len(chosen) >= TOP_FINAL:
                break

        for pos, score, scale, qlen in chosen:
            candidates.append(dict(
                source=src.name,
                source_path=str(src),
                offset_sec=f"{pos/FINE_HZ:.3f}",
                correlation=f"{score:.6f}",
                scale=f"{scale:.3f}",
                query_duration_sec=f"{q_duration:.3f}",
                source_duration_sec=f"{dur:.3f}" if dur is not None else "",
            ))

        best = chosen[0] if chosen else None
        summaries.append(dict(
            source=src.name,
            duration_sec=f"{dur:.3f}" if dur is not None else "",
            coarse_envelope_points=len(s_coarse),
            fine_envelope_points=len(s_fine),
            best_offset_sec=f"{best[0]/FINE_HZ:.3f}" if best else "",
            best_correlation=f"{best[1]:.6f}" if best else "",
            best_scale=f"{best[2]:.3f}" if best else "",
        ))

        if best:
            print(
                f"  best={best[0]/FINE_HZ:.3f}s corr={best[1]:.6f} scale={best[2]:.3f}",
                flush=True
            )

    candidates.sort(key=lambda r:float(r["correlation"]), reverse=True)
    for i,r in enumerate(candidates,1):
        r["global_rank"] = i

    write_tsv(STAGE/"audio_match_candidates.tsv", candidates)
    write_tsv(STAGE/"source_summary.tsv", summaries)

    if not candidates:
        raise RuntimeError("No Stage37 candidates produced")

    # Paired visual confirmation at 4 relative locations for global top 4.
    review=[]
    rel_times=[8.0, 35.0, 70.0, max(8.0, q_duration-8.0)]
    for rank,c in enumerate(candidates[:4],1):
        src=Path(c["source_path"])
        off=float(c["offset_sec"])
        scale=float(c["scale"])

        for j,qt in enumerate(rel_times,1):
            st=off+qt*scale
            simg=REP/f"rank{rank:02d}_{src.stem}_src_{st:09.3f}_rel_{qt:06.3f}.jpg"
            kimg=REP/f"rank{rank:02d}_KR_dk101_{qt:06.3f}.jpg"

            sok=extract_frame(src,st,simg,f"04_rank{rank}_{j}_src_frame.log")
            kok=extract_frame(KR_PMF,qt,kimg,f"05_rank{rank}_{j}_kr_frame.log")

            review.append(dict(
                rank=rank,
                source=src.name,
                correlation=c["correlation"],
                scale=c["scale"],
                offset_sec=c["offset_sec"],
                relative_sec=f"{qt:.3f}",
                source_sec=f"{st:.3f}",
                source_frame=str(simg) if sok else "",
                kr_frame=str(kimg) if kok else "",
            ))

    write_tsv(STAGE/"review_frames.tsv",review)

    best=candidates[0]
    bc=float(best["correlation"])
    if bc>=0.80: confidence="VERY_HIGH"
    elif bc>=0.60: confidence="HIGH"
    elif bc>=0.40: confidence="POSSIBLE"
    else: confidence="WEAK"

    summary=[
        "Naruto PSP MOV05A FIX1 - dk101 Stage37 audio locator",
        "="*80,"",
        "Parser: proven MOV04C PMF/ATRAC recovery",
        "Dependency: pure Python, NumPy not required","",
        f"KR dk101 audio duration={q_duration:.3f}s",
        f"KR ATRAC frames={kra['frame_count']}",
        f"KR audio PES={len(krp['audio'])}","",
        "Best candidate:",
        f"  source={best['source']}",
        f"  offset={best['offset_sec']} sec",
        f"  correlation={best['correlation']}",
        f"  scale={best['scale']}",
        f"  confidence={confidence}","",
        "Paired KR/Stage37 review frames are included.",
        "If visuals match, MOV05B can cut/retime the Stage37 Korean video",
        "and remux exact KR Japanese ATRAC/PTS into a PSP PMF.",
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
