#!/usr/bin/env python3
# Naruto PSP MOV01 FIX4 - Stage37 subtitle-anchor recovery for unresolved DM PMFs
#
# Purpose:
# - Keep FIX3 HIGH/MEDIUM mappings.
# - Re-search FIX3 LOW mappings (currently dm001~dm010) only at timestamps where
#   Stage37/37B had already detected completed Korean dialogue/subtitle frames.
# - This drastically shrinks the candidate search space and prevents unrelated
#   anime/gameplay scenes elsewhere in the ~3 hour source from winning.
#
# Timestamp discovery order:
#   1) CSV/TSV manifests under analysis\stage37 and analysis\stage37b
#      with timestamp/time/timecode/seconds-style columns.
#   2) Exact-count completed image folders (1498 / 588) and timestamp parsing
#      from filenames such as 000001_00h00m12.340.png.
#   3) Stage38A CSV/TSV manifests containing video_part + timestamp as fallback.
#
# Existing FIX2/FIX3 fingerprint caches are reused.  No model is required.

from __future__ import annotations
import csv, json, math, os, re, shutil, statistics, subprocess, sys, traceback
from pathlib import Path

ROOT = Path(r"PROJECT_ROOT")
ANALYSIS = ROOT / "analysis"
STAGE = ANALYSIS / "mov" / "mov01_frame_matching"
CACHE = STAGE / "fingerprint_cache"
KR_MOVIE = ROOT / "kr_extracted" / "PSP_GAME" / "USRDIR" / "movie"
FIX3_MAP = STAGE / "pmf_source_mapping_fix3.csv"

SOURCE = {
    "part1": ANALYSIS / "stage37" / "video" / "source_video.mp4",
    "part2": ANALYSIS / "stage37" / "video" / "part2.mp4",
}
STAGE_ROOTS = {
    "part1": ANALYSIS / "stage37",
    "part2": ANALYSIS / "stage37b",
}
EXPECTED_IMAGES = {"part1": 1498, "part2": 588}

FPS = 2.0
FRAME_W = 33
FRAME_H = 18
FRAME_BYTES = FRAME_W * FRAME_H
TOTAL_BITS = (FRAME_W-1)*FRAME_H + FRAME_W*(FRAME_H-1) + FRAME_W*FRAME_H
VF = (
    "crop=trunc(iw*0.82/2)*2:trunc(ih*0.66/2)*2:0:0,"
    f"fps={FPS:g},scale={FRAME_W}:{FRAME_H}:flags=area,format=gray"
)

TS_COLS = [
    "timestamp", "timecode", "timestamp_sec", "time_sec", "source_time",
    "source_timestamp", "video_time", "seconds", "second", "secs", "sec", "time", "ts"
]
PART_COLS = ["video_part", "part", "source_part"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def log(*a):
    print(*a, flush=True)


def find_tool(name: str) -> str | None:
    x = shutil.which(name)
    if x:
        return x
    for base in [ROOT/"tools", ROOT/"ffmpeg", Path(r"LOCAL_PATH"), Path(r"LOCAL_PATH")]:
        if not base.exists():
            continue
        for en in ([name+".exe", name] if os.name == "nt" else [name]):
            hits = list(base.rglob(en))
            if hits:
                return str(hits[0])
    return None


def probe_duration(ffprobe: str, path: Path) -> float | None:
    p = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", timeout=30
    )
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip().splitlines()[0])
    except Exception:
        return None


def parse_time(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # raw numeric seconds
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", s):
            return float(s)
    except Exception:
        pass

    # HH:MM:SS.mmm / MM:SS.mmm
    m = re.fullmatch(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", s)
    if m:
        h = int(m.group(1) or 0)
        mi = int(m.group(2))
        sec = float(m.group(3))
        return h*3600 + mi*60 + sec

    # 00h00m12.340 or 00h00m12s340
    m = re.search(r"(?i)(\d{1,3})h(\d{1,2})m(\d{1,2}(?:[._]\d+)?)(?:s)?", s)
    if m:
        sec = float(m.group(3).replace("_", "."))
        return int(m.group(1))*3600 + int(m.group(2))*60 + sec

    return None


def timestamp_from_filename(name: str) -> float | None:
    stem = Path(name).stem
    # Preferred Stage37-style: 000001_00h00m12.340
    m = re.search(r"(?i)(\d{1,3})h(\d{1,2})m(\d{1,2}(?:\.\d+)?)", stem)
    if m:
        return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

    # HH-MM-SS.mmm / HH_MM_SS.mmm after any prefix
    matches = list(re.finditer(r"(?<!\d)(\d{1,3})[-_](\d{2})[-_](\d{2}(?:\.\d+)?)(?!\d)", stem))
    if matches:
        m = matches[-1]
        return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

    # explicit t123.456 / ts_123.456 / time_123.456
    m = re.search(r"(?i)(?:^|[_-])(?:t|ts|time)[_-]?(\d+(?:\.\d+)?)(?:$|[_-])", stem)
    if m:
        return float(m.group(1))
    return None


def norm_part(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower().replace(" ", "")
    if s in ("1", "p1", "part1", "part_1"):
        return "part1"
    if s in ("2", "p2", "part2", "part_2"):
        return "part2"
    if "part1" in s:
        return "part1"
    if "part2" in s:
        return "part2"
    return None


def parse_delimited_manifest(path: Path, default_part: str | None) -> list[tuple[str,float,str]]:
    rows = []
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw.strip():
            return []
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
        reader = csv.DictReader(raw.splitlines(), delimiter=delim)
        if not reader.fieldnames:
            return []
        fields = {str(x).strip().lower(): x for x in reader.fieldnames if x is not None}
        ts_field = next((fields[x] for x in TS_COLS if x in fields), None)
        if ts_field is None:
            return []
        part_field = next((fields[x] for x in PART_COLS if x in fields), None)
        for r in reader:
            t = parse_time(r.get(ts_field))
            if t is None:
                continue
            part = norm_part(r.get(part_field)) if part_field else default_part
            if part not in ("part1", "part2"):
                continue
            rows.append((part, t, str(path)))
    except Exception:
        return []
    return rows


def exact_count_image_dir(root: Path, expected: int) -> tuple[Path | None, list[Path]]:
    by_dir: dict[Path,list[Path]] = {}
    if not root.exists():
        return None, []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            by_dir.setdefault(p.parent, []).append(p)
    exact = [(d, fs) for d,fs in by_dir.items() if len(fs) == expected]
    if not exact:
        return None, []
    def score(item):
        d,_ = item
        s = str(d).lower()
        val = 0
        if "completed" in s: val += 100
        if "complete" in s: val += 80
        if "final" in s: val += 50
        if "dialog" in s: val += 30
        if "candidate" in s: val -= 100
        if "sample" in s: val -= 80
        return (-val, str(d))
    exact.sort(key=score)
    return exact[0][0], sorted(exact[0][1], key=lambda p:p.name)


def discover_anchors() -> tuple[dict[str,list[float]], list[str]]:
    anchors = {"part1": [], "part2": []}
    notes = []

    # 1) Stage37 / Stage37B manifests.
    for part, root in STAGE_ROOTS.items():
        if not root.exists():
            notes.append(f"{part}: missing root {root}")
            continue
        manifest_hits = []
        for ext in ("*.tsv", "*.csv"):
            for p in root.rglob(ext):
                rr = parse_delimited_manifest(p, part)
                if rr:
                    manifest_hits.extend(rr)
                    notes.append(f"{part}: manifest {p} -> {len(rr)} timestamp row(s)")
        anchors[part].extend(t for prt,t,_ in manifest_hits if prt == part)

        # 2) Exact-count completed image directory and filename timestamps.
        d, imgs = exact_count_image_dir(root, EXPECTED_IMAGES[part])
        if d:
            parsed = [timestamp_from_filename(p.name) for p in imgs]
            parsed = [x for x in parsed if x is not None]
            notes.append(f"{part}: exact-count image dir {d} -> {len(imgs)} files, {len(parsed)} filename timestamps")
            anchors[part].extend(parsed)
        else:
            notes.append(f"{part}: no exact {EXPECTED_IMAGES[part]}-image directory found")

    # 3) Stage38A manifests as fallback/supplement, if they contain timestamp + part.
    stage38a = ANALYSIS / "stage38a"
    if stage38a.exists():
        for ext in ("*.tsv", "*.csv"):
            for p in stage38a.rglob(ext):
                rr = parse_delimited_manifest(p, None)
                if not rr:
                    continue
                c1 = sum(1 for x in rr if x[0] == "part1")
                c2 = sum(1 for x in rr if x[0] == "part2")
                if c1 or c2:
                    notes.append(f"stage38a fallback manifest {p} -> part1={c1} part2={c2}")
                    for prt,t,_ in rr:
                        anchors[prt].append(t)

    # Deduplicate, validate against actual source durations.
    ffprobe = find_tool("ffprobe")
    for part in ("part1","part2"):
        dur = probe_duration(ffprobe, SOURCE[part]) if ffprobe and SOURCE[part].exists() else None
        xs = sorted(set(round(float(x), 3) for x in anchors[part] if x is not None and x >= 0))
        if dur is not None:
            xs = [x for x in xs if x <= dur + 0.5]
        anchors[part] = xs
        notes.append(f"{part}: final unique anchors={len(xs)}")
    return anchors, notes


def load_cache(tag: str, source_path: Path) -> list[tuple[int,int,int,float]] | None:
    if not CACHE.exists():
        return None
    pattern = f"fix2_{tag}_{re.sub(r'[^A-Za-z0-9_.-]+','_',source_path.stem)}_*.json"
    hits = sorted(CACHE.glob(pattern), key=lambda p:p.stat().st_mtime, reverse=True)
    for cache in hits:
        try:
            obj = json.loads(cache.read_text(encoding="utf-8"))
            if obj.get("fps") != FPS or obj.get("w") != FRAME_W or obj.get("h") != FRAME_H:
                continue
            return [(int(x["h"],16),int(x["v"],16),int(x["a"],16),float(x["mad"])) for x in obj["frames"]]
        except Exception:
            continue
    return None


def frame_signature(frame: bytes) -> tuple[int,int,int,float]:
    hh=0; bit=0
    for y in range(FRAME_H):
        o=y*FRAME_W
        for x in range(FRAME_W-1):
            if frame[o+x] > frame[o+x+1]: hh |= 1<<bit
            bit += 1
    vh=0; bit=0
    for y in range(FRAME_H-1):
        a=y*FRAME_W; b=(y+1)*FRAME_W
        for x in range(FRAME_W):
            if frame[a+x] > frame[b+x]: vh |= 1<<bit
            bit += 1
    mean=sum(frame)/FRAME_BYTES
    ah=0
    for i,v in enumerate(frame):
        if v > mean: ah |= 1<<i
    mad=sum(abs(v-mean) for v in frame)/FRAME_BYTES
    return hh,vh,ah,mad


def fingerprint(ffmpeg: str, path: Path, tag: str) -> list[tuple[int,int,int,float]]:
    cached = load_cache(tag, path)
    if cached is not None:
        return cached
    CACHE.mkdir(parents=True, exist_ok=True)
    cmd=[ffmpeg,"-hide_banner","-loglevel","error","-i",str(path),"-an","-sn","-dn","-vf",VF,"-f","rawvideo","-pix_fmt","gray","-"]
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=2400)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8","replace")[-2000:])
    raw=p.stdout
    n=len(raw)//FRAME_BYTES
    frames=[frame_signature(raw[i*FRAME_BYTES:(i+1)*FRAME_BYTES]) for i in range(n)]
    # Write same FIX2-compatible cache format for future reuse.
    sig=f"{path.stat().st_size}_{int(path.stat().st_mtime)}"
    cache=CACHE/f"fix2_{tag}_{re.sub(r'[^A-Za-z0-9_.-]+','_',path.stem)}_{sig}.json"
    cache.write_text(json.dumps({"source":str(path),"fps":FPS,"w":FRAME_W,"h":FRAME_H,"vf":VF,"frames":[{"h":f"{x[0]:x}","v":f"{x[1]:x}","a":f"{x[2]:x}","mad":round(x[3],5)} for x in frames]}),encoding="utf-8")
    return frames


def dist(a,b) -> float:
    return ((a[0]^b[0]).bit_count()+(a[1]^b[1]).bit_count()+(a[2]^b[2]).bit_count())/TOTAL_BITS


def sample_indices(frames) -> list[int]:
    if not frames: return []
    pad=max(2,round(2*FPS))
    xs=list(range(min(pad,len(frames)-1),max(min(pad,len(frames)-1)+1,len(frames)-pad),max(1,round(FPS))))
    good=[i for i in xs if frames[i][3] >= 8.0]
    return good if len(good)>=5 else xs


def top_anchor_hits(sig, anchor_frames, k=4):
    best=[]
    for rec in anchor_frames:
        d=dist(sig,rec[2])
        if len(best)<k:
            best.append((d,rec)); best.sort(key=lambda x:x[0])
        elif d<best[-1][0]:
            best[-1]=(d,rec); best.sort(key=lambda x:x[0])
    return best


def evaluate_offset(pmf_frames, source_frames, offset: float) -> dict:
    idxs=sample_indices(pmf_frames)
    if len(idxs)>24:
        step=(len(idxs)-1)/(24-1)
        idxs=sorted(set(idxs[round(i*step)] for i in range(24)))
    off=round(offset*FPS)
    radius=round(2.0*FPS)
    vals=[]; drifts=[]
    for pi in idxs:
        expected=off+pi
        lo=max(0,expected-radius); hi=min(len(source_frames)-1,expected+radius)
        if lo>hi: continue
        bd=9.0; bi=None
        for si in range(lo,hi+1):
            d=dist(pmf_frames[pi],source_frames[si])
            if d<bd: bd=d; bi=si
        if bi is not None:
            vals.append(bd); drifts.append((bi-expected)/FPS)
    if not vals:
        return {"score":9.0,"coverage":0.0,"median":9.0,"drift":0.0,"n":0}
    s=sorted(vals); keep=max(3,math.ceil(len(s)*0.80)); kept=s[:keep]
    return {"score":sum(kept)/len(kept),"coverage":sum(x<=0.28 for x in vals)/len(vals),"median":statistics.median(vals),"drift":statistics.median(drifts),"n":len(vals)}


def recover_one(pmf_frames, anchors_by_part, source_fp):
    pidx=sample_indices(pmf_frames)
    # At most 80 one-second PMF samples keeps matching quick for long movies.
    if len(pidx)>80:
        step=(len(pidx)-1)/(80-1)
        pidx=sorted(set(pidx[round(i*step)] for i in range(80)))

    clusters={}
    per_part_best={"part1":[],"part2":[]}
    for part in ("part1","part2"):
        af=anchors_by_part[part]
        for pi in pidx:
            hits=top_anchor_hits(pmf_frames[pi],af,k=4)
            for d,rec in hits:
                if d>0.36:
                    continue
                atime=rec[0]
                local=pi/FPS
                off=atime-local
                if off < -2:
                    continue
                b=round(off)
                key=(part,b)
                # A PMF sample can cast one vote per offset bin; keep its best distance.
                samplemap=clusters.setdefault(key,{})
                old=samplemap.get(pi)
                if old is None or d<old[0]:
                    samplemap[pi]=(d,off,atime)

    candidates=[]
    for (part,b),samplemap in clusters.items():
        vals=list(samplemap.values())
        if not vals: continue
        votes=len(vals)
        meddist=statistics.median(v[0] for v in vals)
        off=statistics.median(v[1] for v in vals)
        ev=evaluate_offset(pmf_frames,source_fp[part],off)
        refined=off+ev["drift"]
        ev2=evaluate_offset(pmf_frames,source_fp[part],refined)
        if ev2["score"]<=ev["score"]:
            off=refined; ev=ev2
        candidates.append({"part":part,"offset":off,"anchor_votes":votes,"anchor_median":meddist,**ev})

    if not candidates:
        return None,[]

    candidates.sort(key=lambda x:(-x["anchor_votes"],x["anchor_median"],x["score"],-x["coverage"]))
    # Among candidates within two votes of the maximum, prefer sequence quality.
    mv=candidates[0]["anchor_votes"]
    plausible=[x for x in candidates if x["anchor_votes"]>=max(1,mv-2)]
    plausible.sort(key=lambda x:(x["score"],x["anchor_median"],-x["coverage"],-x["anchor_votes"]))
    best=plausible[0]

    if best["anchor_votes"]>=5 and best["anchor_median"]<=0.26 and best["score"]<=0.29 and best["coverage"]>=0.45:
        conf="RECOVERED_HIGH"
    elif best["anchor_votes"]>=3 and best["anchor_median"]<=0.30 and best["score"]<=0.34 and best["coverage"]>=0.25:
        conf="RECOVERED_MEDIUM"
    else:
        conf="UNRESOLVED"
    best=dict(best); best["confidence"]=conf
    return best,candidates[:20]


def extract_frame(ffmpeg: str, src: Path, t: float, out: Path):
    out.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([ffmpeg,"-y","-hide_banner","-loglevel","error","-ss",f"{max(0,t):.3f}","-i",str(src),"-frames:v","1","-vf","scale=480:-2:flags=area","-q:v","5",str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)


def write_table(path: Path, rows: list[dict], delim: str):
    if not rows:
        return
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()),delimiter=delim)
        w.writeheader(); w.writerows(rows)


def main():
    STAGE.mkdir(parents=True,exist_ok=True)
    ffmpeg=find_tool("ffmpeg")
    ffprobe=find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(f"ffmpeg/ffprobe required: {ffmpeg} / {ffprobe}")
    if not FIX3_MAP.exists():
        raise RuntimeError(f"FIX3 mapping missing: {FIX3_MAP}")

    log("========================================================================")
    log(" Naruto PSP MOV01 FIX4 - Stage37 dialogue-anchor recovery")
    log("========================================================================")

    anchors,notes=discover_anchors()
    log("\n[1/6] Discover Stage37 timestamp anchors")
    for n in notes: log("  "+n)
    diag=STAGE/"anchor_discovery_FIX4.txt"
    diag.write_text("\n".join(notes)+"\n",encoding="utf-8-sig")

    # Need enough anchors to make this strategy meaningful.
    if len(anchors["part1"])<30 or len(anchors["part2"])<20:
        # Preserve some exact-count filenames to diagnose the format on upload.
        sample=[]
        for part,root in STAGE_ROOTS.items():
            d,imgs=exact_count_image_dir(root,EXPECTED_IMAGES[part])
            sample.append(f"[{part}] dir={d}")
            for p in imgs[:25]: sample.append("  "+p.name)
        (STAGE/"anchor_filename_samples_FIX4.txt").write_text("\n".join(sample)+"\n",encoding="utf-8-sig")
        raise RuntimeError(
            f"Too few timestamp anchors: part1={len(anchors['part1'])}, part2={len(anchors['part2'])}. "
            "Uploaded diagnostics will show the actual Stage37 filename/manifest format."
        )

    log("\n[2/6] Load/reuse source fingerprints")
    source_fp={}
    anchor_frames={}
    for part in ("part1","part2"):
        if not SOURCE[part].exists():
            raise RuntimeError(f"Source missing: {SOURCE[part]}")
        fp=fingerprint(ffmpeg,SOURCE[part],f"src_{part}")
        source_fp[part]=fp
        af=[]
        for t in anchors[part]:
            i=round(t*FPS)
            if 0<=i<len(fp): af.append((t,i,fp[i]))
        # de-duplicate same 2fps source index
        uniq={x[1]:x for x in af}
        af=sorted(uniq.values(),key=lambda x:x[0])
        anchor_frames[part]=af
        log(f"  {part}: source_frames={len(fp)} anchor_frames={len(af)}")

    with FIX3_MAP.open("r",encoding="utf-8-sig",newline="") as f:
        fix3=list(csv.DictReader(f))
    unresolved=[r for r in fix3 if r.get("confidence")=="LOW"]
    log(f"\n[3/6] Re-search FIX3 LOW mappings only: {len(unresolved)} PMF(s)")

    recovery=[]; canddump=[]
    for i,r in enumerate(unresolved,1):
        name=r["filename"]
        pmf=KR_MOVIE/name
        log(f"\n[{i:02d}/{len(unresolved):02d}] {name}")
        pf=fingerprint(ffmpeg,pmf,f"pmf_{pmf.stem}")
        best,cands=recover_one(pf,anchor_frames,source_fp)
        if best is None:
            out={"filename":name,"anchor_status":"UNRESOLVED","source_part":"","source_start_fix4_sec":"","anchor_votes":0,"anchor_median":"","sequence_score":"","sequence_coverage":""}
            log("  => UNRESOLVED: no anchor cluster")
        else:
            out={
                "filename":name,"anchor_status":best["confidence"],"source_part":best["part"],
                "source_start_fix4_sec":round(best["offset"],3),"anchor_votes":best["anchor_votes"],
                "anchor_median":round(best["anchor_median"],6),"sequence_score":round(best["score"],6),
                "sequence_coverage":round(best["coverage"],4),"sequence_median":round(best["median"],6),
            }
            log(f"  => {best['confidence']} {best['part']} start={best['offset']:.3f}s votes={best['anchor_votes']} anchor={best['anchor_median']:.4f} seq={best['score']:.4f} cov={best['coverage']:.2f}")
        recovery.append(out)
        for rank,c in enumerate(cands,1):
            canddump.append({"filename":name,"rank":rank,"source_part":c["part"],"offset_sec":round(c["offset"],3),"anchor_votes":c["anchor_votes"],"anchor_median":round(c["anchor_median"],6),"sequence_score":round(c["score"],6),"sequence_coverage":round(c["coverage"],4)})

    write_table(STAGE/"dm_anchor_recovery_fix4.tsv",recovery,"\t")
    write_table(STAGE/"dm_anchor_candidates_fix4.tsv",canddump,"\t")

    log("\n[4/6] Merge with FIX3 mappings")
    recmap={r["filename"]:r for r in recovery}
    merged=[]
    recovered_count=0
    for r in fix3:
        m=dict(r)
        rr=recmap.get(r["filename"])
        if rr and rr["anchor_status"] in ("RECOVERED_HIGH","RECOVERED_MEDIUM"):
            m["source_part"]=rr["source_part"]
            m["source_start_fix4_sec"]=rr["source_start_fix4_sec"]
            try:
                dur=float(r["pmf_duration_sec"])
                m["source_end_fix4_sec"]=round(float(rr["source_start_fix4_sec"])+dur,3)
            except Exception:
                m["source_end_fix4_sec"]=""
            m["fix4_status"]=rr["anchor_status"]
            m["fix4_anchor_votes"]=rr["anchor_votes"]
            m["fix4_anchor_median"]=rr["anchor_median"]
            m["fix4_sequence_score"]=rr["sequence_score"]
            m["fix4_sequence_coverage"]=rr["sequence_coverage"]
            recovered_count+=1
        else:
            # FIX3 HIGH/MEDIUM remain valid candidates; FIX3 LOW remains unresolved.
            m["source_start_fix4_sec"]=r.get("source_start_fix3_sec","") if r.get("confidence") in ("HIGH","MEDIUM") else ""
            m["source_end_fix4_sec"]=r.get("source_end_fix3_sec","") if r.get("confidence") in ("HIGH","MEDIUM") else ""
            m["fix4_status"]=r.get("confidence") if r.get("confidence") in ("HIGH","MEDIUM") else "UNRESOLVED"
            m["fix4_anchor_votes"]=rr.get("anchor_votes","") if rr else ""
            m["fix4_anchor_median"]=rr.get("anchor_median","") if rr else ""
            m["fix4_sequence_score"]=rr.get("sequence_score","") if rr else ""
            m["fix4_sequence_coverage"]=rr.get("sequence_coverage","") if rr else ""
        merged.append(m)

    write_table(STAGE/"pmf_source_mapping_fix4.tsv",merged,"\t")
    write_table(STAGE/"pmf_source_mapping_fix4.csv",merged,",")

    log("\n[5/6] Verification images for DM anchor candidates")
    vdir=STAGE/"verification_fix4"; vdir.mkdir(parents=True,exist_ok=True)
    verify=[]
    for rr in recovery:
        if not rr.get("source_part") or rr.get("source_start_fix4_sec") in ("",None):
            continue
        old=next(x for x in fix3 if x["filename"]==rr["filename"])
        dur=float(old["pmf_duration_sec"])
        start=float(rr["source_start_fix4_sec"])
        pmf=KR_MOVIE/rr["filename"]; src=SOURCE[rr["source_part"]]
        for label,ratio in [("p10",.1),("p30",.3),("p50",.5),("p70",.7),("p90",.9)]:
            local=max(.25,min(dur-.25,dur*ratio))
            a=vdir/f"{pmf.stem}_{label}_pmf.jpg"; b=vdir/f"{pmf.stem}_{label}_{rr['source_part']}.jpg"
            extract_frame(ffmpeg,pmf,local,a); extract_frame(ffmpeg,src,start+local,b)
            verify.append({"filename":rr["filename"],"anchor_status":rr["anchor_status"],"point":label,"pmf_local_sec":round(local,3),"source_part":rr["source_part"],"source_sec":round(start+local,3),"pmf_image":a.name,"source_image":b.name})
    write_table(STAGE/"verification_fix4_manifest.tsv",verify,"\t")

    log("\n[6/6] Summary")
    status_counts={}
    for r in merged: status_counts[r["fix4_status"]]=status_counts.get(r["fix4_status"],0)+1
    unresolved_count=status_counts.get("UNRESOLVED",0)
    summary=[
        "Naruto PSP MOV01 FIX4 - Stage37 dialogue-anchor recovery",
        "="*76,"",*notes,"",
        f"FIX3 LOW searched={len(unresolved)}",
        f"Recovered LOW mappings={recovered_count}",
        f"Still unresolved={unresolved_count}",
        "Final status: "+", ".join(f"{k}={v}" for k,v in sorted(status_counts.items())),"",
        "MOV02 gate:",
        "- FIX3 HIGH/MEDIUM may enter fine alignment after visual verification.",
        "- FIX4 RECOVERED_HIGH/RECOVERED_MEDIUM may enter fine alignment after verification_fix4 review.",
        "- UNRESOLVED PMFs must not be subtitle-timed yet.",
    ]
    (STAGE/"SUMMARY_FIX4.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    log("\n".join(summary))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        STAGE.mkdir(parents=True,exist_ok=True)
        tb=traceback.format_exc()
        (STAGE/"FAILURE_FIX4.txt").write_text(tb,encoding="utf-8-sig")
        print("\nMOV01 FIX4 FAILED:",e,file=sys.stderr,flush=True)
        print(tb,file=sys.stderr,flush=True)
        raise SystemExit(1)
