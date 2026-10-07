#!/usr/bin/env python3
# Naruto PSP SUB26 - Exceptional semantic review bundle
#
# Read-only, no audio decode, no game patch.
#
# Takes SUB25 FIX2's 344 exceptional subtitle rows and compacts them into
# 177 contiguous exception blocks. For each block:
# - previous/next stable 1G<->1S speaker-compatible group
# - every exceptional Korean subtitle row
# - every game MSG/MSG_FORCED row between the stable game anchors
# - Japanese, same-voice US English, voice_id
# - whether the game row is in SUB25 played-voice consensus
# - all direct audio observations from SUB23 top5
# - FIX1 checkpoint observation when no SUB23 top5 observation exists
#
# This stage makes NO semantic decisions. It creates a review-ready bundle.

from __future__ import annotations
import argparse, csv, hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_GROUPS_SHA="f672817978cc7e2045f711436af88871a1e7e451a79b7fe0abb54e3b7b3b32e9"
EXPECTED_TIMELINE_SHA="026001648382692ff05bde10f071f42f2e72748ad34cf5a728b3874b2509cbd3"
EXPECTED_REVIEW_SHA="b6046a3d464d1dda9da9e2728d724becc0dcd9308d2a0df52a2fa4ddff3f1fd0"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_US_SHA="1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9"
EXPECTED_TOP5_SHA="7be8e92a0c6427a93cda17fd4007eeaa7a934695044c2ee6a3cdbfba280b5cdc"
EXPECTED_CHECKPOINT_SHA="6f295bae8b23acb37c2d5f80f570119b39eec0ebf3155067d8286785b9c433ca"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"

EXPECTED_GROUP_ROWS=1761
EXPECTED_REVIEW_ROWS=344
EXPECTED_EXCEPTION_BLOCKS=177
EXPECTED_CANDIDATE_GAME_ROWS=417
EXPECTED_UNSELECTED_CANDIDATES=139
EXPECTED_MAX_CANDIDATES_PER_BLOCK=23

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):
            h.update(x)
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
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=sha.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def stable_group(r):
    return (
        int(r["assigned_game_count"])==1
        and int(r["speaker_incompatible_count"])==0
        and r["potential_1G_2S_split"]=="NO"
    )

def hint_for_rows(rows):
    flags=[]
    if any(int(r["assigned_game_count"])==0 for r in rows):
        flags.append("HAS_0G")
    if any(int(r["assigned_game_count"])>=2 for r in rows):
        flags.append("HAS_MULTI_G_TO_1S")
    if any(int(r["speaker_incompatible_count"])>0 for r in rows):
        flags.append("HAS_SPEAKER_MISMATCH")
    if any(r["potential_1G_2S_split"]=="YES" for r in rows):
        flags.append("HAS_POTENTIAL_1G_TO_2S")
    return " | ".join(flags) if flags else "OTHER"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_groups=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_subtitle_voice_groups.tsv"
    p_timeline=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_played_voice_timeline.tsv"
    p_review=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_review_groups.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_top5=root/"analysis"/"sub"/"sub23_audio_rescoring_audit"/"sub23_top5_candidate_scores.tsv"
    p_checkpoint=root/"analysis"/"sub"/"sub25_fix1_voice_timeline_reconstruction"/"sub25_fix1_search_checkpoint.tsv"
    p_sub=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned inputs",flush=True)
    groups=pin(p_groups,EXPECTED_GROUPS_SHA,"SUB25 FIX2 groups")
    timeline=pin(p_timeline,EXPECTED_TIMELINE_SHA,"SUB25 FIX2 timeline")
    review=pin(p_review,EXPECTED_REVIEW_SHA,"SUB25 FIX2 review")
    kr=pin(p_kr,EXPECTED_KR_SHA,"SUB19 KR")
    us=pin(p_us,EXPECTED_US_SHA,"SUB19 US")
    top5=pin(p_top5,EXPECTED_TOP5_SHA,"SUB23 top5")
    checkpoint=pin(p_checkpoint,EXPECTED_CHECKPOINT_SHA,"SUB25 FIX1 checkpoint")
    sub09=pin(p_sub,EXPECTED_SUB09_SHA,"SUB09")

    if len(groups)!=EXPECTED_GROUP_ROWS:
        raise RuntimeError(f"group rows={len(groups)} expected={EXPECTED_GROUP_ROWS}")
    if len(review)!=EXPECTED_REVIEW_ROWS:
        raise RuntimeError(f"review rows={len(review)} expected={EXPECTED_REVIEW_ROWS}")

    print("[2/7] Build stable/exception blocks",flush=True)
    stable=[stable_group(r) for r in groups]
    blocks=[]
    cur=[]
    for i,is_stable in enumerate(stable):
        if is_stable:
            if cur:
                blocks.append(cur);cur=[]
        else:
            cur.append(i)
    if cur:blocks.append(cur)

    if len(blocks)!=EXPECTED_EXCEPTION_BLOCKS:
        raise RuntimeError(
            f"exception blocks={len(blocks)} expected={EXPECTED_EXCEPTION_BLOCKS}"
        )

    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    gpos={game_key(r):i for i,r in enumerate(game)}
    game_by_key={game_key(r):r for r in game}
    played={r["game_key"]:r for r in timeline}
    checkpoint_by={r["game_key"]:r for r in checkpoint}

    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:
            us_by[(r["event_file"],r["voice_id"])].append(r)

    top5_by_game=defaultdict(list)
    for r in top5:
        top5_by_game[r["game_key"]].append(r)
    for k in top5_by_game:
        top5_by_game[k].sort(
            key=lambda r:(-float(r["score"]),int(r["sub09_sequence"]),int(r["rank"]))
        )

    print("[3/7] Build block boundaries and game candidate intervals",flush=True)
    block_rows=[]
    subtitle_rows=[]
    candidate_rows=[]
    observation_rows=[]
    anchor_rows=[]
    unselected_rows=[]

    for block_id,idxs in enumerate(blocks,1):
        i0=idxs[0];i1=idxs[-1]

        prev_i=next((j for j in range(i0-1,-1,-1) if stable[j]),None)
        next_i=next((j for j in range(i1+1,len(groups)) if stable[j]),None)
        if prev_i is None or next_i is None:
            raise RuntimeError(f"block {block_id} lacks stable boundary")

        prev=groups[prev_i]
        nxt=groups[next_i]
        prev_key=prev["assigned_game_keys"].strip()
        next_key=nxt["assigned_game_keys"].strip()
        if prev_key not in gpos or next_key not in gpos:
            raise RuntimeError(f"block {block_id} boundary game key missing")
        if gpos[prev_key]>=gpos[next_key]:
            raise RuntimeError(f"block {block_id} reversed boundary")

        candidates=game[gpos[prev_key]+1:gpos[next_key]]
        block_group_rows=[groups[i] for i in idxs]

        for side,r,k in (
            ("PREVIOUS",prev,prev_key),
            ("NEXT",nxt,next_key),
        ):
            g=game_by_key[k]
            hits=us_by.get((g["event_file"],g["voice_id"]),[])
            anchor_rows.append({
                "block_id":block_id,
                "side":side,
                "sub09_sequence":r["sub09_sequence"],
                "speaker":r["speaker"],
                "korean":r["korean"],
                "game_key":k,
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "english":" || ".join(x["text"] for x in hits),
                "voice_time":r["assigned_voice_times"],
                "voice_score":r["assigned_scores"],
            })

        for order,i in enumerate(idxs,1):
            r=groups[i]
            subtitle_rows.append({
                "block_id":block_id,
                "block_subtitle_order":order,
                "sub09_sequence":r["sub09_sequence"],
                "video_part":r["video_part"],
                "observed_first_sec":r["observed_first_sec"],
                "speaker":r["speaker"],
                "korean":r["korean"],
                "assigned_game_count":r["assigned_game_count"],
                "group_kind":r["group_kind"],
                "assigned_game_keys":r["assigned_game_keys"],
                "assigned_voice_ids":r["assigned_voice_ids"],
                "assigned_voice_times":r["assigned_voice_times"],
                "assigned_scores":r["assigned_scores"],
                "speaker_incompatible_count":r["speaker_incompatible_count"],
                "speaker_incompatible_game_keys":r["speaker_incompatible_game_keys"],
                "potential_1G_2S_split":r["potential_1G_2S_split"],
            })

        for order,g in enumerate(candidates,1):
            k=game_key(g)
            hits=us_by.get((g["event_file"],g["voice_id"]),[])
            pl=played.get(k)
            obs=top5_by_game.get(k,[])
            cp=checkpoint_by.get(k)

            best_obs=obs[0] if obs else None
            cp_is_direct=(cp is not None and cp.get("source")=="LOCAL_AT3_SEARCH")

            row={
                "block_id":block_id,
                "candidate_order":order,
                "game_key":k,
                "game_global_dialogue_index":gpos[k]+1,
                "event_file":g["event_file"],
                "event_display_index":g["event_display_index"],
                "command":g["command"],
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "us_match_count":len(hits),
                "english":" || ".join(x["text"] for x in hits),
                "played_voice_consensus":"YES" if pl else "NO",
                "played_audio_time":pl["audio_time_sec"] if pl else "",
                "played_audio_score":pl["audio_score"] if pl else "",
                "direct_top5_observation_count":len(obs),
                "best_direct_top5_score":best_obs["score"] if best_obs else "",
                "best_direct_top5_time":best_obs["best_audio_time_sec"] if best_obs else "",
                "best_direct_top5_sub09_sequence":best_obs["sub09_sequence"] if best_obs else "",
                "best_direct_top5_rank":best_obs["rank"] if best_obs else "",
                "checkpoint_direct_search_available":"YES" if cp_is_direct else "NO",
                "checkpoint_direct_time":cp["matched_time_sec"] if cp_is_direct else "",
                "checkpoint_direct_score":cp["best_score"] if cp_is_direct else "",
            }
            candidate_rows.append(row)
            if not pl:
                unselected_rows.append(row)

            for obs_order,o in enumerate(obs,1):
                observation_rows.append({
                    "block_id":block_id,
                    "game_key":k,
                    "observation_order":obs_order,
                    "source":"SUB23_TOP5",
                    "sub09_sequence":o["sub09_sequence"],
                    "rank":o["rank"],
                    "video_part":o["video_part"],
                    "audio_time_sec":o["best_audio_time_sec"],
                    "score":o["score"],
                    "delta_from_frame_sec":o["delta_from_frame_sec"],
                })
            if not obs and cp_is_direct:
                observation_rows.append({
                    "block_id":block_id,
                    "game_key":k,
                    "observation_order":1,
                    "source":"SUB25_FIX1_CHECKPOINT",
                    "sub09_sequence":"",
                    "rank":"",
                    "video_part":cp["video_part"],
                    "audio_time_sec":cp["matched_time_sec"],
                    "score":cp["best_score"],
                    "delta_from_frame_sec":cp["delta_from_prediction_sec"],
                })

        block_rows.append({
            "block_id":block_id,
            "first_sub09_sequence":groups[i0]["sub09_sequence"],
            "last_sub09_sequence":groups[i1]["sub09_sequence"],
            "subtitle_rows":len(idxs),
            "game_candidate_rows":len(candidates),
            "unselected_game_candidates":sum(
                1 for g in candidates if game_key(g) not in played
            ),
            "previous_stable_sub09_sequence":prev["sub09_sequence"],
            "previous_stable_game":prev_key,
            "next_stable_sub09_sequence":nxt["sub09_sequence"],
            "next_stable_game":next_key,
            "review_hints":hint_for_rows(block_group_rows),
        })

    if len(candidate_rows)!=EXPECTED_CANDIDATE_GAME_ROWS:
        raise RuntimeError(
            f"candidate rows={len(candidate_rows)} expected={EXPECTED_CANDIDATE_GAME_ROWS}"
        )
    if len(unselected_rows)!=EXPECTED_UNSELECTED_CANDIDATES:
        raise RuntimeError(
            f"unselected candidates={len(unselected_rows)} "
            f"expected={EXPECTED_UNSELECTED_CANDIDATES}"
        )
    max_c=max(int(r["game_candidate_rows"]) for r in block_rows)
    if max_c!=EXPECTED_MAX_CANDIDATES_PER_BLOCK:
        raise RuntimeError(
            f"max candidates/block={max_c} expected={EXPECTED_MAX_CANDIDATES_PER_BLOCK}"
        )

    print(
        f"  blocks={len(block_rows)} candidate_game_rows={len(candidate_rows)} "
        f"unselected={len(unselected_rows)} max/block={max_c}",
        flush=True
    )

    print("[4/7] Write structured review tables",flush=True)
    write_tsv(
        out/"sub26_exception_blocks.tsv",block_rows,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence",
            "subtitle_rows","game_candidate_rows","unselected_game_candidates",
            "previous_stable_sub09_sequence","previous_stable_game",
            "next_stable_sub09_sequence","next_stable_game","review_hints"
        ]
    )
    write_tsv(
        out/"sub26_block_subtitles.tsv",subtitle_rows,
        [
            "block_id","block_subtitle_order","sub09_sequence","video_part",
            "observed_first_sec","speaker","korean","assigned_game_count",
            "group_kind","assigned_game_keys","assigned_voice_ids",
            "assigned_voice_times","assigned_scores","speaker_incompatible_count",
            "speaker_incompatible_game_keys","potential_1G_2S_split"
        ]
    )
    candidate_fields=[
        "block_id","candidate_order","game_key","game_global_dialogue_index",
        "event_file","event_display_index","command","speaker_code","voice_id",
        "japanese","us_match_count","english","played_voice_consensus",
        "played_audio_time","played_audio_score","direct_top5_observation_count",
        "best_direct_top5_score","best_direct_top5_time",
        "best_direct_top5_sub09_sequence","best_direct_top5_rank",
        "checkpoint_direct_search_available","checkpoint_direct_time",
        "checkpoint_direct_score"
    ]
    write_tsv(out/"sub26_block_game_candidates.tsv",candidate_rows,candidate_fields)
    write_tsv(out/"sub26_unselected_game_candidates.tsv",unselected_rows,candidate_fields)
    write_tsv(
        out/"sub26_candidate_audio_observations.tsv",observation_rows,
        [
            "block_id","game_key","observation_order","source","sub09_sequence",
            "rank","video_part","audio_time_sec","score","delta_from_frame_sec"
        ]
    )
    write_tsv(
        out/"sub26_stable_anchor_context.tsv",anchor_rows,
        [
            "block_id","side","sub09_sequence","speaker","korean","game_key",
            "speaker_code","voice_id","japanese","english","voice_time","voice_score"
        ]
    )

    print("[5/7] Write semantic-resolution template",flush=True)
    template=[]
    for b in block_rows:
        template.append({
            "block_id":b["block_id"],
            "first_sub09_sequence":b["first_sub09_sequence"],
            "last_sub09_sequence":b["last_sub09_sequence"],
            "review_hints":b["review_hints"],
            "semantic_status":"PENDING",
            "decision_type":"",
            "final_mapping_spec":"",
            "game_rows_to_skip":"",
            "korean_split_or_merge_notes":"",
            "review_notes":"",
        })
    write_tsv(
        out/"sub26_semantic_resolution_template.tsv",template,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence","review_hints",
            "semantic_status","decision_type","final_mapping_spec",
            "game_rows_to_skip","korean_split_or_merge_notes","review_notes"
        ]
    )

    print("[6/7] Write human-readable packets",flush=True)
    subs_by=defaultdict(list)
    for r in subtitle_rows:subs_by[int(r["block_id"])].append(r)
    cands_by=defaultdict(list)
    for r in candidate_rows:cands_by[int(r["block_id"])].append(r)
    anchors_by=defaultdict(list)
    for r in anchor_rows:anchors_by[int(r["block_id"])].append(r)

    packet_names=[]
    chunk=30
    for start in range(1,len(block_rows)+1,chunk):
        end=min(len(block_rows),start+chunk-1)
        name=f"sub26_review_packet_{start:03d}_{end:03d}.txt"
        p=out/name
        lines=[
            f"Naruto PSP SUB26 semantic exception review: blocks {start}..{end}",
            "="*104,
            "",
            "No mapping in this packet is semantic-final.",
            "Use JP + EN + KO + voice timing/order together.",
            "",
        ]
        for bid in range(start,end+1):
            b=block_rows[bid-1]
            lines += [
                "",
                "#"*104,
                f"BLOCK {bid:03d}  SUB09 {b['first_sub09_sequence']}..{b['last_sub09_sequence']}  "
                f"subtitles={b['subtitle_rows']} game_candidates={b['game_candidate_rows']} "
                f"unselected={b['unselected_game_candidates']}",
                f"HINTS: {b['review_hints']}",
                "#"*104,
            ]
            for a in anchors_by[bid]:
                lines += [
                    f"[{a['side']} STABLE] SUB09#{a['sub09_sequence']} "
                    f"{a['speaker']}: {a['korean']}",
                    f"  GAME {a['game_key']} {a['speaker_code']} {a['voice_id']} "
                    f"time={a['voice_time']} score={a['voice_score']}",
                    f"  JP: {a['japanese']}",
                    f"  EN: {a['english']}",
                ]
            lines += ["","[EXCEPTION SUBTITLES]"]
            for s in subs_by[bid]:
                lines += [
                    f"  S{s['sub09_sequence']} {s['speaker']}: {s['korean']}",
                    f"    current={s['group_kind']} games={s['assigned_game_keys'] or '(none)'} "
                    f"split={s['potential_1G_2S_split']} "
                    f"speaker_bad={s['speaker_incompatible_count']}",
                ]
            lines += ["","[ALL GAME ROWS BETWEEN STABLE ANCHORS]"]
            if not cands_by[bid]:
                lines.append("  (none)")
            for g in cands_by[bid]:
                flags=[]
                if g["played_voice_consensus"]=="YES":
                    flags.append("PLAYED")
                else:
                    flags.append("UNSELECTED")
                if g["voice_id"]=="":
                    flags.append("UNVOICED")
                lines += [
                    f"  G{g['candidate_order']:02d} {g['game_key']} "
                    f"{g['speaker_code'] or '<BLANK>'} {g['voice_id'] or '<NO-VOICE>'} "
                    f"[{','.join(flags)}]",
                    f"    JP: {g['japanese']}",
                    f"    EN: {g['english']}",
                    f"    played_time={g['played_audio_time']} played_score={g['played_audio_score']} "
                    f"best_direct={g['best_direct_top5_score']}@{g['best_direct_top5_time']} "
                    f"from_SUB09={g['best_direct_top5_sub09_sequence']}",
                ]
        p.write_text("\n".join(lines)+"\n",encoding="utf-8-sig")
        packet_names.append(name)

    print("[7/7] Report / deterministic checks",flush=True)
    hint_counts=Counter()
    for b in block_rows:
        for h in b["review_hints"].split(" | "):
            if h:hint_counts[h]+=1

    cand_counts=[int(r["game_candidate_rows"]) for r in block_rows]
    report={
        "stage":"SUB26",
        "mode":"READ_ONLY_EXCEPTION_SEMANTIC_REVIEW_BUNDLE",
        "subtitle_group_rows":len(groups),
        "exception_subtitle_rows":len(review),
        "exception_blocks":len(block_rows),
        "candidate_game_rows":len(candidate_rows),
        "candidate_game_rows_unique":len({r["game_key"] for r in candidate_rows}),
        "unselected_candidate_game_rows":len(unselected_rows),
        "candidate_rows_per_block":{
            "min":min(cand_counts),
            "max":max(cand_counts),
            "mean":sum(cand_counts)/len(cand_counts),
        },
        "review_hint_block_counts":dict(hint_counts),
        "packet_files":packet_names,
        "semantic_decisions_made":0,
        "game_files_modified":False,
    }
    (out/"sub26_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB26 - Exceptional Semantic Review Bundle",
        "",
        f"SubtitleGroupRows={len(groups)}",
        f"ExceptionSubtitleRows={len(review)}",
        f"ExceptionBlocks={len(block_rows)}",
        f"CandidateGameRows={len(candidate_rows)}",
        f"UniqueCandidateGameRows={len({r['game_key'] for r in candidate_rows})}",
        f"UnselectedCandidateGameRows={len(unselected_rows)}",
        f"CandidateRowsPerBlockMin={min(cand_counts)}",
        f"CandidateRowsPerBlockMax={max(cand_counts)}",
        f"CandidateRowsPerBlockMean={sum(cand_counts)/len(cand_counts):.3f}",
        "ReviewHintBlockCounts="+json.dumps(dict(hint_counts),ensure_ascii=False,sort_keys=True),
        f"ReviewPacketFiles={len(packet_names)}",
        "",
        "This bundle contains all game rows between stable subtitle/game anchors,",
        "including played-consensus rows, unselected voiced rows, and unvoiced MSG rows.",
        "",
        "No semantic decision was made.",
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
