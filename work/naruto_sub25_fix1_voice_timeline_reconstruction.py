#!/usr/bin/env python3
# Naruto PSP SUB25 - Game voice timeline reconstruction
#
# Read-only.
#
# Purpose:
# Reconstruct the actual played Japanese voice timeline for game MSG/MSG_FORCED rows.
# This is needed because one cleaned Korean SUB09 entry may correspond to multiple
# consecutive game MSG rows (e.g. SUB09 #29 = event000#011 + event000#012).
#
# Strategy:
# - Keep the 1368 SUB24 AUDIO_MONOTONIC_CORE rows as fixed time anchors.
# - Only re-search the remaining voiced game rows against the Japanese gameplay audio.
# - Predict each missing row's time by interpolation between neighboring core anchors.
# - Search its standalone AT3 in a local video-audio window.
# - Build three thresholded monotonic played-voice timelines between fixed core anchors.
# - Rows selected by all three thresholds are PLAYED_VOICE_CONSENSUS.
# - Group consensus voice starts by SUB09 observation intervals to expose
#   0G/1G/2G/3+G -> 1 subtitle relationships.
#
# This stage does NOT patch game data and does NOT declare the grouping semantic-final.

from __future__ import annotations
import argparse, csv, hashlib, json, math, os, shutil, subprocess, sys, tempfile, time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

EXPECTED_CORE_SHA="571526e72f4c605aa526d173539cc1ba381498e8c4005f5d8521baff7b073367"
EXPECTED_TOP5_SHA="7be8e92a0c6427a93cda17fd4007eeaa7a934695044c2ee6a3cdbfba280b5cdc"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_US_SHA="1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"

EXPECTED_GAME_ROWS=1976
EXPECTED_VOICED_ROWS=1823
EXPECTED_CORE_ROWS=1368
EXPECTED_NONCORE_VOICED=455
EXPECTED_DIALOGUE_ROWS=1761

SR=1000
SEARCH_RADIUS_SEC=15.0
PEAK_EXCLUSION_SEC=0.75
THRESHOLDS=(0.06,0.08,0.10)

SPEAKER_ALLOWED={
    "NRT":{"나루토"},"JRY":{"지라이야"},"KSU":{"카스미"},"KKS":{"카카시"},
    "KRH":{"키리히메"},"TND":{"츠나데"},"SKR":{"사쿠라"},"ORC":{"오로치마루"},
    "SIK":{"시카마루"},"KBT":{"카부토"},"SZN":{"시즈네"},"HNT":{"히나타"},
    "HKG":{"3대 호카게"},"NEJ":{"네지"},"ROC":{"리"},"HST":{"병사대장"},
    "GUY":{"가이"},"GAR":{"가아라"},"ONK":{"여자아이"},
    "SN1":{"사념제","사념체"},"KIB":{"키바"},"JJO":{"시녀"},"SIN":{"시도"},
    "TYO":{"쵸지"},"INO":{"이노"},"HIS":{"병사"},"TEN":{"텐텐"},
    "SNS":{"사념체","사념제"},"KSM":{"키사메"},"ITD":{"일동"},
    "JRS":{"일동"},"JT2":{"일동"},
}
SUB_SPEAKER_NORMALIZE={"이도":"이노"}

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path:Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path:Path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def pin(path:Path,sha:str,name:str):
    if not path.exists():raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=sha.lower():raise RuntimeError(f"{name} SHA mismatch: {got}")
    return got

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def run_capture(cmd,timeout=120):
    p=subprocess.run(
        [str(x) for x in cmd],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=(0x08000000 if os.name=="nt" else 0),
    )
    return p.returncode,p.stdout,p.stderr

def find_tool(root:Path,name:str):
    hit=shutil.which(name)
    if hit:return Path(hit)
    exe=name+".exe" if os.name=="nt" and not name.lower().endswith(".exe") else name
    for base in [
        root/"tools",
        root/"analysis"/"stage38a_cuda"/"cuda_runtime",
        root/"analysis"/"stage38a_cuda",
        root/"analysis",
    ]:
        p=base/exe
        if p.exists():return p
    return None

def probe_duration(ffprobe:Path,p:Path):
    rc,out,err=run_capture([
        ffprobe,"-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",p
    ],timeout=30)
    if rc!=0:return None
    try:return float(out.decode("utf-8","replace").strip())
    except:return None

def decode_full_audio(ffmpeg:Path,video:Path,out_raw:Path):
    rc,out,err=run_capture([
        ffmpeg,"-y","-v","error","-i",video,
        "-vn","-ac","1","-ar",str(SR),"-f","f32le",out_raw
    ],timeout=900)
    if rc!=0 or not out_raw.exists() or out_raw.stat().st_size<4:
        raise RuntimeError(
            f"full audio decode failed: {video}\n"+
            err.decode("utf-8","replace")[-4000:]
        )

def decode_voice(ffmpeg:Path,p:Path):
    rc,out,err=run_capture([
        ffmpeg,"-v","error","-i",p,
        "-vn","-ac","1","-ar",str(SR),"-f","f32le","pipe:1"
    ],timeout=30)
    if rc!=0 or len(out)<4:
        return None,err.decode("utf-8","replace")[-2500:]
    return np.frombuffer(out,dtype="<f4").astype(np.float64),""

def preemph(x):
    x=x.astype(np.float64,copy=False)
    if len(x)<2:return x.copy()
    z=np.empty_like(x)
    z[0]=x[0]
    z[1:]=x[1:]-0.97*x[:-1]
    z-=np.mean(z)
    return z

def trim_voice(y):
    if y is None or len(y)<50:return y
    z=preemph(y)
    env=np.abs(z)
    mx=float(np.max(env)) if len(env) else 0.0
    if mx<=1e-9:return z
    nz=np.flatnonzero(env>max(mx*0.012,1e-7))
    if len(nz)>15:
        a=max(0,int(nz[0])-20)
        b=min(len(z),int(nz[-1])+21)
        z=z[a:b]
        z-=np.mean(z)
    return z

def nextpow2(n):
    return 1<<(int(n-1).bit_length())

def ncc_peaks(window,voice):
    if window is None or voice is None:return None
    x=preemph(window)
    y=trim_voice(voice)
    if y is None or len(y)<60 or len(x)<len(y)+5:return None
    n=len(x);m=len(y);nfft=nextpow2(n+m-1)
    corr=np.fft.irfft(
        np.fft.rfft(x,nfft)*np.fft.rfft(y[::-1],nfft),nfft
    )[m-1:n]
    cs=np.concatenate(([0.0],np.cumsum(x*x)))
    local=cs[m:]-cs[:-m]
    ey=float(np.sum(y*y))
    ncc=corr/np.sqrt(np.maximum(local*ey,1e-20))
    i1=int(np.argmax(ncc))
    s1=float(ncc[i1])

    mask=ncc.copy()
    radius=max(int(PEAK_EXCLUSION_SEC*SR),int(m*0.5))
    a=max(0,i1-radius);b=min(len(mask),i1+radius+1)
    mask[a:b]=-1.0e9
    i2=int(np.argmax(mask)) if len(mask) else 0
    s2=float(mask[i2]) if len(mask) and mask[i2]>-1.0e8 else float("nan")
    return {
        "best_score":s1,"best_offset_samples":i1,
        "second_score":s2,"second_offset_samples":i2,
        "voice_samples_used":m,
    }

def linear_predict(anchor_g,anchor_t,g):
    # exact / interpolate / nearest-slope extrapolate
    pos=bisect_left(anchor_g,g)
    if pos<len(anchor_g) and anchor_g[pos]==g:
        return anchor_t[pos]
    if 0<pos<len(anchor_g):
        g0,g1=anchor_g[pos-1],anchor_g[pos]
        t0,t1=anchor_t[pos-1],anchor_t[pos]
        f=(g-g0)/(g1-g0)
        return t0+f*(t1-t0)
    if pos==0:
        if len(anchor_g)>=2:
            slope=(anchor_t[1]-anchor_t[0])/(anchor_g[1]-anchor_g[0])
            return anchor_t[0]+(g-anchor_g[0])*slope
        return anchor_t[0]
    if len(anchor_g)>=2:
        slope=(anchor_t[-1]-anchor_t[-2])/(anchor_g[-1]-anchor_g[-2])
        return anchor_t[-1]+(g-anchor_g[-1])*slope
    return anchor_t[-1]

def best_increasing_subset(cands,left_time,right_time,threshold):
    """
    cands are already in game order. Select increasing best_time rows maximizing
    sum(score-threshold), with fixed anchor times as outer bounds.
    """
    valid=[
        c for c in cands
        if c["matched_time_sec"] is not None
        and c["best_score"] is not None
        and c["best_score"]>threshold
        and c["matched_time_sec"]>left_time+0.02
        and c["matched_time_sec"]<right_time-0.02
    ]
    if not valid:return set()

    n=len(valid)
    dp=[-1e100]*n
    prev=[-1]*n
    for i,c in enumerate(valid):
        w=c["best_score"]-threshold
        dp[i]=w
        for j in range(i):
            if valid[j]["matched_time_sec"]<c["matched_time_sec"]-0.02:
                v=dp[j]+w
                if v>dp[i]:
                    dp[i]=v;prev[i]=j

    # allow empty path
    best_i=max(range(n),key=lambda i:dp[i])
    if dp[best_i]<=0:return set()
    out=set()
    k=best_i
    while k!=-1:
        out.add(valid[k]["game_key"])
        k=prev[k]
    return out

def invert_speaker_map():
    inv=defaultdict(set)
    for code,names in SPEAKER_ALLOWED.items():
        for n in names:inv[n].add(code)
    return inv

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)

    p_core=root/"analysis"/"sub"/"sub24_audio_monotonic_ensemble"/"sub24_audio_monotonic_core.tsv"
    p_top5=root/"analysis"/"sub"/"sub23_audio_rescoring_audit"/"sub23_top5_candidate_scores.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/9] Verify pinned inputs",flush=True)
    pin(p_core,EXPECTED_CORE_SHA,"SUB24 core")
    pin(p_top5,EXPECTED_TOP5_SHA,"SUB23 top5")
    pin(p_kr,EXPECTED_KR_SHA,"SUB19 KR")
    pin(p_us,EXPECTED_US_SHA,"SUB19 US")
    pin(p_sub,EXPECTED_SUB09_SHA,"SUB09")

    core=read_tsv(p_core)
    top5=read_tsv(p_top5)
    kr=read_tsv(p_kr)
    us=read_tsv(p_us)
    sub=read_tsv(p_sub)

    if len(core)!=EXPECTED_CORE_ROWS:
        raise RuntimeError(f"core rows={len(core)} expected={EXPECTED_CORE_ROWS}")

    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=EXPECTED_GAME_ROWS:
        raise RuntimeError(f"game rows={len(game)} expected={EXPECTED_GAME_ROWS}")
    game_pos={game_key(r):i for i,r in enumerate(game)}
    game_by_key={game_key(r):r for r in game}

    voiced=[r for r in game if r["voice_id"]]
    if len(voiced)!=EXPECTED_VOICED_ROWS:
        raise RuntimeError(f"voiced rows={len(voiced)} expected={EXPECTED_VOICED_ROWS}")

    core_by_key={r["game_key"]:r for r in core}
    if len(core_by_key)!=EXPECTED_CORE_ROWS:
        raise RuntimeError("duplicate core game keys")

    noncore_voiced=[r for r in voiced if game_key(r) not in core_by_key]
    if len(noncore_voiced)!=EXPECTED_NONCORE_VOICED:
        raise RuntimeError(
            f"noncore voiced={len(noncore_voiced)} expected={EXPECTED_NONCORE_VOICED}"
        )

    dialogue=[
        r for r in sub
        if r["entry_type"]=="DIALOGUE"
        and 19<=int(r["sequence"])<=1883
    ]
    if len(dialogue)!=EXPECTED_DIALOGUE_ROWS:
        raise RuntimeError(f"dialogue rows={len(dialogue)} expected={EXPECTED_DIALOGUE_ROWS}")

    print("[2/9] Determine Part1/Part2 game-position split from core",flush=True)
    core_part=defaultdict(list)
    for r in core:
        core_part[r["video_part"]].append(
            (game_pos[r["game_key"]],float(r["selected_best_audio_time_sec"]),r)
        )
    for p in core_part:core_part[p].sort()

    if not core_part["part1"] or not core_part["part2"]:
        raise RuntimeError("missing part1/part2 core anchors")
    p1max=core_part["part1"][-1][0]
    p2min=core_part["part2"][0][0]
    if p1max>=p2min:
        raise RuntimeError("part split core overlap")
    split=(p1max+p2min)/2.0
    print(f"  part1 last core gpos={p1max}",flush=True)
    print(f"  part2 first core gpos={p2min}",flush=True)
    print(f"  inferred split={split:.3f}",flush=True)

    def part_for_gpos(gp):
        return "part1" if gp<split else "part2"

    anchors={}
    for part in ("part1","part2"):
        anchors[part]={
            "g":[x[0] for x in core_part[part]],
            "t":[x[1] for x in core_part[part]],
        }

    print("[3/9] Locate tools / videos / voice root",flush=True)
    ffmpeg=find_tool(root,"ffmpeg");ffprobe=find_tool(root,"ffprobe")
    if not ffmpeg or not ffprobe:raise RuntimeError("ffmpeg/ffprobe not found")
    videos={
        "part1":root/"analysis"/"stage37"/"video"/"source_video.mp4",
        "part2":root/"analysis"/"stage37"/"video"/"part2.mp4",
    }
    for part,p in videos.items():
        if not p.exists():raise RuntimeError(f"{part} video missing: {p}")
        d=probe_duration(ffprobe,p)
        print(f"  {part}: {p} duration={d}",flush=True)
        if d is None:raise RuntimeError(f"{part} duration probe failed")
    voice_root=root/"kr_extracted"/"PSP_GAME"/"USRDIR"/"sound"/"voice"
    if not voice_root.exists():raise RuntimeError(f"voice root missing: {voice_root}")

    print("[4/9] Decode gameplay audio once to temporary 1 kHz PCM",flush=True)
    t0=time.time()
    with tempfile.TemporaryDirectory(prefix="naruto_sub25_") as td:
        td=Path(td)
        raws={}
        audio={}
        for part in ("part1","part2"):
            rp=td/(part+".f32")
            decode_full_audio(ffmpeg,videos[part],rp)
            raws[part]=rp
            audio[part]=np.memmap(rp,dtype="<f4",mode="r")
            print(f"  {part}: {rp.stat().st_size/1024/1024:.1f} MiB",flush=True)

        print("[5/9] Re-search 455 non-core voiced game rows",flush=True)
        timeline=[]
        search_errors=[]

        # Fixed core first
        for k,r in core_by_key.items():
            g=game_by_key[k]
            gp=game_pos[k]
            timeline.append({
                "game_key":k,
                "game_global_dialogue_index":gp+1,
                "event_file":g["event_file"],
                "event_display_index":g["event_display_index"],
                "command":g["command"],
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "video_part":r["video_part"],
                "source":"SUB24_CORE_FIXED",
                "predicted_time_sec":float(r["selected_best_audio_time_sec"]),
                "matched_time_sec":float(r["selected_best_audio_time_sec"]),
                "best_score":float(r["selected_audio_score"]),
                "second_peak_score":None,
                "peak_margin":None,
                "delta_from_prediction_sec":0.0,
                "voice_duration_sec":None,
                "search_error":"",
            })

        for idx,g in enumerate(noncore_voiced,1):
            k=game_key(g);gp=game_pos[k];part=part_for_gpos(gp)
            pred=linear_predict(anchors[part]["g"],anchors[part]["t"],gp)
            src=audio[part]
            start=max(0.0,pred-SEARCH_RADIUS_SEC)
            end=min(len(src)/SR,pred+SEARCH_RADIUS_SEC)
            ia=max(0,int(round(start*SR)));ib=min(len(src),int(round(end*SR)))
            win=np.asarray(src[ia:ib],dtype=np.float64)

            vp=voice_root/(g["voice_id"]+".at3")
            row={
                "game_key":k,
                "game_global_dialogue_index":gp+1,
                "event_file":g["event_file"],
                "event_display_index":g["event_display_index"],
                "command":g["command"],
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "video_part":part,
                "source":"LOCAL_AT3_SEARCH",
                "predicted_time_sec":pred,
                "matched_time_sec":None,
                "best_score":None,
                "second_peak_score":None,
                "peak_margin":None,
                "delta_from_prediction_sec":None,
                "voice_duration_sec":None,
                "search_error":"",
            }

            if not vp.exists():
                row["search_error"]="voice file missing"
            else:
                v,err=decode_voice(ffmpeg,vp)
                if v is None:
                    row["search_error"]=err or "voice decode failed"
                else:
                    peaks=ncc_peaks(win,v)
                    row["voice_duration_sec"]=len(v)/SR
                    if peaks is None:
                        row["search_error"]="NCC unavailable"
                    else:
                        mt=start+peaks["best_offset_samples"]/SR
                        row["matched_time_sec"]=mt
                        row["best_score"]=peaks["best_score"]
                        row["second_peak_score"]=(
                            None if math.isnan(peaks["second_score"]) else peaks["second_score"]
                        )
                        row["peak_margin"]=(
                            None if row["second_peak_score"] is None
                            else row["best_score"]-row["second_peak_score"]
                        )
                        row["delta_from_prediction_sec"]=mt-pred

            if row["search_error"]:
                search_errors.append((k,row["search_error"]))
            timeline.append(row)

            if idx==1 or idx%25==0 or idx==len(noncore_voiced):
                ok=idx-len(search_errors)
                print(
                    f"  {idx}/{len(noncore_voiced)} searched, ok={ok}, "
                    f"errors={len(search_errors)}, elapsed={time.time()-t0:.1f}s",
                    flush=True
                )

        # Save the expensive 455-row search checkpoint BEFORE later processing.
        # This file is useful even if a later stage fails.
        checkpoint_fields=[
            "game_key","game_global_dialogue_index","event_file","event_display_index",
            "command","speaker_code","voice_id","japanese","video_part","source",
            "predicted_time_sec","matched_time_sec","best_score","second_peak_score",
            "peak_margin","delta_from_prediction_sec","voice_duration_sec","search_error"
        ]
        write_tsv(
            out/"sub25_fix1_search_checkpoint.tsv",
            sorted(timeline,key=lambda r:int(r["game_global_dialogue_index"])),
            checkpoint_fields
        )
        print(
            f"  search checkpoint saved: {out/'sub25_fix1_search_checkpoint.tsv'}",
            flush=True
        )

        # Explicitly close Windows-backed memmaps before TemporaryDirectory cleanup.
        # Do NOT mutate a dict while iterating over it.
        for part in list(audio.keys()):
            mm=audio.pop(part)
            try:
                mmap_obj=getattr(mm,"_mmap",None)
                if mmap_obj is not None:
                    mmap_obj.close()
            except Exception:
                pass
            del mm

    if search_errors:
        raise RuntimeError(f"voice search errors={len(search_errors)} first={search_errors[:3]}")

    print("[6/9] Build 3-threshold monotonic played-voice ensemble",flush=True)
    timeline.sort(key=lambda r:int(r["game_global_dialogue_index"]))
    by_key={r["game_key"]:r for r in timeline}
    core_keys=set(core_by_key)

    selected_by_threshold={thr:set(core_keys) for thr in THRESHOLDS}

    for part in ("part1","part2"):
        anchors_part=core_part[part]
        # intervals before/between/after fixed core anchors
        boundaries=[]
        for i,(gp,t,r) in enumerate(anchors_part):
            if i==0:
                boundaries.append((None,(gp,t)))
            if i+1<len(anchors_part):
                boundaries.append(((gp,t),(anchors_part[i+1][0],anchors_part[i+1][1])))
            else:
                boundaries.append(((gp,t),None))

        part_duration=probe_duration(ffprobe,videos[part])
        part_rows=[
            r for r in timeline
            if r["video_part"]==part and r["game_key"] not in core_keys
        ]

        for left,right in boundaries:
            left_gp=-1 if left is None else left[0]
            left_t=0.0 if left is None else left[1]
            right_gp=len(game) if right is None else right[0]
            right_t=part_duration if right is None else right[1]
            cands=[
                r for r in part_rows
                if left_gp<int(r["game_global_dialogue_index"])-1<right_gp
            ]
            if not cands:continue
            for thr in THRESHOLDS:
                selected_by_threshold[thr] |= best_increasing_subset(
                    cands,left_t,right_t,thr
                )

    for r in timeline:
        cnt=sum(r["game_key"] in selected_by_threshold[t] for t in THRESHOLDS)
        r["selected_threshold_count"]=cnt
        r["played_voice_consensus"]="YES" if cnt==len(THRESHOLDS) else "NO"
        r["selected_thr_006"]="YES" if r["game_key"] in selected_by_threshold[0.06] else "NO"
        r["selected_thr_008"]="YES" if r["game_key"] in selected_by_threshold[0.08] else "NO"
        r["selected_thr_010"]="YES" if r["game_key"] in selected_by_threshold[0.10] else "NO"

    consensus=[r for r in timeline if r["played_voice_consensus"]=="YES"]
    consensus.sort(key=lambda r:int(r["game_global_dialogue_index"]))

    # Strict per-part time-order invariant.
    for part in ("part1","part2"):
        xs=[r for r in consensus if r["video_part"]==part]
        last=-1e99
        for r in xs:
            mt=float(r["matched_time_sec"])
            if mt<=last-0.02:
                raise RuntimeError(
                    f"played consensus time-order failure {part} at {r['game_key']}"
                )
            last=mt

    print(
        f"  consensus played voices={len(consensus)} "
        f"(core={len(core)} + noncore={len(consensus)-len(core)})",
        flush=True
    )

    print("[7/9] Hard checks for known merged and corrected cases",flush=True)
    # #29 is a known 2-game-msg -> 1 Korean subtitle case.
    for k in ("event000.tbl#011","event000.tbl#012"):
        r=by_key.get(k)
        if not r or r["matched_time_sec"] is None:
            raise RuntimeError(f"known merge voice missing: {k}")
        if float(r["best_score"])<0.12:
            raise RuntimeError(f"known merge voice score too weak {k}: {r['best_score']}")
        print(
            f"  {k} {r['voice_id']} time={r['matched_time_sec']:.3f} "
            f"score={r['best_score']:.6f} consensus={r['played_voice_consensus']}",
            flush=True
        )

    # Core known corrections must still exist.
    required_core={
        "event000.tbl#001":"s_a01_000",
        "event003.tbl#047":"s_a06_043",
        "event112.tbl#122":"s_b15_079",
    }
    for k,v in required_core.items():
        if k not in core_by_key or core_by_key[k]["voice_id"]!=v:
            raise RuntimeError(f"required core anchor missing: {k} / {v}")

    print("[8/9] Group played voices by SUB09 observation intervals",flush=True)
    inv_codes=invert_speaker_map()

    # Use chronological DIALOGUE frames within each video part.
    groups=[]
    detail=[]
    split_flags=set()

    for part in ("part1","part2"):
        subs=[r for r in dialogue if r["video_part"]==part]
        subs.sort(key=lambda r:float(r["observed_first_sec"]))
        voices=[r for r in consensus if r["video_part"]==part]
        voices.sort(key=lambda r:float(r["matched_time_sec"]))

        times=[float(r["matched_time_sec"]) for r in voices]
        previous_frame=0.0

        for si,s in enumerate(subs):
            seq=int(s["sequence"])
            current_frame=float(s["observed_first_sec"])
            # Voice starts after previous captured dialogue frame and no later than current frame.
            # Small 50ms tolerance avoids rounding-edge losses.
            lo=bisect_right(times,previous_frame+0.05)
            hi=bisect_right(times,current_frame+0.05)
            assigned=voices[lo:hi]

            sp=SUB_SPEAKER_NORMALIZE.get(s["speaker"],s["speaker"])
            allowed_codes=inv_codes.get(sp,set())
            compat=[]
            incompatible=[]
            for r in assigned:
                code=r["speaker_code"]
                if not code or not sp or code in allowed_codes:
                    compat.append(r)
                else:
                    incompatible.append(r)

            # Keep all assigned rows visible; compatibility is diagnostic only.
            kinds=len(assigned)
            kind=("0G_1S" if kinds==0 else "1G_1S" if kinds==1 else f"{kinds}G_1S")

            groups.append({
                "sub09_sequence":seq,
                "video_part":part,
                "observed_first_sec":s["observed_first_sec"],
                "speaker":s["speaker"],
                "korean":s["text"],
                "previous_dialogue_frame_sec":f"{previous_frame:.3f}",
                "assigned_game_count":len(assigned),
                "group_kind":kind,
                "assigned_game_keys":" | ".join(r["game_key"] for r in assigned),
                "assigned_voice_ids":" | ".join(r["voice_id"] for r in assigned),
                "assigned_speaker_codes":" | ".join(r["speaker_code"] or "<BLANK>" for r in assigned),
                "assigned_voice_times":" | ".join(f"{float(r['matched_time_sec']):.3f}" for r in assigned),
                "assigned_scores":" | ".join(f"{float(r['best_score']):.6f}" for r in assigned),
                "speaker_compatible_count":len(compat),
                "speaker_incompatible_count":len(incompatible),
                "speaker_incompatible_game_keys":" | ".join(r["game_key"] for r in incompatible),
            })
            for order,r in enumerate(assigned,1):
                g=game_by_key[r["game_key"]]
                detail.append({
                    "sub09_sequence":seq,
                    "group_order":order,
                    "video_part":part,
                    "subtitle_speaker":s["speaker"],
                    "korean":s["text"],
                    "game_key":r["game_key"],
                    "game_global_dialogue_index":r["game_global_dialogue_index"],
                    "speaker_code":r["speaker_code"],
                    "voice_id":r["voice_id"],
                    "japanese":g["text"],
                    "voice_time_sec":f"{float(r['matched_time_sec']):.3f}",
                    "audio_score":f"{float(r['best_score']):.6f}",
                    "source":r["source"],
                    "speaker_compatible":"YES" if r in compat else "NO",
                })
            previous_frame=current_frame

    group_by_seq={int(r["sub09_sequence"]):r for r in groups}

    # Hard grouping check for #29.
    g29=group_by_seq.get(29)
    if not g29:
        raise RuntimeError("SUB09 #29 group missing")
    k29=set(x.strip() for x in g29["assigned_game_keys"].split("|") if x.strip())
    if not {"event000.tbl#011","event000.tbl#012"}.issubset(k29):
        raise RuntimeError(
            f"SUB09 #29 did not capture known merged MSG pair: {g29['assigned_game_keys']}"
        )

    # Flag possible 1G->2S splits: zero-game subtitle adjacent to a same-speaker
    # subtitle that has one or more assigned rows and a small frame gap.
    for part in ("part1","part2"):
        xs=[r for r in groups if r["video_part"]==part]
        for a,b in zip(xs,xs[1:]):
            sa=SUB_SPEAKER_NORMALIZE.get(a["speaker"],a["speaker"])
            sb=SUB_SPEAKER_NORMALIZE.get(b["speaker"],b["speaker"])
            gap=float(b["observed_first_sec"])-float(a["observed_first_sec"])
            if sa and sa==sb and gap<=6.0:
                if int(a["assigned_game_count"])==0 and int(b["assigned_game_count"])>=1:
                    split_flags.add(int(a["sub09_sequence"]))
                    split_flags.add(int(b["sub09_sequence"]))
                elif int(b["assigned_game_count"])==0 and int(a["assigned_game_count"])>=1:
                    split_flags.add(int(a["sub09_sequence"]))
                    split_flags.add(int(b["sub09_sequence"]))

    for r in groups:
        r["potential_1G_2S_split"]="YES" if int(r["sub09_sequence"]) in split_flags else "NO"

    print("[9/9] Write outputs / report",flush=True)

    # US same-voice English metadata for timeline.
    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:us_by[(r["event_file"],r["voice_id"])].append(r)

    for r in timeline:
        hits=us_by.get((r["event_file"],r["voice_id"]),[])
        r["us_match_count"]=len(hits)
        r["english"]=" || ".join(x["text"] for x in hits)

    timeline_fields=[
        "game_key","game_global_dialogue_index","event_file","event_display_index",
        "command","speaker_code","voice_id","japanese","video_part","source",
        "predicted_time_sec","matched_time_sec","best_score","second_peak_score",
        "peak_margin","delta_from_prediction_sec","voice_duration_sec","search_error",
        "selected_threshold_count","selected_thr_006","selected_thr_008","selected_thr_010",
        "played_voice_consensus","us_match_count","english"
    ]
    write_tsv(out/"sub25_game_voice_timeline.tsv",timeline,timeline_fields)
    write_tsv(out/"sub25_played_voice_consensus.tsv",consensus,timeline_fields)
    write_tsv(
        out/"sub25_subtitle_voice_groups.tsv",groups,
        [
            "sub09_sequence","video_part","observed_first_sec","speaker","korean",
            "previous_dialogue_frame_sec","assigned_game_count","group_kind",
            "assigned_game_keys","assigned_voice_ids","assigned_speaker_codes",
            "assigned_voice_times","assigned_scores","speaker_compatible_count",
            "speaker_incompatible_count","speaker_incompatible_game_keys",
            "potential_1G_2S_split"
        ]
    )
    write_tsv(
        out/"sub25_subtitle_voice_group_detail.tsv",detail,
        [
            "sub09_sequence","group_order","video_part","subtitle_speaker","korean",
            "game_key","game_global_dialogue_index","speaker_code","voice_id",
            "japanese","voice_time_sec","audio_score","source","speaker_compatible"
        ]
    )

    group_counts=Counter(r["group_kind"] for r in groups)
    source_counts=Counter(r["source"] for r in consensus)
    incompatible_groups=sum(int(r["speaker_incompatible_count"])>0 for r in groups)
    zero_groups=sum(int(r["assigned_game_count"])==0 for r in groups)
    multi_groups=sum(int(r["assigned_game_count"])>=2 for r in groups)

    # Known #29 evidence
    merge29=[
        r for r in detail
        if int(r["sub09_sequence"])==29
    ]
    write_tsv(
        out/"sub25_known_merge29.tsv",merge29,
        [
            "sub09_sequence","group_order","video_part","subtitle_speaker","korean",
            "game_key","game_global_dialogue_index","speaker_code","voice_id",
            "japanese","voice_time_sec","audio_score","source","speaker_compatible"
        ]
    )

    report={
        "stage":"SUB25_FIX1",
        "mode":"READ_ONLY_GAME_VOICE_TIMELINE_RECONSTRUCTION",
        "sample_rate_hz":SR,
        "search_radius_sec":SEARCH_RADIUS_SEC,
        "game_rows":len(game),
        "voiced_game_rows":len(voiced),
        "core_fixed_rows":len(core),
        "noncore_voiced_searched":len(noncore_voiced),
        "search_errors":len(search_errors),
        "search_checkpoint_written":True,
        "windows_memmap_cleanup_fixed":True,
        "thresholds":list(THRESHOLDS),
        "played_voice_consensus_rows":len(consensus),
        "played_voice_consensus_noncore_rows":len(consensus)-len(core),
        "consensus_source_counts":dict(source_counts),
        "subtitle_dialogue_rows":len(groups),
        "subtitle_group_kind_counts":dict(group_counts),
        "subtitle_zero_game_groups":zero_groups,
        "subtitle_multi_game_groups":multi_groups,
        "subtitle_groups_with_speaker_incompatibility":incompatible_groups,
        "potential_1G_2S_split_rows":len(split_flags),
        "known_merge29_game_keys":[r["game_key"] for r in merge29],
        "semantic_final_claim":False,
        "game_files_modified":False,
    }
    (out/"sub25_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB25 FIX1 - Game Voice Timeline Reconstruction",
        "",
        f"GameRows={len(game)}",
        f"VoicedGameRows={len(voiced)}",
        f"CoreFixedRows={len(core)}",
        f"NoncoreVoicedSearched={len(noncore_voiced)}",
        f"SearchErrors={len(search_errors)}",
        f"PlayedVoiceConsensusRows={len(consensus)}",
        f"PlayedVoiceConsensusNoncoreRows={len(consensus)-len(core)}",
        f"SubtitleDialogueRows={len(groups)}",
        "GroupKindCounts="+json.dumps(dict(group_counts),ensure_ascii=False,sort_keys=True),
        f"SubtitleZeroGameGroups={zero_groups}",
        f"SubtitleMultiGameGroups={multi_groups}",
        f"SubtitleGroupsWithSpeakerIncompatibility={incompatible_groups}",
        f"Potential1G2SSplitRows={len(split_flags)}",
        "",
        "Known merge check:",
    ]
    for r in merge29:
        summary.append(
            f"  SUB09#29 -> {r['game_key']} {r['voice_id']} "
            f"time={r['voice_time_sec']} score={r['audio_score']}"
        )
    summary += [
        "",
        "Important:",
        "  This stage reconstructs played voice timing and grouping candidates.",
        "  It does NOT yet decide how merged Korean text should be split across",
        "  multiple game MSG rows.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
