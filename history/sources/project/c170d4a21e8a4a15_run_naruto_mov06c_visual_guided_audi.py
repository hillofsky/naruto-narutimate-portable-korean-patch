#!/usr/bin/env python3
# Naruto PSP MOV06C
# Visual-guided LOCAL audio refinement for:
#   da101, da201, dk102, dk202
#
# MOV06B visually confirmed these source regions:
#   da101 -> source_video.mp4 around 2270.0 sec
#   da201 -> part2.mp4       around 2667.0 sec
#   dk102 -> source_video.mp4 around 7257.5 sec
#   dk202 -> part2.mp4        around 2880.5 sec
#
# MOV06C only searches Japanese audio in a small window around those visually
# confirmed regions. This prevents the global false matches seen in MOV06A.
#
# Analysis only. No PMF/ISO modification.

from __future__ import annotations
import array, csv, importlib.util, math, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
CORE_PATH = ROOT / "mov06c_proven_movie_core.py"

KR_MOVIE_DIR = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
STAGE37_DIR = ROOT / "analysis" / "stage37" / "video"

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

STAGE = ROOT / "analysis" / "mov" / "mov06c_visual_guided_audio_refine"
WORK = STAGE / "work"
LOGD = STAGE / "logs"
REVIEW = STAGE / "review"
for p in (STAGE, WORK, LOGD, REVIEW):
    p.mkdir(parents=True, exist_ok=True)

RATE = 8000
ENV_HZ = 20.0
WIN = int(round(RATE / ENV_HZ))

TARGETS = [
    dict(target="da101", source="source_video.mp4", visual_start=2270.0),
    dict(target="da201", source="part2.mp4",        visual_start=2667.0),
    dict(target="dk102", source="source_video.mp4", visual_start=7257.5),
    dict(target="dk202", source="part2.mp4",        visual_start=2880.5),
]

LOCAL_PAD = 8.0
LOCAL_SEARCH_RADIUS = 3.5
SCALES = [0.997, 1.000, 1.003]

def load_core():
    spec = importlib.util.spec_from_file_location("mov06c_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load PMF core")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STAGE = STAGE
    m.WORK = WORK
    m.LOGD = LOGD
    m.OUT = STAGE
    return m

def run(cmd, logname, timeout=3600):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
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

def decode_pcm(src, out, tag, is_oma=False, ss=None, dur=None):
    cmd = [FFMPEG, "-y", "-v", "warning"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.6f}"]
    if is_oma:
        cmd += ["-f", "oma"]
    cmd += ["-i", src]
    if dur is not None:
        cmd += ["-t", f"{dur:.6f}"]
    cmd += [
        "-vn", "-ac", "1", "-ar", str(RATE),
        "-f", "s16le", "-c:a", "pcm_s16le", out
    ]
    cp = run(cmd, tag, 3600)
    if cp.returncode != 0 or not Path(out).exists() or Path(out).stat().st_size < 1000:
        raise RuntimeError(f"PCM decode failed: {src}")

def load_pcm(path):
    a = array.array("h")
    with Path(path).open("rb") as f:
        a.fromfile(f, Path(path).stat().st_size // 2)
    if sys.byteorder != "little":
        a.byteswap()
    return a

def envelope(pcm):
    n = (len(pcm) // WIN) * WIN
    out = []
    for i in range(0, n, WIN):
        ss = 0.0
        for v in pcm[i:i+WIN]:
            x = float(v) / 32768.0
            ss += x*x
        out.append(math.log1p(math.sqrt(ss/WIN + 1e-12) * 20.0))
    return out

def corr(a, b):
    if len(a) != len(b) or len(a) < 8:
        return -2.0
    ma = sum(a)/len(a)
    mb = sum(b)/len(b)
    va = sum((x-ma)*(x-ma) for x in a)
    vb = sum((y-mb)*(y-mb) for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return -2.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / math.sqrt(va*vb)

def resample(v, scale):
    if abs(scale-1.0) < 1e-12:
        return list(v)
    n = max(8, int(round(len(v)*scale)))
    out = []
    for j in range(n):
        x = j*(len(v)-1)/max(1,n-1)
        i = int(math.floor(x))
        k = min(len(v)-1, i+1)
        f = x-i
        out.append(v[i]*(1-f)+v[k]*f)
    return out

def anchor_plan(duration):
    if duration >= 240:
        centers = [12,32,52,72,92,112,132,152,172,192,212,232,duration-22,duration-10]
        win = 12.0
    elif duration >= 120:
        centers = [10,28,48,68,88,108,duration-18,duration-8]
        win = 10.0
    elif duration >= 45:
        centers = [7,16,26,36,duration-7]
        win = 8.0
    else:
        centers = [6, duration*0.45, duration-6]
        win = 7.0

    half = win/2
    out = []
    for c in centers:
        c = max(half+0.2, min(duration-half-0.2, float(c)))
        if all(abs(c-x) >= win*0.65 for x in out):
            out.append(c)
    return out, win

def best_local_match(qenv, senv, qcenter, window, expected_local_center):
    half = int(round(window*ENV_HZ/2))
    qc = int(round(qcenter*ENV_HZ))
    qa = qc-half
    qb = qc+half
    if qa < 0 or qb > len(qenv):
        return None

    qbase = qenv[qa:qb]
    best = None

    for scale in SCALES:
        q = resample(qbase, scale)
        shalf = len(q)//2
        lo = int(round((expected_local_center-LOCAL_SEARCH_RADIUS)*ENV_HZ))
        hi = int(round((expected_local_center+LOCAL_SEARCH_RADIUS)*ENV_HZ))

        for sc in range(lo, hi+1):
            sa = sc-shalf
            sb = sa+len(q)
            if sa < 0 or sb > len(senv):
                continue
            c = corr(q, senv[sa:sb])
            source_center_local = (sa + len(q)/2) / ENV_HZ
            item = (c, source_center_local, scale)
            if best is None or item[0] > best[0]:
                best = item
    return best

def linear_fit(xs, ys):
    if len(xs) < 2:
        return (ys[0]-xs[0], 1.0, 0.0)
    mx = sum(xs)/len(xs)
    my = sum(ys)/len(ys)
    denom = sum((x-mx)*(x-mx) for x in xs)
    if denom <= 1e-12:
        return (my-mx, 1.0, 0.0)
    slope = sum((x-mx)*(y-my) for x,y in zip(xs,ys)) / denom
    intercept = my - slope*mx
    residuals = [y-(intercept+slope*x) for x,y in zip(xs,ys)]
    rms = math.sqrt(sum(r*r for r in residuals)/len(residuals))
    return intercept, slope, rms

def classify_offsets(rows):
    good = [r for r in rows if float(r["correlation"]) >= 0.42]
    if not good:
        return dict(status="NO_AUDIO_LOCK")

    offs = [float(r["offset_sec"]) for r in good]
    med = statistics.median(offs)
    spread = max(offs)-min(offs) if len(offs)>1 else 0.0

    xs = [float(r["kr_center_sec"]) for r in good]
    ys = [float(r["source_center_sec"]) for r in good]
    intercept, slope, rms = linear_fit(xs, ys)

    # Detect offset jumps between adjacent trustworthy anchors.
    jumps = []
    sg = sorted(good, key=lambda r: float(r["kr_center_sec"]))
    for a,b in zip(sg, sg[1:]):
        da = float(a["offset_sec"])
        db = float(b["offset_sec"])
        if abs(db-da) >= 0.35:
            jumps.append(dict(
                after_kr_sec=float(a["kr_center_sec"]),
                before_kr_sec=float(b["kr_center_sec"]),
                offset_before=da,
                offset_after=db,
                delta=db-da,
            ))

    if len(good) >= 2 and not jumps and spread <= 0.25 and abs(slope-1.0) <= 0.0025:
        status = "CONTINUOUS"
    elif len(good) >= 3 and not jumps and rms <= 0.12 and abs(slope-1.0) <= 0.006:
        status = "LINEAR_DRIFT"
    elif jumps:
        status = "PIECEWISE_EDIT"
    else:
        status = "REVIEW"

    return dict(
        status=status,
        good_count=len(good),
        median_offset=med,
        spread=spread,
        intercept=intercept,
        slope=slope,
        rms=rms,
        jumps=jumps,
        avg_corr=sum(float(r["correlation"]) for r in good)/len(good),
    )

def extract_frame(src, sec, out, tag):
    cp = run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{max(0,sec):.3f}",
         "-i", src, "-frames:v", "1", "-q:v", "2", out],
        tag, 180
    )
    return cp.returncode == 0 and Path(out).exists()

def main():
    core = load_core()

    for p in [CORE_PATH, FFMPEG, FFPROBE]:
        if not p.exists():
            raise RuntimeError(f"Missing tool/core: {p}")

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("="*80, flush=True)
    print(" Naruto PSP MOV06C - visual-guided LOCAL audio refinement", flush=True)
    print("="*80, flush=True)

    all_rows = []
    summary_rows = []
    jump_rows = []

    for ti, cfg in enumerate(TARGETS, 1):
        target = cfg["target"]
        source = STAGE37_DIR / cfg["source"]
        pmf = KR_MOVIE_DIR / f"{target}.pmf"
        visual_start = float(cfg["visual_start"])

        for p in (source, pmf):
            if not p.exists():
                raise RuntimeError(f"Missing input: {p}")

        print("", flush=True)
        print(f"[{ti}/{len(TARGETS)}] {target}", flush=True)

        # Exact KR audio from PMF.
        parsed = core.parse_pmf(pmf)
        audio = core.recover_audio(parsed)
        if audio["bad_headers"]:
            raise RuntimeError(f"{target}: bad KR AU headers")

        oma = WORK / f"{target}.oma"
        core.build_oma(audio["frames"], oma)

        kr_pcm_path = WORK / f"{target}_kr.s16"
        decode_pcm(oma, kr_pcm_path, f"01_{target}_decode_kr.log", is_oma=True)
        kr_pcm = load_pcm(kr_pcm_path)
        qenv = envelope(kr_pcm)
        qdur = len(kr_pcm)/RATE
        del kr_pcm

        # Local Stage37 window only around the visually confirmed scene.
        local_start = max(0.0, visual_start-LOCAL_PAD)
        local_dur = qdur + 2*LOCAL_PAD
        src_pcm_path = WORK / f"{target}_source_local.s16"
        decode_pcm(
            source, src_pcm_path, f"02_{target}_decode_source_local.log",
            ss=local_start, dur=local_dur
        )
        src_pcm = load_pcm(src_pcm_path)
        senv = envelope(src_pcm)
        del src_pcm

        centers, win = anchor_plan(qdur)
        rows = []

        for ai, qc in enumerate(centers, 1):
            expected_global_center = visual_start + qc
            expected_local_center = expected_global_center - local_start

            m = best_local_match(
                qenv, senv, qc, win, expected_local_center
            )
            if m is None:
                continue

            c, source_center_local, scale = m
            source_center_global = local_start + source_center_local
            off = source_center_global - qc

            row = dict(
                target=target,
                source=source.name,
                anchor_index=ai,
                kr_center_sec=f"{qc:.3f}",
                window_sec=f"{win:.3f}",
                visual_expected_center_sec=f"{expected_global_center:.3f}",
                source_center_sec=f"{source_center_global:.3f}",
                offset_sec=f"{off:.3f}",
                delta_from_visual_start_sec=f"{off-visual_start:.3f}",
                correlation=f"{c:.6f}",
                scale=f"{scale:.3f}",
            )
            rows.append(row)
            all_rows.append(row)

        result = classify_offsets(rows)

        if result["status"] == "NO_AUDIO_LOCK":
            summary_rows.append(dict(
                target=target,
                source=source.name,
                visual_start_sec=f"{visual_start:.3f}",
                audio_status="NO_AUDIO_LOCK",
            ))
            print("  no local audio lock; visual mapping remains authoritative", flush=True)
            continue

        audio_start = result["intercept"]
        slope = result["slope"]

        summary_rows.append(dict(
            target=target,
            source=source.name,
            kr_audio_duration_sec=f"{qdur:.3f}",
            visual_start_sec=f"{visual_start:.3f}",
            trustworthy_anchor_count=result["good_count"],
            anchor_count=len(rows),
            avg_correlation=f"{result['avg_corr']:.6f}",
            median_offset_sec=f"{result['median_offset']:.6f}",
            offset_spread_sec=f"{result['spread']:.6f}",
            fitted_source_start_sec=f"{audio_start:.6f}",
            fitted_time_scale=f"{slope:.9f}",
            fitted_rms_sec=f"{result['rms']:.6f}",
            detected_jump_count=len(result["jumps"]),
            audio_status=result["status"],
        ))

        for ji, j in enumerate(result["jumps"], 1):
            jump_rows.append(dict(
                target=target,
                jump_index=ji,
                after_kr_sec=f"{j['after_kr_sec']:.3f}",
                before_kr_sec=f"{j['before_kr_sec']:.3f}",
                offset_before_sec=f"{j['offset_before']:.3f}",
                offset_after_sec=f"{j['offset_after']:.3f}",
                offset_delta_sec=f"{j['delta']:.3f}",
            ))

        print(
            f"  {result['status']}: anchors={result['good_count']}/{len(rows)} "
            f"corr={result['avg_corr']:.4f} "
            f"start={audio_start:.3f} scale={slope:.7f} "
            f"spread={result['spread']:.3f}s rms={result['rms']:.3f}s "
            f"jumps={len(result['jumps'])}",
            flush=True
        )

        # Representative source/KR images at trustworthy audio anchors.
        good = [r for r in rows if float(r["correlation"]) >= 0.42]
        if good:
            picks = [good[0], good[len(good)//2], good[-1]]
            seen = set()
            for pi, r in enumerate(picks, 1):
                kt = float(r["kr_center_sec"])
                st = float(r["source_center_sec"])
                key = (round(kt,3),round(st,3))
                if key in seen:
                    continue
                seen.add(key)

                ko = REVIEW / f"{target}_pair{pi}_KR_{kt:08.3f}.jpg"
                so = REVIEW / f"{target}_pair{pi}_{source.stem}_{st:09.3f}.jpg"
                extract_frame(pmf, kt, ko, f"review_{target}_{pi}_kr.log")
                extract_frame(source, st, so, f"review_{target}_{pi}_src.log")

    write_tsv(STAGE/"local_audio_anchors.tsv", all_rows)
    write_tsv(STAGE/"target_alignment.tsv", summary_rows)
    write_tsv(STAGE/"detected_offset_jumps.tsv", jump_rows)

    summary = [
        "Naruto PSP MOV06C - visual-guided local audio refinement",
        "="*80,
        "",
        "MOV06B visual matches confirmed by representative-frame review:",
        "  da101 -> source_video.mp4 around 2270 sec",
        "  da201 -> part2.mp4 around 2667 sec",
        "  dk102 -> source_video.mp4 around 7257.5 sec",
        "  dk202 -> part2.mp4 around 2880.5 sec",
        "",
        "MOV06C searches audio ONLY near those confirmed visual regions.",
        "Global MOV06A audio candidates are not reused.",
        "",
    ]

    for r in summary_rows:
        summary += [
            f"{r['target']}:",
            f"  source={r['source']}",
            f"  visual start={r['visual_start_sec']} sec",
            f"  status={r['audio_status']}",
        ]
        if r["audio_status"] != "NO_AUDIO_LOCK":
            summary += [
                f"  fitted audio start={r['fitted_source_start_sec']} sec",
                f"  scale={r['fitted_time_scale']}",
                f"  anchors={r['trustworthy_anchor_count']}/{r['anchor_count']}",
                f"  avg corr={r['avg_correlation']}",
                f"  offset spread={r['offset_spread_sec']} sec",
                f"  jumps={r['detected_jump_count']}",
            ]
        summary.append("")

    summary += [
        "Next:",
        "  CONTINUOUS targets can be built as one exact Stage37 trim.",
        "  LINEAR_DRIFT targets can be resampled by the fitted scale.",
        "  PIECEWISE_EDIT targets will be split at the detected offset jump(s).",
        "  Final PMFs will keep exact KR ATRAC3+ frames and exact KR PTS.",
    ]

    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n", encoding="utf-8-sig")
    print("", flush=True)
    print("\n".join(summary), flush=True)
    return 0

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
