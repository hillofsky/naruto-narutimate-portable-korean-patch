#!/usr/bin/env python3
# Naruto PSP SUB25 FIX2 - Full voice observation monotonic reconstruction
#
# Read-only and FAST.
#
# FIX1 revealed that treating all 1368 SUB24 core rows as fixed times is unsafe:
# some core mappings are semantically shifted around merge/split regions and their
# audio times can even reverse slightly.
#
# FIX2 does NOT decode video/audio again.
#
# It combines:
# 1) every SUB23 top5 observation for each voiced game row
# 2) SUB25 FIX1 checkpoint observations for voiced rows never appearing in top5
#
# Then, separately for Part1 and Part2, it solves a weighted 2D monotonic chain:
#   game row order strictly increases
#   observed audio start time strictly increases
#
# Three thresholds (0.06/0.08/0.10) are solved independently.
# A game voice is PLAYED_VOICE_CONSENSUS only if all three chains select the
# same observation/time for that row.
#
# Finally, consensus voice starts are grouped between consecutive SUB09 dialogue
# frame timestamps. These groups are evidence for:
#   0G->1S, 1G->1S, 2G->1S, 3G+->1S and possible 1G->2S splits.
#
# No TBL/DAT/BOOT/ISO is modified.

from __future__ import annotations
import argparse, bisect, csv, hashlib, io, json, math, sys, zipfile
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_CHECKPOINT_SHA="6f295bae8b23acb37c2d5f80f570119b39eec0ebf3155067d8286785b9c433ca"
EXPECTED_TOP5_SHA="7be8e92a0c6427a93cda17fd4007eeaa7a934695044c2ee6a3cdbfba280b5cdc"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_US_SHA="1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"

EXPECTED_GAME_ROWS=1976
EXPECTED_VOICED_ROWS=1823
EXPECTED_DIALOGUE_ROWS=1761
EXPECTED_TOP5_COVERED_VOICES=1715
EXPECTED_CHECKPOINT_ONLY_VOICES=108

EXPECTED_CHAIN_COUNTS={0.06:1700,0.08:1698,0.10:1695}
EXPECTED_CONSENSUS=1695
EXPECTED_GROUP_COUNTS={0:157,1:1528,2:64,3:9,4:3}
EXPECTED_SPEAKER_INCOMPATIBLE_GROUPS=26
EXPECTED_POTENTIAL_SPLIT_ROWS=206
EXPECTED_REVIEW_GROUPS=344

THRESHOLDS=(0.06,0.08,0.10)
MIN_TIME_GAP_SEC=0.020

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

def sha256_bytes(b:bytes):
    return hashlib.sha256(b).hexdigest()

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):
            h.update(x)
    return h.hexdigest()

def read_tsv(path:Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def read_tsv_bytes(b:bytes):
    return list(csv.DictReader(io.StringIO(b.decode("utf-8-sig")),delimiter="\t"))

def write_tsv(path:Path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def pin_file(path:Path,expected:str,name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def load_checkpoint(root:Path):
    direct=root/"analysis"/"sub"/"sub25_fix1_voice_timeline_reconstruction"/"sub25_fix1_search_checkpoint.tsv"
    if direct.exists():
        b=direct.read_bytes()
        if sha256_bytes(b).lower()!=EXPECTED_CHECKPOINT_SHA:
            raise RuntimeError(
                f"SUB25 FIX1 checkpoint SHA mismatch: {sha256_bytes(b)}"
            )
        return read_tsv_bytes(b),str(direct),"DIRECT_STAGE_FILE"

    zpath=root/"logs"/"fail_naruto_sub25_fix1_voice_timeline_reconstruction_upload.zip"
    if zpath.exists():
        with zipfile.ZipFile(zpath) as z:
            name="sub25_fix1_search_checkpoint.tsv"
            if name not in z.namelist():
                raise RuntimeError(f"{zpath} lacks {name}")
            b=z.read(name)
        if sha256_bytes(b).lower()!=EXPECTED_CHECKPOINT_SHA:
            raise RuntimeError(
                f"checkpoint-in-fail-ZIP SHA mismatch: {sha256_bytes(b)}"
            )
        return read_tsv_bytes(b),str(zpath)+" :: "+name,"FAIL_ZIP_FALLBACK"

    raise RuntimeError(
        "SUB25 FIX1 checkpoint not found in stage dir or canonical fail ZIP"
    )

class FenwickMax:
    def __init__(self,n):
        self.n=n
        self.v=[(-1.0e100,-1)]*(n+1)
    def query(self,i):
        if i<0:return (0.0,-1)
        i+=1
        best=(-1.0e100,-1)
        while i>0:
            if self.v[i][0]>best[0]:
                best=self.v[i]
            i-=i&-i
        return (0.0,-1) if best[0]<-1.0e50 else best
    def update(self,i,item):
        i+=1
        while i<=self.n:
            if item[0]>self.v[i][0]:
                self.v[i]=item
            i+=i&-i

def build_chain(observations_by_gpos,threshold):
    all_times=sorted({
        round(float(o["audio_time_sec"]),3)
        for xs in observations_by_gpos.values() for o in xs
        if float(o["score"])>threshold
    })
    if not all_times:return 0.0,[]

    fw=FenwickMax(len(all_times))
    nodes=[]
    prev=[]

    for gp in sorted(observations_by_gpos):
        pending=[]
        for o in observations_by_gpos[gp]:
            score=float(o["score"])
            if score<=threshold:
                continue
            t=round(float(o["audio_time_sec"]),3)
            q=bisect.bisect_left(all_times,round(t-MIN_TIME_GAP_SEC,3))-1
            base,pid=fw.query(q)
            value=base+(score-threshold)
            pending.append((o,value,pid,t))

        # Do not update until all candidates for this game row have queried.
        # This guarantees at most one observation from each game row in a chain.
        for o,value,pid,t in pending:
            idx=len(nodes)
            nodes.append(o)
            prev.append(pid)
            ti=bisect.bisect_left(all_times,t)
            fw.update(ti,(value,idx))

    value,idx=fw.query(len(all_times)-1)
    path=[]
    while idx!=-1:
        path.append(nodes[idx])
        idx=prev[idx]
    path.reverse()

    last_gp=-1
    last_t=-1.0e99
    seen=set()
    for o in path:
        gp=int(o["game_gpos"])
        t=float(o["audio_time_sec"])
        if gp<=last_gp:
            raise RuntimeError("chain game-order failure")
        if t<last_t+MIN_TIME_GAP_SEC-0.001:
            raise RuntimeError("chain time-order failure")
        if o["game_key"] in seen:
            raise RuntimeError("chain duplicate game row")
        seen.add(o["game_key"])
        last_gp=gp;last_t=t

    return value,path

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
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_top5=root/"analysis"/"sub"/"sub23_audio_rescoring_audit"/"sub23_top5_candidate_scores.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned evidence",flush=True)
    top5=pin_file(p_top5,EXPECTED_TOP5_SHA,"SUB23 top5")
    kr=pin_file(p_kr,EXPECTED_KR_SHA,"SUB19 KR")
    us=pin_file(p_us,EXPECTED_US_SHA,"SUB19 US")
    sub=pin_file(p_sub,EXPECTED_SUB09_SHA,"SUB09")
    checkpoint,checkpoint_source,checkpoint_mode=load_checkpoint(root)
    print(f"  checkpoint={checkpoint_source}",flush=True)
    print(f"  mode={checkpoint_mode}",flush=True)

    if len(checkpoint)!=EXPECTED_VOICED_ROWS:
        raise RuntimeError(
            f"checkpoint rows={len(checkpoint)} expected={EXPECTED_VOICED_ROWS}"
        )

    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=EXPECTED_GAME_ROWS:
        raise RuntimeError(f"game rows={len(game)} expected={EXPECTED_GAME_ROWS}")
    game_pos={game_key(r):i for i,r in enumerate(game)}
    game_by_key={game_key(r):r for r in game}
    voiced_keys={game_key(r) for r in game if r["voice_id"]}
    if len(voiced_keys)!=EXPECTED_VOICED_ROWS:
        raise RuntimeError(f"voiced rows={len(voiced_keys)}")

    dialogue=[
        r for r in sub
        if r["entry_type"]=="DIALOGUE"
        and 19<=int(r["sequence"])<=1883
    ]
    if len(dialogue)!=EXPECTED_DIALOGUE_ROWS:
        raise RuntimeError(f"dialogue rows={len(dialogue)}")

    print("[2/7] Build all direct audio observations",flush=True)
    obs_by_part=defaultdict(lambda:defaultdict(list))
    top5_covered=set()

    for r in top5:
        k=r["game_key"]
        if k not in voiced_keys:
            continue
        gp=game_pos[k]
        top5_covered.add(k)
        obs_by_part[r["video_part"]][gp].append({
            "game_key":k,
            "game_gpos":gp,
            "voice_id":r["voice_id"],
            "video_part":r["video_part"],
            "audio_time_sec":float(r["best_audio_time_sec"]),
            "score":float(r["score"]),
            "source":"SUB23_TOP5",
            "source_sub09_sequence":int(r["sub09_sequence"]),
            "source_rank":int(r["rank"]),
        })

    cp_by={r["game_key"]:r for r in checkpoint}
    missing=voiced_keys-top5_covered
    if len(top5_covered)!=EXPECTED_TOP5_COVERED_VOICES:
        raise RuntimeError(
            f"top5 covered voices={len(top5_covered)} "
            f"expected={EXPECTED_TOP5_COVERED_VOICES}"
        )
    if len(missing)!=EXPECTED_CHECKPOINT_ONLY_VOICES:
        raise RuntimeError(
            f"checkpoint-only voices={len(missing)} "
            f"expected={EXPECTED_CHECKPOINT_ONLY_VOICES}"
        )

    for k in sorted(missing,key=lambda x:game_pos[x]):
        r=cp_by.get(k)
        if not r:
            raise RuntimeError(f"checkpoint lacks top5-uncovered voice: {k}")
        if r["search_error"]:
            raise RuntimeError(f"checkpoint search error {k}: {r['search_error']}")
        gp=game_pos[k]
        obs_by_part[r["video_part"]][gp].append({
            "game_key":k,
            "game_gpos":gp,
            "voice_id":r["voice_id"],
            "video_part":r["video_part"],
            "audio_time_sec":float(r["matched_time_sec"]),
            "score":float(r["best_score"]),
            "source":"SUB25_FIX1_CHECKPOINT",
            "source_sub09_sequence":0,
            "source_rank":0,
        })

    # Robustly confirm a single part boundary using strong direct observations.
    strong_p1=[]
    strong_p2=[]
    for part in ("part1","part2"):
        for gp,xs in obs_by_part[part].items():
            if any(float(x["score"])>=0.30 for x in xs):
                (strong_p1 if part=="part1" else strong_p2).append(gp)
    if not strong_p1 or not strong_p2:
        raise RuntimeError("cannot infer Part1/Part2 boundary")
    p1max=max(strong_p1);p2min=min(strong_p2)
    if p1max>=p2min:
        raise RuntimeError(
            f"Part1/Part2 strong-observation overlap: {p1max} >= {p2min}"
        )
    print(
        f"  top5-covered={len(top5_covered)} checkpoint-only={len(missing)}",
        flush=True
    )
    print(f"  part boundary: Part1 max gpos={p1max}, Part2 min gpos={p2min}",flush=True)

    print("[3/7] Solve 3 weighted game-order x audio-time chains",flush=True)
    chain_results={}
    selected_by_thr={}
    for thr in THRESHOLDS:
        rows=[]
        objective=0.0
        for part in ("part1","part2"):
            v,p=build_chain(obs_by_part[part],thr)
            objective+=v
            rows.extend(p)
        rows.sort(key=lambda x:int(x["game_gpos"]))
        chain_results[thr]={
            "threshold":thr,
            "selected_rows":len(rows),
            "objective":objective,
        }
        selected_by_thr[thr]={r["game_key"]:r for r in rows}
        exp=EXPECTED_CHAIN_COUNTS[thr]
        if len(rows)!=exp:
            raise RuntimeError(
                f"threshold {thr:.2f} selected={len(rows)} expected={exp}"
            )
        print(
            f"  threshold={thr:.2f} selected={len(rows)} "
            f"objective={objective:.6f}",
            flush=True
        )

    print("[4/7] Intersect the 3 chains at exact observation/time",flush=True)
    common=set.intersection(*(set(x) for x in selected_by_thr.values()))
    consensus=[]
    for k in sorted(common,key=lambda x:game_pos[x]):
        obs=[selected_by_thr[t][k] for t in THRESHOLDS]
        signatures={
            (
                round(float(o["audio_time_sec"]),3),
                round(float(o["score"]),6),
                o["source"],
                int(o["source_sub09_sequence"]),
                int(o["source_rank"]),
            )
            for o in obs
        }
        if len(signatures)!=1:
            continue
        consensus.append(obs[1])  # 0.08 representative

    if len(consensus)!=EXPECTED_CONSENSUS:
        raise RuntimeError(
            f"played consensus={len(consensus)} expected={EXPECTED_CONSENSUS}"
        )

    # Strict monotonicity per part.
    for part in ("part1","part2"):
        xs=[r for r in consensus if r["video_part"]==part]
        last_gp=-1;last_t=-1e99
        for r in xs:
            gp=int(r["game_gpos"]);t=float(r["audio_time_sec"])
            if gp<=last_gp or t<last_t+MIN_TIME_GAP_SEC-0.001:
                raise RuntimeError(f"consensus monotonicity failure at {r['game_key']}")
            last_gp=gp;last_t=t

    consensus_keys={r["game_key"] for r in consensus}
    for k in (
        "event000.tbl#001",
        "event000.tbl#011",
        "event000.tbl#012",
        "event003.tbl#047",
        "event112.tbl#122",
    ):
        if k not in consensus_keys:
            raise RuntimeError(f"required voice missing from consensus: {k}")

    print(f"  exact 3-threshold consensus={len(consensus)}",flush=True)

    print("[5/7] Add game/US metadata",flush=True)
    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:
            us_by[(r["event_file"],r["voice_id"])].append(r)

    timeline=[]
    for o in consensus:
        g=game_by_key[o["game_key"]]
        hits=us_by.get((g["event_file"],g["voice_id"]),[])
        timeline.append({
            "game_key":o["game_key"],
            "game_global_dialogue_index":int(o["game_gpos"])+1,
            "event_file":g["event_file"],
            "event_display_index":g["event_display_index"],
            "command":g["command"],
            "speaker_code":g["speaker_code"],
            "voice_id":g["voice_id"],
            "japanese":g["text"],
            "video_part":o["video_part"],
            "audio_time_sec":f"{float(o['audio_time_sec']):.3f}",
            "audio_score":f"{float(o['score']):.6f}",
            "observation_source":o["source"],
            "observation_sub09_sequence":o["source_sub09_sequence"],
            "observation_rank":o["source_rank"],
            "us_match_count":len(hits),
            "english":" || ".join(x["text"] for x in hits),
        })

    timeline_by_key={r["game_key"]:r for r in timeline}

    print("[6/7] Group played voice starts by subtitle-frame intervals",flush=True)
    inv_speaker=invert_speaker_map()
    groups=[]
    details=[]

    for part in ("part1","part2"):
        subs=sorted(
            [r for r in dialogue if r["video_part"]==part],
            key=lambda r:float(r["observed_first_sec"])
        )
        voices=sorted(
            [r for r in timeline if r["video_part"]==part],
            key=lambda r:float(r["audio_time_sec"])
        )
        times=[float(r["audio_time_sec"]) for r in voices]

        previous_frame=0.0
        for s in subs:
            seq=int(s["sequence"])
            current=float(s["observed_first_sec"])
            lo=bisect.bisect_right(times,previous_frame+0.05)
            hi=bisect.bisect_right(times,current+0.05)
            assigned=voices[lo:hi]

            sp=SUB_SPEAKER_NORMALIZE.get(s["speaker"],s["speaker"])
            allowed=inv_speaker.get(sp,set())
            incompatible=[]
            for r in assigned:
                code=r["speaker_code"]
                if code and sp and code not in allowed:
                    incompatible.append(r)

            n=len(assigned)
            group_kind="0G_1S" if n==0 else "1G_1S" if n==1 else f"{n}G_1S"
            groups.append({
                "sub09_sequence":seq,
                "video_part":part,
                "observed_first_sec":s["observed_first_sec"],
                "speaker":s["speaker"],
                "korean":s["text"],
                "previous_dialogue_frame_sec":f"{previous_frame:.3f}",
                "assigned_game_count":n,
                "group_kind":group_kind,
                "assigned_game_keys":" | ".join(r["game_key"] for r in assigned),
                "assigned_voice_ids":" | ".join(r["voice_id"] for r in assigned),
                "assigned_speaker_codes":" | ".join(r["speaker_code"] or "<BLANK>" for r in assigned),
                "assigned_voice_times":" | ".join(r["audio_time_sec"] for r in assigned),
                "assigned_scores":" | ".join(r["audio_score"] for r in assigned),
                "speaker_compatible_count":n-len(incompatible),
                "speaker_incompatible_count":len(incompatible),
                "speaker_incompatible_game_keys":" | ".join(r["game_key"] for r in incompatible),
                "potential_1G_2S_split":"NO",
            })

            for order,r in enumerate(assigned,1):
                details.append({
                    "sub09_sequence":seq,
                    "group_order":order,
                    "video_part":part,
                    "subtitle_speaker":s["speaker"],
                    "korean":s["text"],
                    **r,
                    "speaker_compatible":"NO" if r in incompatible else "YES",
                })

            previous_frame=current

    group_by_seq={int(r["sub09_sequence"]):r for r in groups}

    # Detect adjacent same-speaker 0G/1+G patterns likely caused by one game MSG
    # being split over two cleaned subtitle entries.
    split_flags=set()
    for part in ("part1","part2"):
        xs=[r for r in groups if r["video_part"]==part]
        for a,b in zip(xs,xs[1:]):
            sa=SUB_SPEAKER_NORMALIZE.get(a["speaker"],a["speaker"])
            sb=SUB_SPEAKER_NORMALIZE.get(b["speaker"],b["speaker"])
            gap=float(b["observed_first_sec"])-float(a["observed_first_sec"])
            na=int(a["assigned_game_count"]);nb=int(b["assigned_game_count"])
            if sa and sa==sb and gap<=6.0:
                if (na==0 and nb>=1) or (nb==0 and na>=1):
                    split_flags.add(int(a["sub09_sequence"]))
                    split_flags.add(int(b["sub09_sequence"]))

    for r in groups:
        if int(r["sub09_sequence"]) in split_flags:
            r["potential_1G_2S_split"]="YES"

    # Hard semantic-structure evidence checks.
    g29=group_by_seq[29]
    k29={x.strip() for x in g29["assigned_game_keys"].split("|") if x.strip()}
    if not {"event000.tbl#011","event000.tbl#012"}.issubset(k29):
        raise RuntimeError(f"#29 merge check failed: {g29['assigned_game_keys']}")

    g164=group_by_seq[164]
    if "event003.tbl#047" not in g164["assigned_game_keys"]:
        raise RuntimeError(f"#164 true voice missing from group: {g164['assigned_game_keys']}")

    g1883=group_by_seq[1883]
    if "event112.tbl#122" not in g1883["assigned_game_keys"]:
        raise RuntimeError(f"#1883 final voice missing from group: {g1883['assigned_game_keys']}")

    # #38/#39 is a known useful split pattern in this region.
    if 38 not in split_flags or 39 not in split_flags:
        raise RuntimeError("#38/#39 expected split diagnostic was not detected")

    print("[7/7] Write outputs / exact regression checks",flush=True)
    group_counts=Counter(int(r["assigned_game_count"]) for r in groups)
    got_group_counts={k:group_counts.get(k,0) for k in EXPECTED_GROUP_COUNTS}
    if got_group_counts!=EXPECTED_GROUP_COUNTS:
        raise RuntimeError(
            f"group counts={got_group_counts} expected={EXPECTED_GROUP_COUNTS}"
        )

    incompatible_groups=sum(
        1 for r in groups if int(r["speaker_incompatible_count"])>0
    )
    if incompatible_groups!=EXPECTED_SPEAKER_INCOMPATIBLE_GROUPS:
        raise RuntimeError(
            f"speaker-incompatible groups={incompatible_groups} "
            f"expected={EXPECTED_SPEAKER_INCOMPATIBLE_GROUPS}"
        )
    if len(split_flags)!=EXPECTED_POTENTIAL_SPLIT_ROWS:
        raise RuntimeError(
            f"potential split rows={len(split_flags)} "
            f"expected={EXPECTED_POTENTIAL_SPLIT_ROWS}"
        )

    review_groups=[
        r for r in groups
        if int(r["assigned_game_count"])!=1
        or int(r["speaker_incompatible_count"])>0
        or r["potential_1G_2S_split"]=="YES"
    ]
    if len(review_groups)!=EXPECTED_REVIEW_GROUPS:
        raise RuntimeError(
            f"review groups={len(review_groups)} expected={EXPECTED_REVIEW_GROUPS}"
        )

    timeline_fields=[
        "game_key","game_global_dialogue_index","event_file","event_display_index",
        "command","speaker_code","voice_id","japanese","video_part",
        "audio_time_sec","audio_score","observation_source",
        "observation_sub09_sequence","observation_rank","us_match_count","english"
    ]
    write_tsv(out/"sub25_fix2_played_voice_timeline.tsv",timeline,timeline_fields)

    group_fields=[
        "sub09_sequence","video_part","observed_first_sec","speaker","korean",
        "previous_dialogue_frame_sec","assigned_game_count","group_kind",
        "assigned_game_keys","assigned_voice_ids","assigned_speaker_codes",
        "assigned_voice_times","assigned_scores","speaker_compatible_count",
        "speaker_incompatible_count","speaker_incompatible_game_keys",
        "potential_1G_2S_split"
    ]
    write_tsv(out/"sub25_fix2_subtitle_voice_groups.tsv",groups,group_fields)
    write_tsv(out/"sub25_fix2_review_groups.tsv",review_groups,group_fields)

    detail_fields=[
        "sub09_sequence","group_order","video_part","subtitle_speaker","korean",
        "game_key","game_global_dialogue_index","event_file","event_display_index",
        "command","speaker_code","voice_id","japanese","audio_time_sec","audio_score",
        "observation_source","observation_sub09_sequence","observation_rank",
        "us_match_count","english","speaker_compatible"
    ]
    write_tsv(out/"sub25_fix2_group_detail.tsv",details,detail_fields)

    variant_rows=[]
    for thr in THRESHOLDS:
        x=chain_results[thr]
        variant_rows.append({
            "threshold":f"{thr:.2f}",
            "selected_rows":x["selected_rows"],
            "objective":f"{x['objective']:.9f}",
        })
    write_tsv(
        out/"sub25_fix2_chain_summary.tsv",
        variant_rows,
        ["threshold","selected_rows","objective"]
    )

    merge29=[
        r for r in details
        if int(r["sub09_sequence"])==29
    ]
    write_tsv(out/"sub25_fix2_known_merge29.tsv",merge29,detail_fields)

    # Compact human review packet: exceptional groups only.
    detail_by_seq=defaultdict(list)
    for r in details:
        detail_by_seq[int(r["sub09_sequence"])].append(r)

    packet=[
        "Naruto PSP SUB25 FIX2 - Exceptional Voice Group Review",
        "="*100,
        "",
        "These are timing/voice grouping candidates, not semantic-final mappings.",
        "",
    ]
    for r in review_groups:
        seq=int(r["sub09_sequence"])
        packet += [
            "",
            "#"*100,
            f"SUB09 #{seq} [{r['group_kind']}] {r['speaker']}",
            f"KO: {r['korean']}",
            f"frame={r['observed_first_sec']} split={r['potential_1G_2S_split']} "
            f"incompatible={r['speaker_incompatible_count']}",
        ]
        if not detail_by_seq[seq]:
            packet.append("  (no consensus game voice start in this frame interval)")
        for d in detail_by_seq[seq]:
            packet += [
                f"  {d['game_key']} {d['voice_id']} t={d['audio_time_sec']} "
                f"score={d['audio_score']} speaker_ok={d['speaker_compatible']}",
                f"    JP: {d['japanese']}",
                f"    EN: {d['english']}",
            ]
    (out/"sub25_fix2_review_packet.txt").write_text(
        "\n".join(packet)+"\n",encoding="utf-8-sig"
    )

    report={
        "stage":"SUB25_FIX2",
        "mode":"READ_ONLY_FULL_VOICE_OBSERVATION_2D_MONOTONIC_RECONSTRUCTION",
        "checkpoint_source":checkpoint_source,
        "checkpoint_mode":checkpoint_mode,
        "game_rows":len(game),
        "voiced_game_rows":len(voiced_keys),
        "top5_covered_voice_rows":len(top5_covered),
        "checkpoint_only_voice_rows":len(missing),
        "part1_strong_max_gpos":p1max,
        "part2_strong_min_gpos":p2min,
        "chain_counts":{
            f"{t:.2f}":chain_results[t]["selected_rows"] for t in THRESHOLDS
        },
        "played_voice_consensus":len(timeline),
        "subtitle_dialogue_rows":len(groups),
        "group_count_distribution":{
            str(k):v for k,v in sorted(group_counts.items())
        },
        "speaker_incompatible_groups":incompatible_groups,
        "potential_1G_2S_split_rows":len(split_flags),
        "review_groups":len(review_groups),
        "known_merge29":[r["game_key"] for r in merge29],
        "required_anchors":{
            "SUB09_164":"event003.tbl#047",
            "SUB09_1883":"event112.tbl#122",
        },
        "semantic_final_claim":False,
        "game_files_modified":False,
    }
    (out/"sub25_fix2_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB25 FIX2 - Full Voice Observation Monotonic Reconstruction",
        "",
        f"CheckpointMode={checkpoint_mode}",
        f"GameRows={len(game)}",
        f"VoicedGameRows={len(voiced_keys)}",
        f"Top5CoveredVoiceRows={len(top5_covered)}",
        f"CheckpointOnlyVoiceRows={len(missing)}",
        "",
    ]
    for thr in THRESHOLDS:
        summary.append(
            f"Threshold{thr:.2f}Selected={chain_results[thr]['selected_rows']}"
        )
    summary += [
        f"PlayedVoiceConsensus={len(timeline)}",
        f"SubtitleDialogueRows={len(groups)}",
        "GroupCounts="+json.dumps(
            {str(k):v for k,v in sorted(group_counts.items())},
            ensure_ascii=False
        ),
        f"SpeakerIncompatibleGroups={incompatible_groups}",
        f"Potential1G2SSplitRows={len(split_flags)}",
        f"ReviewGroups={len(review_groups)}",
        "",
        "Known checks:",
        "  #29  -> event000#011 + event000#012",
        "  #164 -> event003#047",
        "  #1883 -> event112#122",
        "  #38/#39 detected as potential one-game-to-two-subtitle split",
        "",
        "Important:",
        "  SUB24 core rows are NOT fixed truth in FIX2.",
        "  All available direct audio observations compete under global",
        "  game-order + audio-time monotonicity.",
        "",
        "No audio is decoded again.",
        "No TBL/DAT/BOOT/ISO files were modified.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
