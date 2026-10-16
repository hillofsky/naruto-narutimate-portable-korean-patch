#!/usr/bin/env python3
# Naruto PSP MOV03N FIX5 - Exact-frame KR subtitle detector
#
# Why FIX2:
# Paired KR-US frame differencing is vulnerable to tiny edit/duration drift.
# The KR DM movies already provide a much cleaner signal:
#   bottom subtitle band = black
#   burned Japanese glyphs = bright white/gray
#
# We decode ONLY the KR bottom band to raw grayscale at 10 fps and detect
# bright glyph pixels directly.
#
# No OCR is performed here. The goal is accurate subtitle timing + clean
# representative crops for the next transcription/translation stage.

from __future__ import annotations
import csv, hashlib, math, os, subprocess, sys, traceback, zlib, binascii, shutil, struct
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"

STAGE = ROOT / "analysis" / "mov" / "mov03n_subtitle_timing"
REP = STAGE / "representatives"
LOGD = STAGE / "logs"
for p in (STAGE, REP, LOGD):
    p.mkdir(parents=True, exist_ok=True)

FAILURE = STAGE / "FAILURE.txt"
if FAILURE.exists():
    FAILURE.unlink()

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

DM = [f"dm{i:03d}" for i in range(1,11)]

FPS = 10.0
W = 432
H = 40
X = 24
Y = 232
FRAME_BYTES = W * H

# A genuine subtitle pixel is far brighter than the encoded black bar.
LUMA_THRESHOLD = 96

# 20 pixels out of 17,280 = 0.116%. Even a tiny "!!" caption is larger.
MIN_BRIGHT_PIXELS = 20

# A stable text replacement has a low overlap with the previous glyph mask.
TEXT_CHANGE_JACCARD = 0.34

# Reject one-frame noise. 2 frames at 10 fps = 0.2 sec.
MIN_SEGMENT_FRAMES = 2

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

def probe_duration(path):
    cp = run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        Path(path).stem + "_fix2_duration.log", 120
    )
    if cp.returncode != 0:
        return None
    try:
        return float(cp.stdout.strip().splitlines()[-1])
    except Exception:
        return None

def popcount_bytes(mask):
    return sum(1 for b in mask if b)

def mask_from_gray(frame):
    # bytearray 0/1 keeps Jaccard calculation dependency-free.
    return bytearray(1 if b >= LUMA_THRESHOLD else 0 for b in frame)

def jaccard(a, b):
    inter = 0
    union = 0
    # Pure Python is fast enough: ~6k frames * 17k pixels ~100M small ops.
    for x, y in zip(a, b):
        if x or y:
            union += 1
            if x and y:
                inter += 1
    return (inter / union) if union else 1.0

def decode_bottom_frames(path):
    cmd = [
        str(FFMPEG), "-v", "error", "-i", str(path),
        "-vf", f"fps={FPS},crop={W}:{H}:{X}:{Y},format=gray",
        "-pix_fmt", "gray", "-f", "rawvideo", "-"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    assert p.stdout is not None
    while True:
        buf = p.stdout.read(FRAME_BYTES)
        if not buf:
            break
        if len(buf) != FRAME_BYTES:
            # Ignore incomplete final frame.
            break
        frames.append(buf)
    stderr = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
    rc = p.wait()
    (LOGD / (Path(path).stem + "_fix2_rawdecode.log")).write_text(
        "COMMANLOCAL_PATH" + " ".join(cmd) +
        "\n\nRETURN CODLOCAL_PATH" + str(rc) +
        "\n\nSTDERLOCAL_PATH" + stderr + "\n",
        encoding="utf-8-sig"
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg raw decode failed for {Path(path).name}")
    return frames

def segments_from_frames(frames):
    masks = []
    counts = []
    active = []
    for fr in frames:
        m = mask_from_gray(fr)
        c = popcount_bytes(m)
        masks.append(m)
        counts.append(c)
        active.append(c >= MIN_BRIGHT_PIXELS)

    # First pass: contiguous active regions, but split immediately when a
    # stable active caption changes to a different active caption.
    raw = []
    start = None
    prev_active_idx = None

    for i, is_on in enumerate(active):
        if not is_on:
            if start is not None:
                raw.append((start, i - 1))
                start = None
            prev_active_idx = None
            continue

        if start is None:
            start = i
            prev_active_idx = i
            continue

        # Both frames are active. A severe glyph-mask change means a new line
        # even if there was no blank frame between them.
        jac = jaccard(masks[prev_active_idx], masks[i]) if prev_active_idx is not None else 1.0

        # During fade-in a mask can grow rapidly. Only force a split if both
        # sides already contain a useful amount of glyph material.
        stable_a = counts[prev_active_idx] >= max(MIN_BRIGHT_PIXELS * 3, 60)
        stable_b = counts[i] >= max(MIN_BRIGHT_PIXELS * 3, 60)

        if stable_a and stable_b and jac < TEXT_CHANGE_JACCARD:
            raw.append((start, i - 1))
            start = i

        prev_active_idx = i

    if start is not None:
        raw.append((start, len(frames) - 1))

    # Remove single-frame noise.
    raw = [(a, b) for a, b in raw if (b - a + 1) >= MIN_SEGMENT_FRAMES]

    # Merge segments separated by one blank frame only when the text on both
    # sides is clearly the SAME caption. This repairs a rare decode/compression
    # dropout without merging adjacent dialogue lines.
    merged = []
    for seg in raw:
        if not merged:
            merged.append(seg)
            continue
        pa, pb = merged[-1]
        a, b = seg
        gap = a - pb - 1
        if gap == 1:
            # Compare strongest frame in each neighboring segment.
            pi = max(range(pa, pb + 1), key=lambda k: counts[k])
            ni = max(range(a, b + 1), key=lambda k: counts[k])
            if jaccard(masks[pi], masks[ni]) >= 0.78:
                merged[-1] = (pa, b)
                continue
        merged.append(seg)

    return merged, masks, counts, active


def png_chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)

def write_gray_png_exact(frame, out_path, scale2=True):
    """
    Save the EXACT grayscale frame used by the detector.
    No PMF seeking is performed.

    For OCR readability we write a 2x nearest-neighbor image:
      432x40 -> 864x80
    using only Python stdlib PNG encoding.
    """
    if len(frame) != FRAME_BYTES:
        raise ValueError(f"bad gray frame length {len(frame)}")

    if scale2:
        ow, oh = W * 2, H * 2
        rows = []
        for y in range(H):
            src = frame[y*W:(y+1)*W]
            doubled = bytes(v for b in src for v in (b, b))
            rows.append(b"\x00" + doubled)
            rows.append(b"\x00" + doubled)
    else:
        ow, oh = W, H
        rows = [b"\x00" + frame[y*W:(y+1)*W] for y in range(H)]

    raw = b"".join(rows)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += png_chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 0, 0, 0, 0))
    png += png_chunk(b"IDAT", zlib.compress(raw, 9))
    png += png_chunk(b"IEND", b"")
    Path(out_path).write_bytes(png)

def extract_full_reps_exact(name, src, rep_specs):
    """
    Extract all requested full frames for one movie in ONE ffmpeg pass.

    rep_specs:
      list of (segment_no, frame_index, representative_time)

    The exact index is relative to the same `fps=10` timeline used by the
    detector, eliminating inaccurate PMF fast seeking.
    """
    if not rep_specs:
        return {}

    tmp = STAGE / f"_fullrep_{name}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    indices = [idx for _, idx, _ in rep_specs]
    select_expr = "+".join(f"eq(n\\,{idx})" for idx in indices)
    pattern = tmp / "frame_%03d.jpg"

    cp = run(
        [FFMPEG, "-y", "-v", "error", "-i", src,
         "-vf", f"fps={FPS},select={select_expr},scale=480:272",
         "-fps_mode", "vfr", "-q:v", "3", pattern],
        f"{name}_fix3_fullrep.log", 600
    )

    result = {}
    generated = sorted(tmp.glob("frame_*.jpg"))

    if cp.returncode == 0 and len(generated) == len(rep_specs):
        for generated_path, (segno, frame_idx, rt) in zip(generated, rep_specs):
            out = REP / f"{name}_seg{segno:03d}_{rt:08.3f}_kr_full.jpg"
            shutil.move(str(generated_path), str(out))
            result[segno] = str(out)

    shutil.rmtree(tmp, ignore_errors=True)
    return result

def main():
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise RuntimeError("LOCAL_PATH / ffprobe.exe missing")

    # FIX4 self-test: verify the stdlib PNG writer before expensive PMF work.
    png_selftest = STAGE / "_png_writer_selftest.png"
    try:
        write_gray_png_exact(bytes([0]) * FRAME_BYTES, png_selftest, scale2=True)
        sig = png_selftest.read_bytes()[:8]
        if sig != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("PNG writer self-test produced an invalid PNG signature")
    finally:
        if png_selftest.exists():
            png_selftest.unlink()

    print("=" * 80, flush=True)
    print(" Naruto PSP MOV03N FIX5 - Exact-frame KR subtitle detector", flush=True)
    print("=" * 80, flush=True)

    # Remove stale representative images from previous paired-diff pass.
    for pattern in ("*.jpg", "*.png"):
        for p in REP.glob(pattern):
            p.unlink()

    all_segments = []
    frame_rows = []
    movie_rows = []
    total_segments = 0

    for mi, name in enumerate(DM, 1):
        src = KR_MOV / f"{name}.pmf"
        print(f"[{mi:02d}/10] {name}", flush=True)

        if not src.exists():
            movie_rows.append(dict(movie=name, status="MISSING_KR_SOURCE"))
            print("  missing KR source", flush=True)
            continue

        dur = probe_duration(src)

        try:
            frames = decode_bottom_frames(src)
        except Exception as e:
            movie_rows.append(dict(movie=name, status="DECODE_FAILED", error=str(e)))
            print(f"  FAIL: {e}", flush=True)
            continue

        segs, masks, counts, active = segments_from_frames(frames)

        # Frame-level diagnostics.
        for i, c in enumerate(counts):
            frame_rows.append(dict(
                movie=name,
                frame=i,
                time_sec=f"{i/FPS:.3f}",
                bright_pixels=c,
                bright_fraction=f"{c/FRAME_BYTES:.8f}",
                binary_yavg_equiv=f"{255.0*c/FRAME_BYTES:.6f}",
                active="YES" if active[i] else "NO",
            ))

        movie_segment_start = len(all_segments)
        full_rep_specs = []

        for si, (a, b) in enumerate(segs, 1):
            total_segments += 1

            # Best OCR frame = maximum bright glyph count. If tied, choose
            # closest to middle of the segment rather than a fade boundary.
            peak = max(counts[a:b+1])
            candidates = [i for i in range(a, b+1) if counts[i] == peak]
            mid = (a + b) / 2.0
            rep_i = min(candidates, key=lambda i: abs(i - mid))

            start = a / FPS
            end = (b + 1) / FPS
            rt = rep_i / FPS
            full_rep_specs.append((si, rep_i, rt))

            # Save the EXACT detector frame directly. This avoids the PMF
            # fast-seek mismatch that produced blank representative crops in
            # FIX2 even when peak_bright_pixels proved text was present.
            sub_out = REP / f"{name}_seg{si:03d}_{rt:08.3f}_kr_sub.png"
            write_gray_png_exact(frames[rep_i], sub_out, scale2=True)

            # Full frame is extracted later in one exact-index pass per movie.
            # Keep the requested index here.
            # Measure stability at representative vs preceding/following
            # active frame for later review.
            prev_j = ""
            next_j = ""
            if rep_i > a:
                prev_j = f"{jaccard(masks[rep_i-1], masks[rep_i]):.6f}"
            if rep_i < b:
                next_j = f"{jaccard(masks[rep_i], masks[rep_i+1]):.6f}"

            all_segments.append(dict(
                movie=name,
                segment=si,
                start_sec=f"{start:.3f}",
                end_sec=f"{end:.3f}",
                duration_sec=f"{end-start:.3f}",
                representative_sec=f"{rt:.3f}",
                peak_bright_pixels=peak,
                peak_bright_fraction=f"{peak/FRAME_BYTES:.8f}",
                rep_prev_jaccard=prev_j,
                rep_next_jaccard=next_j,
                kr_sub_image=str(sub_out),
                kr_full_image="",
                representative_frame=rep_i,
                ocr_japanese="",
                korean_translation="",
                review_status="PENDING",
            ))

        # Extract exact full reference frames once per movie using the same
        # fps=10 frame indices, then attach paths to just-added segment rows.
        full_paths = extract_full_reps_exact(name, src, full_rep_specs)
        for r in all_segments[movie_segment_start:]:
            segno = int(r["segment"])
            r["kr_full_image"] = full_paths.get(segno, "")

        active_frames = sum(1 for x in active if x)
        max_count = max(counts) if counts else 0
        movie_rows.append(dict(
            movie=name,
            status="OK",
            kr_duration=f"{dur:.6f}" if dur is not None else "",
            frames_analyzed=len(frames),
            active_frames=active_frames,
            active_time_sec=f"{active_frames/FPS:.3f}",
            segments=len(segs),
            max_bright_pixels=max_count,
            max_bright_fraction=f"{max_count/FRAME_BYTES:.8f}",
            luma_threshold=LUMA_THRESHOLD,
            min_bright_pixels=MIN_BRIGHT_PIXELS,
        ))

        print(
            f"  frames={len(frames)} active={active_frames} "
            f"segments={len(segs)} max-white={max_count}",
            flush=True
        )

    write_tsv(STAGE / "subtitle_segments.tsv", all_segments)
    write_tsv(STAGE / "frame_metrics.tsv", frame_rows)
    write_tsv(STAGE / "movie_summary.tsv", movie_rows)

    ok_movies = sum(1 for r in movie_rows if r.get("status") == "OK")
    zero_movies = [r["movie"] for r in movie_rows
                   if r.get("status") == "OK" and int(r.get("segments", 0)) == 0]

    summary = [
        "Naruto PSP MOV03N FIX5 - Exact-frame KR subtitle detector",
        "=" * 80, "",
        f"Movies analyzed={ok_movies}/10",
        f"Detected subtitle segments={total_segments}",
        f"Movies with zero detected subtitles={','.join(zero_movies) if zero_movies else '(none)'}",
        f"Analysis FPS={FPS}",
        f"Crop={W}x{H} at ({X},{Y})",
        f"Bright-pixel luma threshold={LUMA_THRESHOLD}",
        f"Minimum bright glyph pixels={MIN_BRIGHT_PIXELS}",
        "",
        "Method:",
        "  decode KR bottom black subtitle bar only",
        "  threshold bright Japanese glyph pixels directly",
        "  split on blank intervals and strong glyph-mask replacement",
        "  representative subtitle PNG = exact detector raw frame (no seeking)",
        "  representative full frame = exact fps=10 frame index",
        "",
        "This avoids KR-US drift and also saves OCR crops from the exact detector frames.",
        "",
        f"Representatives: {REP}",
    ]
    (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if ok_movies == 10 and total_segments > 0 else 2

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
