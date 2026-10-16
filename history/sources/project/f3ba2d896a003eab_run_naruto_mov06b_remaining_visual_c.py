#!/usr/bin/env python3
# Naruto PSP MOV06B
# Full Stage37 VISUAL anchor clustering for:
#   da101, da201, dk102, dk202
#
# Why:
#   MOV06A audio-only candidates were LOW confidence and manual review showed
#   that all four selected locations were visually wrong.
#
# Method:
#   1) decode both Stage37 videos to tiny central grayscale frames at 2 fps
#   2) decode each KR PMF the same way
#   3) choose many detailed KR query frames along the full KR timeline
#   4) search every query frame independently across BOTH Stage37 videos
#   5) use perceptual binary fingerprints (mean threshold + gradient)
#   6) cluster source_time - KR_time offsets
#   7) derive contiguous KR runs whose queries agree on one Stage37 mapping
#   8) export paired review frames for the strongest clusters/runs
#
# Analysis only. No PMF/ISO modification.

from __future__ import annotations
import csv, math, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOVIE_DIR = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
STAGE37_DIR = ROOT / "analysis" / "stage37" / "video"

SOURCES = [
    STAGE37_DIR / "source_video.mp4",
    STAGE37_DIR / "part2.mp4",
]
TARGETS = ["da101", "da201", "dk102", "dk202"]

STAGE = ROOT / "analysis" / "mov" / "mov06b_remaining_visual_clusters"
WORK = STAGE / "work"
REVIEW = STAGE / "review"
LOGD = STAGE / "logs"
for p in (STAGE, WORK, REVIEW, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

FPS = 2.0
W = 32
H = 18
FRAME_BYTES = W * H

# Central crop:
# - avoid bottom subtitles
# - avoid top-right uploader watermark
# - avoid outer black borders
FILTER = (
    "crop="
    "trunc(iw*0.76/2)*2:"
    "trunc(ih*0.58/2)*2:"
    "trunc(iw*0.08/2)*2:"
    "trunc(ih*0.13/2)*2,"
    f"scale={W}:{H}:flags=area,"
    "format=gray,"
    f"fps={FPS:g}"
)

TOP_MATCHES_PER_QUERY = 10
MATCH_MIN_SEPARATION_SEC = 2.5
OFFSET_CLUSTER_RADIUS = 2.0

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

def decode_visual_raw(src, out, tag):
    cp = run(
        [FFMPEG, "-y", "-v", "warning", "-i", src,
         "-an", "-vf", FILTER,
         "-f", "rawvideo", "-pix_fmt", "gray", out],
        tag, 3600
    )
    if cp.returncode != 0 or not Path(out).exists() or Path(out).stat().st_size < FRAME_BYTES:
        raise RuntimeError(f"Visual raw decode failed: {src}")

def load_frames(path):
    data = Path(path).read_bytes()
    n = len(data) // FRAME_BYTES
    return [data[i*FRAME_BYTES:(i+1)*FRAME_BYTES] for i in range(n)]

def signature(frame):
    vals = frame
    mean = sum(vals) / len(vals)
    var = sum((x-mean)*(x-mean) for x in vals) / len(vals)
    std = math.sqrt(max(var, 0.0))

    ah = 0
    for i, x in enumerate(vals):
        if x >= mean:
            ah |= (1 << i)

    # Gradient hash: left < right on each row.
    gh = 0
    bit = 0
    for y in range(H):
        row = y * W
        for x in range(W-1):
            if vals[row+x] < vals[row+x+1]:
                gh |= (1 << bit)
            bit += 1

    return (ah, gh, mean, std)

def similarity(a, b):
    ah1, gh1, mean1, std1 = a
    ah2, gh2, mean2, std2 = b

    asim = 1.0 - ((ah1 ^ ah2).bit_count() / FRAME_BYTES)
    gbits = H * (W-1)
    gsim = 1.0 - ((gh1 ^ gh2).bit_count() / gbits)

    # Compression / localized text / brightness should not dominate.
    light_pen = min(0.05, abs(mean1-mean2) / 255.0 * 0.05)
    return 0.42*asim + 0.58*gsim - light_pen

def choose_query_times(duration, sigs):
    # Adaptive temporal spacing.
    if duration <= 40:
        step = 3.0
    elif duration <= 90:
        step = 5.0
    elif duration <= 180:
        step = 8.0
    else:
        step = 10.0

    candidates = []
    t = 1.0
    while t < duration - 1.0:
        idx = max(0, min(len(sigs)-1, int(round(t*FPS))))
        std = sigs[idx][3]
        candidates.append((std, t))
        t += step

    # Keep timeline coverage, but reject near-black/featureless frames.
    chosen = [(std,t) for std,t in candidates if std >= 12.0]

    # If too few survived, bring back most detailed frames.
    minimum = 5 if duration > 25 else 3
    if len(chosen) < minimum:
        chosen = sorted(candidates, reverse=True)[:minimum]

    # Cap huge targets while preserving temporal coverage.
    chosen = sorted(chosen, key=lambda x: x[1])
    if len(chosen) > 28:
        picks = []
        for i in range(28):
            j = round(i * (len(chosen)-1) / 27)
            picks.append(chosen[j])
        chosen = []
        seen = set()
        for x in picks:
            if x[1] not in seen:
                chosen.append(x)
                seen.add(x[1])

    return [t for _,t in chosen]

def top_matches(query_sig, source_sigs):
    vals = []
    for i, ss in enumerate(source_sigs):
        vals.append((similarity(query_sig, ss), i))

    vals.sort(reverse=True)
    picked = []
    sep = int(round(MATCH_MIN_SEPARATION_SEC * FPS))
    for score, idx in vals:
        if all(abs(idx-j) >= sep for _,j in picked):
            picked.append((score, idx))
            if len(picked) >= TOP_MATCHES_PER_QUERY:
                break
    return picked

def cluster_matches(rows):
    if not rows:
        return []

    clusters = []
    for seed in rows:
        source = seed["source"]
        center = float(seed["offset_sec"])

        members = [
            r for r in rows
            if r["source"] == source
            and abs(float(r["offset_sec"]) - center) <= OFFSET_CLUSTER_RADIUS
            and float(r["visual_score"]) >= 0.60
        ]

        # One best candidate per KR query time.
        by_query = {}
        for r in members:
            qt = float(r["kr_query_sec"])
            if qt not in by_query or float(r["visual_score"]) > float(by_query[qt]["visual_score"]):
                by_query[qt] = r
        members = list(by_query.values())
        if not members:
            continue

        count = len(members)
        avg = sum(float(r["visual_score"]) for r in members) / count
        worst = min(float(r["visual_score"]) for r in members)

        weights = [max(0.001, float(r["visual_score"])**3) for r in members]
        off = sum(float(r["offset_sec"])*w for r,w in zip(members,weights)) / sum(weights)

        kr_times = sorted(float(r["kr_query_sec"]) for r in members)
        span = kr_times[-1] - kr_times[0] if len(kr_times) > 1 else 0.0

        clusters.append(dict(
            source=source,
            offset=off,
            query_count=count,
            avg_score=avg,
            worst_score=worst,
            kr_span=span,
            members=members,
        ))

    # Deduplicate similar cluster centers.
    out = []
    for c in sorted(
        clusters,
        key=lambda x: (x["query_count"], x["kr_span"], x["avg_score"]),
        reverse=True
    ):
        if all(c["source"] != x["source"] or abs(c["offset"]-x["offset"]) > 1.0 for x in out):
            out.append(c)
        if len(out) >= 12:
            break
    return out

def assign_queries_to_clusters(query_times, all_rows, clusters):
    assignments = []
    for qt in query_times:
        qr = [r for r in all_rows if abs(float(r["kr_query_sec"])-qt) < 1e-6]
        best = None

        for ci, c in enumerate(clusters, 1):
            candidates = [
                r for r in qr
                if r["source"] == c["source"]
                and abs(float(r["offset_sec"])-c["offset"]) <= OFFSET_CLUSTER_RADIUS
            ]
            if not candidates:
                continue
            r = max(candidates, key=lambda x: float(x["visual_score"]))
            score = float(r["visual_score"])

            # Require a plausible visual match.
            if score < 0.60:
                continue

            rank = (score, c["query_count"], c["avg_score"])
            if best is None or rank > best[0]:
                best = (rank, ci, c, r)

        if best is None:
            assignments.append(dict(
                kr_query_sec=qt,
                cluster_id=0,
                source="",
                source_sec="",
                offset_sec="",
                visual_score="",
            ))
        else:
            _, ci, c, r = best
            assignments.append(dict(
                kr_query_sec=qt,
                cluster_id=ci,
                source=c["source"],
                source_sec=r["source_sec"],
                offset_sec=f"{float(r['offset_sec']):.3f}",
                visual_score=r["visual_score"],
            ))
    return assignments

def derive_runs(assignments):
    if not assignments:
        return []

    # Fill isolated unknown queries only when neighbors agree.
    arr = [dict(x) for x in assignments]
    for i in range(1, len(arr)-1):
        if arr[i]["cluster_id"] == 0:
            if arr[i-1]["cluster_id"] != 0 and arr[i-1]["cluster_id"] == arr[i+1]["cluster_id"]:
                arr[i]["cluster_id"] = arr[i-1]["cluster_id"]
                arr[i]["source"] = arr[i-1]["source"]

    runs = []
    start = 0
    for i in range(1, len(arr)+1):
        if i == len(arr) or arr[i]["cluster_id"] != arr[start]["cluster_id"]:
            block = arr[start:i]
            cid = block[0]["cluster_id"]
            runs.append(dict(
                cluster_id=cid,
                source=block[0]["source"],
                first_query_sec=block[0]["kr_query_sec"],
                last_query_sec=block[-1]["kr_query_sec"],
                query_count=len(block),
                avg_score=(
                    sum(float(x["visual_score"]) for x in block if x["visual_score"]!="")
                    / max(1, sum(1 for x in block if x["visual_score"]!=""))
                ),
            ))
            start = i
    return runs

def extract_frame(src, sec, out, tag):
    cp = run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{max(0,sec):.3f}",
         "-i", src, "-frames:v", "1", "-q:v", "2", out],
        tag, 180
    )
    return cp.returncode == 0 and Path(out).exists()

def main():
    for p in [FFMPEG, FFPROBE] + SOURCES:
        if not p.exists():
            raise RuntimeError(f"Missing tool/source: {p}")
    for t in TARGETS:
        p = KR_MOVIE_DIR / f"{t}.pmf"
        if not p.exists():
            raise RuntimeError(f"Missing KR PMF: {p}")

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("="*80, flush=True)
    print(" Naruto PSP MOV06B - full Stage37 VISUAL anchor clustering", flush=True)
    print("="*80, flush=True)

    # Decode source videos once.
    source_data = {}
    source_rows = []
    for si, src in enumerate(SOURCES, 1):
        raw = WORK / f"{src.stem}_visual.raw"
        print(f"[source {si}/2] decoding visual fingerprints: {src.name}", flush=True)
        decode_visual_raw(src, raw, f"01_source{si}_visual_decode.log")
        frames = load_frames(raw)
        sigs = [signature(f) for f in frames]
        dur = probe_duration(src, f"01_source{si}_duration.log")
        source_data[src.name] = dict(path=src, sigs=sigs, duration=dur)
        source_rows.append(dict(
            source=src.name,
            duration_sec=f"{dur:.3f}" if dur is not None else "",
            fingerprint_frames=len(sigs),
            fps=FPS,
        ))
        del frames

    write_tsv(STAGE/"stage37_visual_sources.tsv", source_rows)

    all_match_rows = []
    all_cluster_rows = []
    all_assignment_rows = []
    all_run_rows = []
    target_summary = []

    for ti, target in enumerate(TARGETS, 1):
        print("", flush=True)
        print(f"[target {ti}/{len(TARGETS)}] {target}", flush=True)

        pmf = KR_MOVIE_DIR / f"{target}.pmf"
        dur = probe_duration(pmf, f"02_{target}_duration.log")
        if dur is None:
            raise RuntimeError(f"{target}: cannot probe duration")

        raw = WORK / f"{target}_visual.raw"
        decode_visual_raw(pmf, raw, f"02_{target}_visual_decode.log")
        qframes = load_frames(raw)
        qsigs = [signature(f) for f in qframes]
        del qframes

        query_times = choose_query_times(dur, qsigs)
        print(f"  duration={dur:.3f}s visual_queries={len(query_times)}", flush=True)

        target_rows = []

        for qi, qt in enumerate(query_times, 1):
            qidx = max(0, min(len(qsigs)-1, int(round(qt*FPS))))
            qsig = qsigs[qidx]

            for source_name, sd in source_data.items():
                matches = top_matches(qsig, sd["sigs"])
                for rank, (score, idx) in enumerate(matches, 1):
                    st = idx / FPS
                    row = dict(
                        target=target,
                        query_index=qi,
                        kr_query_sec=f"{qt:.3f}",
                        source=source_name,
                        rank=rank,
                        source_sec=f"{st:.3f}",
                        offset_sec=f"{st-qt:.3f}",
                        visual_score=f"{score:.6f}",
                        kr_detail_std=f"{qsig[3]:.3f}",
                    )
                    target_rows.append(row)
                    all_match_rows.append(row)

        clusters = cluster_matches(target_rows)

        for ci, c in enumerate(clusters, 1):
            all_cluster_rows.append(dict(
                target=target,
                cluster_id=ci,
                source=c["source"],
                offset_sec=f"{c['offset']:.3f}",
                query_count=c["query_count"],
                avg_visual_score=f"{c['avg_score']:.6f}",
                worst_visual_score=f"{c['worst_score']:.6f}",
                kr_query_span_sec=f"{c['kr_span']:.3f}",
            ))

        assignments = assign_queries_to_clusters(query_times, target_rows, clusters)
        for a in assignments:
            row = dict(target=target, **a)
            all_assignment_rows.append(row)

        runs = derive_runs(assignments)
        for ri, r in enumerate(runs, 1):
            if r["cluster_id"] > 0 and r["cluster_id"] <= len(clusters):
                c = clusters[r["cluster_id"]-1]
                off = c["offset"]
                source = c["source"]
                source_first = r["first_query_sec"] + off
                source_last = r["last_query_sec"] + off
            else:
                off = None
                source = ""
                source_first = source_last = None

            row = dict(
                target=target,
                run_id=ri,
                cluster_id=r["cluster_id"],
                source=source,
                kr_first_query_sec=f"{r['first_query_sec']:.3f}",
                kr_last_query_sec=f"{r['last_query_sec']:.3f}",
                query_count=r["query_count"],
                avg_visual_score=f"{r['avg_score']:.6f}",
                cluster_offset_sec=f"{off:.3f}" if off is not None else "",
                source_first_query_sec=f"{source_first:.3f}" if source_first is not None else "",
                source_last_query_sec=f"{source_last:.3f}" if source_last is not None else "",
            )
            all_run_rows.append(row)

        # Target-level confidence based on best cluster.
        if clusters:
            best = clusters[0]
            ratio = best["query_count"] / max(1, len(query_times))
            if best["query_count"] >= 4 and best["avg_score"] >= 0.78:
                confidence = "VERY_HIGH"
            elif best["query_count"] >= 3 and best["avg_score"] >= 0.72:
                confidence = "HIGH"
            elif best["query_count"] >= 2 and best["avg_score"] >= 0.66:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            target_summary.append(dict(
                target=target,
                duration_sec=f"{dur:.3f}",
                visual_query_count=len(query_times),
                cluster_count=len(clusters),
                best_source=best["source"],
                best_offset_sec=f"{best['offset']:.3f}",
                best_cluster_query_count=best["query_count"],
                best_cluster_query_ratio=f"{ratio:.3f}",
                best_cluster_avg_score=f"{best['avg_score']:.6f}",
                derived_run_count=len(runs),
                confidence=confidence,
            ))

            print(
                f"  best cluster: {best['source']} offset={best['offset']:+.3f}s "
                f"queries={best['query_count']}/{len(query_times)} "
                f"score={best['avg_score']:.4f} runs={len(runs)} {confidence}",
                flush=True
            )
        else:
            target_summary.append(dict(
                target=target,
                duration_sec=f"{dur:.3f}",
                visual_query_count=len(query_times),
                cluster_count=0,
                best_source="",
                best_offset_sec="",
                best_cluster_query_count=0,
                best_cluster_query_ratio="0",
                best_cluster_avg_score="",
                derived_run_count=len(runs),
                confidence="NO_MATCH",
            ))
            print("  no visual cluster", flush=True)

        # Review strongest cluster members and derived run centers.
        for ci, c in enumerate(clusters[:4], 1):
            mem = sorted(c["members"], key=lambda r: float(r["kr_query_sec"]))
            if not mem:
                continue
            picks = [mem[0], mem[len(mem)//2], mem[-1]]
            seen = set()
            for pi, r in enumerate(picks, 1):
                key = (r["kr_query_sec"], r["source_sec"])
                if key in seen:
                    continue
                seen.add(key)

                kt = float(r["kr_query_sec"])
                st = float(r["source_sec"])
                src_path = source_data[r["source"]]["path"]

                kout = REVIEW / f"{target}_cluster{ci}_pair{pi}_KR_{kt:08.3f}.jpg"
                sout = REVIEW / f"{target}_cluster{ci}_pair{pi}_{src_path.stem}_{st:09.3f}.jpg"
                extract_frame(pmf, kt, kout, f"review_{target}_c{ci}_p{pi}_kr.log")
                extract_frame(src_path, st, sout, f"review_{target}_c{ci}_p{pi}_src.log")

    write_tsv(STAGE/"visual_anchor_matches.tsv", all_match_rows)
    write_tsv(STAGE/"visual_offset_clusters.tsv", all_cluster_rows)
    write_tsv(STAGE/"visual_query_assignments.tsv", all_assignment_rows)
    write_tsv(STAGE/"visual_timeline_runs.tsv", all_run_rows)
    write_tsv(STAGE/"target_summary.tsv", target_summary)

    summary = [
        "Naruto PSP MOV06B - full Stage37 visual anchor clustering",
        "="*80,
        "",
        "MOV06A audio-only candidates were rejected after manual frame review:",
        "  da101 = visually wrong",
        "  da201 = visually wrong",
        "  dk102 = visually wrong",
        "  dk202 = visually wrong",
        "",
        "MOV06B searches every selected KR visual anchor independently across",
        "both complete Stage37 videos and clusters source_time - KR_time offsets.",
        "",
    ]

    for r in target_summary:
        summary += [
            f"{r['target']}:",
            f"  queries={r['visual_query_count']}",
            f"  clusters={r['cluster_count']}",
            f"  best={r['best_source']} offset={r['best_offset_sec']}",
            f"  support={r['best_cluster_query_count']} ({r['best_cluster_query_ratio']})",
            f"  avg visual score={r['best_cluster_avg_score']}",
            f"  timeline runs={r['derived_run_count']}",
            f"  confidence={r['confidence']}",
            "",
        ]

    summary += [
        "Next:",
        "  Inspect the strongest visual clusters/runs.",
        "  Then construct each movie from independently approved Stage37 runs,",
        "  preserving exact KR Japanese ATRAC3+ and exact KR PTS.",
        "",
        "Accepted dk101 note remains unchanged:",
        "  MOV05D accepted with ~2-3 tolerated Stage37 tail frames at the end",
        "  of the second internal video.",
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
