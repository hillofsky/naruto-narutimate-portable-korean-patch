#!/usr/bin/env python3
# Naruto PSP SUB23 - Full dialogue audio-rescoring audit
#
# Read-only.
# Objective evidence: gameplay Japanese audio vs standalone Japanese AT3 voices.
#
# Scope:
# - SUB09 event-window DIALOGUE rows: 1761 (#19..#1883)
# - game MSG/MSG_FORCED: 1976
# - candidate center comes from SUB20 FIX1's 3 structural variants
# - candidates are nearby voiced game rows with compatible speaker, plus nearby
#   blank-speaker voiced rows and every structurally proposed voiced row
#
# Scoring:
# - both gameplay and voice are decoded by ffmpeg to mono 1000 Hz float PCM
# - local window: subtitle timestamp -10s .. +1s
# - pre-emphasized normalized cross-correlation
# - top candidates are kept, but NO final mapping is asserted in this stage
#
# Hard pilot checks:
# - #19 s_a01_000 must correlate
# - #164 s_a06_043 must beat wrong s_a07_013 by >= 0.05

from __future__ import annotations
import argparse, csv, hashlib, json, math, os, re, shutil, subprocess, sys, tempfile, time
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_STATUS_SHA="c803a1f97a982174a59364c50d1e992d5034715630143fe3d5241a24a203c7ee"

EXPECTED_DIALOGUE_ROWS=1761
EXPECTED_GAME_ROWS=1976
SR=1000
WINDOW_BEFORE=10.0
WINDOW_AFTER=1.0
BASE_BAND=50
EXPAND_BAND=100
MAX_CANDIDATES=35
TOP_KEEP=5

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

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def split_keys(s):
    if not s:return []
    return [x.strip() for x in s.split("|") if x.strip()]

def parse_time_sec(r):
    return float(r["observed_first_sec"])

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
    cmd=[
        ffmpeg,"-y","-v","error","-i",video,
        "-vn","-ac","1","-ar",str(SR),"-f","f32le",out_raw
    ]
    rc,out,err=run_capture(cmd,timeout=900)
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
        return None,err.decode("utf-8","replace")[-2000:]
    return np.frombuffer(out,dtype="<f4").astype(np.float64),""

def trim_voice(y):
    if y is None or len(y)<100:return y
    # high-pass/preemphasis first, then trim near-silent edges
    z=np.empty_like(y)
    z[0]=y[0]
    z[1:]=y[1:]-0.97*y[:-1]
    env=np.abs(z)
    mx=float(np.max(env)) if len(env) else 0.0
    if mx<=1e-9:return z
    nz=np.flatnonzero(env>max(mx*0.012,1e-7))
    if len(nz)>20:
        a=max(0,int(nz[0])-20)
        b=min(len(z),int(nz[-1])+21)
        z=z[a:b]
    z=z-np.mean(z)
    return z

def preemph_window(x):
    x=x.astype(np.float64,copy=False)
    if len(x)<2:return x
    z=np.empty_like(x)
    z[0]=x[0]
    z[1:]=x[1:]-0.97*x[:-1]
    z=z-np.mean(z)
    return z

def nextpow2(n):
    return 1<<(int(n-1).bit_length())

def ncc_score(window,voice):
    if window is None or voice is None:return None,None
    x=preemph_window(window)
    y=trim_voice(voice)
    if y is None or len(y)<80 or len(x)<len(y)+5:return None,None

    n=len(x);m=len(y);nfft=nextpow2(n+m-1)
    X=np.fft.rfft(x,nfft)
    Y=np.fft.rfft(y[::-1],nfft)
    conv=np.fft.irfft(X*Y,nfft)
    corr=conv[m-1:n]

    cs=np.concatenate(([0.0],np.cumsum(x*x)))
    local=cs[m:]-cs[:-m]
    ey=float(np.sum(y*y))
    den=np.sqrt(np.maximum(local*ey,1e-20))
    ncc=corr/den
    idx=int(np.argmax(ncc))
    return float(ncc[idx]),idx

def inverse_speaker_codes():
    inv=defaultdict(set)
    for code,names in SPEAKER_ALLOWED.items():
        for n in names:inv[n].add(code)
    return inv

def derive_centers(status,game_pos):
    centers=[]
    raw=[]
    for r in status:
        xs=[]
        for fld in ("variant_baseline","variant_conservative","variant_merge_friendly"):
            for k in split_keys(r[fld]):
                if k in game_pos:xs.append(game_pos[k])
        c=float(np.median(xs)) if xs else None
        raw.append(c)

    prev=[None]*len(raw);last=None
    for i,c in enumerate(raw):
        if c is not None:last=(i,c)
        prev[i]=last
    nxt=[None]*len(raw);last=None
    for i in range(len(raw)-1,-1,-1):
        c=raw[i]
        if c is not None:last=(i,c)
        nxt[i]=last

    for i,c in enumerate(raw):
        if c is not None:
            centers.append(c);continue
        a=prev[i];b=nxt[i]
        if a and b and b[0]!=a[0]:
            f=(i-a[0])/(b[0]-a[0])
            centers.append(a[1]+f*(b[1]-a[1]))
        elif a:centers.append(a[1])
        elif b:centers.append(b[1])
        else:
            centers.append(i*(EXPECTED_GAME_ROWS-1)/max(1,len(raw)-1))
    return centers

def select_candidates(i,status_row,center,game,game_pos,inv_codes):
    sp=SUB_SPEAKER_NORMALIZE.get(
        status_row["subtitle_speaker_alignment"],
        status_row["subtitle_speaker_alignment"]
    )
    codes=inv_codes.get(sp,set())
    variant_keys=set()
    for fld in ("variant_baseline","variant_conservative","variant_merge_friendly"):
        variant_keys.update(k for k in split_keys(status_row[fld]) if k in game_pos)

    def collect(band):
        lo=max(0,int(math.floor(center-band)))
        hi=min(len(game)-1,int(math.ceil(center+band)))
        out=[]
        for gi in range(lo,hi+1):
            g=game[gi]
            if not g["voice_id"]:continue
            if g["speaker_code"] in codes:
                out.append((gi,0))
            elif not g["speaker_code"] and abs(gi-center)<=25:
                out.append((gi,1))
        return out

    pairs=collect(BASE_BAND)
    explicit_count=sum(kind==0 for _,kind in pairs)
    if explicit_count<3:
        pairs=collect(EXPAND_BAND)

    d={gi:kind for gi,kind in pairs}
    for k in variant_keys:
        gi=game_pos[k]
        if game[gi]["voice_id"]:
            d.setdefault(gi,2)

    ordered=sorted(
        d.items(),
        key=lambda kv:(
            0 if game[kv[0]]["speaker_code"] in codes else 1,
            abs(kv[0]-center),
            kv[0]
        )
    )

    if len(ordered)>MAX_CANDIDATES:
        must={game_pos[k] for k in variant_keys if k in game_pos and game[game_pos[k]]["voice_id"]}
        kept=[]
        for item in ordered:
            if item[0] in must and item not in kept:kept.append(item)
        for item in ordered:
            if item not in kept:
                kept.append(item)
            if len(kept)>=MAX_CANDIDATES:break
        ordered=kept

    return [gi for gi,_ in ordered],variant_keys,sp,codes

def confidence(top,runner,margin):
    if top is None:return "NO_SCORE"
    if top>=0.20 and margin>=0.08:return "VERY_STRONG"
    if top>=0.14 and margin>=0.05:return "STRONG"
    if top>=0.09 and margin>=0.025:return "MEDIUM"
    return "WEAK"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)

    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_status=root/"analysis"/"sub"/"sub20_fix1_structural_alignment"/"sub20_all_dialogue_status.tsv"
    for p in (p_sub,p_kr,p_status):
        if not p.exists():raise RuntimeError(f"required input missing: {p}")
    if sha256_file(p_sub).lower()!=EXPECTED_SUB09_SHA:raise RuntimeError("SUB09 SHA mismatch")
    if sha256_file(p_kr).lower()!=EXPECTED_KR_SHA:raise RuntimeError("SUB19 KR SHA mismatch")
    if sha256_file(p_status).lower()!=EXPECTED_STATUS_SHA:raise RuntimeError("SUB20 FIX1 status SHA mismatch")

    sub_all=read_tsv(p_sub)
    kr=read_tsv(p_kr)
    status=read_tsv(p_status)
    if len(status)!=EXPECTED_DIALOGUE_ROWS:raise RuntimeError(f"status rows={len(status)}")

    sub_by_seq={int(r["sequence"]):r for r in sub_all}
    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=EXPECTED_GAME_ROWS:raise RuntimeError(f"game rows={len(game)}")
    game_pos={game_key(r):i for i,r in enumerate(game)}

    ffmpeg=find_tool(root,"ffmpeg");ffprobe=find_tool(root,"ffprobe")
    if not ffmpeg or not ffprobe:raise RuntimeError("ffmpeg/ffprobe not found")

    part1=root/"analysis"/"stage37"/"video"/"source_video.mp4"
    part2=root/"analysis"/"stage37"/"video"/"part2.mp4"
    for p in (part1,part2):
        if not p.exists():raise RuntimeError(f"source video missing: {p}")

    print("[1/7] Probe source videos",flush=True)
    d1=probe_duration(ffprobe,part1);d2=probe_duration(ffprobe,part2)
    print(f"part1={part1} duration={d1}",flush=True)
    print(f"part2={part2} duration={d2}",flush=True)
    if d1 is None or d1<7328:raise RuntimeError("part1 duration too short")
    if d2 is None or d2<2972:raise RuntimeError("part2 duration too short")

    print("[2/7] Build candidate centers",flush=True)
    centers=derive_centers(status,game_pos)
    inv_codes=inverse_speaker_codes()

    voice_root=root/"kr_extracted"/"PSP_GAME"/"USRDIR"/"sound"/"voice"
    if not voice_root.exists():raise RuntimeError(f"voice root missing: {voice_root}")

    # Candidate lists before audio decode.
    plans=[]
    for i,sr in enumerate(status):
        seq=int(sr["sub09_sequence"])
        sub=sub_by_seq[seq]
        cand,vkeys,sp,codes=select_candidates(i,sr,centers[i],game,game_pos,inv_codes)
        plans.append({
            "status":sr,"sub":sub,"seq":seq,"center":centers[i],
            "candidate_indices":cand,"variant_keys":vkeys,
            "speaker_norm":sp,"speaker_codes":codes,
        })

    cand_counts=[len(p["candidate_indices"]) for p in plans]
    print(
        f"candidate count min={min(cand_counts)} max={max(cand_counts)} "
        f"mean={sum(cand_counts)/len(cand_counts):.2f}",
        flush=True
    )

    print("[3/7] Decode full gameplay audio to temporary 1 kHz PCM",flush=True)
    t0=time.time()
    with tempfile.TemporaryDirectory(prefix="naruto_sub23_") as td:
        td=Path(td)
        raw1=td/"part1_1k.f32";raw2=td/"part2_1k.f32"
        decode_full_audio(ffmpeg,part1,raw1)
        print(f"  part1 decoded {raw1.stat().st_size/1024/1024:.1f} MiB",flush=True)
        decode_full_audio(ffmpeg,part2,raw2)
        print(f"  part2 decoded {raw2.stat().st_size/1024/1024:.1f} MiB",flush=True)

        a1=np.memmap(raw1,dtype="<f4",mode="r")
        a2=np.memmap(raw2,dtype="<f4",mode="r")

        voice_cache={}
        voice_errors={}

        def get_voice(vid):
            if vid in voice_cache:return voice_cache[vid]
            if vid in voice_errors:return None
            p=voice_root/(vid+".at3")
            if not p.exists():
                voice_errors[vid]="missing"
                return None
            arr,err=decode_voice(ffmpeg,p)
            if arr is None:
                voice_errors[vid]=err
                return None
            voice_cache[vid]=arr
            return arr

        def get_window(part,t):
            src=a1 if part=="part1" else a2
            start=max(0.0,t-WINDOW_BEFORE)
            end=t+WINDOW_AFTER
            ia=max(0,int(round(start*SR)))
            ib=min(len(src),int(round(end*SR)))
            return np.asarray(src[ia:ib],dtype=np.float64),start

        print("[4/7] Hard pilot at 1 kHz",flush=True)
        # Helper score by explicit voice at a given subtitle.
        def pilot(seq,vid):
            sub=sub_by_seq[seq]
            t=parse_time_sec(sub)
            win,start=get_window(sub["video_part"],t)
            v=get_voice(vid)
            sc,off=ncc_score(win,v)
            best=None if sc is None else start+off/SR
            return sc,best

        p19,b19=pilot(19,"s_a01_000")
        p164t,b164t=pilot(164,"s_a06_043")
        p164f,b164f=pilot(164,"s_a07_013")
        print(f"  #19  true s_a01_000 score={p19} best={b19}",flush=True)
        print(f"  #164 true s_a06_043 score={p164t} best={b164t}",flush=True)
        print(f"  #164 wrong s_a07_013 score={p164f} best={b164f}",flush=True)
        if p19 is None or p19<0.10:
            raise RuntimeError(f"1k pilot #19 too weak: {p19}")
        if p164t is None or p164f is None or (p164t-p164f)<0.05:
            raise RuntimeError(f"1k pilot #164 discrimination insufficient: true={p164t} wrong={p164f}")

        print("[5/7] Score all 1761 dialogue rows",flush=True)
        summary_rows=[]
        score_rows=[]
        conf_counter=Counter()
        structural_single=0
        audio_agree=0
        no_candidate=0

        for pi,plan in enumerate(plans,1):
            seq=plan["seq"];sub=plan["sub"];sr=plan["status"]
            t=parse_time_sec(sub);part=sub["video_part"]
            win,wstart=get_window(part,t)
            scored=[]

            for gi in plan["candidate_indices"]:
                g=game[gi];vid=g["voice_id"]
                v=get_voice(vid)
                if v is None:continue
                sc,off=ncc_score(win,v)
                if sc is None:continue
                best=wstart+off/SR
                scored.append({
                    "score":sc,"gi":gi,"best":best,
                    "delta":best-t,
                })

            scored.sort(key=lambda x:(-x["score"],abs(x["delta"]),x["gi"]))
            if not scored:
                no_candidate+=1
                top=None;runner=None;margin=None
                conf="NO_SCORE"
            else:
                top=scored[0]
                runner=scored[1] if len(scored)>1 else None
                margin=top["score"]-(runner["score"] if runner else 0.0)
                conf=confidence(top["score"],runner["score"] if runner else None,margin)
            conf_counter[conf]+=1

            consensus=split_keys(sr["consensus_game_rows"])
            structural_key=consensus[0] if len(consensus)==1 else ""
            if structural_key:structural_single+=1

            top_key=game_key(game[top["gi"]]) if top else ""
            agree="YES" if structural_key and top_key==structural_key else "NO"
            if agree=="YES":audio_agree+=1

            summary_rows.append({
                "sub09_sequence":seq,
                "video_part":part,
                "timestamp_sec":f"{t:.3f}",
                "speaker":sub["speaker"],
                "speaker_alignment":plan["speaker_norm"],
                "korean":sub["text"],
                "structural_high":sr["structural_high"],
                "structural_consensus_game":structural_key,
                "structural_consensus_voice":(
                    game[game_pos[structural_key]]["voice_id"]
                    if structural_key in game_pos else ""
                ),
                "candidate_count":len(plan["candidate_indices"]),
                "scored_candidate_count":len(scored),
                "audio_top_game":top_key,
                "audio_top_voice":game[top["gi"]]["voice_id"] if top else "",
                "audio_top_speaker_code":game[top["gi"]]["speaker_code"] if top else "",
                "audio_top_japanese":game[top["gi"]]["text"] if top else "",
                "audio_top_score":"" if not top else f"{top['score']:.6f}",
                "audio_top_best_time_sec":"" if not top else f"{top['best']:.3f}",
                "audio_top_delta_from_frame_sec":"" if not top else f"{top['delta']:+.3f}",
                "audio_runner_game":"" if not runner else game_key(game[runner["gi"]]),
                "audio_runner_voice":"" if not runner else game[runner["gi"]]["voice_id"],
                "audio_runner_score":"" if not runner else f"{runner['score']:.6f}",
                "audio_margin":"" if margin is None else f"{margin:.6f}",
                "audio_confidence":conf,
                "audio_agrees_structural":agree,
            })

            for rank,x in enumerate(scored[:TOP_KEEP],1):
                g=game[x["gi"]]
                score_rows.append({
                    "sub09_sequence":seq,
                    "rank":rank,
                    "video_part":part,
                    "timestamp_sec":f"{t:.3f}",
                    "subtitle_speaker":sub["speaker"],
                    "korean":sub["text"],
                    "game_key":game_key(g),
                    "game_global_dialogue_index":x["gi"]+1,
                    "command":g["command"],
                    "speaker_code":g["speaker_code"],
                    "voice_id":g["voice_id"],
                    "japanese":g["text"],
                    "score":f"{x['score']:.6f}",
                    "best_audio_time_sec":f"{x['best']:.3f}",
                    "delta_from_frame_sec":f"{x['delta']:+.3f}",
                    "was_structural_variant_candidate":"YES" if game_key(g) in plan["variant_keys"] else "NO",
                    "was_structural_consensus":"YES" if game_key(g)==structural_key else "NO",
                })

            if pi==1 or pi%50==0 or pi==len(plans):
                print(
                    f"  {pi}/{len(plans)} voice_cache={len(voice_cache)} "
                    f"confidence={dict(conf_counter)} elapsed={time.time()-t0:.1f}s",
                    flush=True
                )

        # memmaps no longer needed
        del a1;del a2

    print("[6/7] Write audit tables",flush=True)
    write_tsv(
        out/"sub23_audio_audit.tsv",summary_rows,
        [
            "sub09_sequence","video_part","timestamp_sec","speaker","speaker_alignment","korean",
            "structural_high","structural_consensus_game","structural_consensus_voice",
            "candidate_count","scored_candidate_count",
            "audio_top_game","audio_top_voice","audio_top_speaker_code","audio_top_japanese",
            "audio_top_score","audio_top_best_time_sec","audio_top_delta_from_frame_sec",
            "audio_runner_game","audio_runner_voice","audio_runner_score","audio_margin",
            "audio_confidence","audio_agrees_structural"
        ]
    )
    write_tsv(
        out/"sub23_top5_candidate_scores.tsv",score_rows,
        [
            "sub09_sequence","rank","video_part","timestamp_sec","subtitle_speaker","korean",
            "game_key","game_global_dialogue_index","command","speaker_code","voice_id","japanese",
            "score","best_audio_time_sec","delta_from_frame_sec",
            "was_structural_variant_candidate","was_structural_consensus"
        ]
    )

    # Strong audio anchors are evidence candidates, still not final semantic mapping.
    strong=[
        r for r in summary_rows
        if r["audio_confidence"] in ("VERY_STRONG","STRONG")
    ]
    write_tsv(
        out/"sub23_strong_audio_anchors.tsv",strong,
        list(summary_rows[0].keys())
    )

    disagreements=[
        r for r in strong
        if r["structural_consensus_game"] and r["audio_agrees_structural"]=="NO"
    ]
    write_tsv(
        out/"sub23_strong_audio_structural_disagreements.tsv",disagreements,
        list(summary_rows[0].keys())
    )

    print("[7/7] Final validation / report",flush=True)
    row19=next(r for r in summary_rows if int(r["sub09_sequence"])==19)
    row164=next(r for r in summary_rows if int(r["sub09_sequence"])==164)
    if row19["audio_top_voice"]!="s_a01_000":
        raise RuntimeError(f"#19 batch top mismatch: {row19['audio_top_voice']}")
    if row164["audio_top_voice"]!="s_a06_043":
        raise RuntimeError(f"#164 batch top mismatch: {row164['audio_top_voice']}")

    report={
        "stage":"SUB23",
        "mode":"READ_ONLY_FULL_AUDIO_RESCORING_AUDIT",
        "sample_rate_hz":SR,
        "window_before_sec":WINDOW_BEFORE,
        "window_after_sec":WINDOW_AFTER,
        "dialogue_rows":len(summary_rows),
        "game_rows":len(game),
        "candidate_count":{
            "min":min(cand_counts),"max":max(cand_counts),
            "mean":sum(cand_counts)/len(cand_counts)
        },
        "confidence_counts":dict(conf_counter),
        "strong_audio_anchors":len(strong),
        "strong_audio_vs_structural_disagreements":len(disagreements),
        "structural_single_rows":structural_single,
        "audio_agrees_structural":audio_agree,
        "no_score_rows":no_candidate,
        "decoded_unique_voice_files":len(voice_cache),
        "voice_decode_errors":len(voice_errors),
        "pilot_1k":{
            "sub09_19_s_a01_000":p19,
            "sub09_164_true_s_a06_043":p164t,
            "sub09_164_wrong_s_a07_013":p164f,
            "true_minus_wrong":p164t-p164f,
        },
        "important":"Audio top candidates are objective evidence, but this stage does not patch or declare all rows final.",
        "game_files_modified":False,
    }
    (out/"sub23_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB23 - Full Dialogue Audio Rescoring Audit",
        "",
        f"DialogueRows={len(summary_rows)}",
        f"GameRows={len(game)}",
        f"CandidateMin={min(cand_counts)}",
        f"CandidateMax={max(cand_counts)}",
        f"CandidateMean={sum(cand_counts)/len(cand_counts):.3f}",
        f"DecodedUniqueVoiceFiles={len(voice_cache)}",
        f"VoiceDecodeErrors={len(voice_errors)}",
        f"ConfidenceCounts={dict(conf_counter)}",
        f"StrongAudioAnchors={len(strong)}",
        f"StrongAudioStructuralDisagreements={len(disagreements)}",
        f"StructuralSingleRows={structural_single}",
        f"AudioAgreesStructural={audio_agree}",
        f"NoScoreRows={no_candidate}",
        "",
        f"Pilot1k #19 s_a01_000={p19:.6f}",
        f"Pilot1k #164 TRUE s_a06_043={p164t:.6f}",
        f"Pilot1k #164 WRONG s_a07_013={p164f:.6f}",
        f"Pilot1k true-minus-wrong={p164t-p164f:+.6f}",
        "",
        "IMPORTANT:",
        "  This is an audio evidence audit, not a final patch mapping.",
        "  Strong audio/structural disagreements are especially valuable for",
        "  correcting the earlier speaker/order drift.",
        "",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
