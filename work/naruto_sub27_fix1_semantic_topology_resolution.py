#!/usr/bin/env python3
# -*- coding: ascii -*-
# Naruto PSP SUB27 - Manual semantic topology resolution
#
# Read-only. No game patching.
#
# This stage consumes the SUB26 exception bundle and applies a manually reviewed
# JP + US English + Korean semantic topology decision for all 177 exception blocks.
#
# IMPORTANT:
# - This resolves correspondence TOPOLOGY only.
# - It does NOT yet rewrite/split Korean text to max_bytes per individual game MSG.
# - It does NOT automatically discard game rows with no SUB09 counterpart.
#   Such rows are explicitly emitted for direct JP/EN -> KO translation later.

from __future__ import annotations
import argparse, csv, hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED = {
    "sub26_exception_blocks.tsv": "f0b3215eb235bd3e2e3e7c4142f69a095fd7b8bcc2bfd01bc609cde9cb614553",
    "sub26_block_subtitles.tsv": "fff7e8e624c3ca6d6718696182290dee083ce90205f8c72c76b13622de31d315",
    "sub26_block_game_candidates.tsv": "ddcf11bb5867f76389307999e662548b48334804fe23db083badf523b85bed1b",
    "sub26_stable_anchor_context.tsv": "886117fdcfad36d677b7eb8b7b9e71411a4e194308395cbf7d233242b3a885ed",
    "sub25_fix2_subtitle_voice_groups.tsv": "f672817978cc7e2045f711436af88871a1e7e451a79b7fe0abb54e3b7b3b32e9",
    "sub19_fix1_kr_display_messages.tsv": "aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54",
    "sub19_fix1_us_display_messages.tsv": "1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9",
    "sub09_final_sequence.tsv": "59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e",
}

EXPECTED_COUNTS = {
    "blocks": 177,
    "mapping_units": 253,
    "ocr_partial_drops": 6,
    "video_only_subtitles": 1,
    "anchor_override_units": 10,
    "stable_base_game_rows": 1417,
    "mapped_game_rows_total": 1672,
    "all_unmapped_game_rows": 304,
    "all_unmapped_voiced": 167,
    "all_unmapped_unvoiced": 137,
    "exception_candidate_unmapped": 162,
}

EXPECTED_RELATIONS = {
    "1G1S": 134,
    "1G_TO_2S": 78,
    "UNVOICED_1G1S": 16,
    "2G_TO_1S": 12,
    "ANCHOR_SPLIT_1G_TO_2S": 10,
    "1G_TO_3S": 3,
}

SPEAKER_ALLOWED = {
    "NRT":{"\ub098\ub8e8\ud1a0"},"JRY":{"\uc9c0\ub77c\uc774\uc57c"},"KSU":{"\uce74\uc2a4\ubbf8"},"KKS":{"\uce74\uce74\uc2dc"},
    "KRH":{"\ud0a4\ub9ac\ud788\uba54"},"TND":{"\uce20\ub098\ub370"},"SKR":{"\uc0ac\ucfe0\ub77c"},"ORC":{"\uc624\ub85c\uce58\ub9c8\ub8e8"},
    "SIK":{"\uc2dc\uce74\ub9c8\ub8e8"},"KBT":{"\uce74\ubd80\ud1a0"},"SZN":{"\uc2dc\uc988\ub124"},"HNT":{"\ud788\ub098\ud0c0"},
    "HKG":{"3\ub300 \ud638\uce74\uac8c"},"NEJ":{"\ub124\uc9c0"},"ROC":{"\ub9ac"},"HST":{"\ubcd1\uc0ac\ub300\uc7a5"},
    "GUY":{"\uac00\uc774"},"GAR":{"\uac00\uc544\ub77c"},"ONK":{"\uc5ec\uc790\uc544\uc774"},
    "SN1":{"\uc0ac\ub150\uc81c","\uc0ac\ub150\uccb4"},"KIB":{"\ud0a4\ubc14"},"JJO":{"\uc2dc\ub140"},"SIN":{"\uc2dc\ub3c4"},
    "TYO":{"\ucd78\uc9c0"},"INO":{"\uc774\ub178"},"HIS":{"\ubcd1\uc0ac"},"TEN":{"\ud150\ud150"},
    "SNS":{"\uc0ac\ub150\uccb4","\uc0ac\ub150\uc81c"},"KSM":{"\ud0a4\uc0ac\uba54"},"ITD":{"\uc77c\ub3d9"},
    "JRS":{"\uc77c\ub3d9"},"JT2":{"\uc77c\ub3d9"},
}

DECISIONS_PATH=Path(__file__).with_name("sub27_manual_decisions.json")
if not DECISIONS_PATH.exists():
    raise RuntimeError(f"manual decisions JSON missing: {DECISIONS_PATH}")
MANUAL_DECISIONS=json.loads(DECISIONS_PATH.read_text(encoding="ascii"))


def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path:Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path:Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def pin(path:Path, expected:str, name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected.lower():
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

def mapping_spec(units):
    chunks=[]
    for u in units:
        ss="+".join("S"+str(x) for x in u["subs"])
        gg="+".join(u["games"])
        chunks.append(f"{ss}=>{gg}[{u['relation']}]")
    return "; ".join(chunks)

def joined_korean(sub_by_seq, seqs):
    return " / ".join(sub_by_seq[s]["text"] for s in seqs if s in sub_by_seq)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    p_blocks=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_exception_blocks.tsv"
    p_subs=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_block_subtitles.tsv"
    p_cands=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_block_game_candidates.tsv"
    p_anchors=root/"analysis"/"sub"/"sub26_semantic_exception_bundle"/"sub26_stable_anchor_context.tsv"
    p_groups=root/"analysis"/"sub"/"sub25_fix2_voice_timeline_reconstruction"/"sub25_fix2_subtitle_voice_groups.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/7] Verify pinned inputs", flush=True)
    blocks=pin(p_blocks, EXPECTED[p_blocks.name], "SUB26 blocks")
    block_subs=pin(p_subs, EXPECTED[p_subs.name], "SUB26 block subtitles")
    candidates=pin(p_cands, EXPECTED[p_cands.name], "SUB26 game candidates")
    anchors=pin(p_anchors, EXPECTED[p_anchors.name], "SUB26 stable anchors")
    groups=pin(p_groups, EXPECTED[p_groups.name], "SUB25 FIX2 groups")
    kr=pin(p_kr, EXPECTED[p_kr.name], "SUB19 KR")
    us=pin(p_us, EXPECTED[p_us.name], "SUB19 US")
    sub09=pin(p_sub09, EXPECTED[p_sub09.name], "SUB09")

    if len(blocks)!=EXPECTED_COUNTS["blocks"]:
        raise RuntimeError(f"block count={len(blocks)}")

    sub_by_seq={int(r["sequence"]):r for r in sub09}
    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    game_by_key={game_key(r):r for r in game}
    game_pos={game_key(r):i for i,r in enumerate(game)}

    us_by=defaultdict(list)
    for r in us:
        if r["voice_id"]:
            us_by[(r["event_file"], r["voice_id"])].append(r)

    subs_by_block=defaultdict(list)
    for r in block_subs:
        subs_by_block[int(r["block_id"])].append(r)
    cands_by_block=defaultdict(list)
    for r in candidates:
        cands_by_block[int(r["block_id"])].append(r)
    anchors_by_block=defaultdict(list)
    for r in anchors:
        anchors_by_block[int(r["block_id"])].append(r)

    print("[2/7] Validate 177 manual semantic decisions", flush=True)
    if set(map(int,MANUAL_DECISIONS.keys())) != set(range(1,178)):
        raise RuntimeError("manual decision block ids are incomplete")

    mapping_rows=[]
    block_rows=[]
    exclusion_rows=[]
    anchor_override_rows=[]
    relation_counts=Counter()
    mapped_overlay_games=set()
    exception_candidate_unmapped=[]

    intentional_speaker_mismatches=[]

    for bid in range(1,178):
        d=MANUAL_DECISIONS[str(bid)] if str(bid) in MANUAL_DECISIONS else MANUAL_DECISIONS[bid]
        exception_seqs={int(r["sub09_sequence"]) for r in subs_by_block[bid]}

        covered=set(d.get("drops",[])) | set(d.get("video",[]))
        allowed_games={r["game_key"] for r in cands_by_block[bid]}
        allowed_games |= {r["game_key"] for r in anchors_by_block[bid]}

        mapped_here=set()

        for unit_index,u in enumerate(d["units"],1):
            subs=[int(x) for x in u["subs"]]
            games=list(u["games"])
            relation=u["relation"]
            note=u.get("note","")

            covered |= (set(subs) & exception_seqs)

            for g in games:
                if g not in allowed_games:
                    raise RuntimeError(f"block {bid}: game outside candidate/anchor scope: {g}")
                if g not in game_by_key:
                    raise RuntimeError(f"block {bid}: unknown game key: {g}")

            # monotonic semantic ordering is checked later globally
            relation_counts[relation]+=1
            mapped_here.update(games)
            mapped_overlay_games.update(games)

            subtitle_speakers=sorted({sub_by_seq[s]["speaker"] for s in subs if s in sub_by_seq})
            game_codes=sorted({game_by_key[g]["speaker_code"] for g in games if game_by_key[g]["speaker_code"]})
            allowed_names=set()
            for gc in game_codes:
                allowed_names |= SPEAKER_ALLOWED.get(gc,set())
            normalized_speakers={"\uc774\ub178" if x=="\uc774\ub3c4" else x for x in subtitle_speakers}
            speaker_mismatch=bool(allowed_names and not normalized_speakers.issubset(allowed_names))
            if speaker_mismatch:
                intentional_speaker_mismatches.append((bid,subs,games,subtitle_speakers,game_codes))

            game_meta=[]
            for g in games:
                gr=game_by_key[g]
                hits=us_by.get((gr["event_file"],gr["voice_id"]),[])
                game_meta.append({
                    "key":g,
                    "speaker_code":gr["speaker_code"],
                    "voice_id":gr["voice_id"],
                    "jp":gr["text"],
                    "en":" || ".join(x["text"] for x in hits),
                })

            mapping_rows.append({
                "block_id":bid,
                "unit_index":unit_index,
                "relation":relation,
                "subtitle_sequences":" ".join(map(str,subs)),
                "subtitle_speakers":" | ".join(subtitle_speakers),
                "korean_joined":joined_korean(sub_by_seq,subs),
                "game_keys":" | ".join(games),
                "game_speaker_codes":" | ".join(x["speaker_code"] or "<BLANK>" for x in game_meta),
                "voice_ids":" | ".join(x["voice_id"] or "<NO-VOICE>" for x in game_meta),
                "japanese_joined":" || ".join(x["jp"] for x in game_meta),
                "english_joined":" || ".join(x["en"] for x in game_meta),
                "speaker_mismatch":"YES" if speaker_mismatch else "NO",
                "note":note,
            })

            if relation=="ANCHOR_SPLIT_1G_TO_2S":
                anchor_override_rows.append(mapping_rows[-1].copy())

        if covered != exception_seqs:
            raise RuntimeError(
                f"block {bid}: subtitle coverage mismatch expected={sorted(exception_seqs)} got={sorted(covered)}"
            )

        for s in d.get("drops",[]):
            exclusion_rows.append({
                "block_id":bid,
                "sub09_sequence":s,
                "type":"OCR_PARTIAL_DROP",
                "speaker":sub_by_seq[s]["speaker"],
                "korean":sub_by_seq[s]["text"],
                "reason":"\uc9c4\ud589 \uc911 OCR \uc870\uac01/\uc911\ubcf5 \ud504\ub808\uc784\uc73c\ub85c \uc758\ubbf8 \ub2e8\uc704\uc5d0\uc11c \uc81c\uc678",
            })
        for s in d.get("video",[]):
            exclusion_rows.append({
                "block_id":bid,
                "sub09_sequence":s,
                "type":"VIDEO_ONLY_NO_GAME_MSG",
                "speaker":sub_by_seq[s]["speaker"],
                "korean":sub_by_seq[s]["text"],
                "reason":"\uc601\uc0c1/\uc5f0\ucd9c \uc790\ub9c9\uc73c\ub85c \ud655\uc778\ub418\uc5b4 \ud574\ub2f9 \uc774\ubca4\ud2b8 TBL MSG\uc640 \uc758\ubbf8 \ub300\uc751 \uc5c6\uc74c",
            })

        candidate_keys={r["game_key"] for r in cands_by_block[bid]}
        for g in sorted(candidate_keys-mapped_here, key=lambda x:game_pos[x]):
            gr=game_by_key[g]
            hits=us_by.get((gr["event_file"],gr["voice_id"]),[])
            exception_candidate_unmapped.append({
                "block_id":bid,
                "game_key":g,
                "game_global_dialogue_index":game_pos[g]+1,
                "event_file":gr["event_file"],
                "event_display_index":gr["event_display_index"],
                "command":gr["command"],
                "speaker_code":gr["speaker_code"],
                "voice_id":gr["voice_id"],
                "japanese":gr["text"],
                "english":" || ".join(x["text"] for x in hits),
                "reason":"NO_SUB09_SEMANTIC_COUNTERPART_IN_EXCEPTION_BLOCK",
                "next_action":"DIRECT_TRANSLATE_JP_EN_TO_KO_LATER",
            })

        block_rows.append({
            "block_id":bid,
            "first_sub09_sequence":blocks[bid-1]["first_sub09_sequence"],
            "last_sub09_sequence":blocks[bid-1]["last_sub09_sequence"],
            "semantic_status":"RESOLVED_TOPOLOGY",
            "confidence":d.get("confidence","HIGH"),
            "decision_types":" | ".join(sorted({u["relation"] for u in d["units"]})) or "NO_GAME_MAPPING",
            "final_mapping_spec":mapping_spec(d["units"]),
            "ocr_partial_drop_sequences":" ".join(map(str,d.get("drops",[]))),
            "video_only_sequences":" ".join(map(str,d.get("video",[]))),
            "unmapped_candidate_game_count":len(candidate_keys-mapped_here),
            "unmapped_candidate_game_keys":" | ".join(
                sorted(candidate_keys-mapped_here,key=lambda x:game_pos[x])
            ),
            "review_notes":d.get("note",""),
        })

    if len(mapping_rows)!=EXPECTED_COUNTS["mapping_units"]:
        raise RuntimeError(f"mapping units={len(mapping_rows)}")
    if relation_counts != Counter(EXPECTED_RELATIONS):
        raise RuntimeError(f"relation counts={dict(relation_counts)}")
    if len(exclusion_rows)!=EXPECTED_COUNTS["ocr_partial_drops"]+EXPECTED_COUNTS["video_only_subtitles"]:
        raise RuntimeError(f"exclusion rows={len(exclusion_rows)}")
    if len(anchor_override_rows)!=EXPECTED_COUNTS["anchor_override_units"]:
        raise RuntimeError(f"anchor overrides={len(anchor_override_rows)}")
    if len(exception_candidate_unmapped)!=EXPECTED_COUNTS["exception_candidate_unmapped"]:
        raise RuntimeError(f"exception candidate unmapped={len(exception_candidate_unmapped)}")

    # Only one manual mapping intentionally crosses the SUB09 speaker label:
    # block 144 S1592 is labeled Kakashi in OCR but the actual line is Jiraiya.
    if len(intentional_speaker_mismatches)!=1 or intentional_speaker_mismatches[0][0]!=144:
        raise RuntimeError(
            f"unexpected semantic speaker mismatches: {intentional_speaker_mismatches[:10]}"
        )

    print("[3/7] Build full game-row semantic coverage", flush=True)
    stable_rows=[r for r in groups if stable_group(r)]
    base_stable_games={r["assigned_game_keys"].strip() for r in stable_rows if r["assigned_game_keys"].strip()}
    if len(base_stable_games)!=EXPECTED_COUNTS["stable_base_game_rows"]:
        raise RuntimeError(f"stable base games={len(base_stable_games)}")

    mapped_all=base_stable_games | mapped_overlay_games
    if len(mapped_all)!=EXPECTED_COUNTS["mapped_game_rows_total"]:
        raise RuntimeError(f"mapped game rows={len(mapped_all)}")

    all_unmapped=[]
    for g in game:
        k=game_key(g)
        if k in mapped_all:
            continue
        hits=us_by.get((g["event_file"],g["voice_id"]),[])
        all_unmapped.append({
            "game_key":k,
            "game_global_dialogue_index":game_pos[k]+1,
            "event_file":g["event_file"],
            "event_display_index":g["event_display_index"],
            "command":g["command"],
            "speaker_code":g["speaker_code"],
            "voice_id":g["voice_id"],
            "voiced":"YES" if g["voice_id"] else "NO",
            "japanese":g["text"],
            "english":" || ".join(x["text"] for x in hits),
            "status":"NO_SUB09_SEMANTIC_MAPPING",
            "next_action":"DIRECT_TRANSLATE_JP_EN_TO_KO_LATER",
        })

    if len(all_unmapped)!=EXPECTED_COUNTS["all_unmapped_game_rows"]:
        raise RuntimeError(f"all unmapped game rows={len(all_unmapped)}")
    voiced=sum(r["voiced"]=="YES" for r in all_unmapped)
    unvoiced=len(all_unmapped)-voiced
    if voiced!=EXPECTED_COUNTS["all_unmapped_voiced"] or unvoiced!=EXPECTED_COUNTS["all_unmapped_unvoiced"]:
        raise RuntimeError(f"unmapped voiced/unvoiced={voiced}/{unvoiced}")

    print("[4/7] Check global ordering of manual mappings", flush=True)
    # Check within each block by semantic unit order.
    for bid in range(1,178):
        rows=[r for r in mapping_rows if int(r["block_id"])==bid]
        last=-1
        for r in rows:
            gs=[x.strip() for x in r["game_keys"].split("|") if x.strip()]
            if not gs:
                continue
            lo=min(game_pos[x] for x in gs)
            hi=max(game_pos[x] for x in gs)
            if lo<last:
                raise RuntimeError(f"block {bid}: semantic mapping game order reversal")
            last=hi

    print("[5/7] Write normalized semantic outputs", flush=True)
    write_tsv(
        out/"sub27_semantic_block_resolution.tsv",
        block_rows,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence",
            "semantic_status","confidence","decision_types","final_mapping_spec",
            "ocr_partial_drop_sequences","video_only_sequences",
            "unmapped_candidate_game_count","unmapped_candidate_game_keys",
            "review_notes"
        ]
    )
    write_tsv(
        out/"sub27_mapping_units.tsv",
        mapping_rows,
        [
            "block_id","unit_index","relation","subtitle_sequences",
            "subtitle_speakers","korean_joined","game_keys","game_speaker_codes",
            "voice_ids","japanese_joined","english_joined","speaker_mismatch","note"
        ]
    )
    write_tsv(
        out/"sub27_anchor_overrides.tsv",
        anchor_override_rows,
        [
            "block_id","unit_index","relation","subtitle_sequences",
            "subtitle_speakers","korean_joined","game_keys","game_speaker_codes",
            "voice_ids","japanese_joined","english_joined","speaker_mismatch","note"
        ]
    )
    write_tsv(
        out/"sub27_subtitle_exclusions.tsv",
        exclusion_rows,
        ["block_id","sub09_sequence","type","speaker","korean","reason"]
    )
    write_tsv(
        out/"sub27_exception_game_only_rows.tsv",
        exception_candidate_unmapped,
        [
            "block_id","game_key","game_global_dialogue_index","event_file",
            "event_display_index","command","speaker_code","voice_id",
            "japanese","english","reason","next_action"
        ]
    )
    write_tsv(
        out/"sub27_all_unmapped_game_rows.tsv",
        all_unmapped,
        [
            "game_key","game_global_dialogue_index","event_file","event_display_index",
            "command","speaker_code","voice_id","voiced","japanese","english",
            "status","next_action"
        ]
    )

    # Fill the original SUB26-shaped resolution template.
    filled=[]
    by_bid={int(r["block_id"]):r for r in block_rows}
    for bid in range(1,178):
        r=by_bid[bid]
        filled.append({
            "block_id":bid,
            "first_sub09_sequence":r["first_sub09_sequence"],
            "last_sub09_sequence":r["last_sub09_sequence"],
            "review_hints":blocks[bid-1]["review_hints"],
            "semantic_status":"RESOLVED_TOPOLOGY",
            "decision_type":r["decision_types"],
            "final_mapping_spec":r["final_mapping_spec"],
            "game_rows_to_skip":"",
            "korean_split_or_merge_notes":"Per-MSG Korean text split is deferred to next stage; see sub27_mapping_units.tsv",
            "review_notes":r["review_notes"],
        })
    write_tsv(
        out/"sub27_semantic_resolution_filled.tsv",
        filled,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence","review_hints",
            "semantic_status","decision_type","final_mapping_spec",
            "game_rows_to_skip","korean_split_or_merge_notes","review_notes"
        ]
    )

    print("[6/7] Build audit packet", flush=True)
    packet=[
        "Naruto PSP SUB27 - Manual Semantic Topology Resolution",
        "="*110,
        "",
        "All 177 SUB26 exception blocks were reviewed using KO + JP + US EN context.",
        "This is topology resolution only; byte-budgeted per-MSG Korean rewriting is deferred.",
        "",
    ]
    for bid in range(1,178):
        br=by_bid[bid]
        packet += [
            "",
            "#"*110,
            f"BLOCK {bid:03d}  SUB09 {br['first_sub09_sequence']}..{br['last_sub09_sequence']}",
            f"STATUS={br['semantic_status']}  TYPE={br['decision_types']}",
            f"MAP: {br['final_mapping_spec'] or '(no game mapping)'}",
        ]
        if br["ocr_partial_drop_sequences"]:
            packet.append(f"OCR PARTIAL DROP: {br['ocr_partial_drop_sequences']}")
        if br["video_only_sequences"]:
            packet.append(f"VIDEO ONLY: {br['video_only_sequences']}")
        if br["unmapped_candidate_game_keys"]:
            packet.append(f"GAME-ONLY/DIRECT-TRANSLATE: {br['unmapped_candidate_game_keys']}")
        if br["review_notes"]:
            packet.append(f"NOTE: {br['review_notes']}")
        for mr in [x for x in mapping_rows if int(x["block_id"])==bid]:
            packet += [
                f"  {mr['relation']}: S[{mr['subtitle_sequences']}] -> {mr['game_keys']}",
                f"    KO: {mr['korean_joined']}",
                f"    JP: {mr['japanese_joined']}",
                f"    EN: {mr['english_joined']}",
            ]
    (out/"sub27_semantic_audit_packet.txt").write_text(
        "\n".join(packet)+"\n", encoding="utf-8-sig"
    )

    print("[7/7] Report / deterministic checks", flush=True)
    report={
        "stage":"SUB27",
        "mode":"READ_ONLY_MANUAL_SEMANTIC_TOPOLOGY_RESOLUTION",
        "exception_blocks_resolved":len(block_rows),
        "mapping_units":len(mapping_rows),
        "relation_counts":dict(relation_counts),
        "ocr_partial_subtitle_drops":sum(r["type"]=="OCR_PARTIAL_DROP" for r in exclusion_rows),
        "video_only_subtitles":sum(r["type"]=="VIDEO_ONLY_NO_GAME_MSG" for r in exclusion_rows),
        "anchor_override_units":len(anchor_override_rows),
        "stable_base_game_rows":len(base_stable_games),
        "mapped_game_rows_total":len(mapped_all),
        "all_game_rows":len(game),
        "all_unmapped_game_rows":len(all_unmapped),
        "all_unmapped_voiced":voiced,
        "all_unmapped_unvoiced":unvoiced,
        "exception_candidate_unmapped":len(exception_candidate_unmapped),
        "intentional_speaker_label_corrections":[
            {
                "block_id":x[0],
                "subtitle_sequences":x[1],
                "game_keys":x[2],
                "subtitle_speakers":x[3],
                "game_speaker_codes":x[4],
            }
            for x in intentional_speaker_mismatches
        ],
        "semantic_topology_resolved":True,
        "per_msg_korean_text_finalized":False,
        "direct_translation_of_unmapped_rows_completed":False,
        "game_files_modified":False,
    }
    (out/"sub27_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB27 - Manual Semantic Topology Resolution",
        "",
        f"ExceptionBlocksResolved={len(block_rows)}",
        f"MappingUnits={len(mapping_rows)}",
        "RelationCounts="+json.dumps(dict(relation_counts),ensure_ascii=False,sort_keys=True),
        f"OCRPartialDrops={sum(r['type']=='OCR_PARTIAL_DROP' for r in exclusion_rows)}",
        f"VideoOnlySubtitles={sum(r['type']=='VIDEO_ONLY_NO_GAME_MSG' for r in exclusion_rows)}",
        f"AnchorOverrideUnits={len(anchor_override_rows)}",
        "",
        f"StableBaseGameRows={len(base_stable_games)}",
        f"MappedGameRowsTotal={len(mapped_all)}/{len(game)}",
        f"UnmappedGameRows={len(all_unmapped)}",
        f"UnmappedVoiced={voiced}",
        f"UnmappedUnvoiced={unvoiced}",
        f"ExceptionCandidateUnmapped={len(exception_candidate_unmapped)}",
        "",
        "Intentional speaker-label correction:",
        "  SUB09 #1592 is labeled Kakashi in OCR, but JP/EN/game speaker proves Jiraiya.",
        "",
        "IMPORTANT:",
        "  All 177 exception blocks now have semantic topology decisions.",
        "  This stage does NOT yet split/merge Korean wording into final per-MSG text",
        "  and does NOT translate the 304 game rows without a SUB09 semantic mapping.",
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
