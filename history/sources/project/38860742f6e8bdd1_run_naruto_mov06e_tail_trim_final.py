#!/usr/bin/env python3
# Naruto PSP MOV06E
#
# User-requested final tail trims:
#   da101  -> keep through 32.265 sec
#   da201  -> keep through 48.786 sec
#   dk101  -> keep through 1:55.602 = 115.602 sec
#
# Important:
#   PMF audio is ATRAC3+ with 2048 samples/frame @ 44100 Hz.
#   To guarantee that no audio/video survives past the requested cutoff,
#   the effective PMF duration is floored to the last complete ATRAC frame
#   at or before the requested cutoff (max ~46.44 ms earlier).
#
# We rebuild from the CURRENT translated PMFs, so all existing Korean visuals
# before the cutoff are preserved.
#
# Base ISO:
#   MOV06D_AllTranslatedMovies.iso
#
# Only da101 / da201 / dk101 are replaced.
# All other translated PMFs remain untouched.

from __future__ import annotations
import csv, importlib.util, math, shutil, struct, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
CORE_PATH = ROOT / "mov06e_proven_movie_core.py"

FFMPEG = Path(r"LOCAL_PATH")
FFPROBE = Path(r"LOCAL_PATH")

KR_MOV = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"

MOV06D_DIR = ROOT / "analysis" / "mov" / "mov06d_remaining_final_batch"
MOV05D_DIR = ROOT / "analysis" / "mov" / "mov05d_dk101_segmented_final"

BASE_ISO = MOV06D_DIR / "output" / "Naruto_KR_MOV06D_AllTranslatedMovies.iso"

STAGE = ROOT / "analysis" / "mov" / "mov06e_tail_trim_final"
WORK = STAGE / "work"
OUT = STAGE / "output"
LOGD = STAGE / "logs"
FONTD = STAGE / "fonts"
for p in (STAGE, WORK, OUT, LOGD, FONTD):
    p.mkdir(parents=True, exist_ok=True)

FINAL_ISO = OUT / "Naruto_KR_MOV06E_AllTranslatedMovies_TrimmedTails.iso"
FINAL_SET_DIR = ROOT / "analysis" / "mov" / "FINAL_TRANSLATED_PMFS"

SECTOR = 2048

TARGETS = [
    dict(
        name="da101",
        cutoff=32.265,
        translated=MOV06D_DIR / "output" / "da101.pmf",
    ),
    dict(
        name="da201",
        cutoff=48.786,
        translated=MOV06D_DIR / "output" / "da201.pmf",
    ),
    dict(
        name="dk101",
        cutoff=115.602,
        translated=MOV05D_DIR / "output" / "dk101_stage37_segmented_KOvideo_KRJPaudio.pmf",
    ),
]

BITRATE_ATTEMPTS = [
    (1000,1550),
    (975,1500),
    (950,1450),
    (925,1400),
    (900,1350),
    (875,1300),
    (850,1250),
    (825,1200),
    (800,1150),
]

def load_core():
    spec = importlib.util.spec_from_file_location("mov06e_core", CORE_PATH)
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
        ('"%s"'%str(x) if " " in str(x) else str(x)) for x in cmd
    )
    txt += "\n\nRETURN CODLOCAL_PATH" + str(cp.returncode)
    txt += "\n\nSTDOULOCAL_PATH" + cp.stdout
    txt += "\n\nSTDERLOCAL_PATH" + cp.stderr + "\n"
    (LOGD/logname).write_text(txt, encoding="utf-8-sig")
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
        s = s.split(";",1)[0]
    return s.rstrip(".").lower()

def pvd_root(f):
    f.seek(16*SECTOR)
    p = f.read(SECTOR)
    if len(p) != SECTOR or p[0] != 1 or p[1:6] != b"CD001":
        raise RuntimeError("ISO9660 PVD missing")
    r = p[156:]
    r = r[:r[0]]
    return struct.unpack_from("<I",r,2)[0], struct.unpack_from("<I",r,10)[0]

def read_dir(f, ext, size):
    base = ext*SECTOR
    f.seek(base)
    data = f.read(size)
    out = []
    pos = 0

    while pos < len(data):
        rl = data[pos]
        if rl == 0:
            pos = ((pos//SECTOR)+1)*SECTOR
            continue

        rec = data[pos:pos+rl]
        ex = struct.unpack_from("<I",rec,2)[0]
        sz = struct.unpack_from("<I",rec,10)[0]
        flags = rec[25]
        nl = rec[32]
        raw = rec[33:33+nl]
        name = "." if raw == b"\0" else ".." if raw == b"\1" else iso_norm(raw)

        out.append(dict(
            name=name,
            extent=ex,
            size=sz,
            is_dir=bool(flags&2),
            record_offset=base+pos,
        ))
        pos += rl

    return out

def find_entry(f, parts):
    ext,sz = pvd_root(f)
    e = None
    for i,p in enumerate(parts):
        matches = [x for x in read_dir(f,ext,sz) if x["name"] == p.lower()]
        if not matches:
            raise FileNotFoundError("/"+"/".join(parts[:i+1]))
        e = matches[0]
        if i < len(parts)-1:
            ext,sz = e["extent"],e["size"]
    return e

def patch_size(f, off, new_size):
    f.seek(off+10)
    f.write(struct.pack("<I",new_size))
    f.write(struct.pack(">I",new_size))

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
        b = f.read(min(remain,1024*1024))
        if not b:
            break
        h.update(b)
        remain -= len(b)
    if remain:
        raise RuntimeError("EOF while hashing ISO region")
    return h.hexdigest()

def patch_iso_file(iso_path, name, replacement, allocation):
    parts = ["PSP_GAME","USRDIR","movie",name+".pmf"]
    data = Path(replacement).read_bytes()

    if len(data) > allocation:
        raise RuntimeError(
            f"{name}: replacement {len(data)} exceeds allocation {allocation}"
        )

    with Path(iso_path).open("r+b") as f:
        e = find_entry(f, parts)
        f.seek(e["extent"]*SECTOR)
        f.write(data)

        remain = allocation-len(data)
        zero = b"\0"*min(32768,max(1,remain))
        while remain > 0:
            n = min(remain,len(zero))
            f.write(zero[:n])
            remain -= n

        patch_size(f,e["record_offset"],len(data))

def verify_iso_file(iso_path, name, replacement, expected_extent):
    parts = ["PSP_GAME","USRDIR","movie",name+".pmf"]
    expected_sha = sha_file(replacement)

    with Path(iso_path).open("rb") as f:
        e = find_entry(f,parts)
        actual_sha = sha_region(f,e["extent"]*SECTOR,e["size"])

    return (
        e["extent"] == expected_extent
        and e["size"] == Path(replacement).stat().st_size
        and actual_sha == expected_sha
    )

def ffprobe_duration(path, tag):
    cp = run([
        FFPROBE, "-v","error",
        "-show_entries","format=duration",
        "-of","default=nw=1:nk=1",
        path
    ],tag,120)
    if cp.returncode != 0:
        return None
    try:
        return float(cp.stdout.strip())
    except Exception:
        return None

def build_video_trim(source_pmf, duration, out_path, tag):
    # Re-encode current translated visual only; audio is rebuilt separately
    # from original KR ATRAC frames.
    cp = run([
        FFMPEG, "-y", "-v","warning",
        "-i", source_pmf,
        "-t", f"{duration:.9f}",
        "-an",
        "-vf",
        "setpts=PTS-STARTPTS,"
        "scale=480:272:flags=lanczos,"
        "fps=30000/1001,"
        "setsar=1,"
        "format=yuv420p",
        "-c:v","ffv1","-level","3",
        "-pix_fmt","yuv420p",
        "-fps_mode","cfr",
        out_path
    ], tag, 3600)

    if cp.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"{source_pmf.name}: trimmed lossless video failed")

def make_pts_subset(core, kr_parsed, generated_mps):
    # MpsMuxer packetizes the truncated ATRAC stream. Its PES count is known
    # only after muxing. Use the same number of leading KR PES timestamps.
    data = bytearray(Path(generated_mps).read_bytes())
    gen = core.parse_ps_stream(data,0)
    count = len(gen["audio"])

    if count > len(kr_parsed["audio"]):
        raise RuntimeError(
            f"Generated truncated audio PES count {count} exceeds KR {len(kr_parsed['audio'])}"
        )

    sub = dict(kr_parsed)
    sub["audio"] = kr_parsed["audio"][:count]
    return sub

def build_one(core, cfg, base_iso):
    name = cfg["name"]
    cutoff = float(cfg["cutoff"])
    translated = cfg["translated"]
    kr_pmf = KR_MOV / f"{name}.pmf"

    if not translated.exists():
        raise RuntimeError(f"{name}: translated PMF missing: {translated}")
    if not kr_pmf.exists():
        raise RuntimeError(f"{name}: KR PMF missing: {kr_pmf}")

    krp = core.parse_pmf(kr_pmf)
    kra = core.recover_audio(krp)
    if kra["bad_headers"]:
        raise RuntimeError(f"{name}: KR ATRAC header validation failed")

    frame_duration = core.SAMPLES_PER_FRAME / core.SAMPLE_RATE

    # Floor to complete ATRAC frame so NOTHING exists after user cutoff.
    requested_frames = int(math.floor(cutoff / frame_duration + 1e-12))
    keep_frames = min(requested_frames, kra["frame_count"])
    if keep_frames <= 0:
        raise RuntimeError(f"{name}: cutoff leaves no audio frames")

    actual_duration = keep_frames * frame_duration
    removed_sec = max(0.0, cutoff-actual_duration)

    expected_frames = kra["frames"][:keep_frames*core.ATRAC_FRAME]
    expected_logical = bytearray()
    for i in range(keep_frames):
        fr = expected_frames[i*core.ATRAC_FRAME:(i+1)*core.ATRAC_FRAME]
        expected_logical += core.AU_HEADER + fr
    expected_logical = bytes(expected_logical)

    parts = ["PSP_GAME","USRDIR","movie",name+".pmf"]
    with Path(base_iso).open("rb") as f:
        e = find_entry(f,parts)
        allocation = math.ceil(e["size"]/SECTOR)*SECTOR
        extent = e["extent"]

    print(
        f"\n[{name}] requested cutoff={cutoff:.3f}s "
        f"ATRAC-safe end={actual_duration:.6f}s "
        f"({keep_frames} frames; {removed_sec*1000:.1f}ms before requested)",
        flush=True
    )

    lossless = WORK / f"{name}_trimmed_lossless.avi"
    build_video_trim(
        translated,
        actual_duration,
        lossless,
        f"10_{name}_video_trim.log"
    )

    composer = core.find_exe("oMPSComposer.exe")
    mps2pmf = core.find_exe("Mps2Pmf.exe")
    helper = ROOT / "invoke_naruto_mov06e_raw_mux.ps1"

    if composer is None or mps2pmf is None or not helper.exists():
        raise RuntimeError(f"{name}: PMF tools/helper missing")

    riff = WORK / f"{name}_truncated.at3"
    core.build_riff(expected_frames, riff)

    cdir = composer.parent
    local_ffmpeg = cdir/"ffmpeg.exe"
    temp_ffmpeg = False
    if not local_ffmpeg.exists():
        shutil.copy2(FFMPEG,local_ffmpeg)
        temp_ffmpeg = True

    chosen = None

    try:
        for idx,(avg,maxbr) in enumerate(BITRATE_ATTEMPTS,1):
            tag = f"{name}_try{idx}_{avg}"
            print(f"  encode {idx}: avg={avg} max={maxbr}",flush=True)

            vmps = WORK/f"{tag}_video.mps"
            cp = run([
                composer,lossless,"-",vmps,
                "--avg-bitrate",str(avg),
                "--max-bitrate",str(maxbr),
                "--encode-mode","2pass",
                "--idr-duration","2000",
                "--m-frames","1"
            ],f"11_{tag}_video.log",3600,cwd=cdir)
            if cp.returncode != 0 or not vmps.exists():
                continue

            whole = int(math.ceil(actual_duration))
            mins,secs = divmod(whole,60)

            vpmf = WORK/f"{tag}_video.pmf"
            cp = run([
                mps2pmf,
                "-i",vmps,
                "-o",vpmf,
                "-m",str(mins),
                "-s",str(secs)
            ],f"12_{tag}_video_pmf.log",600,cwd=mps2pmf.parent)
            if cp.returncode != 0 or not vpmf.exists():
                continue

            h264 = WORK/f"{tag}.264"
            if not core.extract_h264(vpmf,h264,f"13_{tag}_h264.log"):
                continue
            video_sha = core.sha_file(h264)

            fmps = WORK/f"{tag}_final.mps"
            cp = run([
                "powershell.exe","-NoProfile","-ExecutionPolicy","Bypass",
                "-File",helper,
                "-Composer",composer,
                "-H264",h264,
                "-AtracRiff",riff,
                "-OutputMps",fmps
            ],f"14_{tag}_mux.log",1800)
            if cp.returncode != 0 or not fmps.exists():
                continue

            # Restore leading KR PTS/PES timestamp sequence for the shortened audio.
            kr_subset = make_pts_subset(core,krp,fmps)
            core.patch_mps_audio_pts_exact(fmps,kr_subset)

            final_pmf = WORK/f"{tag}_final.pmf"
            cp = run([
                mps2pmf,
                "-i",fmps,
                "-o",final_pmf,
                "-m",str(mins),
                "-s",str(secs)
            ],f"15_{tag}_final_pmf.log",600,cwd=mps2pmf.parent)
            if cp.returncode != 0 or not final_pmf.exists():
                continue

            fp = core.parse_pmf(final_pmf)
            fa = core.recover_audio(fp)

            final_h264 = WORK/f"{tag}_final.264"
            if not core.extract_h264(final_pmf,final_h264,f"16_{tag}_final_h264.log"):
                continue

            video_ok = core.sha_file(final_h264) == video_sha
            logical_ok = fa["logical"] == expected_logical
            frames_ok = fa["frames"] == expected_frames

            generated_pts = [x["pts"] for x in fp["audio"]]
            expected_pts = [x["pts"] for x in krp["audio"][:len(fp["audio"])]]
            pts_ok = generated_pts == expected_pts

            # Generated PES count must be no greater than original and its PTS
            # must exactly match the corresponding leading KR sequence.
            pes_ok = len(fp["audio"]) == len(expected_pts)

            oma = WORK/f"{tag}.oma"
            core.build_oma(fa["frames"],oma)
            cp = run([
                FFMPEG,"-v","warning",
                "-f","oma","-i",oma,
                "-f","null","-"
            ],f"17_{tag}_atrac_decode.log",1200)
            decode_ok = cp.returncode == 0

            info = core.probe(final_pmf,f"18_{tag}_probe.log")
            vs = core.get_video(info)
            format_ok = bool(
                vs
                and vs.get("codec_name") == "h264"
                and int(vs.get("width",0)) == 480
                and int(vs.get("height",0)) == 272
            )

            pmf_duration = ffprobe_duration(final_pmf,f"19_{tag}_duration.log")
            duration_ok = (
                pmf_duration is not None
                and pmf_duration <= cutoff + 0.080
            )

            strict = all([
                video_ok,logical_ok,frames_ok,pts_ok,pes_ok,
                decode_ok,format_ok,duration_ok
            ])
            fits = final_pmf.stat().st_size <= allocation

            print(
                f"    bytes={final_pmf.stat().st_size} "
                f"strict={strict} fit={fits} duration={pmf_duration}",
                flush=True
            )

            if strict and fits:
                dst = OUT/f"{name}.pmf"
                shutil.copy2(final_pmf,dst)

                chosen = dict(
                    name=name,
                    cutoff=cutoff,
                    atrac_safe_end=actual_duration,
                    atrac_frames=keep_frames,
                    pmf_duration=pmf_duration,
                    avg=avg,
                    maxbr=maxbr,
                    size=dst.stat().st_size,
                    allocation=allocation,
                    extent=extent,
                    translated_source=translated,
                    logical_ok=logical_ok,
                    frames_ok=frames_ok,
                    pts_ok=pts_ok,
                    pes_ok=pes_ok,
                    decode_ok=decode_ok,
                    format_ok=format_ok,
                    duration_ok=duration_ok,
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
        raise RuntimeError(f"{name}: no valid trimmed PMF could be built")

    # Frames around new ending for quick visual check.
    for label,t in [
        ("before_end",max(0,actual_duration-0.30)),
        ("near_end",max(0,actual_duration-0.08)),
    ]:
        out = OUT/f"review_{name}_{label}_{t:08.3f}.jpg"
        run([
            FFMPEG,"-y","-v","error",
            "-ss",f"{t:.3f}",
            "-i",chosen["path"],
            "-frames:v","1",
            "-q:v","2",out
        ],f"20_review_{name}_{label}.log",180)

    return chosen

def main():
    core = load_core()

    for p in (CORE_PATH,FFMPEG,FFPROBE,BASE_ISO):
        if not p.exists():
            raise RuntimeError(f"Missing input/tool: {p}")

    failure = STAGE/"FAILURE.txt"
    if failure.exists():
        failure.unlink()

    print("="*80,flush=True)
    print(" Naruto PSP MOV06E - user-requested PMF tail trims",flush=True)
    print("="*80,flush=True)
    print(" da101 <= 32.265 sec",flush=True)
    print(" da201 <= 48.786 sec",flush=True)
    print(" dk101 <= 1:55.602 (115.602 sec)",flush=True)

    # Base metadata before patch.
    base_meta = {}
    with BASE_ISO.open("rb") as f:
        for cfg in TARGETS:
            e = find_entry(
                f,["PSP_GAME","USRDIR","movie",cfg["name"]+".pmf"]
            )
            base_meta[cfg["name"]] = dict(
                extent=e["extent"],
                size=e["size"],
                allocation=math.ceil(e["size"]/SECTOR)*SECTOR
            )

    results = []
    for cfg in TARGETS:
        results.append(build_one(core,cfg,BASE_ISO))

    # Patch only requested PMFs into existing MOV06D integrated ISO.
    if FINAL_ISO.exists():
        FINAL_ISO.unlink()
    shutil.copyfile(BASE_ISO,FINAL_ISO)

    iso_rows = []
    for r in results:
        patch_iso_file(
            FINAL_ISO,
            r["name"],
            r["path"],
            base_meta[r["name"]]["allocation"]
        )
        ok = verify_iso_file(
            FINAL_ISO,
            r["name"],
            r["path"],
            base_meta[r["name"]]["extent"]
        )
        if not ok:
            raise RuntimeError(f"{r['name']}: ISO verification failed after trim patch")
        iso_rows.append(dict(
            name=r["name"],
            extent=base_meta[r["name"]]["extent"],
            final_size=r["size"],
            sha256=sha_file(r["path"]),
            status="PASS"
        ))

    # Keep easy-to-view translated PMF folder synchronized.
    FINAL_SET_DIR.mkdir(parents=True,exist_ok=True)
    for r in results:
        shutil.copy2(r["path"], FINAL_SET_DIR/(r["name"]+".pmf"))

    result_rows = []
    for r in results:
        result_rows.append(dict(
            name=r["name"],
            requested_cutoff_sec=f"{r['cutoff']:.6f}",
            atrac_safe_end_sec=f"{r['atrac_safe_end']:.6f}",
            actual_probe_duration_sec=f"{r['pmf_duration']:.6f}" if r["pmf_duration"] is not None else "",
            kept_atrac_frames=r["atrac_frames"],
            timeline_policy="TRUNCATED_AT_OR_BEFORE_USER_CUTOFF",
            encoded_avg_kbps=r["avg"],
            encoded_max_kbps=r["maxbr"],
            final_pmf_bytes=r["size"],
            allocation_bytes=r["allocation"],
            logical_audio_exact_prefix="YES" if r["logical_ok"] else "NO",
            atrac_frames_exact_prefix="YES" if r["frames_ok"] else "NO",
            pts_exact_prefix="YES" if r["pts_ok"] else "NO",
            pes_validation="PASS" if r["pes_ok"] else "FAIL",
            atrac_decode="PASS" if r["decode_ok"] else "FAIL",
            video_format="PASS" if r["format_ok"] else "FAIL",
            duration_not_past_cutoff="PASS" if r["duration_ok"] else "FAIL",
            status="PASS"
        ))

    write_tsv(STAGE/"mov06e_result.tsv",result_rows)
    write_tsv(STAGE/"iso_verification.tsv",iso_rows)

    summary = [
        "Naruto PSP MOV06E - user-requested final tail trims",
        "="*80,
        "",
        "RESULT=PASS",
        "",
        "Requested cutoffs:",
        "  da101 = 32.265 sec",
        "  da201 = 48.786 sec",
        "  dk101 = 1:55.602 = 115.602 sec",
        "",
        "Policy:",
        "  End at the last complete ATRAC3+ frame at or before the requested cutoff.",
        "  Therefore no video/audio survives past the requested cutoff.",
        "  Exact leading KR Japanese ATRAC3+ frames and matching leading KR PTS are retained.",
        "",
    ]

    for r in results:
        summary += [
            f"{r['name']}:",
            f"  requested={r['cutoff']:.3f} sec",
            f"  ATRAC-safe end={r['atrac_safe_end']:.6f} sec",
            f"  probed PMF duration={r['pmf_duration']:.6f} sec",
            f"  kept ATRAC frames={r['atrac_frames']}",
            f"  bitrate={r['avg']}/{r['maxbr']} kbps",
            f"  PMF={r['size']} bytes",
            "  validation=PASS",
            "",
        ]

    summary += [
        "Only da101 / da201 / dk101 were replaced.",
        "All other MOV06D translated PMFs are unchanged.",
        "",
        f"Final ISO={FINAL_ISO}",
        f"Updated view folder={FINAL_SET_DIR}",
        "",
        "Previous dk101 2-3 frame tolerated-tail note is superseded by MOV06E.",
    ]

    (STAGE/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("",flush=True)
    print("\n".join(summary),flush=True)
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb = traceback.format_exc()
        (STAGE/"FAILURE.txt").write_text(tb,encoding="utf-8-sig")
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
