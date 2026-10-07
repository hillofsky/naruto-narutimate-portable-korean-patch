#!/usr/bin/env python3
# Naruto PSP SUB24 - Global monotonic audio ensemble alignment
#
# Read-only.
#
# Inputs:
#   SUB23 audio audit + top5 candidate scores
#   SUB19 KR/US decoded message inventories
#   SUB09 final subtitle corpus
#
# Goal:
#   Correct local audio top1 mistakes by enforcing GLOBAL game-message order.
#
# Five independent weighted strictly-increasing chains are built over the same
# top5 audio candidates. Only subtitle rows where ALL FIVE variants select the
# SAME game row are called AUDIO_MONOTONIC_CONSENSUS.
#
# A stricter AUDIO_MONOTONIC_CORE additionally requires:
#   - original SUB23 audio confidence is STRONG or VERY_STRONG
#   - no >0.5 sec local audio-time reversal against neighboring consensus anchors
#
# No semantic-final claim and no game patching.

from __future__ import annotations
import argparse, bisect, csv, hashlib, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_SUB23_AUDIT_SHA="94bd6b542630736d1cde62dd14d96d73ac6e88f51f36f15ac6a75dd23bc282d4"
EXPECTED_SUB23_TOP5_SHA="7be8e92a0c6427a93cda17fd4007eeaa7a934695044c2ee6a3cdbfba280b5cdc"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_US_SHA="1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"

EXPECTED_DIALOGUE_ROWS=1761
EXPECTED_GAME_ROWS=1976
EXPECTED_CONSENSUS=1565
EXPECTED_CORE=1368
EXPECTED_REVIEW=393
EXPECTED_REVIEW_BLOCKS=302

VARIANTS={
    "RAW": lambda score,rank: score,
    "RANK_LIGHT": lambda score,rank: score - 0.010*(rank-1),
    "RANK_MED": lambda score,rank: score - 0.025*(rank-1),
    "SQUARED": lambda score,rank: score*score,
    "THRESH": lambda score,rank: max(0.0,score-0.050),
}

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

def pin(path:Path,expected:str,name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return got

class FenwickMax:
    def __init__(self,n):
        self.n=n
        self.val=[(-1.0e100,-1)]*(n+1)
    def query(self,i):
        # max over [0..i]
        if i<0:return (0.0,-1)
        i+=1
        best=(-1.0e100,-1)
        while i>0:
            if self.val[i][0]>best[0]:
                best=self.val[i]
            i-=i&-i
        if best[0]<-1.0e50:
            return (0.0,-1)
        return best
    def update(self,i,item):
        i+=1
        while i<=self.n:
            if item[0]>self.val[i][0]:
                self.val[i]=item
            i+=i&-i

def build_chain(by_seq,game_count,weight_name,weight_fn):
    fw=FenwickMax(game_count)
    points=[]
    values=[]
    prev=[]

    for seq in sorted(by_seq):
        pending=[]
        # IMPORTANT: query all candidates before updating this subtitle,
        # so one subtitle cannot contribute multiple nodes to a chain.
        for c in sorted(by_seq[seq],key=lambda r:int(r["rank"])):
            base,pid=fw.query(c["_gpos"]-1)
            score=float(c["score"])
            rank=int(c["rank"])
            value=base+weight_fn(score,rank)
            pending.append((c,value,pid))

        for c,value,pid in pending:
            idx=len(points)
            points.append(c)
            values.append(value)
            prev.append(pid)
            fw.update(c["_gpos"],(value,idx))

    best_value,best_idx=fw.query(game_count-1)
    path=[]
    while best_idx!=-1:
        path.append(points[best_idx])
        best_idx=prev[best_idx]
    path.reverse()

    # hard invariants
    last_seq=-1
    last_g=-1
    seen_game=set()
    for r in path:
        seq=int(r["sub09_sequence"])
        gp=int(r["_gpos"])
        if seq<=last_seq or gp<=last_g:
            raise RuntimeError(f"{weight_name}: chain monotonicity failure at seq={seq}")
        if r["game_key"] in seen_game:
            raise RuntimeError(f"{weight_name}: duplicate game key {r['game_key']}")
        seen_game.add(r["game_key"])
        last_seq=seq;last_g=gp

    return best_value,path

def unique_us_map(rows):
    x=defaultdict(list)
    for r in rows:
        if r["voice_id"]:
            x[(r["event_file"],r["voice_id"])].append(r)
    return x

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_audit=root/"analysis"/"sub"/"sub23_audio_rescoring_audit"/"sub23_audio_audit.tsv"
    p_top5=root/"analysis"/"sub"/"sub23_audio_rescoring_audit"/"sub23_top5_candidate_scores.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned inputs",flush=True)
    pin(p_audit,EXPECTED_SUB23_AUDIT_SHA,"SUB23 audit")
    pin(p_top5,EXPECTED_SUB23_TOP5_SHA,"SUB23 top5")
    pin(p_kr,EXPECTED_KR_SHA,"SUB19 KR")
    pin(p_us,EXPECTED_US_SHA,"SUB19 US")
    pin(p_sub,EXPECTED_SUB09_SHA,"SUB09")

    audit=read_tsv(p_audit)
    top5=read_tsv(p_top5)
    kr=read_tsv(p_kr)
    us=read_tsv(p_us)
    sub=read_tsv(p_sub)

    if len(audit)!=EXPECTED_DIALOGUE_ROWS:
        raise RuntimeError(f"SUB23 audit rows={len(audit)} expected={EXPECTED_DIALOGUE_ROWS}")

    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=EXPECTED_GAME_ROWS:
        raise RuntimeError(f"game rows={len(game)} expected={EXPECTED_GAME_ROWS}")

    game_by_key={game_key(r):r for r in game}
    game_pos={game_key(r):i for i,r in enumerate(game)}
    audit_by_seq={int(r["sub09_sequence"]):r for r in audit}
    sub_by_seq={int(r["sequence"]):r for r in sub}
    us_by_voice=unique_us_map(us)

    print("[2/7] Build top5 candidate matrix",flush=True)
    by_seq=defaultdict(list)
    for r in top5:
        k=r["game_key"]
        if k not in game_pos:
            raise RuntimeError(f"top5 game key missing: {k}")
        x=dict(r)
        x["_gpos"]=game_pos[k]
        by_seq[int(r["sub09_sequence"])].append(x)

    if len(by_seq)!=EXPECTED_DIALOGUE_ROWS:
        raise RuntimeError(f"top5 subtitle rows={len(by_seq)} expected={EXPECTED_DIALOGUE_ROWS}")

    print("[3/7] Run five independent global monotonic chains",flush=True)
    chains={}
    variant_summary=[]
    for name,fn in VARIANTS.items():
        value,path=build_chain(by_seq,len(game),name,fn)
        chains[name]={int(r["sub09_sequence"]):r for r in path}
        variant_summary.append({
            "variant":name,
            "selected_rows":len(path),
            "objective_value":f"{value:.9f}",
            "first_sub09_sequence":int(path[0]["sub09_sequence"]),
            "last_sub09_sequence":int(path[-1]["sub09_sequence"]),
            "first_game":path[0]["game_key"],
            "last_game":path[-1]["game_key"],
        })
        print(f"  {name}: selected={len(path)} objective={value:.6f}",flush=True)

    print("[4/7] Compute five-variant exact consensus",flush=True)
    consensus=[]
    all_seqs=[int(r["sub09_sequence"]) for r in audit]
    for seq in all_seqs:
        selected=[chains[n].get(seq) for n in VARIANTS]
        if all(selected):
            keys={r["game_key"] for r in selected}
            if len(keys)==1:
                consensus.append(selected[0])

    if len(consensus)!=EXPECTED_CONSENSUS:
        raise RuntimeError(f"consensus={len(consensus)} expected={EXPECTED_CONSENSUS}")

    consensus_by_seq={int(r["sub09_sequence"]):r for r in consensus}

    # Global strict game-order check.
    last=-1
    seen=set()
    for c in consensus:
        gp=game_pos[c["game_key"]]
        if gp<=last:
            raise RuntimeError(f"consensus game order violation at SUB09#{c['sub09_sequence']}")
        if c["game_key"] in seen:
            raise RuntimeError(f"consensus duplicate game row: {c['game_key']}")
        last=gp;seen.add(c["game_key"])

    # Known correctness anchors.
    expected_anchors={
        19:("event000.tbl#001","s_a01_000"),
        164:("event003.tbl#047","s_a06_043"),
        1883:("event112.tbl#122","s_b15_079"),
    }
    for seq,(k,v) in expected_anchors.items():
        c=consensus_by_seq.get(seq)
        if not c:
            raise RuntimeError(f"required anchor SUB09#{seq} missing from consensus")
        if c["game_key"]!=k or c["voice_id"]!=v:
            raise RuntimeError(
                f"anchor mismatch SUB09#{seq}: {c['game_key']} {c['voice_id']} != {k} {v}"
            )

    print("[5/7] Audit local audio-time order",flush=True)
    time_warning_seqs=set()
    time_pairs=[]
    for part in ("part1","part2"):
        rows=[
            c for c in consensus
            if audit_by_seq[int(c["sub09_sequence"])]["video_part"]==part
        ]
        for a,b in zip(rows,rows[1:]):
            ta=float(a["best_audio_time_sec"])
            tb=float(b["best_audio_time_sec"])
            if tb < ta-0.5:
                sa=int(a["sub09_sequence"]);sb=int(b["sub09_sequence"])
                time_warning_seqs.update((sa,sb))
                time_pairs.append({
                    "video_part":part,
                    "previous_sub09_sequence":sa,
                    "previous_game":a["game_key"],
                    "previous_voice":a["voice_id"],
                    "previous_best_audio_time_sec":f"{ta:.3f}",
                    "next_sub09_sequence":sb,
                    "next_game":b["game_key"],
                    "next_voice":b["voice_id"],
                    "next_best_audio_time_sec":f"{tb:.3f}",
                    "time_reversal_sec":f"{tb-ta:+.3f}",
                })

    print(f"  time-order warning pairs={len(time_pairs)} rows={len(time_warning_seqs)}",flush=True)

    print("[6/7] Build consensus/core/review tables",flush=True)
    consensus_rows=[]
    core_rows=[]
    review_rows=[]

    for seq in all_seqs:
        a=audit_by_seq[seq]
        c=consensus_by_seq.get(seq)

        if c:
            g=game_by_key[c["game_key"]]
            ushits=us_by_voice.get((g["event_file"],g["voice_id"]),[])
            english=" || ".join(x["text"] for x in ushits)

            row={
                "sub09_sequence":seq,
                "video_part":a["video_part"],
                "timestamp_sec":a["timestamp_sec"],
                "speaker":a["speaker"],
                "korean":a["korean"],
                "game_key":c["game_key"],
                "game_global_dialogue_index":game_pos[c["game_key"]]+1,
                "event_file":g["event_file"],
                "event_display_index":g["event_display_index"],
                "command":g["command"],
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "us_match_count":len(ushits),
                "english":english,
                "selected_rank":c["rank"],
                "selected_audio_score":c["score"],
                "selected_best_audio_time_sec":c["best_audio_time_sec"],
                "selected_delta_from_frame_sec":c["delta_from_frame_sec"],
                "sub23_top1_game":a["audio_top_game"],
                "sub23_top1_voice":a["audio_top_voice"],
                "sub23_top1_score":a["audio_top_score"],
                "sub23_audio_confidence":a["audio_confidence"],
                "sub20_structural_consensus_game":a["structural_consensus_game"],
                "selected_equals_sub23_top1":"YES" if c["game_key"]==a["audio_top_game"] else "NO",
                "selected_equals_sub20_structural":"YES" if c["game_key"]==a["structural_consensus_game"] else "NO",
                "audio_time_order_warning":"YES" if seq in time_warning_seqs else "NO",
                "five_variant_monotonic_consensus":"YES",
            }
            consensus_rows.append(row)

            is_core=(
                a["audio_confidence"] in ("VERY_STRONG","STRONG")
                and seq not in time_warning_seqs
            )
            if is_core:
                core_rows.append(row)
            else:
                reasons=[]
                if a["audio_confidence"] not in ("VERY_STRONG","STRONG"):
                    reasons.append("AUDIO_CONFIDENCE_"+a["audio_confidence"])
                if seq in time_warning_seqs:
                    reasons.append("AUDIO_TIME_ORDER_WARNING")
                rr=dict(row)
                rr["review_reasons"]=" | ".join(reasons)
                review_rows.append(rr)
        else:
            # No five-variant exact consensus.
            rr={
                "sub09_sequence":seq,
                "video_part":a["video_part"],
                "timestamp_sec":a["timestamp_sec"],
                "speaker":a["speaker"],
                "korean":a["korean"],
                "game_key":"",
                "game_global_dialogue_index":"",
                "event_file":"",
                "event_display_index":"",
                "command":"",
                "speaker_code":"",
                "voice_id":"",
                "japanese":"",
                "us_match_count":"",
                "english":"",
                "selected_rank":"",
                "selected_audio_score":"",
                "selected_best_audio_time_sec":"",
                "selected_delta_from_frame_sec":"",
                "sub23_top1_game":a["audio_top_game"],
                "sub23_top1_voice":a["audio_top_voice"],
                "sub23_top1_score":a["audio_top_score"],
                "sub23_audio_confidence":a["audio_confidence"],
                "sub20_structural_consensus_game":a["structural_consensus_game"],
                "selected_equals_sub23_top1":"",
                "selected_equals_sub20_structural":"",
                "audio_time_order_warning":"NO",
                "five_variant_monotonic_consensus":"NO",
                "review_reasons":"NO_5_VARIANT_MONOTONIC_CONSENSUS",
            }
            review_rows.append(rr)

    if len(core_rows)!=EXPECTED_CORE:
        raise RuntimeError(f"core={len(core_rows)} expected={EXPECTED_CORE}")
    if len(review_rows)!=EXPECTED_REVIEW:
        raise RuntimeError(f"review={len(review_rows)} expected={EXPECTED_REVIEW}")

    base_fields=[
        "sub09_sequence","video_part","timestamp_sec","speaker","korean",
        "game_key","game_global_dialogue_index","event_file","event_display_index",
        "command","speaker_code","voice_id","japanese","us_match_count","english",
        "selected_rank","selected_audio_score","selected_best_audio_time_sec",
        "selected_delta_from_frame_sec","sub23_top1_game","sub23_top1_voice",
        "sub23_top1_score","sub23_audio_confidence",
        "sub20_structural_consensus_game",
        "selected_equals_sub23_top1","selected_equals_sub20_structural",
        "audio_time_order_warning","five_variant_monotonic_consensus",
    ]
    write_tsv(out/"sub24_audio_monotonic_consensus.tsv",consensus_rows,base_fields)
    write_tsv(out/"sub24_audio_monotonic_core.tsv",core_rows,base_fields)
    write_tsv(out/"sub24_review_rows.tsv",review_rows,base_fields+["review_reasons"])
    write_tsv(
        out/"sub24_variant_summary.tsv",variant_summary,
        [
            "variant","selected_rows","objective_value","first_sub09_sequence",
            "last_sub09_sequence","first_game","last_game"
        ]
    )
    write_tsv(
        out/"sub24_audio_time_order_warnings.tsv",time_pairs,
        [
            "video_part","previous_sub09_sequence","previous_game","previous_voice",
            "previous_best_audio_time_sec","next_sub09_sequence","next_game","next_voice",
            "next_best_audio_time_sec","time_reversal_sec"
        ]
    )

    # Review blocks based on CORE anchors, not all consensus anchors.
    core_set={int(r["sub09_sequence"]) for r in core_rows}
    blocks=[]
    cur=[]
    for seq in all_seqs:
        if seq in core_set:
            if cur:
                blocks.append(cur);cur=[]
        else:
            cur.append(seq)
    if cur:blocks.append(cur)

    if len(blocks)!=EXPECTED_REVIEW_BLOCKS:
        raise RuntimeError(f"review blocks={len(blocks)} expected={EXPECTED_REVIEW_BLOCKS}")

    review_by_seq={int(r["sub09_sequence"]):r for r in review_rows}
    core_by_seq={int(r["sub09_sequence"]):r for r in core_rows}
    pos={s:i for i,s in enumerate(all_seqs)}

    block_rows=[]
    packet_lines=[
        "Naruto PSP SUB24 - Audio Monotonic Review Packet",
        "="*100,
        "",
        "CORE anchors are strong audio+global-order evidence, not yet semantic-final proof.",
        "",
    ]

    for bi,bseqs in enumerate(blocks,1):
        i0=pos[bseqs[0]]
        i1=pos[bseqs[-1]]
        prev_seq=all_seqs[i0-1] if i0>0 and all_seqs[i0-1] in core_set else None
        next_seq=all_seqs[i1+1] if i1+1<len(all_seqs) and all_seqs[i1+1] in core_set else None

        block_rows.append({
            "block_id":bi,
            "first_sub09_sequence":bseqs[0],
            "last_sub09_sequence":bseqs[-1],
            "review_rows":len(bseqs),
            "sequences":" ".join(map(str,bseqs)),
            "previous_core_sub09_sequence":prev_seq or "",
            "previous_core_game":core_by_seq[prev_seq]["game_key"] if prev_seq else "",
            "next_core_sub09_sequence":next_seq or "",
            "next_core_game":core_by_seq[next_seq]["game_key"] if next_seq else "",
            "reasons":" || ".join(
                review_by_seq[s]["review_reasons"] for s in bseqs
            ),
        })

        packet_lines += [
            "",
            "#"*100,
            f"BLOCK {bi:03d}  SUB09 {bseqs[0]}..{bseqs[-1]}  rows={len(bseqs)}",
            "#"*100,
        ]
        if prev_seq:
            p=core_by_seq[prev_seq]
            packet_lines += [
                f"[PREV CORE] S{prev_seq} {p['speaker']}: {p['korean']}",
                f"  {p['game_key']} {p['voice_id']} score={p['selected_audio_score']} rank={p['selected_rank']}",
                f"  JP: {p['japanese']}",
                f"  EN: {p['english']}",
            ]
        for s in bseqs:
            r=review_by_seq[s]
            packet_lines += [
                "",
                f"[REVIEW] S{s} {r['speaker']}: {r['korean']}",
                f"  reason: {r['review_reasons']}",
                f"  SUB23 top1: {r['sub23_top1_game']} {r['sub23_top1_voice']} "
                f"score={r['sub23_top1_score']} confidence={r['sub23_audio_confidence']}",
            ]
            # include five audio candidates
            for c in sorted(by_seq[s],key=lambda x:int(x["rank"])):
                g=game_by_key[c["game_key"]]
                ush=us_by_voice.get((g["event_file"],g["voice_id"]),[])
                en=" || ".join(x["text"] for x in ush)
                selected_mark=" *CONSENSUS*" if r["game_key"] and c["game_key"]==r["game_key"] else ""
                packet_lines += [
                    f"    R{c['rank']} {c['game_key']} {c['voice_id']} "
                    f"score={c['score']} time={c['best_audio_time_sec']}{selected_mark}",
                    f"       JP: {g['text']}",
                    f"       EN: {en}",
                ]
        if next_seq:
            n=core_by_seq[next_seq]
            packet_lines += [
                "",
                f"[NEXT CORE] S{next_seq} {n['speaker']}: {n['korean']}",
                f"  {n['game_key']} {n['voice_id']} score={n['selected_audio_score']} rank={n['selected_rank']}",
                f"  JP: {n['japanese']}",
                f"  EN: {n['english']}",
            ]

    write_tsv(
        out/"sub24_review_blocks.tsv",block_rows,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence","review_rows",
            "sequences","previous_core_sub09_sequence","previous_core_game",
            "next_core_sub09_sequence","next_core_game","reasons"
        ]
    )
    (out/"sub24_review_packet.txt").write_text(
        "\n".join(packet_lines)+"\n",encoding="utf-8-sig"
    )

    print("[7/7] Final report",flush=True)
    rank_counts=Counter(int(r["selected_rank"]) for r in consensus_rows)
    review_reason_counts=Counter()
    for r in review_rows:
        for x in r["review_reasons"].split(" | "):
            if x:review_reason_counts[x]+=1

    report={
        "stage":"SUB24",
        "mode":"READ_ONLY_GLOBAL_MONOTONIC_AUDIO_ENSEMBLE",
        "dialogue_rows":EXPECTED_DIALOGUE_ROWS,
        "game_rows":EXPECTED_GAME_ROWS,
        "variant_selected_rows":{
            r["variant"]:r["selected_rows"] for r in variant_summary
        },
        "five_variant_exact_consensus":len(consensus_rows),
        "consensus_rank_distribution":dict(sorted(rank_counts.items())),
        "audio_monotonic_core":len(core_rows),
        "review_rows":len(review_rows),
        "review_blocks":len(blocks),
        "review_reason_counts":dict(review_reason_counts),
        "audio_time_order_warning_pairs":len(time_pairs),
        "audio_time_order_warning_rows":len(time_warning_seqs),
        "required_anchors":{
            "19":"event000.tbl#001 / s_a01_000",
            "164":"event003.tbl#047 / s_a06_043",
            "1883":"event112.tbl#122 / s_b15_079",
        },
        "semantic_final_claim":False,
        "game_files_modified":False,
    }
    (out/"sub24_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB24 - Global Monotonic Audio Ensemble",
        "",
        f"DialogueRows={EXPECTED_DIALOGUE_ROWS}",
        f"GameRows={EXPECTED_GAME_ROWS}",
        "",
    ]
    for r in variant_summary:
        summary.append(f"{r['variant']}SelectedRows={r['selected_rows']}")
    summary += [
        "",
        f"FiveVariantExactConsensus={len(consensus_rows)}",
        "ConsensusRankDistribution="+json.dumps(dict(sorted(rank_counts.items())),ensure_ascii=False),
        f"AudioMonotonicCore={len(core_rows)}",
        f"ReviewRows={len(review_rows)}",
        f"ReviewBlocks={len(blocks)}",
        f"AudioTimeOrderWarningPairs={len(time_pairs)}",
        f"AudioTimeOrderWarningRows={len(time_warning_seqs)}",
        "",
        "Required anchors:",
        "  SUB09 #19   -> event000.tbl#001 / s_a01_000",
        "  SUB09 #164  -> event003.tbl#047 / s_a06_043",
        "  SUB09 #1883 -> event112.tbl#122 / s_b15_079",
        "",
        "Important:",
        "  SUB23 local top1 is NOT used as final truth.",
        "  Five global monotonic variants correct cases such as #1883,",
        "  where local top1 repeats the previous voice and rank2 is the correct next row.",
        "",
        "  AUDIO_MONOTONIC_CORE is strong evidence, not semantic-final proof.",
        "  No TBL/DAT/BOOT/ISO files were modified.",
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
