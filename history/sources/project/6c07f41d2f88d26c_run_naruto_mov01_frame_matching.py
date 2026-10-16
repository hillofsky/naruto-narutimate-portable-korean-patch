#!/usr/bin/env python3
# Naruto PSP MOV01 FIX2 - robust PMF <-> YouTube visual matching
# Standard library only. Requires ffmpeg + ffprobe.
#
# Why FIX2:
# - FIX1 used one 64-bit dHash at 1 fps.
# - Visual review showed most LOW matches were genuinely wrong scenes.
# - FIX2 uses a much stronger frame signature and offset-voting search:
#     * 2 fps
#     * upper-left 82% x 66% video region (bottom subtitles + top-right watermark excluded)
#     * 33x18 grayscale
#     * horizontal gradient hash + vertical gradient hash + average hash (~1731 bits/frame)
#     * low-information frames rejected
#     * per-sample nearest-frame voting
#     * clustered source offset consensus
#     * local +/-1.5 sec temporal tolerance
# - No third-party Python packages are required.

from __future__ import annotations
import csv, json, math, os, re, shutil, subprocess, sys, traceback, statistics
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
ANALYSIS = ROOT / "analysis"
STAGE = ANALYSIS / "mov" / "mov01_frame_matching"
VERIFY = STAGE / "verification_fix2"
CACHE = STAGE / "fingerprint_cache"
KR_MOVIE = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
INVENTORY = ANALYSIS / "stage38f_movie_inventory" / "movie_inventory.csv"

PREFERRED_SOURCES = {
    "part1": ANALYSIS / "stage37" / "video" / "source_video.mp4",
    "part2": ANALYSIS / "stage37" / "video" / "part2.mp4",
}
TARGETS = {
    "part1": 7327.720,
    "part2": 2971.669,
}
MAX_REASONABLE_TAIL_SEC = 15 * 60

FPS = 2.0
FRAME_W = 33
FRAME_H = 18
FRAME_BYTES = FRAME_W * FRAME_H
H_BITS = (FRAME_W - 1) * FRAME_H   # 576
V_BITS = FRAME_W * (FRAME_H - 1)   # 561
A_BITS = FRAME_W * FRAME_H         # 594
TOTAL_BITS = H_BITS + V_BITS + A_BITS
PMF_LOGOS = {"logo_a.pmf", "logo_b.pmf", "logo_c.pmf"}

# Keep subtitles and YouTube watermark out of the fingerprint:
# left 82% of width, upper 66% of height.
VF = (
    "crop=trunc(iw*0.82/2)*2:trunc(ih*0.66/2)*2:0:0,"
    f"fps={FPS:g},scale={FRAME_W}:{FRAME_H}:flags=area,format=gray"
)

def eprint(*a):
    print(*a, file=sys.stderr, flush=True)

def run_text(cmd: list[str], timeout=120) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    return p.returncode, p.stdout, p.stderr

def find_tool(name: str) -> str | None:
    x = shutil.which(name)
    if x:
        return x
    candidates = [
        ROOT / "tools", ROOT / "ffmpeg", ANALYSIS,
        Path(r"LOCAL_PATH"), Path(r"LOCAL_PATH"),
        Path(r"LOCAL_PATH Files\ffmpeg"),
        Path(r"LOCAL_PATH Files (x86)\ffmpeg"),
    ]
    exe_names = [name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        exe_names.insert(0, name + ".exe")
    for base in candidates:
        if not base.exists():
            continue
        for en in exe_names:
            for p in base.rglob(en):
                if p.is_file():
                    return str(p)
    return None

def probe_duration(ffprobe: str, path: Path) -> float | None:
    rc, out, err = run_text([
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], timeout=30)
    if rc != 0:
        return None
    try:
        return float(out.strip().splitlines()[0])
    except Exception:
        return None

def read_override() -> dict[str, str]:
    p = STAGE / "source_override.txt"
    out = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().lower()
        v = v.strip().strip('"')
        if k in ("part1", "part2") and v:
            out[k] = v
    return out

def choose_sources(ffprobe: str) -> tuple[dict[str, Path], list[str]]:
    override = read_override()
    out = {}
    notes = []
    for part in ("part1", "part2"):
        p = None
        mode = None
        if part in override:
            p = Path(override[part])
            if not p.is_absolute():
                p = ROOT / p
            mode = "override"
        elif PREFERRED_SOURCES[part].exists():
            p = PREFERRED_SOURCES[part]
            mode = "Stage37 preferred"

        if p is None or not p.exists():
            raise RuntimeError(
                f"{part} source not found. Expected {PREFERRED_SOURCES[part]}. "
                f"Or create {STAGE/'source_override.txt'} with PART1=... / PART2=..."
            )

        dur = probe_duration(ffprobe, p)
        if dur is None:
            raise RuntimeError(f"Could not probe source duration: {p}")
        tail = dur - TARGETS[part]
        if tail < 0:
            raise RuntimeError(
                f"{part} source is shorter than the last Stage37 dialogue frame: "
                f"duration={dur:.3f}, target={TARGETS[part]:.3f}"
            )
        if tail > MAX_REASONABLE_TAIL_SEC:
            raise RuntimeError(
                f"{part} source has unexpectedly long unused tail: {tail:.3f}s"
            )
        out[part] = p
        notes.append(
            f"{part}: {mode} -> {p} ({dur:.3f}s, dialogue-tail={tail:.3f}s)"
        )
    if out["part1"].resolve() == out["part2"].resolve():
        raise RuntimeError("Part1 and Part2 resolved to the same file.")
    return out, notes

def frame_signature(frame: bytes) -> tuple[int, int, int, float]:
    if len(frame) != FRAME_BYTES:
        raise ValueError("invalid frame size")

    # Horizontal gradient hash.
    hh = 0
    bit = 0
    for y in range(FRAME_H):
        off = y * FRAME_W
        for x in range(FRAME_W - 1):
            if frame[off + x] > frame[off + x + 1]:
                hh |= 1 << bit
            bit += 1

    # Vertical gradient hash.
    vh = 0
    bit = 0
    for y in range(FRAME_H - 1):
        a = y * FRAME_W
        b = (y + 1) * FRAME_W
        for x in range(FRAME_W):
            if frame[a + x] > frame[b + x]:
                vh |= 1 << bit
            bit += 1

    mean = sum(frame) / FRAME_BYTES

    # Average hash.
    ah = 0
    for i, v in enumerate(frame):
        if v > mean:
            ah |= 1 << i

    # Mean absolute deviation: cheap information/contrast metric.
    mad = sum(abs(v - mean) for v in frame) / FRAME_BYTES
    return hh, vh, ah, mad

def signature_distance(a, b) -> float:
    diff = (
        (a[0] ^ b[0]).bit_count()
        + (a[1] ^ b[1]).bit_count()
        + (a[2] ^ b[2]).bit_count()
    )
    return diff / TOTAL_BITS

def fingerprint(ffmpeg: str, path: Path, cache_tag: str) -> list[tuple[int,int,int,float]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    sig = f"{path.stat().st_size}_{int(path.stat().st_mtime)}"
    cache = CACHE / (
        "fix2_" + cache_tag + "_" +
        re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem) + "_" + sig + ".json"
    )

    if cache.exists():
        try:
            obj = json.loads(cache.read_text(encoding="utf-8"))
            if (
                obj.get("fps") == FPS and obj.get("w") == FRAME_W
                and obj.get("h") == FRAME_H and obj.get("vf") == VF
            ):
                return [
                    (int(x["h"], 16), int(x["v"], 16), int(x["a"], 16), float(x["mad"]))
                    for x in obj["frames"]
                ]
        except Exception:
            pass

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-an", "-sn", "-dn", "-vf", VF,
        "-f", "rawvideo", "-pix_fmt", "gray", "-"
    ]
    p = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2400
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fingerprint failed: {path}\n"
            + p.stderr.decode("utf-8", "replace")[-1800:]
        )

    raw = p.stdout
    n = len(raw) // FRAME_BYTES
    out = []
    for i in range(n):
        f = raw[i*FRAME_BYTES:(i+1)*FRAME_BYTES]
        out.append(frame_signature(f))

    cache.write_text(
        json.dumps({
            "source": str(path),
            "fps": FPS, "w": FRAME_W, "h": FRAME_H, "vf": VF,
            "frames": [
                {"h": f"{x[0]:x}", "v": f"{x[1]:x}", "a": f"{x[2]:x}", "mad": round(x[3], 5)}
                for x in out
            ]
        }, ensure_ascii=False),
        encoding="utf-8"
    )
    return out

def pick_samples(frames, max_samples=20) -> list[int]:
    n = len(frames)
    if n <= 0:
        return []

    # Ignore first/last ~1.5 sec where fades are common.
    pad = max(1, round(FPS * 1.5))
    lo = min(pad, n-1)
    hi = max(lo, n-1-pad)
    if hi < lo:
        lo, hi = 0, n-1

    # Even candidates first.
    count = min(max_samples * 2, max(1, hi-lo+1))
    cand = []
    if count == 1:
        cand = [(lo + hi) // 2]
    else:
        for i in range(count):
            x = round(lo + (hi-lo) * i / (count-1))
            if not cand or x != cand[-1]:
                cand.append(x)

    # Prefer informative frames.
    informative = [i for i in cand if frames[i][3] >= 14.0]
    if len(informative) < min(8, max_samples):
        informative = [i for i in cand if frames[i][3] >= 8.0]
    if len(informative) < 4:
        informative = cand

    # Evenly reduce to max_samples.
    if len(informative) <= max_samples:
        return informative
    out = []
    for i in range(max_samples):
        j = round(i * (len(informative)-1) / (max_samples-1))
        x = informative[j]
        if not out or x != out[-1]:
            out.append(x)
    return out

def top_matches_one_sample(pmf_sig, source_frames, k=6) -> list[tuple[float,int]]:
    # Maintain a tiny sorted list; avoids allocating/sorting all source distances.
    best = []
    for si, sf in enumerate(source_frames):
        # Reject almost-empty source frames if PMF is informative.
        if pmf_sig[3] >= 14.0 and sf[3] < 6.0:
            continue
        d = signature_distance(pmf_sig, sf)
        if len(best) < k:
            best.append((d, si))
            best.sort()
        elif d < best[-1][0]:
            best[-1] = (d, si)
            best.sort()
    return best

def build_offset_clusters(pmf_frames, sample_idx, source_frames) -> list[dict]:
    # Bin candidate offsets at 1 second.  Each PMF sample can vote once per bin.
    bins: dict[int, dict] = {}
    for pi in sample_idx:
        hits = top_matches_one_sample(pmf_frames[pi], source_frames, k=6)
        seen_bins = set()
        for dist, si in hits:
            offset_sec = (si - pi) / FPS
            if offset_sec < -2:
                continue
            b = round(offset_sec)
            if b in seen_bins:
                continue
            seen_bins.add(b)
            rec = bins.setdefault(b, {
                "bin": b, "sample_ids": set(), "dists": [], "offsets": []
            })
            rec["sample_ids"].add(pi)
            rec["dists"].append(dist)
            rec["offsets"].append(offset_sec)

    rows = []
    for rec in bins.values():
        if not rec["sample_ids"]:
            continue
        med = statistics.median(rec["dists"])
        off = statistics.median(rec["offsets"])
        rows.append({
            "offset": off,
            "votes": len(rec["sample_ids"]),
            "median_nearest_dist": med,
            "cluster_bin": rec["bin"],
        })

    rows.sort(key=lambda x: (-x["votes"], x["median_nearest_dist"]))
    return rows[:12]

def evaluate_offset(pmf_frames, sample_idx, source_frames, offset_sec: float) -> dict:
    # Match each PMF sample near its predicted source time. Independent local
    # tolerance absorbs tiny encoder/playback timing differences.
    off_frames = round(offset_sec * FPS)
    radius = max(1, round(1.5 * FPS))
    per = []
    drifts = []

    for pi in sample_idx:
        expected = off_frames + pi
        best_d = 9.0
        best_si = None
        lo = max(0, expected-radius)
        hi = min(len(source_frames)-1, expected+radius)
        if lo > hi:
            continue
        for si in range(lo, hi+1):
            d = signature_distance(pmf_frames[pi], source_frames[si])
            if d < best_d:
                best_d = d
                best_si = si
        if best_si is not None:
            per.append(best_d)
            drifts.append((best_si - expected) / FPS)

    if not per:
        return {
            "score": 9.0, "coverage": 0.0, "median": 9.0,
            "median_drift": 0.0, "used": 0
        }

    # Trim worst 20% so fades/overlay changes do not dominate.
    s = sorted(per)
    keep_n = max(3, math.ceil(len(s) * 0.80))
    kept = s[:keep_n]
    score = sum(kept) / len(kept)
    coverage = sum(1 for x in per if x <= 0.24) / len(per)
    return {
        "score": score,
        "coverage": coverage,
        "median": statistics.median(per),
        "median_drift": statistics.median(drifts) if drifts else 0.0,
        "used": len(per),
    }

def match_pmf(pmf_frames, source_by_part) -> tuple[dict, list[dict]]:
    sample_idx = pick_samples(pmf_frames, 20)
    all_candidates = []

    for part in ("part1", "part2"):
        src = source_by_part[part]
        clusters = build_offset_clusters(pmf_frames, sample_idx, src)

        # Evaluate leading clusters plus a few alternates.
        for c in clusters[:8]:
            ev = evaluate_offset(pmf_frames, sample_idx, src, c["offset"])

            # One refinement using median local drift.
            refined_offset = c["offset"] + ev["median_drift"]
            ev2 = evaluate_offset(pmf_frames, sample_idx, src, refined_offset)
            if ev2["score"] <= ev["score"]:
                ev = ev2
                chosen_offset = refined_offset
            else:
                chosen_offset = c["offset"]

            if chosen_offset < 0:
                continue
            if (chosen_offset * FPS + len(pmf_frames)) > len(src) + round(3*FPS):
                continue

            all_candidates.append({
                "part": part,
                "offset": chosen_offset,
                "votes": c["votes"],
                "nearest_median": c["median_nearest_dist"],
                **ev,
            })

    if not all_candidates:
        return ({
            "part": "UNKNOWN", "offset": -1.0, "votes": 0,
            "nearest_median": 9.0, "score": 9.0, "coverage": 0.0,
            "median": 9.0, "median_drift": 0.0, "used": 0,
            "second_score": 9.0, "margin": 0.0, "confidence": "LOW"
        }, [])

    all_candidates.sort(
        key=lambda x: (-x["votes"], x["score"], -x["coverage"], x["nearest_median"])
    )
    best = all_candidates[0]

    # Re-rank candidates with similar vote counts by actual sequence score.
    max_votes = best["votes"]
    plausible = [x for x in all_candidates if x["votes"] >= max(3, max_votes-2)]
    plausible.sort(key=lambda x: (x["score"], -x["coverage"], -x["votes"]))
    best = plausible[0]

    second = None
    for c in plausible[1:] + all_candidates:
        if c is best:
            continue
        if c["part"] != best["part"] or abs(c["offset"] - best["offset"]) >= 8.0:
            second = c
            break
    second_score = second["score"] if second else 9.0
    margin = second_score - best["score"] if second else 0.0

    votes = best["votes"]
    score = best["score"]
    cov = best["coverage"]

    if votes >= 6 and score <= 0.18 and cov >= 0.60 and margin >= 0.015:
        conf = "HIGH"
    elif votes >= 4 and score <= 0.25 and cov >= 0.40:
        conf = "MEDIUM"
    else:
        conf = "LOW"

    best = dict(best)
    best["second_score"] = second_score
    best["margin"] = margin
    best["confidence"] = conf
    return best, all_candidates

def extract_frame(ffmpeg: str, src: Path, t: float, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0,t):.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", "scale=480:-2:flags=area",
        "-q:v", "5", str(out)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)

def load_pmfs() -> list[dict]:
    rows = []
    if INVENTORY.exists():
        with INVENTORY.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                name = r.get("filename", "")
                if not name.lower().endswith(".pmf"):
                    continue
                if name.lower() in PMF_LOGOS:
                    continue
                if r.get("subtitle_candidate", "YES") != "YES":
                    continue
                rows.append(r)
    else:
        for p in sorted(KR_MOVIE.glob("*.pmf")):
            if p.name.lower() not in PMF_LOGOS:
                rows.append({
                    "filename": p.name,
                    "family": p.stem[:2].upper(),
                    "duration_sec": ""
                })
    return rows

def write_table(path: Path, rows: list[dict], delimiter: str):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=delimiter)
        w.writeheader()
        w.writerows(rows)

def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    VERIFY.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"ffmpeg/ffprobe required. ffmpeg={ffmpeg} ffprobe={ffprobe}")

    print("========================================================================", flush=True)
    print(" Naruto PSP MOV01 FIX2 - Robust visual matching", flush=True)
    print("========================================================================", flush=True)
    print(f"ffmpeg : {ffmpeg}", flush=True)
    print(f"ffprobe: {ffprobe}", flush=True)
    print(f"FPS    : {FPS:g}", flush=True)
    print(f"Filter : {VF}", flush=True)

    print("\n[1/6] Resolve Stage37 source videos", flush=True)
    sources, notes = choose_sources(ffprobe)
    for x in notes:
        print("  " + x, flush=True)
    (STAGE / "selected_sources.txt").write_text(
        "".join(f"{k.upper()}={v}\n" for k, v in sources.items()),
        encoding="utf-8-sig"
    )

    print("\n[2/6] Build/load strong 2-fps source fingerprints", flush=True)
    source_fp = {}
    for part, p in sources.items():
        print(f"  {part}: {p}", flush=True)
        fp = fingerprint(ffmpeg, p, f"src_{part}")
        source_fp[part] = fp
        print(f"    fingerprint frames={len(fp)} duration~{len(fp)/FPS:.1f}s", flush=True)

    print("\n[3/6] Robustly match 21 PMFs", flush=True)
    pmfs = load_pmfs()
    print(f"  PMF candidates={len(pmfs)}", flush=True)

    results = []
    candidate_dump = []
    for idx, r in enumerate(pmfs, 1):
        name = r["filename"]
        p = KR_MOVIE / name
        if not p.exists():
            raise RuntimeError(f"PMF missing: {p}")

        print(f"\n[{idx:02d}/{len(pmfs):02d}] {name}", flush=True)
        pf = fingerprint(ffmpeg, p, f"pmf_{p.stem}")
        samples = pick_samples(pf, 20)
        print(
            f"  pmf_frames={len(pf)} samples={len(samples)} "
            f"duration~{len(pf)/FPS:.1f}s", flush=True
        )

        best, allc = match_pmf(pf, source_fp)

        dur = probe_duration(ffprobe, p)
        if dur is None:
            try:
                dur = float(r.get("duration_sec") or (len(pf)/FPS))
            except Exception:
                dur = len(pf)/FPS

        start = float(best["offset"])
        end = start + dur if start >= 0 else -1.0

        print(
            f"  => {best['part']} start={start:.3f}s end={end:.3f}s "
            f"votes={best['votes']} score={best['score']:.4f} "
            f"coverage={best['coverage']:.2f} margin={best['margin']:.4f} "
            f"confidence={best['confidence']}",
            flush=True
        )

        results.append({
            "filename": name,
            "family": r.get("family", p.stem[:2].upper()),
            "pmf_duration_sec": round(dur, 3),
            "source_part": best["part"],
            "source_start_fix2_sec": round(start, 3),
            "source_end_fix2_sec": round(end, 3),
            "votes": best["votes"],
            "sample_points": best["used"],
            "strong_score": round(best["score"], 6),
            "median_score": round(best["median"], 6),
            "coverage_le_0.24": round(best["coverage"], 4),
            "nearest_frame_median": round(best["nearest_median"], 6),
            "second_score": round(best["second_score"], 6),
            "margin": round(best["margin"], 6),
            "confidence": best["confidence"],
            "source_path": str(sources.get(best["part"], "")),
        })

        for rank, c in enumerate(allc[:10], 1):
            candidate_dump.append({
                "filename": name,
                "rank": rank,
                "source_part": c["part"],
                "offset_sec": round(c["offset"], 3),
                "votes": c["votes"],
                "score": round(c["score"], 6),
                "coverage": round(c["coverage"], 4),
                "nearest_median": round(c["nearest_median"], 6),
            })

    write_table(STAGE / "pmf_source_mapping_fix2.tsv", results, "\t")
    write_table(STAGE / "pmf_source_mapping_fix2.csv", results, ",")
    write_table(STAGE / "candidate_offsets_fix2.tsv", candidate_dump, "\t")

    print("\n[4/6] Compare FIX2 against previous MOV01 results", flush=True)
    old_path = None
    # Wrapper archives previous run under logs\old, but if old result remains for any reason use it.
    for cand in [
        STAGE / "pmf_source_mapping_coarse.csv",
        STAGE / "previous_results" / "pmf_source_mapping_coarse.csv",
    ]:
        if cand.exists():
            old_path = cand
            break

    # Search most recent archived coarse result.
    if old_path is None:
        old_root = ROOT / "logs" / "old"
        hits = sorted(old_root.glob("*/mov01_frame_matching/previous_results/pmf_source_mapping_coarse.csv"))
        if hits:
            old_path = hits[-1]

    old = {}
    if old_path:
        print(f"  Previous map: {old_path}", flush=True)
        with old_path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                old[r["filename"]] = r

    comparisons = []
    for r in results:
        o = old.get(r["filename"])
        oldpart = o.get("source_part", "") if o else ""
        try:
            oldstart = float(o.get("source_start_coarse_sec", "")) if o else None
        except Exception:
            oldstart = None
        changed = ""
        delta = ""
        if o:
            if oldpart != r["source_part"]:
                changed = "PART_CHANGED"
            elif oldstart is not None:
                d = r["source_start_fix2_sec"] - oldstart
                delta = round(d, 3)
                if abs(d) > 3:
                    changed = "OFFSET_CHANGED"
                else:
                    changed = "SAME_AREA"
        comparisons.append({
            "filename": r["filename"],
            "old_part": oldpart,
            "old_start_sec": "" if oldstart is None else round(oldstart,3),
            "old_confidence": o.get("confidence","") if o else "",
            "fix2_part": r["source_part"],
            "fix2_start_sec": r["source_start_fix2_sec"],
            "delta_sec": delta,
            "change": changed,
            "fix2_confidence": r["confidence"],
        })
    write_table(STAGE / "fix1_vs_fix2.tsv", comparisons, "\t")

    print("\n[5/6] Extract visual verification frames", flush=True)
    verify_rows = []
    for r in results:
        if r["source_part"] not in sources:
            continue
        pmf = KR_MOVIE / r["filename"]
        src = sources[r["source_part"]]
        dur = float(r["pmf_duration_sec"])
        start = float(r["source_start_fix2_sec"])
        if start < 0:
            continue

        points = [
            ("p10", max(0.5, dur*0.10)),
            ("p30", dur*0.30),
            ("p50", dur*0.50),
            ("p70", dur*0.70),
            ("p90", max(0.5, min(dur-0.5, dur*0.90))),
        ]
        for label, local in points:
            p1 = VERIFY / f"{pmf.stem}_{label}_pmf.jpg"
            p2 = VERIFY / f"{pmf.stem}_{label}_{r['source_part']}.jpg"
            extract_frame(ffmpeg, pmf, local, p1)
            extract_frame(ffmpeg, src, start + local, p2)
            verify_rows.append({
                "filename": r["filename"],
                "confidence": r["confidence"],
                "point": label,
                "pmf_local_sec": round(local,3),
                "source_part": r["source_part"],
                "source_sec": round(start+local,3),
                "pmf_image": p1.name if p1.exists() else "",
                "source_image": p2.name if p2.exists() else "",
            })

    write_table(STAGE / "verification_fix2_manifest.tsv", verify_rows, "\t")

    print("\n[6/6] Summary", flush=True)
    counts = {}
    for r in results:
        counts[r["confidence"]] = counts.get(r["confidence"], 0) + 1
    changed = sum(1 for x in comparisons if x["change"] in ("PART_CHANGED","OFFSET_CHANGED"))
    highmed = sum(1 for r in results if r["confidence"] in ("HIGH","MEDIUM"))

    summary = [
        "Naruto PSP MOV01 FIX2 - Robust PMF <-> YouTube visual matching",
        "="*76,
        "",
        *notes,
        "",
        f"PMF candidates={len(results)}",
        "Confidence: " + ", ".join(f"{k}={v}" for k,v in sorted(counts.items())),
        f"HIGH+MEDIUM={highmed}/{len(results)}",
        f"Mappings changed >3s or source part changed vs FIX1={changed}",
        "",
        "FIX2 method:",
        f"- {FPS:g} fps fingerprints",
        "- crop left 82% / upper 66% to exclude Korean/JP subtitle area and YouTube watermark",
        f"- {FRAME_W}x{FRAME_H} grayscale",
        f"- horizontal + vertical + average hashes = {TOTAL_BITS} bits/frame",
        "- low-information PMF frames deprioritized",
        "- independent nearest-frame votes -> 1s offset clusters",
        "- sequence verification with local +/-1.5s temporal tolerance",
        "- worst 20% sample distances trimmed",
        "",
        "Gate before MOV02:",
        "- Do NOT perform 0.1s refinement on LOW mappings.",
        "- Review verification_fix2 images.",
        "- MOV02 should refine only confirmed HIGH/MEDIUM matches and separately handle unresolved LOW.",
    ]
    (STAGE / "SUMMARY_FIX2.txt").write_text("\n".join(summary)+"\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        STAGE.mkdir(parents=True, exist_ok=True)
        msg = traceback.format_exc()
        (STAGE / "FAILURE_FIX2.txt").write_text(msg, encoding="utf-8-sig")
        eprint("\nMOV01 FIX2 FAILED:", e)
        eprint(msg)
        raise SystemExit(1)
