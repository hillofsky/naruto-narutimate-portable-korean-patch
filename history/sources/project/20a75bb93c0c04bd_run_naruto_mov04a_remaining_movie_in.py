#!/usr/bin/env python3
# Naruto PSP MOV04A - remaining DA/DK movie subtitle inventory
#
# Targets:
#   da101 da102 da103 da201
#   dk101 dk102 dk103 dk104 dk201 dk202 dk203
#
# Goal:
#   Find which remaining KR movies contain burned Japanese subtitles/text that
#   need the same Korean-video treatment as dm001..dm010.
#
# Two independent signals are used:
#
#   A) KR-only lower-band bright-text signal
#      Useful when subtitles sit on a dark/black lower band.
#
#   B) KR-vs-US aligned lower-band visual difference
#      Useful when subtitles are burned over picture instead of a black bar.
#      Scene fingerprints ABOVE the subtitle area are used to locally align
#      KR and US frames before the lower band is compared.
#
# This is an inventory/review stage only. It does not modify any PMF/ISO.

from __future__ import annotations
import csv, json, math, os, shutil, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov04a_remaining_movie_inventory"
REP = STAGE / "representatives"
LOGD = STAGE / "logs"
WORK = STAGE / "work"
for p in (STAGE, REP, LOGD, WORK):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

MOVIES = [
    "da101","da102","da103","da201",
    "dk101","dk102","dk103","dk104","dk201","dk202","dk203",
]

FPS = 5.0

# Scene fingerprint excludes bottom 64 px.
SCENE_X, SCENE_Y, SCENE_W, SCENE_H = 24, 0, 432, 208
SCENE_LW, SCENE_LH = 32, 16
SCENE_BYTES = SCENE_LW * SCENE_LH

# Subtitle/text comparison band.
BOT_X, BOT_Y, BOT_W, BOT_H = 24, 208, 432, 64
BOT_LW, BOT_LH = 108, 16
BOT_BYTES = BOT_LW * BOT_LH

SEARCH_RADIUS_FRAMES = 10     # +/-2.0 sec at 5 fps
MIN_SEGMENT_FRAMES = 1
FILL_GAP_FRAMES = 1

def run(cmd, logname, timeout=1200):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        timeout=timeout
    )
    text = "COMMANLOCAL_PATH" + " ".join(
        ('"%s"' % str(x) if " " in str(x) else str(x)) for x in cmd
    )
    text += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    text += "\n\nSTDOULOCAL_PATH" + cp.stdout
    text += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(text, encoding="utf-8-sig")
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

def probe(path, tag):
    cp = run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        f"{tag}_probe.log", 120
    )
    if cp.returncode != 0:
        return None
    try:
        return json.loads(cp.stdout)
    except Exception:
        return None

def get_duration(info):
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

def us_source(name):
    # Prefer localized clean *e.pmf if present.
    candidates = [
        US_MOV / f"{name}e.pmf",
        US_MOV / f"{name}.pmf",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def decode_raw_gray(path, vf, frame_bytes, tag):
    cmd = [
        str(FFMPEG), "-v", "error", "-i", str(path),
        "-vf", vf,
        "-pix_fmt", "gray", "-f", "rawvideo", "-"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    assert p.stdout is not None

    while True:
        b = p.stdout.read(frame_bytes)
        if not b:
            break
        if len(b) != frame_bytes:
            break
        frames.append(b)

    stderr = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
    rc = p.wait()

    (LOGD / f"{tag}_decode.log").write_text(
        "COMMANLOCAL_PATH" + " ".join(cmd) +
        "\n\nRETURN CODLOCAL_PATH" + str(rc) +
        "\n\nSTDERLOCAL_PATH" + stderr + "\n",
        encoding="utf-8-sig"
    )

    if rc != 0:
        raise RuntimeError(f"{tag}: ffmpeg decode failed")
    return frames

def decode_movie_features(path, tag):
    scene_vf = (
        f"fps={FPS},crop={SCENE_W}:{SCENE_H}:{SCENE_X}:{SCENE_Y},"
        f"scale={SCENE_LW}:{SCENE_LH}:flags=area,format=gray"
    )
    bottom_vf = (
        f"fps={FPS},crop={BOT_W}:{BOT_H}:{BOT_X}:{BOT_Y},"
        f"scale={BOT_LW}:{BOT_LH}:flags=area,format=gray"
    )
    scene = decode_raw_gray(path, scene_vf, SCENE_BYTES, tag + "_scene")
    bottom = decode_raw_gray(path, bottom_vf, BOT_BYTES, tag + "_bottom")
    n = min(len(scene), len(bottom))
    return scene[:n], bottom[:n]

def mad(a, b):
    return sum(abs(x-y) for x, y in zip(a,b)) / len(a)

def percentile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    x = (len(s)-1) * q
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    if lo == hi:
        return float(s[lo])
    f = x-lo
    return s[lo]*(1-f)+s[hi]*f

def robust_threshold(vals):
    if not vals:
        return 999.0, 0.0, 0.0
    med = statistics.median(vals)
    absdev = [abs(v-med) for v in vals]
    madv = statistics.median(absdev)
    p90 = percentile(vals, 0.90)

    # Localized burned text is typically well above normal codec/localization
    # noise. Keep a floor so near-identical streams do not over-trigger.
    threshold = max(med + max(2.0, 6.0*madv), p90 + 1.25)
    return threshold, med, madv

def align_frames(kr_scene, us_scene):
    if not kr_scene or not us_scene:
        return []
    ratio = ((len(us_scene)-1)/(len(kr_scene)-1)) if len(kr_scene) > 1 else 1.0
    mapped = []

    prev = 0
    for i, kf in enumerate(kr_scene):
        expected = int(round(i * ratio))
        lo = max(prev, expected - SEARCH_RADIUS_FRAMES)
        hi = min(len(us_scene)-1, expected + SEARCH_RADIUS_FRAMES)
        if lo > hi:
            lo = hi = min(len(us_scene)-1, max(0, expected))

        best_j = lo
        best_s = None
        for j in range(lo, hi+1):
            s = mad(kf, us_scene[j])
            if best_s is None or s < best_s:
                best_s = s
                best_j = j

        mapped.append((best_j, best_s if best_s is not None else 999.0))
        prev = best_j

    return mapped

def bright_dark_score(frame):
    # Low-res bottom band heuristic:
    # count clearly bright pixels, but only reward them when the surrounding
    # band is fairly dark.
    if not frame:
        return 0.0, 0, 255.0
    mean = sum(frame)/len(frame)
    bright = sum(1 for x in frame if x >= 150)
    # "text score" intentionally collapses on bright scene backgrounds.
    dark_factor = max(0.0, min(1.0, (105.0 - mean)/70.0))
    score = bright * dark_factor
    return score, bright, mean

def binary_segments(active):
    # Fill single-frame holes.
    a = list(active)
    for i in range(1, len(a)-1):
        if not a[i] and a[i-1] and a[i+1]:
            a[i] = True

    out = []
    start = None
    for i, on in enumerate(a):
        if on and start is None:
            start = i
        if not on and start is not None:
            if i-start >= MIN_SEGMENT_FRAMES:
                out.append((start, i-1))
            start = None
    if start is not None and len(a)-start >= MIN_SEGMENT_FRAMES:
        out.append((start, len(a)-1))
    return out

def extract_exact_images(src, indices, name, side):
    """
    Extract exact FPS-grid full frame + lower-band crop for all requested
    indices in two batch ffmpeg passes.
    """
    unique = sorted(set(int(i) for i in indices))
    if not unique:
        return {}, {}

    result_full = {}
    result_bottom = {}

    for kind, vf_tail, ext in [
        ("full", "scale=480:272", "jpg"),
        ("bottom", f"crop={BOT_W}:{BOT_H}:{BOT_X}:{BOT_Y},scale=864:128:flags=neighbor", "png"),
    ]:
        tmp = WORK / f"_{name}_{side}_{kind}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)

        expr = "+".join(f"eq(n\\,{i})" for i in unique)
        pattern = tmp / f"f_%04d.{ext}"

        cmd = [
            FFMPEG, "-y", "-v", "error", "-i", src,
            "-vf", f"fps={FPS},select={expr},{vf_tail}",
            "-fps_mode", "vfr"
        ]
        if ext == "jpg":
            cmd += ["-q:v", "3"]
        cmd += [pattern]

        cp = run(cmd, f"{name}_{side}_{kind}_extract.log", 900)
        generated = sorted(tmp.glob(f"*.{ext}"))

        if cp.returncode == 0 and len(generated) == len(unique):
            for idx, gp in zip(unique, generated):
                out = REP / f"{name}_{side}_f{idx:05d}_{kind}.{ext}"
                shutil.move(str(gp), str(out))
                if kind == "full":
                    result_full[idx] = str(out)
                else:
                    result_bottom[idx] = str(out)

        shutil.rmtree(tmp, ignore_errors=True)

    return result_full, result_bottom

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("LOCAL_PATH / ffprobe.exe missing")

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    for p in REP.glob("*"):
        if p.is_file():
            p.unlink()

    print("="*80, flush=True)
    print(" Naruto PSP MOV04A - remaining DA/DK subtitle inventory", flush=True)
    print("="*80, flush=True)

    movie_rows = []
    segment_rows = []
    frame_rows = []

    for mi, name in enumerate(MOVIES, 1):
        kr = KR_MOV / f"{name}.pmf"
        us = us_source(name)

        print(f"[{mi:02d}/11] {name}", flush=True)

        if not kr.exists():
            movie_rows.append(dict(movie=name, status="MISSING_KR"))
            print("  KR source missing", flush=True)
            continue

        ki = probe(kr, name+"_kr")
        kd = get_duration(ki)

        if us is None:
            # Still run KR-only dark-band heuristic.
            kr_scene, kr_bottom = decode_movie_features(kr, name+"_kr")
            diff_scores = [0.0]*len(kr_bottom)
            mappings = [(i, 0.0) for i in range(len(kr_bottom))]
            us_scene = []
            us_bottom = []
            threshold = 999.0
            baseline = 0.0
            baseline_mad = 0.0
            ud = None
        else:
            ui = probe(us, name+"_us")
            ud = get_duration(ui)
            kr_scene, kr_bottom = decode_movie_features(kr, name+"_kr")
            us_scene, us_bottom = decode_movie_features(us, name+"_us")
            mappings = align_frames(kr_scene, us_scene)

            diff_scores = []
            for i, (uj, scene_mad) in enumerate(mappings):
                if i >= len(kr_bottom) or uj >= len(us_bottom):
                    diff_scores.append(0.0)
                else:
                    diff_scores.append(mad(kr_bottom[i], us_bottom[uj]))

            threshold, baseline, baseline_mad = robust_threshold(diff_scores)

        dark_scores = []
        bright_counts = []
        band_means = []
        for fr in kr_bottom:
            score, bright, mean = bright_dark_score(fr)
            dark_scores.append(score)
            bright_counts.append(bright)
            band_means.append(mean)

        # Adaptive KR-only threshold. A dark-band subtitle typically generates
        # a strong score; use p90 to avoid treating normal frame texture as text.
        dark_thr = max(8.0, percentile(dark_scores, 0.90) + 4.0)

        active = []
        for i in range(len(kr_bottom)):
            diff_on = bool(us is not None and i < len(diff_scores) and diff_scores[i] >= threshold)
            dark_on = dark_scores[i] >= dark_thr
            active.append(diff_on or dark_on)

            uj = mappings[i][0] if i < len(mappings) else ""
            sm = mappings[i][1] if i < len(mappings) else ""
            frame_rows.append(dict(
                movie=name,
                kr_frame=i,
                kr_time=f"{i/FPS:.3f}",
                us_frame=uj,
                us_time=f"{uj/FPS:.3f}" if uj != "" else "",
                scene_match_mad=f"{sm:.6f}" if sm != "" else "",
                bottom_diff_mad=f"{diff_scores[i]:.6f}" if i < len(diff_scores) else "",
                dark_text_score=f"{dark_scores[i]:.6f}",
                bright_pixels_lowres=bright_counts[i],
                bottom_mean=f"{band_means[i]:.6f}",
                diff_active="YES" if (us is not None and i < len(diff_scores) and diff_scores[i] >= threshold) else "NO",
                dark_active="YES" if dark_scores[i] >= dark_thr else "NO",
                candidate_active="YES" if active[i] else "NO",
            ))

        segs = binary_segments(active)

        # Choose representative by strongest normalized evidence.
        reps = []
        us_rep_indices = []
        for si, (a,b) in enumerate(segs, 1):
            best_i = a
            best_score = -1.0
            for i in range(a,b+1):
                ds = (diff_scores[i]/threshold) if threshold > 0 and threshold < 900 else 0.0
                ks = (dark_scores[i]/dark_thr) if dark_thr > 0 else 0.0
                score = max(ds, ks)
                if score > best_score:
                    best_score = score
                    best_i = i

            uj = mappings[best_i][0] if best_i < len(mappings) else best_i
            reps.append((si,a,b,best_i,uj,best_score))
            us_rep_indices.append(uj)

        kr_indices = [x[3] for x in reps]
        kr_full, kr_bottom_img = extract_exact_images(kr, kr_indices, name, "KR")

        if us is not None:
            us_full, us_bottom_img = extract_exact_images(us, us_rep_indices, name, "US")
        else:
            us_full, us_bottom_img = {}, {}

        for si,a,b,ri,uj,best_score in reps:
            segment_rows.append(dict(
                movie=name,
                segment=si,
                kr_start_sec=f"{a/FPS:.3f}",
                kr_end_sec=f"{(b+1)/FPS:.3f}",
                duration_sec=f"{(b-a+1)/FPS:.3f}",
                kr_rep_frame=ri,
                kr_rep_sec=f"{ri/FPS:.3f}",
                us_rep_frame=uj if us is not None else "",
                us_rep_sec=f"{uj/FPS:.3f}" if us is not None else "",
                rep_bottom_diff_mad=f"{diff_scores[ri]:.6f}" if ri < len(diff_scores) else "",
                rep_dark_text_score=f"{dark_scores[ri]:.6f}",
                rep_strength=f"{best_score:.6f}",
                kr_full_image=kr_full.get(ri,""),
                kr_bottom_image=kr_bottom_img.get(ri,""),
                us_full_image=us_full.get(uj,"") if us is not None else "",
                us_bottom_image=us_bottom_img.get(uj,"") if us is not None else "",
                review_status="PENDING",
            ))

        max_diff = max(diff_scores) if diff_scores else 0.0
        max_dark = max(dark_scores) if dark_scores else 0.0

        movie_rows.append(dict(
            movie=name,
            status="OK",
            kr_source=str(kr),
            us_source=str(us) if us else "",
            us_counterpart="YES" if us else "NO",
            kr_duration=f"{kd:.6f}" if kd is not None else "",
            us_duration=f"{ud:.6f}" if ud is not None else "",
            duration_delta=f"{(ud-kd):+.6f}" if (ud is not None and kd is not None) else "",
            frames_analyzed=len(kr_bottom),
            candidate_segments=len(segs),
            paired_diff_threshold=f"{threshold:.6f}" if us else "",
            paired_diff_baseline=f"{baseline:.6f}" if us else "",
            paired_diff_mad=f"{baseline_mad:.6f}" if us else "",
            paired_diff_max=f"{max_diff:.6f}",
            dark_text_threshold=f"{dark_thr:.6f}",
            dark_text_max=f"{max_dark:.6f}",
            likely_needs_review="YES" if segs else "NO",
        ))

        print(
            f"  KR/US duration={kd if kd is not None else '?'} / "
            f"{ud if ud is not None else 'N/A'}  "
            f"candidates={len(segs)} "
            f"diffMax={max_diff:.2f} darkMax={max_dark:.2f}",
            flush=True
        )

    write_tsv(STAGE/"movie_inventory.tsv", movie_rows)
    write_tsv(STAGE/"candidate_segments.tsv", segment_rows)
    write_tsv(STAGE/"frame_metrics.tsv", frame_rows)

    ok_movies = sum(1 for r in movie_rows if r.get("status")=="OK")
    candidate_movies = [r["movie"] for r in movie_rows if int(r.get("candidate_segments",0)) > 0]
    total_segments = sum(int(r.get("candidate_segments",0)) for r in movie_rows if r.get("status")=="OK")

    summary = [
        "Naruto PSP MOV04A - remaining DA/DK subtitle inventory",
        "="*80, "",
        f"Movies analyzed={ok_movies}/11",
        f"Movies with candidate burned text={len(candidate_movies)}",
        f"Candidate segments={total_segments}",
        "Candidate movies=" + (", ".join(candidate_movies) if candidate_movies else "(none)"),
        "",
        "Signals:",
        "  1) KR-only bright text on dark lower band",
        "  2) locally aligned KR-vs-US lower-band visual difference",
        "",
        "Representatives include KR/US full frames and lower-band crops.",
        "This stage is deliberately sensitive; visual review determines which",
        "candidates are real subtitles versus localized graphics/scene changes.",
    ]
    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if ok_movies == 11 else 2

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True, exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
