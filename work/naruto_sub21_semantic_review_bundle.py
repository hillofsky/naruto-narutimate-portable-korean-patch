#!/usr/bin/env python3
# Naruto PSP SUB21 - Semantic review bundle builder
#
# Read-only.
# Builds compact review packets for the 157 ambiguous SUB20 FIX1 blocks.
# Each block contains:
# - Korean SUB09 subtitle rows
# - previous/next structural-high anchors
# - all KR game MSG/MSG_FORCED rows between those anchors
# - US English text matched by exact same-event voice_id where available
# - the union of all 3 structural-variant assignments
# - whether a game row was skipped by all 3 variants
#
# No semantic decision is made here.
# No TBL/DAT/BOOT/ISO modification.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import defaultdict
from pathlib import Path

EXPECTED_STATUS_SHA="c803a1f97a982174a59364c50d1e992d5034715630143fe3d5241a24a203c7ee"
EXPECTED_BLOCKS_SHA="b55914f30db9240e4368f7855637703d288f1374ce2703e28fa9c87053ac9a17"
EXPECTED_HIGH_SHA="96b7a6d42f05cfc0934d7e7a291a8cb1a0c33f44b54d96f12dfea9bb2aaba6f3"
EXPECTED_KR_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_US_SHA="1199095eb836c2c2d9110e4bc3ca77ff27444b3a723c3429d4d9da7bd6a470d9"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"

EXPECTED_STATUS_ROWS=1761
EXPECTED_HIGH_ROWS=1338
EXPECTED_REVIEW_ROWS=423
EXPECTED_BLOCKS=157

VARIANT_FIELDS=[
    ("BASELINE","variant_baseline"),
    ("CONSERVATIVE","variant_conservative"),
    ("MERGE_FRIENDLY","variant_merge_friendly"),
]

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
        for r in rows:
            w.writerow(r)

def game_key(r):
    return f"{r['event_file']}#{int(r['event_display_index']):03d}"

def split_keys(s):
    if not s:
        return []
    return [x.strip() for x in s.split("|") if x.strip()]

def single_key(s):
    xs=split_keys(s)
    return xs[0] if len(xs)==1 else ""

def short(s,n=180):
    s=(s or "").replace("\r"," ").replace("\n","\\n")
    return s if len(s)<=n else s[:n-1]+"…"

def load_pinned(path:Path,expected_sha:str,name:str):
    if not path.exists():
        raise RuntimeError(f"required input missing: {path}")
    got=sha256_file(path)
    if got.lower()!=expected_sha.lower():
        raise RuntimeError(f"{name} SHA mismatch: {got}")
    return read_tsv(path)

def us_index(rows):
    by_voice=defaultdict(list)
    for r in rows:
        voice=r["voice_id"]
        if voice:
            by_voice[(r["event_file"],voice)].append(r)
    return by_voice

def us_for_game(g,idx):
    voice=g["voice_id"]
    if not voice:
        return [],""
    hits=idx.get((g["event_file"],voice),[])
    texts=" || ".join(x["text"] for x in hits)
    return hits,texts

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    p_status=root/"analysis"/"sub"/"sub20_fix1_structural_alignment"/"sub20_all_dialogue_status.tsv"
    p_blocks=root/"analysis"/"sub"/"sub20_fix1_structural_alignment"/"sub20_ambiguous_blocks.tsv"
    p_high=root/"analysis"/"sub"/"sub20_fix1_structural_alignment"/"sub20_structural_high_anchors.tsv"
    p_skipped=root/"analysis"/"sub"/"sub20_fix1_structural_alignment"/"sub20_game_rows_skipped_by_all_variants.tsv"
    p_kr=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    p_us=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_us_display_messages.tsv"
    p_sub09=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    print("[1/6] Verify pinned inputs",flush=True)
    status=load_pinned(p_status,EXPECTED_STATUS_SHA,"SUB20 status")
    blocks=load_pinned(p_blocks,EXPECTED_BLOCKS_SHA,"SUB20 blocks")
    high=load_pinned(p_high,EXPECTED_HIGH_SHA,"SUB20 high")
    kr=load_pinned(p_kr,EXPECTED_KR_SHA,"SUB19 KR")
    us=load_pinned(p_us,EXPECTED_US_SHA,"SUB19 US")
    sub09=load_pinned(p_sub09,EXPECTED_SUB09_SHA,"SUB09")
    skipped=read_tsv(p_skipped) if p_skipped.exists() else []

    if len(status)!=EXPECTED_STATUS_ROWS:
        raise RuntimeError(f"status rows={len(status)}")
    if len(high)!=EXPECTED_HIGH_ROWS:
        raise RuntimeError(f"high rows={len(high)}")
    if len(blocks)!=EXPECTED_BLOCKS:
        raise RuntimeError(f"blocks={len(blocks)}")

    review=[r for r in status if r["structural_high"]!="YES"]
    if len(review)!=EXPECTED_REVIEW_ROWS:
        raise RuntimeError(f"review rows={len(review)}")

    print("[2/6] Build game/US indices",flush=True)
    game=[r for r in kr if r["command"] in ("MSG","MSG_FORCED")]
    if len(game)!=1976:
        raise RuntimeError(f"game dialogue-like rows={len(game)} expected=1976")

    game_by_key={game_key(r):r for r in game}
    game_pos={game_key(r):i for i,r in enumerate(game)}
    us_by_voice=us_index(us)
    skipped_all={r["game_key"] for r in skipped}

    status_by_seq={int(r["sub09_sequence"]):r for r in status}
    high_by_seq={int(r["sub09_sequence"]):r for r in high}
    sub09_by_seq={int(r["sequence"]):r for r in sub09}

    print("[3/6] Build block candidate intervals",flush=True)
    block_summary=[]
    subtitle_rows=[]
    game_rows=[]
    anchor_rows=[]

    for bi,b in enumerate(blocks,1):
        block_id=int(b["block_id"])
        seqs=[int(x) for x in b["subtitle_sequences"].split()]
        prev_key=b["previous_high_game"].strip()
        next_key=b["next_high_game"].strip()

        if not prev_key or not next_key:
            raise RuntimeError(f"block {block_id} lacks bounding high anchors")
        if prev_key not in game_pos or next_key not in game_pos:
            raise RuntimeError(f"block {block_id} anchor key missing from game index")

        a=game_pos[prev_key]+1
        z=game_pos[next_key]
        if a>z:
            raise RuntimeError(f"block {block_id} reversed game interval")

        interval_keys=[game_key(r) for r in game[a:z]]

        variant_union=set()
        variant_hits=defaultdict(lambda:defaultdict(list))
        for seq in seqs:
            s=status_by_seq[seq]
            for vname,field in VARIANT_FIELDS:
                for k in split_keys(s[field]):
                    variant_union.add(k)
                    variant_hits[k][vname].append(seq)

        candidate_keys=[]
        seen=set()
        for k in interval_keys + sorted(variant_union,key=lambda x:game_pos.get(x,10**9)):
            if k in game_by_key and k not in seen:
                candidate_keys.append(k);seen.add(k)

        # Variant candidates should remain inside the two trusted high anchors.
        outside=[k for k in variant_union if k in game_pos and not (a<=game_pos[k]<z)]
        if outside:
            raise RuntimeError(f"block {block_id} variant candidates outside high-anchor interval: {outside}")

        # block subtitles
        for seq in seqs:
            s=status_by_seq[seq]
            subtitle_rows.append({
                "block_id":block_id,
                "sub09_sequence":seq,
                "video_part":s["video_part"],
                "speaker_original":s["subtitle_speaker_original"],
                "speaker_alignment":s["subtitle_speaker_alignment"],
                "korean":s["subtitle_text"],
                "baseline":s["variant_baseline"],
                "conservative":s["variant_conservative"],
                "merge_friendly":s["variant_merge_friendly"],
                "three_variant_consensus":s["three_variant_consensus"],
            })

        # game candidates
        for order,k in enumerate(candidate_keys,1):
            g=game_by_key[k]
            hits,us_text=us_for_game(g,us_by_voice)
            hit_desc=[]
            for vname,_ in VARIANT_FIELDS:
                ss=variant_hits[k].get(vname,[])
                if ss:
                    hit_desc.append(vname+":"+",".join(map(str,ss)))

            game_rows.append({
                "block_id":block_id,
                "candidate_order":order,
                "game_key":k,
                "event_file":g["event_file"],
                "event_display_index":g["event_display_index"],
                "command":g["command"],
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "us_match_count":len(hits),
                "us_commands":" | ".join(x["command"] for x in hits),
                "us_speakers":" | ".join(x["speaker_code"] for x in hits),
                "english":" || ".join(x["text"] for x in hits),
                "in_high_anchor_interval":"YES" if k in interval_keys else "NO",
                "variant_assigned":"YES" if k in variant_union else "NO",
                "variant_assignments":" | ".join(hit_desc),
                "skipped_by_all_3_variants":"YES" if k in skipped_all else "NO",
            })

        # high anchor context
        for side,key,seq_text in (
            ("PREVIOUS",prev_key,b["previous_high_sub09_sequence"]),
            ("NEXT",next_key,b["next_high_sub09_sequence"]),
        ):
            seq=int(seq_text)
            h=high_by_seq[seq]
            g=game_by_key[key]
            hits,us_text=us_for_game(g,us_by_voice)
            anchor_rows.append({
                "block_id":block_id,
                "side":side,
                "sub09_sequence":seq,
                "speaker":h["subtitle_speaker_original"],
                "korean":h["subtitle_text"],
                "game_key":key,
                "speaker_code":g["speaker_code"],
                "voice_id":g["voice_id"],
                "japanese":g["text"],
                "english":us_text,
            })

        block_summary.append({
            "block_id":block_id,
            "first_sub09_sequence":seqs[0],
            "last_sub09_sequence":seqs[-1],
            "subtitle_rows":len(seqs),
            "candidate_game_rows":len(candidate_keys),
            "interval_game_rows":len(interval_keys),
            "variant_union_rows":len(variant_union),
            "previous_high_sub09_sequence":b["previous_high_sub09_sequence"],
            "previous_high_game":prev_key,
            "next_high_sub09_sequence":b["next_high_sub09_sequence"],
            "next_high_game":next_key,
            "crosses_event_boundary":"YES" if game_by_key[prev_key]["event_file"]!=game_by_key[next_key]["event_file"] else "NO",
            "subtitle_preview":" || ".join(
                f"{status_by_seq[s]['subtitle_speaker_original']}:{short(status_by_seq[s]['subtitle_text'],80)}"
                for s in seqs[:6]
            ),
        })

    print("[4/6] Write TSV review bundle",flush=True)
    write_tsv(
        out/"sub21_review_blocks.tsv",block_summary,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence",
            "subtitle_rows","candidate_game_rows","interval_game_rows","variant_union_rows",
            "previous_high_sub09_sequence","previous_high_game",
            "next_high_sub09_sequence","next_high_game",
            "crosses_event_boundary","subtitle_preview"
        ]
    )
    write_tsv(
        out/"sub21_block_subtitles.tsv",subtitle_rows,
        [
            "block_id","sub09_sequence","video_part","speaker_original","speaker_alignment",
            "korean","baseline","conservative","merge_friendly","three_variant_consensus"
        ]
    )
    write_tsv(
        out/"sub21_block_game_candidates.tsv",game_rows,
        [
            "block_id","candidate_order","game_key","event_file","event_display_index",
            "command","speaker_code","voice_id","japanese",
            "us_match_count","us_commands","us_speakers","english",
            "in_high_anchor_interval","variant_assigned","variant_assignments",
            "skipped_by_all_3_variants"
        ]
    )
    write_tsv(
        out/"sub21_block_high_anchor_context.tsv",anchor_rows,
        [
            "block_id","side","sub09_sequence","speaker","korean",
            "game_key","speaker_code","voice_id","japanese","english"
        ]
    )

    print("[5/6] Build human-readable packets",flush=True)
    sub_by_block=defaultdict(list)
    for r in subtitle_rows:sub_by_block[int(r["block_id"])].append(r)
    game_by_block=defaultdict(list)
    for r in game_rows:game_by_block[int(r["block_id"])].append(r)
    anchor_by_block=defaultdict(list)
    for r in anchor_rows:anchor_by_block[int(r["block_id"])].append(r)

    packet_paths=[]
    chunk=25
    for start in range(1,EXPECTED_BLOCKS+1,chunk):
        end=min(EXPECTED_BLOCKS,start+chunk-1)
        p=out/f"sub21_review_packet_{start:03d}_{end:03d}.txt"
        lines=[
            f"Naruto PSP SUB21 semantic review packet: blocks {start}..{end}",
            "="*92,
            "",
            "This packet contains CANDIDATES ONLY. No mapping is semantically confirmed here.",
            "",
        ]
        for bid in range(start,end+1):
            bs=block_summary[bid-1]
            lines += [
                "",
                "#"*92,
                f"BLOCK {bid:03d}  SUB09 {bs['first_sub09_sequence']}..{bs['last_sub09_sequence']}  "
                f"subtitles={bs['subtitle_rows']} candidates={bs['candidate_game_rows']}",
                "#"*92,
            ]
            for arow in anchor_by_block[bid]:
                lines += [
                    f"[{arow['side']} HIGH] SUB09#{arow['sub09_sequence']} "
                    f"{arow['speaker']}: {arow['korean']}",
                    f"  GAME {arow['game_key']} {arow['speaker_code']} {arow['voice_id']}",
                    f"  JP: {arow['japanese']}",
                    f"  EN: {arow['english']}",
                ]
            lines.append("")
            lines.append("[KOREAN SUBTITLES TO ALIGN]")
            for s in sub_by_block[bid]:
                lines.append(
                    f"  S{s['sub09_sequence']} {s['speaker_original']}: {s['korean']}"
                )
                lines.append(
                    f"    DP B={s['baseline']} / C={s['conservative']} / M={s['merge_friendly']}"
                )
            lines.append("")
            lines.append("[GAME CANDIDATES BETWEEN HIGH ANCHORS]")
            for g in game_by_block[bid]:
                flags=[]
                if g["variant_assigned"]=="YES":flags.append("DP")
                if g["skipped_by_all_3_variants"]=="YES":flags.append("SKIP-ALL")
                flag=(" ["+",".join(flags)+"]") if flags else ""
                lines.append(
                    f"  G{g['candidate_order']:02d} {g['game_key']} "
                    f"{g['speaker_code']} {g['voice_id']}{flag}"
                )
                lines.append(f"    JP: {g['japanese']}")
                lines.append(f"    EN: {g['english']}")
                if g["variant_assignments"]:
                    lines.append(f"    VAR: {g['variant_assignments']}")
            lines.append("")
        p.write_text("\n".join(lines)+"\n",encoding="utf-8-sig")
        packet_paths.append(p)

    # Quick statistics
    cand_counts=[int(r["candidate_game_rows"]) for r in block_summary]
    cross=sum(1 for r in block_summary if r["crosses_event_boundary"]=="YES")
    us_unique=sum(1 for r in game_rows if int(r["us_match_count"])==1)
    us_missing=sum(1 for r in game_rows if int(r["us_match_count"])==0)

    report={
        "stage":"SUB21",
        "mode":"READ_ONLY_SEMANTIC_REVIEW_BUNDLE",
        "ambiguous_blocks":len(block_summary),
        "subtitle_rows_to_review":len(subtitle_rows),
        "candidate_game_rows_emitted":len(game_rows),
        "candidate_rows_per_block":{
            "min":min(cand_counts),
            "max":max(cand_counts),
            "mean":sum(cand_counts)/len(cand_counts),
        },
        "cross_event_blocks":cross,
        "candidate_rows_with_unique_us_voice_match":us_unique,
        "candidate_rows_without_us_voice_match":us_missing,
        "packet_files":[p.name for p in packet_paths],
        "semantic_decisions_made":0,
        "game_files_modified":False,
    }
    (out/"sub21_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    print("[6/6] Final checks",flush=True)
    if len(block_summary)!=157:
        raise RuntimeError("block count changed")
    if len(subtitle_rows)!=423:
        raise RuntimeError("review subtitle count changed")
    if min(cand_counts)<1:
        raise RuntimeError("block with zero candidates")
    if max(cand_counts)>40:
        raise RuntimeError(f"unexpected huge candidate interval: {max(cand_counts)}")

    summary=[
        "Naruto PSP SUB21 - Semantic Review Bundle",
        "",
        f"AmbiguousBlocks={len(block_summary)}",
        f"SubtitleRowsToReview={len(subtitle_rows)}",
        f"CandidateGameRowsEmitted={len(game_rows)}",
        f"CandidateRowsPerBlockMin={min(cand_counts)}",
        f"CandidateRowsPerBlockMax={max(cand_counts)}",
        f"CandidateRowsPerBlockMean={sum(cand_counts)/len(cand_counts):.3f}",
        f"CrossEventBlocks={cross}",
        f"CandidateRowsWithUniqueUSVoiceMatch={us_unique}",
        f"CandidateRowsWithoutUSVoiceMatch={us_missing}",
        f"ReviewPacketFiles={len(packet_paths)}",
        "",
        "Each block contains:",
        "  previous/next structural-high anchor",
        "  Korean SUB09 rows to align",
        "  every KR game dialogue candidate between the two high anchors",
        "  exact same-event voice-ID US text when available",
        "  assignments proposed by each of the 3 SUB20 variants",
        "  SKIP-ALL marker for game rows skipped by all 3 variants",
        "",
        "No semantic mapping was decided in SUB21.",
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
