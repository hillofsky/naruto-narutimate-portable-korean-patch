#!/usr/bin/env python3
# Naruto PSP MOV06D
#
# Final Stage37 Korean-visual PMF builder for:
#   da101 / da201 / dk102 / dk202
#
# Proven by MOV06B + MOV06C:
#   da101 source_video.mp4 start +2270.242 sec
#   da201 part2.mp4        start +2667.250 sec
#   dk102 source_video.mp4 start +7257.450 sec
#   dk202 part2.mp4        start +2880.650 sec
#
# All four are CONTINUOUS. No edit jumps.
# Offset spread <= 0.018 sec, so no time stretching is applied.
#
# Video = Stage37 Korean-localized visual
# Audio = exact KR Japanese ATRAC3+ frames
# PTS   = exact KR audio PTS
#
# Base ISO prefers the user-validated MOV05D dk101 smoke ISO.
# Result therefore contains:
#   dm001..dm010 translated movies from MOV03T base
#   dk101 accepted MOV05D segmented movie
#   da101 / da201 / dk102 / dk202 from this MOV06D stage

from __future__ import annotations
import csv, importlib.util, math, os, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
CORE_PATH = ROOT / "mov06d_proven_movie_core.py"

KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
STAGE37 = ROOT / "analysis" / "stage37" / "video"

MOV05D_ISO = (
    ROOT / "analysis" / "mov" / "mov05d_dk101_segmented_final" / "output" /
    "Naruto_KR_MOV05D_dk101_segmented_smoketest.iso"
)
MOV05D_PMF = (
    ROOT / "analysis" / "mov" / "mov05d_dk101_segmented_final" / "output" /
    "dk101_stage37_segmented_KOvideo_KRJPaudio.pmf"
)
MOV03T_ISO = (
    ROOT / "analysis" / "mov" / "mov03t_iso_install" / "output" /
    "Naruto_KR_MOV03S_KoreanMovies.iso"
)

STAGE = ROOT / "analysis" / "mov" / "mov06d_remaining_final_batch"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

FINAL_ISO = OUT / "Naruto_KR_MOV06D_AllTranslatedMovies.iso"

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

SECTOR = 2048

TARGETS = [
    dict(
        name="da101",
        source=STAGE37 / "source_video.mp4",
        source_start=2270.242,
    ),
    dict(
        name="da201",
        source=STAGE37 / "part2.mp4",
        source_start=2667.250,
    ),
    dict(
        name="dk102",
        source=STAGE37 / "source_video.mp4",
        source_start=7257.450,
    ),
    dict(
        name="dk202",
        source=STAGE37 / "part2.mp4",
        source_start=2880.650,
    ),
]

BITRATE_ATTEMPTS = [
    (1000, 1550),
    (975, 1500),
    (950, 1450),
    (925, 1400),
    (900, 1350),
    (875, 1300),
    (850, 1250),
    (825, 1200),
    (800, 1150),
    (775, 1100),
]

def load_core():
    spec = importlib.util.spec_from_file_location("mov06d_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load proven PMF core")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STAGE = STAGE
    m.WORK = WORK
    m.OUT = OUT
    m.LOGD = LOGD
    m.FONTD = FONTD
    return m

def run(cmd, logname, timeout=3600, cwd=None):
    cp = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
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

def iso_norm(raw):
    s = raw.decode("ascii", errors="replace")
    if ";" in s:
        s = s.split(";", 1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16 * SECTOR)
    p = f.read(SECTOR)
    if len(p) != SECTOR or p[0] != 1 or p[1:6] != b"CD001":
        raise RuntimeError("ISO9660 PVD missing")
    r = p[156:]
    r = r[:r[0]]
    return struct.unpack_from("<I", r, 2)[0], struct.unpack_from("<I", r, 10)[0]

def read_dir(f, ext, size):
    base = ext * SECTOR
    f.seek(base)
    data = f.read(size)
    out = []
    pos = 0

    while pos < len(data):
        rl = data[pos]
        if rl == 0:
            pos = ((pos // SECTOR) + 1) * SECTOR
            continue

        rec = data[pos:pos+rl]
        ex = struct.unpack_from("<I", rec, 2)[0]
        sz = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        nl = rec[32]
        raw = rec[33:33+nl]
        name = "." if raw == b"\0" else ".." if raw == b"\1" else iso_norm(raw)

        out.append(dict(
            name=name,
            extent=ex,
            size=sz,
            is_dir=bool(flags & 2),
            record_offset=base+pos,
        ))
        pos += rl

    return out

def find_entry(f, parts):
    ext, sz = pvd_root(f)
    e = None
    for i, p in enumerate(parts):
        matches = [x for x in read_dir(f, ext, sz) if x["name"] == p.lower()]
        if not matches:
            raise FileNotFoundError("/" + "/".join(parts[:i+1]))
        e = matches[0]
        if i < len(parts)-1:
            ext, sz = e["extent"], e["size"]
    return e

def patch_size(f, off, new_size):
    f.seek(off+10)
    f.write(struct.pack("<I", new_size))
    f.write(struct.pack(">I", new_size))

def sha_file(path):
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def sha_region(f, off, size):
    import hashlib
    h = hashlib.sha256()
    f.seek(off)
    remain = size
    while remain:
        b = f.read(min(remain, 1024*1024))
        if not b:
            break
        h.update(b)
        remain -= len(b)
    if remain:
        raise RuntimeError("EOF while hashing ISO region")
    return h.hexdigest()

def patch_iso_file(iso_path, internal_name, replacement, allocation_override=None):
    parts = ["PSP_GAME", "USRDIR", "movie", internal_name + ".pmf"]
    data = Path(replacement).read_bytes()

    with Path(iso_path).open("r+b") as f:
        e = find_entry(f, parts)
        allocation = (
            int(allocation_override)
            if allocation_override is not None
            else int(math.ceil(e["size"] / SECTOR) * SECTOR)
        )

        if len(data) > allocation:
            raise RuntimeError(
                f"{internal_name}: replacement {len(data)} > allocation {allocation}"
            )

        f.seek(e["extent"] * SECTOR)
        f.write(data)

        remain = allocation - len(data)
        block = b"\0" * min(32768, max(1, remain))
        while remain > 0:
            n = min(remain, len(block))
            f.write(block[:n])
            remain -= n

        patch_size(f, e["record_offset"], len(data))

    return allocation

def verify_iso_file(iso_path, internal_name, replacement, expected_extent=None):
    parts = ["PSP_GAME", "USRDIR", "movie", internal_name + ".pmf"]
    expected_sha = sha_file(replacement)
    expected_size = Path(replacement).stat().st_size

    with Path(iso_path).open("rb") as f:
        e = find_entry(f, parts)
        actual_sha = sha_region(f, e["extent"] * SECTOR, e["size"])

    return dict(
        ok=(
            e["size"] == expected_size
            and actual_sha == expected_sha
            and (expected_extent is None or e["extent"] == expected_extent)
        ),
        extent=e["extent"],
        size=e["size"],
        sha=actual_sha,
    )

def prepare_base_iso():
    """
    Prefer the already user-validated MOV05D ISO.

    Fallback:
      copy MOV03T and insert the existing MOV05D dk101 PMF.
    """
    base_copy = WORK / "base_with_mov05d.iso"
    if base_copy.exists():
        base_copy.unlink()

    if MOV05D_ISO.exists():
        print(f"Base ISO: validated MOV05D\n  {MOV05D_ISO}", flush=True)
        shutil.copyfile(MOV05D_ISO, base_copy)
        return base_copy, "MOV05D_ISO"

    if MOV03T_ISO.exists() and MOV05D_PMF.exists():
        print("MOV05D ISO missing; rebuilding equivalent base from MOV03T + dk101 PMF.", flush=True)
        shutil.copyfile(MOV03T_ISO, base_copy)
        patch_iso_file(base_copy, "dk101", MOV05D_PMF)
        v = verify_iso_file(base_copy, "dk101", MOV05D_PMF)
        if not v["ok"]:
            raise RuntimeError("Fallback base dk101 verification failed")
        return base_copy, "MOV03T_PLUS_MOV05D_PMF"

    raise RuntimeError(
        "Validated MOV05D base not found. Need eitheLOCAL_PATH"
        f"  {MOV05D_ISO}\n"
        "or botLOCAL_PATH"
        f"  {MOV03T_ISO}\n"
        f"  {MOV05D_PMF}"
    )

def build_lossless_trim(cfg, duration, out_path):
    """
    Exact one-piece Stage37 trim. No speed modification.
    """
    start = cfg["source_start"]
    vf = (
        "setpts=PTS-STARTPTS,"
        "scale=480:272:flags=lanczos,"
        "fps=30000/1001,"
        "setsar=1,"
        "format=yuv420p"
    )

    cp = run([
        FFMPEG, "-y", "-v", "warning",
        "-ss", f"{start:.6f}",
        "-t", f"{duration:.6f}",
        "-i", cfg["source"],
        "-an",
        "-vf", vf,
        "-c:v", "ffv1", "-level", "3",
        "-pix_fmt", "yuv420p",
        "-fps_mode", "cfr",
        out_path,
    ], f"10_{cfg['name']}_lossless_trim.log", 3600)

    if cp.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"{cfg['name']}: Stage37 lossless trim failed")

def build_one(core, cfg, base_iso):
    name = cfg["name"]
    kr_pmf = KR_MOV / f"{name}.pmf"

    parsed = core.parse_pmf(kr_pmf)
    audio = core.recover_audio(parsed)
    if audio["bad_headers"]:
        raise RuntimeError(f"{name}: KR AU headers invalid: {audio['bad_headers']}")

    audio_duration = audio["frame_count"] * core.SAMPLES_PER_FRAME / core.SAMPLE_RATE

    # Determine fixed ISO allocation before encoding.
    target_parts = ["PSP_GAME", "USRDIR", "movie", name + ".pmf"]
    with Path(base_iso).open("rb") as f:
        entry = find_entry(f, target_parts)
        allocation = math.ceil(entry["size"] / SECTOR) * SECTOR
        original_extent = entry["extent"]

    print(
        f"\n[{name}] KR audio={audio_duration:.3f}s "
        f"source={cfg['source'].name}@{cfg['source_start']:.3f}s "
        f"allocation={allocation}",
        flush=True
    )

    lossless = WORK / f"{name}_stage37_lossless.avi"
    build_lossless_trim(cfg, audio_duration, lossless)

    # Sanity-check source trim duration.
    info = core.probe(lossless, f"11_{name}_lossless_probe.log")
    v = core.get_video(info)
    if not v:
        raise RuntimeError(f"{name}: lossless trim has no video stream")

    composer = core.find_exe("oMPSComposer.exe")
    mps2pmf = core.find_exe("Mps2Pmf.exe")
    helper = ROOT / "invoke_naruto_mov06d_raw_mux.ps1"

    if composer is None or mps2pmf is None or not helper.exists():
        raise RuntimeError(f"{name}: PMF tools/helper missing")

    # Exact KR compressed audio.
    riff = WORK / f"{name}_kr_frames.at3"
    core.build_riff(audio["frames"], riff)

    cdir = composer.parent
    local_ffmpeg = cdir / "ffmpeg.exe"
    temp_ffmpeg = False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG, local_ffmpeg)
        temp_ffmpeg = True

    chosen = None

    try:
        for idx, (avg, maxbr) in enumerate(BITRATE_ATTEMPTS, 1):
            tag = f"{name}_try{idx}_{avg}"
            print(
                f"  encode {idx}/{len(BITRATE_ATTEMPTS)}: "
                f"avg={avg} max={maxbr}",
                flush=True
            )

            vmps = WORK / f"{tag}_video.mps"
            cp = run([
                composer,
                lossless,
                "-",
                vmps,
                "--avg-bitrate", str(avg),
                "--max-bitrate", str(maxbr),
                "--encode-mode", "2pass",
                "--idr-duration", "2000",
                "--m-frames", "1",
            ], f"12_{tag}_video_encode.log", 3600, cwd=cdir)

            if cp.returncode != 0 or not vmps.exists():
                continue

            whole = int(math.ceil(audio_duration))
            mins, secs = divmod(whole, 60)

            video_pmf = WORK / f"{tag}_video.pmf"
            cp = run([
                mps2pmf,
                "-i", vmps,
                "-o", video_pmf,
                "-m", str(mins),
                "-s", str(secs),
            ], f"13_{tag}_video_pmf.log", 600, cwd=mps2pmf.parent)

            if cp.returncode != 0 or not video_pmf.exists():
                continue

            h264 = WORK / f"{tag}.264"
            if not core.extract_h264(video_pmf, h264, f"14_{tag}_extract_h264.log"):
                continue
            expected_video_sha = core.sha_file(h264)

            final_mps = WORK / f"{tag}_final.mps"
            cp = run([
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", helper,
                "-Composer", composer,
                "-H264", h264,
                "-AtracRiff", riff,
                "-OutputMps", final_mps,
            ], f"15_{tag}_mux.log", 1800)

            if cp.returncode != 0 or not final_mps.exists():
                continue

            # Exact original KR audio timestamp sequence.
            core.patch_mps_audio_pts_exact(final_mps, parsed)

            final_pmf = WORK / f"{tag}_final.pmf"
            total_duration = max(
                audio_duration,
                audio["frame_count"] * core.SAMPLES_PER_FRAME / core.SAMPLE_RATE,
            )
            whole = int(math.ceil(total_duration))
            mins, secs = divmod(whole, 60)

            cp = run([
                mps2pmf,
                "-i", final_mps,
                "-o", final_pmf,
                "-m", str(mins),
                "-s", str(secs),
            ], f"16_{tag}_final_pmf.log", 600, cwd=mps2pmf.parent)

            if cp.returncode != 0 or not final_pmf.exists():
                continue

            # Strict validation.
            fp = core.parse_pmf(final_pmf)
            fa = core.recover_audio(fp)

            final_h264 = WORK / f"{tag}_final.264"
            if not core.extract_h264(final_pmf, final_h264, f"17_{tag}_final_h264.log"):
                continue

            video_ok = core.sha_file(final_h264) == expected_video_sha
            logical_ok = core.sha_bytes(fa["logical"]) == core.sha_bytes(audio["logical"])
            frames_ok = core.sha_bytes(fa["frames"]) == core.sha_bytes(audio["frames"])
            pes_ok = len(fp["audio"]) == len(parsed["audio"])
            pts_ok = [x["pts"] for x in fp["audio"]] == [x["pts"] for x in parsed["audio"]]

            oma = WORK / f"{tag}.oma"
            core.build_oma(fa["frames"], oma)
            cp = run([
                FFMPEG,
                "-v", "warning",
                "-f", "oma",
                "-i", oma,
                "-f", "null", "-"
            ], f"18_{tag}_atrac_decode.log", 1200)
            decode_ok = cp.returncode == 0

            info = core.probe(final_pmf, f"19_{tag}_probe.log")
            vs = core.get_video(info)
            format_ok = bool(
                vs
                and vs.get("codec_name") == "h264"
                and int(vs.get("width", 0)) == 480
                and int(vs.get("height", 0)) == 272
            )

            strict = all([
                video_ok,
                logical_ok,
                frames_ok,
                pes_ok,
                pts_ok,
                decode_ok,
                format_ok,
            ])
            fits = final_pmf.stat().st_size <= allocation

            print(
                f"    size={final_pmf.stat().st_size} "
                f"strict={strict} fit={fits}",
                flush=True
            )

            if strict and fits:
                dst = OUT / f"{name}.pmf"
                shutil.copy2(final_pmf, dst)
                chosen = dict(
                    name=name,
                    source=cfg["source"].name,
                    source_start=cfg["source_start"],
                    audio_duration=audio_duration,
                    avg=avg,
                    maxbr=maxbr,
                    size=dst.stat().st_size,
                    allocation=allocation,
                    original_extent=original_extent,
                    video_ok=video_ok,
                    logical_ok=logical_ok,
                    frames_ok=frames_ok,
                    pes_ok=pes_ok,
                    pts_ok=pts_ok,
                    decode_ok=decode_ok,
                    format_ok=format_ok,
                    path=dst,
                )
                break
    finally:
        if temp_ffmpeg:
            try:
                local_ffmpeg.unlink()
            except Exception:
                pass

    if chosen is None:
        raise RuntimeError(
            f"{name}: no strict-valid PMF fit allocation {allocation}"
        )

    # Representative output frames, including very near the tail.
    for label, t in [
        ("start", 1.0),
        ("quarter", audio_duration*0.25),
        ("middle", audio_duration*0.50),
        ("threequarter", audio_duration*0.75),
        ("tail", max(0.0, audio_duration-0.20)),
    ]:
        out = OUT / f"review_{name}_{label}_{t:08.3f}.jpg"
        run([
            FFMPEG, "-y", "-v", "error",
            "-ss", f"{t:.3f}",
            "-i", chosen["path"],
            "-frames:v", "1",
            "-q:v", "2",
            out,
        ], f"20_review_{name}_{label}.log", 180)

    return chosen

def main():
    core = load_core()

    for p in (CORE_PATH, FFMPEG, FFPROBE):
        if not p.exists():
            raise RuntimeError(f"Missing tool/core: {p}")

    for cfg in TARGETS:
        kr = KR_MOV / f"{cfg['name']}.pmf"
        if not kr.exists():
            raise RuntimeError(f"Missing KR PMF: {kr}")
        if not cfg["source"].exists():
            raise RuntimeError(f"Missing Stage37 source: {cfg['source']}")

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("="*80, flush=True)
    print(" Naruto PSP MOV06D - final Stage37 remaining movie batch", flush=True)
    print("="*80, flush=True)
    print("All 4 targets classified CONTINUOUS by MOV06C.", flush=True)
    print("No video stretch will be applied.", flush=True)

    base_iso, base_mode = prepare_base_iso()

    # Read original allocations/extents from the prepared base before modification.
    base_meta = {}
    with base_iso.open("rb") as f:
        for cfg in TARGETS:
            e = find_entry(
                f,
                ["PSP_GAME", "USRDIR", "movie", cfg["name"] + ".pmf"]
            )
            base_meta[cfg["name"]] = dict(
                extent=e["extent"],
                original_size=e["size"],
                allocation=math.ceil(e["size"]/SECTOR)*SECTOR,
            )

    results = []

    for i, cfg in enumerate(TARGETS, 1):
        print("", flush=True)
        print(f"========== TARGET {i}/{len(TARGETS)}: {cfg['name']} ==========", flush=True)
        r = build_one(core, cfg, base_iso)
        results.append(r)

    # Integrated ISO.
    if FINAL_ISO.exists():
        FINAL_ISO.unlink()
    shutil.copyfile(base_iso, FINAL_ISO)

    for r in results:
        allocation = base_meta[r["name"]]["allocation"]
        patch_iso_file(
            FINAL_ISO,
            r["name"],
            r["path"],
            allocation_override=allocation,
        )

    iso_rows = []
    for r in results:
        v = verify_iso_file(
            FINAL_ISO,
            r["name"],
            r["path"],
            expected_extent=base_meta[r["name"]]["extent"],
        )
        if not v["ok"]:
            raise RuntimeError(f"{r['name']}: integrated ISO verification failed")
        iso_rows.append(dict(
            name=r["name"],
            iso_extent=v["extent"],
            iso_size=v["size"],
            replacement_sha256=sha_file(r["path"]),
            iso_region_sha256=v["sha"],
            status="PASS",
        ))

    # Verify accepted dk101 is still present when MOV05D PMF is available.
    dk101_status = "NOT_CHECKED"
    if MOV05D_PMF.exists():
        v = verify_iso_file(FINAL_ISO, "dk101", MOV05D_PMF)
        dk101_status = "PASS" if v["ok"] else "FAIL"
        if not v["ok"]:
            raise RuntimeError("Integrated ISO no longer matches accepted MOV05D dk101 PMF")

    result_rows = []
    for r in results:
        result_rows.append(dict(
            name=r["name"],
            source=r["source"],
            source_start_sec=f"{r['source_start']:.6f}",
            kr_audio_duration_sec=f"{r['audio_duration']:.6f}",
            timeline_model="CONTINUOUS_FIXED_OFFSET_NO_STRETCH",
            encoded_avg_kbps=r["avg"],
            encoded_max_kbps=r["maxbr"],
            final_pmf_bytes=r["size"],
            allocation_bytes=r["allocation"],
            spare_bytes=r["allocation"]-r["size"],
            h264_equal_encoded_video="YES" if r["video_ok"] else "NO",
            logical_752_equal_kr="YES" if r["logical_ok"] else "NO",
            frames_744_equal_kr="YES" if r["frames_ok"] else "NO",
            audio_pes_equal_kr="YES" if r["pes_ok"] else "NO",
            audio_pts_equal_kr="YES" if r["pts_ok"] else "NO",
            atrac_decode="PASS" if r["decode_ok"] else "FAIL",
            video_format="PASS" if r["format_ok"] else "FAIL",
            status="PASS",
        ))

    write_tsv(STAGE / "mov06d_result.tsv", result_rows)
    write_tsv(STAGE / "iso_verification.tsv", iso_rows)

    summary = [
        "Naruto PSP MOV06D - final Stage37 remaining movie batch",
        "="*80,
        "",
        "RESULT=PASS",
        "",
        f"Base mode={base_mode}",
        "",
        "MOV06C-proven continuous mappings:",
        "  da101 <- source_video.mp4 @ +2270.242 sec",
        "  da201 <- part2.mp4        @ +2667.250 sec",
        "  dk102 <- source_video.mp4 @ +7257.450 sec",
        "  dk202 <- part2.mp4        @ +2880.650 sec",
        "",
        "No time stretching.",
        "No piecewise edits.",
        "Each Stage37 source is trimmed once at normal speed.",
        "",
        "Audio for all four movies:",
        "  exact KR Japanese ATRAC3+ frames",
        "  exact KR logical 752-byte AU payload",
        "  exact KR audio PES count",
        "  exact KR PTS sequence",
        "",
        "Integrated ISO includes the validated MOV05D dk101 base.",
        f"dk101 verification={dk101_status}",
        "",
        "Accepted dk101 runtime note:",
        "  About 2-3 Stage37/YouTube tail frames remain at the end of",
        "  dk101 internal video 2. User explicitly accepted this artifact.",
        "",
    ]

    for r in results:
        summary += [
            f"{r['name']}:",
            f"  bitrate={r['avg']}/{r['maxbr']} kbps",
            f"  PMF={r['size']} bytes",
            f"  allocation={r['allocation']} bytes",
            f"  spare={r['allocation']-r['size']} bytes",
            "  strict validation=PASS",
            "",
        ]

    summary += [
        f"Final integrated ISO={FINAL_ISO}",
        "",
        "Wrapper will auto-launch this ISO using the user-confirmed PPSSPP folder.",
    ]

    (STAGE / "SUMMARY.txt").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8-sig"
    )

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
        (STAGE / "FAILURE.txt").write_text(tb, encoding="utf-8-sig")
        print(tb, file=sys.stderr, flush=True)
        raise SystemExit(1)
