#!/usr/bin/env python3
# Naruto PSP SUB20 - Ensemble structural dialogue alignment
#
# Read-only. No semantic claim and no game patch.
#
# Inputs:
#   SUB19 FIX1 KR decoded display-message inventory
#   SUB09 final 1900 subtitle corpus
#
# Scope:
#   Game: MSG / MSG_FORCED rows (including blank speaker rows)
#   Subtitle: DIALOGUE rows sequence 19..1883
#
# Three independent speaker-structure dynamic-programming variants are run.
# Only identical 1:1 assignments across ALL THREE variants with an explicit
# compatible game speaker are promoted to STRUCTURAL_HIGH anchors.
#
# Important:
# This is speaker/order consensus, NOT semantic verification.

from __future__ import annotations
import argparse, csv, hashlib, json, math, sys, time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_KR_TSV_SHA="aad0a83b6b60acc86b107dfde029903dcced86c1fdb198f6c2daa46809531f54"
EXPECTED_SUB09_SHA="59e376ba446e9e898e52d293b79f3eac13235bc9fb0ef4fc3bb22f6df47d8d4e"
EXPECTED_GAME_ROWS=1976
EXPECTED_SUB_ROWS=1761

# Speaker map established from code names + direct text/context checks.
# A set is used because some apparition labels in the OCR corpus vary.
SPEAKER_ALLOWED={
    "NRT":{"나루토"},
    "JRY":{"지라이야"},
    "KSU":{"카스미"},
    "KKS":{"카카시"},
    "KRH":{"키리히메"},
    "TND":{"츠나데"},
    "SKR":{"사쿠라"},
    "ORC":{"오로치마루"},
    "SIK":{"시카마루"},
    "KBT":{"카부토"},
    "SZN":{"시즈네"},
    "HNT":{"히나타"},
    "HKG":{"3대 호카게"},
    "NEJ":{"네지"},
    "ROC":{"리"},
    "HST":{"병사대장"},
    "GUY":{"가이"},
    "GAR":{"가아라"},
    "ONK":{"여자아이"},
    "SN1":{"사념제","사념체"},
    "KIB":{"키바"},
    "JJO":{"시녀"},
    "SIN":{"시도"},
    "TYO":{"쵸지"},
    "INO":{"이노"},
    "HIS":{"병사"},
    "TEN":{"텐텐"},
    "SNS":{"사념체","사념제"},
    "KSM":{"키사메"},
    "ITD":{"일동"},
    "JRS":{"일동"},
    "JT2":{"일동"},
}

# Alignment-only normalization. The SUB09 source file is NEVER modified.
SUB_SPEAKER_NORMALIZE={
    "이도":"이노",  # OCR label error visible in the Ino/Shikamaru/Choji scene
}

VARIANTS=[
    {
        "name":"BASELINE",
        "merge2":0.18,"merge3":0.38,
        "split2":0.28,"split3":0.55,
        "skip_game":1.00,"skip_sub":1.40,
        "wildcard":0.35,
    },
    {
        "name":"CONSERVATIVE",
        "merge2":0.32,"merge3":0.75,
        "split2":0.45,"split3":0.90,
        "skip_game":0.90,"skip_sub":1.50,
        "wildcard":0.35,
    },
    {
        "name":"MERGE_FRIENDLY",
        "merge2":0.08,"merge3":0.20,
        "split2":0.18,"split3":0.35,
        "skip_game":1.10,"skip_sub":1.30,
        "wildcard":0.35,
    },
]

OP_NAME={
    1:"1G_1S",
    2:"SKIP_GAME",
    3:"SKIP_SUB",
    4:"2G_1S",
    5:"3G_1S",
    6:"1G_2S",
    7:"1G_3S",
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

def game_desc(r):
    return (
        f"{game_key(r)} {r['command']} "
        f"{r['speaker_code'] or '<BLANK>'} {r['voice_id']} :: {r['text']}"
    )

def sub_desc(r):
    return f"SUB09#{int(r['sequence']):04d} {r['speaker']} :: {r['text']}"

def load_inputs(root:Path):
    kr_path=root/"analysis"/"sub"/"sub19_fix1_event_inventory"/"sub19_fix1_kr_display_messages.tsv"
    sub_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_sequence.tsv"

    for p in (kr_path,sub_path):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    kr_sha=sha256_file(kr_path)
    sub_sha=sha256_file(sub_path)
    if kr_sha.lower()!=EXPECTED_KR_TSV_SHA:
        raise RuntimeError(f"KR SUB19 TSV SHA mismatch: {kr_sha}")
    if sub_sha.lower()!=EXPECTED_SUB09_SHA:
        raise RuntimeError(f"SUB09 TSV SHA mismatch: {sub_sha}")

    kr=read_tsv(kr_path)
    subs=read_tsv(sub_path)

    game=[]
    for r in kr:
        if r["command"] not in ("MSG","MSG_FORCED"):
            continue
        x=dict(r)
        code=x["speaker_code"]
        x["_allowed"]=frozenset(SPEAKER_ALLOWED.get(code,set())) if code else frozenset()
        x["_key"]=game_key(x)
        game.append(x)

    sub=[]
    for r in subs:
        seq=int(r["sequence"])
        if not (19<=seq<=1883):
            continue
        if r["entry_type"]!="DIALOGUE":
            continue
        x=dict(r)
        x["_speaker_norm"]=SUB_SPEAKER_NORMALIZE.get(x["speaker"],x["speaker"])
        sub.append(x)

    if len(game)!=EXPECTED_GAME_ROWS:
        raise RuntimeError(f"game dialogue-like rows={len(game)} expected={EXPECTED_GAME_ROWS}")
    if len(sub)!=EXPECTED_SUB_ROWS:
        raise RuntimeError(f"SUB09 event-window dialogue rows={len(sub)} expected={EXPECTED_SUB_ROWS}")

    return kr_path,sub_path,game,sub

def compatible(allowed,subspeaker):
    return (not allowed) or (subspeaker in allowed)

def run_alignment(game,sub,cfg,variant_index):
    """
    Full DP, standard-library only.
    op matrix is bytearray; score matrix uses float32 array.
    """
    n=len(game); m=len(sub); width=m+1
    size=(n+1)*width
    INF=1.0e20

    print(f"[variant {variant_index}/3] {cfg['name']} initialize {n} x {m}",flush=True)
    dp=array("f",[INF])*size
    op=bytearray(size)
    dp[0]=0.0

    for i in range(1,n+1):
        idx=i*width
        dp[idx]=dp[(i-1)*width]+cfg["skip_game"]
        op[idx]=2
    for j in range(1,m+1):
        dp[j]=dp[j-1]+cfg["skip_sub"]
        op[j]=3

    t0=time.time()

    for i in range(1,n+1):
        if i==1 or i%250==0 or i==n:
            print(
                f"[variant {variant_index}/3] {cfg['name']} "
                f"row {i}/{n} elapsed={time.time()-t0:.1f}s",
                flush=True
            )

        g=game[i-1]
        ga=g["_allowed"]
        row=i*width
        prev=(i-1)*width
        prev2=(i-2)*width if i>=2 else 0
        prev3=(i-3)*width if i>=3 else 0

        g2=game[i-2] if i>=2 else None
        g3=game[i-3] if i>=3 else None

        for j in range(1,m+1):
            ssp=sub[j-1]["_speaker_norm"]

            c=cfg["wildcard"] if not ga else (0.0 if ssp in ga else 4.0)
            best=dp[prev+j-1]+c
            bop=1

            v=dp[prev+j]+cfg["skip_game"]
            if v<best:
                best=v; bop=2

            v=dp[row+j-1]+cfg["skip_sub"]
            if v<best:
                best=v; bop=3

            if i>=2:
                ok=compatible(g2["_allowed"],ssp) and compatible(ga,ssp)
                if ok:
                    blanks=(1 if not g2["_allowed"] else 0)+(1 if not ga else 0)
                    v=dp[prev2+j-1]+cfg["merge2"]+0.08*blanks
                    if v<best:
                        best=v; bop=4

            if i>=3:
                ok=(
                    compatible(g3["_allowed"],ssp)
                    and compatible(g2["_allowed"],ssp)
                    and compatible(ga,ssp)
                )
                if ok:
                    blanks=(
                        (1 if not g3["_allowed"] else 0)
                        +(1 if not g2["_allowed"] else 0)
                        +(1 if not ga else 0)
                    )
                    v=dp[prev3+j-1]+cfg["merge3"]+0.08*blanks
                    if v<best:
                        best=v; bop=5

            if j>=2 and sub[j-2]["_speaker_norm"]==ssp and compatible(ga,ssp):
                v=dp[prev+j-2]+cfg["split2"]+(0.08 if not ga else 0.0)
                if v<best:
                    best=v; bop=6

            if (
                j>=3
                and sub[j-2]["_speaker_norm"]==ssp
                and sub[j-3]["_speaker_norm"]==ssp
                and compatible(ga,ssp)
            ):
                v=dp[prev+j-3]+cfg["split3"]+(0.08 if not ga else 0.0)
                if v<best:
                    best=v; bop=7

            dp[row+j]=best
            op[row+j]=bop

    final_score=float(dp[n*width+m])
    print(
        f"[variant {variant_index}/3] {cfg['name']} DP done "
        f"score={final_score:.3f} elapsed={time.time()-t0:.1f}s",
        flush=True
    )

    # Traceback.
    i=n; j=m
    steps=[]
    sub_assign={}
    game_assign=defaultdict(list)

    while i or j:
        o=op[i*width+j]

        if o==1:
            gi=[i-1]; sj=[j-1]
            i-=1; j-=1
        elif o==2:
            gi=[i-1]; sj=[]
            i-=1
        elif o==3:
            gi=[]; sj=[j-1]
            j-=1
        elif o==4:
            gi=[i-2,i-1]; sj=[j-1]
            i-=2; j-=1
        elif o==5:
            gi=[i-3,i-2,i-1]; sj=[j-1]
            i-=3; j-=1
        elif o==6:
            gi=[i-1]; sj=[j-2,j-1]
            i-=1; j-=2
        elif o==7:
            gi=[i-1]; sj=[j-3,j-2,j-1]
            i-=1; j-=3
        else:
            raise RuntimeError(f"traceback invalid op={o} at i={i} j={j}")

        steps.append((o,gi,sj))

    steps.reverse()

    for o,gi,sj in steps:
        keys=tuple(game[x]["_key"] for x in gi)
        for sidx in sj:
            sub_assign[int(sub[sidx]["sequence"])]=keys
        for gidx in gi:
            for sidx in sj:
                game_assign[game[gidx]["_key"]].append(int(sub[sidx]["sequence"]))

    counts=Counter(OP_NAME[o] for o,_,_ in steps)
    skipped_game=[
        game[gi[0]]["_key"]
        for o,gi,sj in steps if o==2
    ]
    skipped_sub=[
        int(sub[sj[0]]["sequence"])
        for o,gi,sj in steps if o==3
    ]

    del dp
    del op

    return {
        "name":cfg["name"],
        "score":final_score,
        "steps":steps,
        "sub_assign":sub_assign,
        "game_assign":dict(game_assign),
        "counts":dict(counts),
        "skipped_game":skipped_game,
        "skipped_sub":skipped_sub,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    kr_path,sub_path,game,sub=load_inputs(root)

    print(f"GameDialogueLikeRows={len(game)}",flush=True)
    print(f"SubtitleDialogueRows={len(sub)}",flush=True)

    results=[]
    for idx,cfg in enumerate(VARIANTS,1):
        results.append(run_alignment(game,sub,cfg,idx))

    game_by_key={r["_key"]:r for r in game}
    sub_by_seq={int(r["sequence"]):r for r in sub}

    # Speaker map evidence table.
    code_counts=Counter(r["speaker_code"] for r in game)
    speaker_rows=[]
    for code,count in sorted(code_counts.items(),key=lambda kv:(-kv[1],kv[0])):
        allowed=SPEAKER_ALLOWED.get(code,set()) if code else set()
        speaker_rows.append({
            "speaker_code":code or "<BLANK>",
            "game_rows":count,
            "allowed_subtitle_speakers":" | ".join(sorted(allowed)) if allowed else "<WILDCARD>",
            "policy":(
                "BLANK_WILDCARD"
                if not code else
                "APPARITION_ALIAS"
                if code in ("SN1","SNS") else
                "FIXED_MAP"
            ),
        })
    write_tsv(
        out/"sub20_speaker_map.tsv",
        speaker_rows,
        ["speaker_code","game_rows","allowed_subtitle_speakers","policy"]
    )

    # One row per subtitle dialogue.
    all_rows=[]
    high_rows=[]
    ambiguous_rows=[]
    event_high=Counter()

    for s in sub:
        seq=int(s["sequence"])
        assigns=[r["sub_assign"].get(seq,tuple()) for r in results]
        consensus=(assigns[0]==assigns[1]==assigns[2])
        consensus_keys=assigns[0] if consensus else tuple()

        high=False
        high_reason=""
        if consensus and len(consensus_keys)==1:
            g=game_by_key[consensus_keys[0]]
            if g["_allowed"] and s["_speaker_norm"] in g["_allowed"]:
                high=True
                high_reason="3_VARIANT_CONSENSUS_1TO1_EXPLICIT_SPEAKER"
                event_high[g["event_file"]]+=1

        row={
            "sub09_sequence":seq,
            "video_part":s["video_part"],
            "subtitle_speaker_original":s["speaker"],
            "subtitle_speaker_alignment":s["_speaker_norm"],
            "subtitle_text":s["text"],
            "variant_baseline":" | ".join(assigns[0]),
            "variant_conservative":" | ".join(assigns[1]),
            "variant_merge_friendly":" | ".join(assigns[2]),
            "three_variant_consensus":"YES" if consensus else "NO",
            "consensus_game_rows":" | ".join(consensus_keys),
            "structural_high":"YES" if high else "NO",
            "high_reason":high_reason,
        }

        if consensus_keys:
            gs=[game_by_key[k] for k in consensus_keys]
            row.update({
                "consensus_event_files":" | ".join(g["event_file"] for g in gs),
                "consensus_commands":" | ".join(g["command"] for g in gs),
                "consensus_speaker_codes":" | ".join(g["speaker_code"] or "<BLANK>" for g in gs),
                "consensus_voice_ids":" | ".join(g["voice_id"] for g in gs),
                "consensus_japanese":" || ".join(g["text"] for g in gs),
            })
        else:
            row.update({
                "consensus_event_files":"",
                "consensus_commands":"",
                "consensus_speaker_codes":"",
                "consensus_voice_ids":"",
                "consensus_japanese":"",
            })

        all_rows.append(row)
        if high:
            high_rows.append(row)
        else:
            ambiguous_rows.append(row)

    fields=[
        "sub09_sequence","video_part",
        "subtitle_speaker_original","subtitle_speaker_alignment","subtitle_text",
        "variant_baseline","variant_conservative","variant_merge_friendly",
        "three_variant_consensus","consensus_game_rows","structural_high","high_reason",
        "consensus_event_files","consensus_commands","consensus_speaker_codes",
        "consensus_voice_ids","consensus_japanese",
    ]
    write_tsv(out/"sub20_all_dialogue_status.tsv",all_rows,fields)
    write_tsv(out/"sub20_structural_high_anchors.tsv",high_rows,fields)
    write_tsv(out/"sub20_needs_semantic_review.tsv",ambiguous_rows,fields)

    # Contiguous ambiguous blocks in subtitle-dialogue order.
    high_seq={int(r["sub09_sequence"]) for r in high_rows}
    blocks=[]
    cur=[]
    for s in sub:
        seq=int(s["sequence"])
        if seq in high_seq:
            if cur:
                blocks.append(cur); cur=[]
        else:
            cur.append(seq)
    if cur:blocks.append(cur)

    block_rows=[]
    dialogue_seqs=[int(s["sequence"]) for s in sub]
    pos={seq:i for i,seq in enumerate(dialogue_seqs)}

    for bi,block in enumerate(blocks,1):
        first=block[0]; last=block[-1]
        p0=pos[first]; p1=pos[last]
        prev_seq=dialogue_seqs[p0-1] if p0>0 else None
        next_seq=dialogue_seqs[p1+1] if p1+1<len(dialogue_seqs) else None

        prev_row=next((r for r in high_rows if int(r["sub09_sequence"])==prev_seq),None)
        next_row=next((r for r in high_rows if int(r["sub09_sequence"])==next_seq),None)

        block_rows.append({
            "block_id":bi,
            "first_sub09_sequence":first,
            "last_sub09_sequence":last,
            "subtitle_dialogue_rows":len(block),
            "subtitle_sequences":" ".join(str(x) for x in block),
            "previous_high_sub09_sequence":prev_seq or "",
            "previous_high_game":prev_row["consensus_game_rows"] if prev_row else "",
            "next_high_sub09_sequence":next_seq or "",
            "next_high_game":next_row["consensus_game_rows"] if next_row else "",
            "subtitle_preview":" || ".join(
                f"{sub_by_seq[x]['speaker']}:{sub_by_seq[x]['text']}"
                for x in block[:8]
            ),
        })

    write_tsv(
        out/"sub20_ambiguous_blocks.tsv",
        block_rows,
        [
            "block_id","first_sub09_sequence","last_sub09_sequence",
            "subtitle_dialogue_rows","subtitle_sequences",
            "previous_high_sub09_sequence","previous_high_game",
            "next_high_sub09_sequence","next_high_game","subtitle_preview"
        ]
    )

    # Variant operation/skips report.
    variant_rows=[]
    for r in results:
        variant_rows.append({
            "variant":r["name"],
            "score":f"{r['score']:.6f}",
            "operations":json.dumps(r["counts"],ensure_ascii=False,sort_keys=True),
            "skipped_game_rows":len(r["skipped_game"]),
            "skipped_subtitle_rows":len(r["skipped_sub"]),
            "skipped_subtitle_sequences":" ".join(str(x) for x in r["skipped_sub"]),
        })
    write_tsv(
        out/"sub20_variant_summary.tsv",
        variant_rows,
        [
            "variant","score","operations","skipped_game_rows",
            "skipped_subtitle_rows","skipped_subtitle_sequences"
        ]
    )

    # Game rows skipped by ALL three structural variants.
    skipped_all=set(results[0]["skipped_game"])
    for r in results[1:]:
        skipped_all &= set(r["skipped_game"])

    skipped_all_rows=[]
    for key in sorted(
        skipped_all,
        key=lambda k:(
            int(game_by_key[k]["global_display_sequence"])
        )
    ):
        g=game_by_key[key]
        skipped_all_rows.append({
            "game_key":key,
            "event_file":g["event_file"],
            "event_display_index":g["event_display_index"],
            "command":g["command"],
            "speaker_code":g["speaker_code"],
            "voice_id":g["voice_id"],
            "japanese":g["text"],
            "note":"SKIPPED_BY_ALL_3_STRUCTURAL_VARIANTS",
        })
    write_tsv(
        out/"sub20_game_rows_skipped_by_all_variants.tsv",
        skipped_all_rows,
        [
            "game_key","event_file","event_display_index","command",
            "speaker_code","voice_id","japanese","note"
        ]
    )

    # High-anchor event coverage.
    total_by_event=Counter(r["event_file"] for r in game)
    event_rows=[]
    for ev in sorted(total_by_event,key=lambda x:int(x[5:8])):
        event_rows.append({
            "event_file":ev,
            "game_dialogue_like_rows":total_by_event[ev],
            "structural_high_anchors":event_high[ev],
            "anchor_ratio":f"{event_high[ev]/total_by_event[ev]:.6f}",
        })
    write_tsv(
        out/"sub20_event_anchor_coverage.tsv",
        event_rows,
        ["event_file","game_dialogue_like_rows","structural_high_anchors","anchor_ratio"]
    )

    # Important fixed anchors.
    first_high=next((r for r in high_rows if int(r["sub09_sequence"])==19),None)
    last_high=next((r for r in high_rows if int(r["sub09_sequence"])==1883),None)
    if not first_high or first_high["consensus_game_rows"]!="event000.tbl#001":
        raise RuntimeError("opening anchor SUB09#19 -> event000#001 was not preserved")
    if not last_high or last_high["consensus_game_rows"]!="event112.tbl#122":
        raise RuntimeError("closing anchor SUB09#1883 -> event112#122 was not preserved")

    # Sequence 1337 is expected to sit in the movie bridge between event025/event100.
    s1337=next(r for r in all_rows if int(r["sub09_sequence"])==1337)

    report={
        "stage":"SUB20",
        "mode":"READ_ONLY_3_VARIANT_STRUCTURAL_ALIGNMENT",
        "input_kr_tsv_sha256":sha256_file(kr_path),
        "input_sub09_sha256":sha256_file(sub_path),
        "game_dialogue_like_rows":len(game),
        "subtitle_event_window_dialogue_rows":len(sub),
        "structural_high_anchors":len(high_rows),
        "needs_semantic_review_rows":len(ambiguous_rows),
        "ambiguous_blocks":len(block_rows),
        "speaker_normalization_alignment_only":SUB_SPEAKER_NORMALIZE,
        "variant_summaries":variant_rows,
        "game_rows_skipped_by_all_variants":len(skipped_all_rows),
        "opening_anchor":"SUB09#19 -> event000.tbl#001",
        "closing_anchor":"SUB09#1883 -> event112.tbl#122",
        "sub09_1337":{
            "speaker":s1337["subtitle_speaker_original"],
            "text":s1337["subtitle_text"],
            "structural_high":s1337["structural_high"],
            "note":"Located in non-event/movie bridge between event025 and event100; do not force into TBL.",
        },
        "semantic_verification_performed":False,
        "game_files_modified":False,
    }
    (out/"sub20_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB20 - 3-Variant Structural Dialogue Alignment",
        "",
        f"GameDialogueLikeRows={len(game)}",
        f"SubtitleEventWindowDialogueRows={len(sub)}",
        f"StructuralHighAnchors={len(high_rows)}",
        f"NeedsSemanticReviewRows={len(ambiguous_rows)}",
        f"AmbiguousBlocks={len(block_rows)}",
        f"GameRowsSkippedByAllVariants={len(skipped_all_rows)}",
        "",
        "OpeningAnchor=SUB09#19 -> event000.tbl#001",
        "ClosingAnchor=SUB09#1883 -> event112.tbl#122",
        "",
        "Alignment-only speaker handling:",
        "  이도 -> 이노 (source SUB09 is NOT modified)",
        "  SN1/SNS apparition labels allow 사념제/사념체 aliases",
        "  blank game speaker is a low-cost wildcard",
        "",
        "IMPORTANT:",
        "  STRUCTURAL_HIGH means all 3 speaker/order DPs chose the same",
        "  explicit-speaker 1:1 game row. It is NOT yet semantic proof.",
        "  All remaining rows must be reviewed using JP/KO context before patching.",
        "",
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
