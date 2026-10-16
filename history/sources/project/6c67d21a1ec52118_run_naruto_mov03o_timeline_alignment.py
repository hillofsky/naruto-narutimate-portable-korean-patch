#!/usr/bin/env python3
# Naruto PSP MOV03O - KR subtitle timeline -> US clean movie alignment
#
# Input:
#   MOV03N subtitle_segments.tsv (KR 10-fps timeline)
#
# Final video source:
#   US dmXXXe.pmf clean localized movie
#
# Problem:
#   KR/US movie durations differ slightly, so KR subtitle times must not be
#   copied blindly onto the US video.
#
# Method:
#   Decode KR and US visual content ABOVE the subtitle bar at 10 fps:
#     crop 432x216 at x=24,y=0
#     scale to 32x16 grayscale
#
#   For each subtitle segment, match three KR frames independently:
#     start
#     representative
#     end
#
#   Search the corresponding US frame inside a local +/-3.0 second window.
#   Score = mean absolute grayscale difference.
#
#   The subtitle bar itself is excluded, so burned Japanese text cannot affect
#   the visual match.
#
# Outputs:
#   subtitle_segments_us_timing.tsv
#   alignment_anchor_details.tsv
#   alignment_movie_summary.tsv
#   alignment_samples\  (first/middle/last segment KR/US pair per movie)
#
# No OCR/translation is performed here.

from __future__ import annotations
import csv, math, os, shutil, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
US_MOV = ROOT / "us_extracted" / "PSP_GAME" / "USRDIR" / "movie"

N_STAGE = ROOT / "analysis" / "mov" / "mov03n_subtitle_timing"
IN_TSV = N_STAGE / "subtitle_segments.tsv"

STAGE = ROOT / "analysis" / "mov" / "mov03o_timeline_alignment"
WORK = STAGE / "work"
SAMPLES = STAGE / "alignment_samples"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, SAMPLES, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")

FPS = 10.0
LW = 32
LH = 16
FRAME_BYTES = LW * LH
SEARCH_RADIUS = 30  # frames = +/- 3.0 sec
POOR_MAD = 24.0

DM = [f"dm{i:03d}" for i in range(1, 11)]

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

def read_tsv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def run(cmd, logname, timeout=900):
    cp = subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    txt = "COMMANLOCAL_PATH" + " ".join(('"%s"' % x if " " in str(x) else str(x)) for x in cmd)
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout + "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD / logname).write_text(txt, encoding="utf-8-sig")
    return cp

def us_source(name):
    e = US_MOV / f"{name}e.pmf"
    if e.exists():
        return e
    p = US_MOV / f"{name}.pmf"
    return p if p.exists() else None

def decode_lowres(path, name, side):
    """
    Exact 10-fps visual fingerprint frames, excluding subtitle band.
    480x272 -> crop center 432x216 -> 32x16 gray.
    """
    cmd = [
        str(FFMPEG), "-v", "error", "-i", str(path),
        "-vf", f"fps={FPS},crop=432:216:24:0,scale={LW}:{LH}:flags=area,format=gray",
        "-pix_fmt", "gray", "-f", "rawvideo", "-"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    assert p.stdout is not None
    while True:
        b = p.stdout.read(FRAME_BYTES)
        if not b:
            break
        if len(b) != FRAME_BYTES:
            break
        frames.append(b)
    stderr = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
    rc = p.wait()
    (LOGD / f"{name}_{side}_lowres.log").write_text(
        "COMMANLOCAL_PATH" + " ".join(cmd) +
        "\n\nRETURN CODLOCAL_PATH" + str(rc) +
        "\n\nSTDERLOCAL_PATH" + stderr + "\n",
        encoding="utf-8-sig"
    )
    if rc != 0 or not frames:
        raise RuntimeError(f"{name}: failed low-res decode for {side}")
    return frames

def mad(a, b):
    # Mean absolute difference, 0..255.
    return sum(abs(x-y) for x, y in zip(a, b)) / FRAME_BYTES

def texture_score(frame):
    # Simple local contrast indicator. Low values mean visually flat/static
    # frames where time matching is inherently less unique.
    m = sum(frame) / len(frame)
    return sum(abs(x-m) for x in frame) / len(frame)

def match_frame(kr_frames, us_frames, kidx, expected):
    expected = max(0, min(len(us_frames)-1, int(round(expected))))
    lo = max(0, expected - SEARCH_RADIUS)
    hi = min(len(us_frames)-1, expected + SEARCH_RADIUS)

    scored = []
    kf = kr_frames[kidx]
    for j in range(lo, hi+1):
        s = mad(kf, us_frames[j])
        scored.append((s, abs(j-expected), j))

    scored.sort(key=lambda x: (x[0], x[1]))
    best = scored[0]
    second = scored[1] if len(scored) > 1 else best

    # A second-best at the adjacent frame is expected for low-motion video.
    # Also compute a "distant" runner-up >=3 frames away.
    distant = next((x for x in scored[1:] if abs(x[2]-best[2]) >= 3), second)

    return dict(
        us_index=best[2],
        mad=best[0],
        second_mad=second[0],
        distant_second_mad=distant[0],
        margin=distant[0]-best[0],
        expected=expected,
        search_lo=lo,
        search_hi=hi,
        kr_texture=texture_score(kf),
    )

def exact_index_jpegs(src, name, indices, outdir, prefix):
    """
    Extract unique fps=10 frame indices in one FFmpeg pass.
    Returns {frame_index: jpg_path}.
    """
    unique = sorted(set(int(i) for i in indices))
    if not unique:
        return {}

    tmp = WORK / f"_extract_{name}_{prefix}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    expr = "+".join(f"eq(n\\,{i})" for i in unique)
    pat = tmp / "f_%04d.jpg"
    cp = run(
        [FFMPEG, "-y", "-v", "error", "-i", src,
         "-vf", f"fps={FPS},select={expr},scale=480:272",
         "-fps_mode", "vfr", "-q:v", "3", pat],
        f"{name}_{prefix}_sample_extract.log", 600
    )
    gen = sorted(tmp.glob("f_*.jpg"))
    if cp.returncode != 0 or len(gen) != len(unique):
        shutil.rmtree(tmp, ignore_errors=True)
        return {}

    result = {}
    for idx, gp in zip(unique, gen):
        out = outdir / f"{name}_{prefix}_f{idx:04d}.jpg"
        shutil.move(str(gp), str(out))
        result[idx] = out
    shutil.rmtree(tmp, ignore_errors=True)
    return result

def main():
    if not FFMPEG.exists():
        raise RuntimeError("LOCAL_PATH missing")
    if not IN_TSV.exists():
        raise RuntimeError(f"MOV03N subtitle TSV missing: {IN_TSV}")

    rows = read_tsv(IN_TSV)
    if not rows:
        raise RuntimeError("subtitle_segments.tsv is empty")

    # Remove stale samples from earlier alignment attempts.
    for p in SAMPLES.glob("*"):
        if p.is_file():
            p.unlink()

    print("="*80, flush=True)
    print(" Naruto PSP MOV03O - KR -> US subtitle timeline alignment", flush=True)
    print("="*80, flush=True)

    out_rows = []
    anchor_rows = []
    movie_summary = []
    poor_total = 0

    by_movie = {m: [r for r in rows if r["movie"] == m] for m in DM}

    for mi, movie in enumerate(DM, 1):
        mrows = by_movie[movie]
        kr_path = KR_MOV / f"{movie}.pmf"
        us_path = us_source(movie)

        print(f"[{mi:02d}/10] {movie} segments={len(mrows)}", flush=True)

        if not mrows:
            movie_summary.append(dict(movie=movie, status="NO_SEGMENTS"))
            continue
        if not kr_path.exists() or us_path is None:
            raise RuntimeError(f"{movie}: source PMF missing")

        kr_frames = decode_lowres(kr_path, movie, "kr")
        us_frames = decode_lowres(us_path, movie, "us")

        # Initial prediction uses total-frame ratio, which already absorbs
        # small overall duration differences. Local search handles edit drift.
        ratio = ((len(us_frames)-1) / (len(kr_frames)-1)
                 if len(kr_frames) > 1 else 1.0)

        movie_anchor_start = len(anchor_rows)
        movie_out_start = len(out_rows)
        best_mads = []
        offsets = []
        poor = 0

        for r in mrows:
            seg = int(r["segment"])
            k_start = max(0, min(len(kr_frames)-1, int(round(float(r["start_sec"]) * FPS))))
            k_rep = max(0, min(len(kr_frames)-1, int(r.get("representative_frame") or round(float(r["representative_sec"]) * FPS))))

            # end_sec is exclusive in MOV03N. Match the final active KR frame.
            k_end = max(k_start, min(len(kr_frames)-1, int(round(float(r["end_sec"]) * FPS)) - 1))

            matches = {}
            for kind, kidx in (("start", k_start), ("rep", k_rep), ("end", k_end)):
                exp = kidx * ratio
                m = match_frame(kr_frames, us_frames, kidx, exp)
                matches[kind] = m
                best_mads.append(m["mad"])
                offsets.append(m["us_index"] - kidx)
                quality = "POOR" if m["mad"] > POOR_MAD else "OK"
                if quality == "POOR":
                    poor += 1
                    poor_total += 1

                anchor_rows.append(dict(
                    movie=movie,
                    segment=seg,
                    anchor=kind,
                    kr_frame=kidx,
                    kr_time=f"{kidx/FPS:.3f}",
                    predicted_us_frame=m["expected"],
                    us_frame=m["us_index"],
                    us_time=f"{m['us_index']/FPS:.3f}",
                    frame_offset=m["us_index"]-kidx,
                    mad=f"{m['mad']:.6f}",
                    distant_second_mad=f"{m['distant_second_mad']:.6f}",
                    margin=f"{m['margin']:.6f}",
                    kr_texture=f"{m['kr_texture']:.6f}",
                    quality=quality,
                ))

            us_start = matches["start"]["us_index"] / FPS
            us_rep = matches["rep"]["us_index"] / FPS
            us_end = (matches["end"]["us_index"] + 1) / FPS

            # Preserve sane ordering in rare static-frame ambiguous matches.
            if us_rep < us_start:
                us_rep = us_start
            if us_end <= us_start:
                us_end = us_start + max(0.1, float(r["duration_sec"]))

            nr = dict(r)
            nr.update(
                kr_start_sec=r["start_sec"],
                kr_end_sec=r["end_sec"],
                kr_representative_sec=r["representative_sec"],
                us_start_sec=f"{us_start:.3f}",
                us_end_sec=f"{us_end:.3f}",
                us_duration_sec=f"{us_end-us_start:.3f}",
                us_representative_sec=f"{us_rep:.3f}",
                us_start_frame=matches["start"]["us_index"],
                us_end_frame_exclusive=matches["end"]["us_index"]+1,
                us_representative_frame=matches["rep"]["us_index"],
                start_match_mad=f"{matches['start']['mad']:.6f}",
                rep_match_mad=f"{matches['rep']['mad']:.6f}",
                end_match_mad=f"{matches['end']['mad']:.6f}",
                alignment_status=("REVIEW" if any(matches[k]["mad"] > POOR_MAD for k in matches) else "OK"),
            )
            out_rows.append(nr)

        # Make compact visual review samples: first / middle / last subtitle.
        picks = sorted(set([0, len(mrows)//2, len(mrows)-1]))
        out_slice = out_rows[movie_out_start:]
        sample_rows = [out_slice[i] for i in picks]
        kr_indices = [int(x["representative_frame"]) for x in sample_rows]
        us_indices = [int(x["us_representative_frame"]) for x in sample_rows]

        kr_imgs = exact_index_jpegs(kr_path, movie, kr_indices, SAMPLES, "KR")
        us_imgs = exact_index_jpegs(us_path, movie, us_indices, SAMPLES, "US")

        sample_manifest = []
        for x in sample_rows:
            ki = int(x["representative_frame"])
            ui = int(x["us_representative_frame"])
            sample_manifest.append(dict(
                movie=movie,
                segment=x["segment"],
                kr_frame=ki,
                us_frame=ui,
                kr_image=str(kr_imgs.get(ki, "")),
                us_image=str(us_imgs.get(ui, "")),
                rep_match_mad=x["rep_match_mad"],
            ))

        write_tsv(STAGE / f"{movie}_alignment_samples.tsv", sample_manifest)

        m_mads = [float(x["mad"]) for x in anchor_rows[movie_anchor_start:]]
        m_offsets = [int(x["frame_offset"]) for x in anchor_rows[movie_anchor_start:]]
        movie_summary.append(dict(
            movie=movie,
            status="OK",
            segments=len(mrows),
            kr_frames=len(kr_frames),
            us_frames=len(us_frames),
            frame_ratio=f"{ratio:.9f}",
            anchors=len(m_mads),
            poor_anchors=poor,
            mad_min=f"{min(m_mads):.6f}" if m_mads else "",
            mad_median=f"{statistics.median(m_mads):.6f}" if m_mads else "",
            mad_max=f"{max(m_mads):.6f}" if m_mads else "",
            offset_frames_min=min(m_offsets) if m_offsets else "",
            offset_frames_median=f"{statistics.median(m_offsets):.3f}" if m_offsets else "",
            offset_frames_max=max(m_offsets) if m_offsets else "",
        ))

        print(
            f"  frames KR/US={len(kr_frames)}/{len(us_frames)} "
            f"MAD median={statistics.median(m_mads):.3f} "
            f"max={max(m_mads):.3f} poor={poor}",
            flush=True
        )

    write_tsv(STAGE / "subtitle_segments_us_timing.tsv", out_rows)
    write_tsv(STAGE / "alignment_anchor_details.tsv", anchor_rows)
    write_tsv(STAGE / "alignment_movie_summary.tsv", movie_summary)

    ok_movies = sum(1 for r in movie_summary if r.get("status") == "OK")
    all_mads = [float(r["mad"]) for r in anchor_rows]

    summary = [
        "Naruto PSP MOV03O - KR -> US subtitle timeline alignment",
        "="*80, "",
        f"Movies aligned={ok_movies}/10",
        f"Subtitle segments={len(out_rows)}",
        f"Frame anchors={len(anchor_rows)} (start/rep/end)",
        f"Search radius=+/-{SEARCH_RADIUS/FPS:.1f}s",
        f"Poor-match threshold MAD>{POOR_MAD:.1f}",
        f"Poor anchors={poor_total}/{len(anchor_rows)}",
        f"Global MAD median={statistics.median(all_mads):.6f}" if all_mads else "Global MAD median=N/A",
        f"Global MAD max={max(all_mads):.6f}" if all_mads else "Global MAD max=N/A",
        "",
        "Output subtitle_segments_us_timing.tsv contains BOTH:",
        "  original KR timing",
        "  mapped US clean-video timing",
        "",
        "Next step after reviewing this alignment:",
        "  Japanese transcription + Korean translation using exact MOV03N PNG crops.",
    ]
    (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if ok_movies == 10 and len(out_rows) == len(rows) else 2

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
