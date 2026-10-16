#!/usr/bin/env python3
# Naruto PSP MOV04D FIX1 - rebuild only oversized DA/DK PMFs to fit original ISO allocation.
#
# Oversized from MOV04D preflight:
#   da101.pmf: +18,432 bytes
#   dk202.pmf: +108,544 bytes
#
# Strategy:
#   - preserve original file LBA/extent
#   - preserve Korean subtitles
#   - preserve exact KR Japanese ATRAC3+ frames and KR audio PTS
#   - only lower H.264 video bitrate slightly
#   - try 99%, 98%, 96%, 94% of normal PSP video bitrate and stop at the
#     highest-quality attempt that fits the original allocation.

from __future__ import annotations
import importlib.util, math, os, shutil, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
CORE_PATH = ROOT / "mov04d_fix1_core.py"
ASS_DIR = ROOT / "mov04c_ass"

STAGE = ROOT / "analysis" / "mov" / "mov04d_fix1_fit_rebuild"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

TARGETS = {
    "da101": 4659200,
    "dk202": 43497472,
}
FACTORS = [0.99, 0.98, 0.96, 0.94]

def load_core():
    if not CORE_PATH.exists():
        raise RuntimeError(f"Missing bundled MOV04C core: {CORE_PATH}")
    spec = importlib.util.spec_from_file_location("mov04d_fix1_core", CORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    # Redirect proven MOV04C helpers to FIX1 stage.
    mod.STAGE = STAGE
    mod.WORK = WORK
    mod.OUT = OUT
    mod.LOGD = LOGD
    mod.FONTD = FONTD
    mod.ASS_DIR = ASS_DIR
    return mod

def main():
    core = load_core()

    failure = STAGE / "FAILURE.txt"
    if failure.exists():
        failure.unlink()

    if not core.FFMPEG.exists() or not core.FFPROBE.exists():
        raise RuntimeError("ffmpeg/ffprobe missing")

    composer = core.find_exe("oMPSComposer.exe")
    mps2pmf = core.find_exe("Mps2Pmf.exe")
    helper = ROOT / "invoke_naruto_mov04d_fix1_raw_mux.ps1"
    if composer is None or mps2pmf is None:
        raise RuntimeError("oMPSComposer.exe / Mps2Pmf.exe not found")
    if not helper.exists():
        raise RuntimeError("MOV04D FIX1 reflection helper missing")

    _, _font_copy = core.choose_font()

    # oMPSComposer requires ffmpeg beside itself.
    cdir = composer.parent
    local_ffmpeg = cdir / "ffmpeg.exe"
    temp_ffmpeg = False
    if not local_ffmpeg.exists():
        shutil.copy2(core.FFMPEG, local_ffmpeg)
        temp_ffmpeg = True

    rows = []
    all_ok = True

    print("=" * 80, flush=True)
    print(" Naruto PSP MOV04D FIX1 - fit rebuild for da101 / dk202", flush=True)
    print("=" * 80, flush=True)

    try:
        for num, name in enumerate(TARGETS, 1):
            limit = TARGETS[name]
            print(f"[{num:02d}/02] {name} allocation={limit}", flush=True)

            row = {"movie": name, "allocation_limit": limit}
            mw = WORK / name
            shutil.rmtree(mw, ignore_errors=True)
            mw.mkdir(parents=True, exist_ok=True)

            try:
                kr = core.KR_MOV / f"{name}.pmf"
                us = core.us_source(name)
                ass_src = ASS_DIR / f"{name}_ko.ass"

                if not kr.exists():
                    raise RuntimeError("KR PMF missing")
                if us is None:
                    raise RuntimeError("US clean PMF missing")
                if not ass_src.exists():
                    raise RuntimeError("Korean ASS missing")

                krp = core.parse_pmf(kr)
                kra = core.recover_audio(krp)
                if kra["bad_headers"]:
                    raise RuntimeError(f"unexpected KR AU headers: {kra['bad_headers']}")

                ass = mw / f"{name}.ass"
                shutil.copy2(ass_src, ass)
                events = [
                    ln for ln in ass.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                    if ln.startswith("Dialogue:")
                ]

                us264 = mw / f"{name}_us.264"
                if not core.extract_h264(us, us264, f"{name}_01_extract_us_h264.log"):
                    raise RuntimeError("US H264 extraction failed")
                ui = core.probe(us, f"{name}_02_probe_us.log")
                ud = core.get_duration(ui)
                if not ud:
                    raise RuntimeError("US duration unavailable")

                kbps = us264.stat().st_size * 8 / ud / 1000.0
                base_avg = max(500, min(3500, int(round(kbps / 50.0) * 50)))
                base_max = min(4700, int(round(max(base_avg + 500, base_avg * 1.55) / 50.0) * 50))
                if base_max <= base_avg:
                    base_max = min(4700, base_avg + 500)

                # Burn once losslessly; all retries encode from this same source.
                burned = mw / f"{name}_burned.avi"
                rel_ass = os.path.relpath(ass, STAGE).replace("\\", "/")
                rel_fonts = os.path.relpath(FONTD, STAGE).replace("\\", "/")
                vf = f"setpts=PTS-STARTPTS,ass=filename='{rel_ass}':fontsdir='{rel_fonts}'"
                cp = core.run(
                    [core.FFMPEG, "-y", "-v", "warning", "-i", us, "-an",
                     "-vf", vf, "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p",
                     "-fps_mode", "cfr", burned],
                    f"{name}_03_burn.log", 1800, cwd=STAGE
                )
                if cp.returncode != 0 or not burned.exists():
                    raise RuntimeError("subtitle burn failed")

                bi = core.probe(burned, f"{name}_04_probe_burned.log")
                bd = core.get_duration(bi)
                if not bd:
                    raise RuntimeError("burned duration unavailable")

                # Exact KR ATRAC source reused for every attempt.
                riff = mw / f"{name}_KR_frames.at3"
                core.build_riff(kra["frames"], riff)

                chosen = None
                attempt_results = []

                for attempt, factor in enumerate(FACTORS, 1):
                    avg = max(450, int(math.floor(base_avg * factor / 25.0) * 25))
                    maxbr = max(avg + 300, int(math.floor(base_max * factor / 25.0) * 25))
                    maxbr = min(4700, maxbr)

                    tag = f"{name}_try{attempt}_{int(factor*100)}pct"
                    print(f"  attempt {attempt}: avg={avg} max={maxbr} kbps", flush=True)

                    v_mps = mw / f"{tag}_video.mps"
                    cp = core.run(
                        [composer, burned, "-", v_mps,
                         "--avg-bitrate", str(avg), "--max-bitrate", str(maxbr),
                         "--encode-mode", "2pass", "--idr-duration", "2000", "--m-frames", "1"],
                        f"{tag}_05_oMPSComposer_video.log", 3000, cwd=cdir
                    )
                    if cp.returncode != 0 or not v_mps.exists():
                        attempt_results.append((factor, avg, maxbr, None, "VIDEO_ENCODE_FAIL"))
                        continue

                    v_pmf = mw / f"{tag}_video_only.pmf"
                    whole = int(math.ceil(bd))
                    mins, secs = divmod(whole, 60)
                    cp = core.run(
                        [mps2pmf, "-i", v_mps, "-o", v_pmf, "-m", str(mins), "-s", str(secs)],
                        f"{tag}_06_Mps2Pmf_video.log", 300, cwd=mps2pmf.parent
                    )
                    if cp.returncode != 0 or not v_pmf.exists():
                        attempt_results.append((factor, avg, maxbr, None, "VIDEO_PMF_FAIL"))
                        continue

                    sub264 = mw / f"{tag}_KOsub.264"
                    if not core.extract_h264(v_pmf, sub264, f"{tag}_07_extract_sub_h264.log"):
                        attempt_results.append((factor, avg, maxbr, None, "H264_EXTRACT_FAIL"))
                        continue
                    sub_sha = core.sha_file(sub264)

                    final_mps = mw / f"{tag}_final.mps"
                    cp = core.run(
                        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", helper,
                         "-Composer", composer,
                         "-H264", sub264,
                         "-AtracRiff", riff,
                         "-OutputMps", final_mps],
                        f"{tag}_08_reflection_mux.log", 1200
                    )
                    if cp.returncode != 0 or not final_mps.exists():
                        attempt_results.append((factor, avg, maxbr, None, "MUX_FAIL"))
                        continue

                    patched_pts = core.patch_mps_audio_pts_exact(final_mps, krp)

                    candidate = mw / f"{tag}_final.pmf"
                    total_sec = max(bd, kra["frame_count"] * core.SAMPLES_PER_FRAME / core.SAMPLE_RATE)
                    whole = int(math.ceil(total_sec))
                    mins, secs = divmod(whole, 60)
                    cp = core.run(
                        [mps2pmf, "-i", final_mps, "-o", candidate, "-m", str(mins), "-s", str(secs)],
                        f"{tag}_09_Mps2Pmf_final.log", 300, cwd=mps2pmf.parent
                    )
                    if cp.returncode != 0 or not candidate.exists():
                        attempt_results.append((factor, avg, maxbr, None, "FINAL_PMF_FAIL"))
                        continue

                    fp = core.parse_pmf(candidate)
                    fa = core.recover_audio(fp)

                    final264 = mw / f"{tag}_final.264"
                    if not core.extract_h264(candidate, final264, f"{tag}_10_extract_final_h264.log"):
                        attempt_results.append((factor, avg, maxbr, candidate.stat().st_size, "FINAL_H264_FAIL"))
                        continue

                    video_ok = core.sha_file(final264) == sub_sha
                    logical_ok = core.sha_bytes(fa["logical"]) == core.sha_bytes(kra["logical"])
                    frames_ok = core.sha_bytes(fa["frames"]) == core.sha_bytes(kra["frames"])
                    pes_ok = len(fp["audio"]) == len(krp["audio"])
                    pts_ok = [x["pts"] for x in fp["audio"]] == [x["pts"] for x in krp["audio"]]

                    oma = mw / f"{tag}.oma"
                    core.build_oma(fa["frames"], oma)
                    cp = core.run(
                        [core.FFMPEG, "-v", "warning", "-f", "oma", "-i", oma, "-f", "null", "-"],
                        f"{tag}_11_decode_audio.log", 600
                    )
                    decode_ok = cp.returncode == 0

                    info = core.probe(candidate, f"{tag}_12_probe_final.log")
                    vs = core.get_video(info)
                    format_ok = bool(
                        vs and vs.get("codec_name") == "h264"
                        and int(vs.get("width", 0)) == 480
                        and int(vs.get("height", 0)) == 272
                    )

                    strict_ok = all([video_ok, logical_ok, frames_ok, pes_ok, pts_ok, decode_ok, format_ok])
                    size = candidate.stat().st_size
                    fits = size <= limit

                    attempt_results.append(
                        (factor, avg, maxbr, size, "PASS_FIT" if strict_ok and fits else
                         "PASS_OVERSIZE" if strict_ok else "VALIDATION_FAIL")
                    )

                    print(
                        f"    size={size} limit={limit} "
                        f"strict={'PASS' if strict_ok else 'FAIL'} "
                        f"fit={'YES' if fits else 'NO'}",
                        flush=True
                    )

                    if strict_ok and fits:
                        final = OUT / f"{name}.pmf"
                        shutil.copy2(candidate, final)
                        chosen = dict(
                            factor=factor, avg=avg, maxbr=maxbr, size=size,
                            patched_pts=patched_pts,
                            video_ok=video_ok, logical_ok=logical_ok,
                            frames_ok=frames_ok, pes_ok=pes_ok, pts_ok=pts_ok,
                            decode_ok=decode_ok, format_ok=format_ok,
                            output=str(final),
                        )
                        break

                if chosen is None:
                    raise RuntimeError(
                        "No bitrate attempt produced a strict-valid PMF within allocation: "
                        + repr(attempt_results)
                    )

                row.update(
                    subtitle_count=len(events),
                    source_video_kbps=f"{kbps:.3f}",
                    base_avg_kbps=base_avg,
                    base_max_kbps=base_max,
                    chosen_factor=f"{chosen['factor']:.2f}",
                    chosen_avg_kbps=chosen["avg"],
                    chosen_max_kbps=chosen["maxbr"],
                    final_size=chosen["size"],
                    spare_bytes=limit-chosen["size"],
                    logical_752_equal_kr="YES" if chosen["logical_ok"] else "NO",
                    frames_744_equal_kr="YES" if chosen["frames_ok"] else "NO",
                    audio_pts_equal_kr="YES" if chosen["pts_ok"] else "NO",
                    audio_pes_equal_kr="YES" if chosen["pes_ok"] else "NO",
                    atrac_decode="PASS" if chosen["decode_ok"] else "FAIL",
                    video_format="PASS" if chosen["format_ok"] else "FAIL",
                    output_pmf=chosen["output"],
                    attempts=repr(attempt_results),
                    status="PASS",
                )
                rows.append(row)
                print(
                    f"  CHOSEN: factor={chosen['factor']:.2f} "
                    f"size={chosen['size']} spare={limit-chosen['size']}",
                    flush=True
                )

            except Exception as e:
                all_ok = False
                row["status"] = "FAIL"
                row["error"] = str(e)
                rows.append(row)
                print(f"  FAIL: {e}", flush=True)

            finally:
                shutil.rmtree(mw, ignore_errors=True)

    finally:
        if temp_ffmpeg:
            try:
                local_ffmpeg.unlink()
            except Exception:
                pass

    core.write_tsv(STAGE / "fit_rebuild_results.tsv", rows)

    passed = sum(1 for r in rows if r.get("status") == "PASS")
    summary = [
        "Naruto PSP MOV04D FIX1 - fit rebuild",
        "=" * 80,
        "",
        f"PASS={passed}/2",
        "",
        "Purpose:",
        "  fit da101/dk202 inside their original ISO allocations without relocation",
        "",
        "Audio:",
        "  exact KR Japanese ATRAC3+ frames preserved",
        "  exact KR audio PTS preserved",
        "",
        "Only PSP H.264 video bitrate may be reduced slightly.",
        "",
        f"RESULT={'PASS' if passed == 2 else 'FAIL'}",
    ]
    (STAGE / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8-sig")
    print("\n".join(summary), flush=True)

    return 0 if passed == 2 and all_ok else 2

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
