#!/usr/bin/env python3
# -*- coding: ascii -*-
# Naruto PSP SUB31 - Full semantic translation review bundle
#
# Read-only. No game patching.
# Every one of the 1976 game dialogue rows becomes a review target.
# OCR-derived Korean is reference-only, never authoritative.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter
from pathlib import Path

EXPECTED_SUB29_SHA="e7376f57f4b475aaaa0ae3707ea297b28b8d0de4bcbf6fafc21e88fd021b1b71"
EXPECTED_ROWS=1976
PACKET_SIZE=200

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
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

def context_text(r):
    if not r:
        return ""
    return " | ".join([
        r.get("speaker_code",""),
        r.get("japanese",""),
        r.get("english",""),
        r.get("final_korean",""),
    ])

def source_class(r):
    s=r.get("sub29_source","")
    if s=="SUB28_REUSE":
        return "OCR_REUSE_DRAFT"
    if s=="SUB28_REUSE_FIX":
        return "OCR_REUSE_TECH_FIX_DRAFT"
    if s=="SUB29_DIRECT":
        return "JP_EN_DIRECT_DRAFT"
    if s=="SUB29_TOPOLOGY_REWRITE":
        return "TOPOLOGY_REWRITE_DRAFT"
    return s or "UNKNOWN"

def flags(r):
    out=[]
    sc=source_class(r)
    if sc.startswith("OCR_REUSE"):
        out.append("OCR_REFERENCE_ONLY")
    if sc=="JP_EN_DIRECT_DRAFT":
        out.append("DIRECT_TRANSLATION_REVIEW")
    if sc=="TOPOLOGY_REWRITE_DRAFT":
        out.append("MERGE_SPLIT_REVIEW")
    if int(r.get("max_visible_chars_per_line") or 0)>=24:
        out.append("LONG_LINE")
    if "<br>" in r.get("final_korean",""):
        out.append("HAS_BR")
    if "<KOFF>" in r.get("final_korean","") or "<KON>" in r.get("final_korean",""):
        out.append("HAS_KOFF_KON")
    if not r.get("speaker_code",""):
        out.append("BLANK_SPEAKER")
    if not r.get("voice_id",""):
        out.append("UNVOICED")
    return " | ".join(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub29_completed_korean_draft"/"sub29_full_korean_draft_1976.tsv"
    if not src.exists():
        raise RuntimeError(f"SUB29 draft missing: {src}")
    got=sha256_file(src)
    if got.lower()!=EXPECTED_SUB29_SHA.lower():
        raise RuntimeError(f"SUB29 draft SHA mismatch: {got}")

    rows=read_tsv(src)
    if len(rows)!=EXPECTED_ROWS:
        raise RuntimeError(f"SUB29 row count={len(rows)} expected={EXPECTED_ROWS}")

    review=[]
    source_counts=Counter()
    for i,r in enumerate(rows):
        prev_r=rows[i-1] if i>0 and rows[i-1]["event_file"]==r["event_file"] else None
        next_r=rows[i+1] if i+1<len(rows) and rows[i+1]["event_file"]==r["event_file"] else None
        sc=source_class(r)
        source_counts[sc]+=1

        review.append({
            "review_index":i+1,
            "game_global_dialogue_index":r["game_global_dialogue_index"],
            "game_key":r["game_key"],
            "event_file":r["event_file"],
            "event_display_index":r["event_display_index"],
            "command":r["command"],
            "speaker_code":r["speaker_code"],
            "voice_id":r["voice_id"],
            "topology_status":r["topology_status"],
            "sub09_sequences":r["sub09_sequences"],
            "draft_source_class":sc,
            "review_flags":flags(r),

            "japanese":r["japanese"],
            "english":r["english"],
            "ocr_korean_reference":r["source_korean"],
            "current_sub29_korean":r["final_korean"],
            "original_control_sequence":r["original_control_sequence"],

            "previous_context":context_text(prev_r),
            "next_context":context_text(next_r),

            "current_payload_bytes":r["final_payload_bytes"],
            "current_max_visible_chars_per_line":r["max_visible_chars_per_line"],

            "review_status":"PENDING_FULL_SEMANTIC_REVIEW",
            "revised_korean":"",
            "review_note":"",
        })

    fields=list(review[0].keys())
    write_tsv(out/"sub31_full_semantic_review_1976.tsv",review,fields)

    packet_files=[]
    for start in range(0,len(review),PACKET_SIZE):
        chunk=review[start:start+PACKET_SIZE]
        a=start+1
        b=start+len(chunk)
        p=out/f"sub31_review_{a:04d}_{b:04d}.tsv"
        write_tsv(p,chunk,fields)
        packet_files.append(p.name)

    event_counts=Counter(r["event_file"] for r in rows)
    event_summary=[]
    for event in sorted(event_counts):
        erows=[r for r in review if r["event_file"]==event]
        event_summary.append({
            "event_file":event,
            "rows":len(erows),
            "first_review_index":erows[0]["review_index"],
            "last_review_index":erows[-1]["review_index"],
            "ocr_reuse_rows":sum(x["draft_source_class"].startswith("OCR_REUSE") for x in erows),
            "direct_draft_rows":sum(x["draft_source_class"]=="JP_EN_DIRECT_DRAFT" for x in erows),
            "topology_rewrite_rows":sum(x["draft_source_class"]=="TOPOLOGY_REWRITE_DRAFT" for x in erows),
        })
    write_tsv(
        out/"sub31_event_review_summary.tsv",
        event_summary,
        [
            "event_file","rows","first_review_index","last_review_index",
            "ocr_reuse_rows","direct_draft_rows","topology_rewrite_rows"
        ]
    )

    report={
        "stage":"SUB31",
        "mode":"READ_ONLY_FULL_SEMANTIC_TRANSLATION_REVIEW_BUNDLE",
        "rows":len(review),
        "all_rows_require_semantic_review":True,
        "ocr_is_reference_only":True,
        "source_counts":dict(source_counts),
        "packet_size":PACKET_SIZE,
        "packet_files":packet_files,
        "game_files_modified":False,
    }
    (out/"sub31_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    readme = """# Naruto PSP SUB31 - \uc804\uccb4 \ubc88\uc5ed \uc758\ubbf8 \uac80\uc218 \uaddc\uce59

## \ud575\uc2ec \uc6d0\uce59

1976\uac1c \uac8c\uc784 \ub300\uc0ac \uc804\ubd80\ub97c \ub2e4\uc2dc \uac80\uc218\ud55c\ub2e4.

- \uc77c\ubcf8\uc5b4 \uc6d0\ubb38: **1\ucc28 \uc758\ubbf8 \uae30\uc900**
- US \uc601\uc5b4: **2\ucc28 \uc758\ubbf8/\ubb38\ub9e5 \ucc38\uace0**
- OCR \ud55c\uad6d\uc5b4: **\uae30\uc874 \ud55c\uad6d\uc5b4 \ud45c\ud604 \ucc38\uace0\uc790\ub8cc\uc77c \ubfd0 \uc815\ub2f5\uc73c\ub85c \ucde8\uae09\ud558\uc9c0 \uc54a\uc74c**
- SUB29 \ud55c\uad6d\uc5b4: **\uac80\uc218 \uc804 \ucd08\uc548**

`OCR \ud55c\uad6d\uc5b4\uc640 \ud604\uc7ac \ud55c\uad6d\uc5b4\uac00 \uac19\uc74c`\uc740 \ud1b5\uacfc \uadfc\uac70\uac00 \uc544\ub2c8\ub2e4.

## revised_korean \uc791\uc131 \uaddc\uce59

1. \uc77c\ubcf8\uc5b4 \uc6d0\ubb38\uc758 \uc758\ubbf8\uc640 \ud654\uc790 \ub9d0\ud22c\ub97c \uc6b0\uc120\ud55c\ub2e4.
2. \uc601\uc5b4\ub294 \uc560\ub9e4\ud55c \uc77c\ubcf8\uc5b4/\ubb38\ub9e5 \ud655\uc778\uc6a9\uc73c\ub85c \uc0ac\uc6a9\ud55c\ub2e4.
3. OCR \ud55c\uad6d\uc5b4\ub294 \uae30\uc874 \ubc88\uc5ed \uc5b4\ud718\ub098 \ub9d0\ud22c\ub97c \ucc38\uace0\ud560 \ub54c\ub9cc \uc0ac\uc6a9\ud55c\ub2e4.
4. \ubc88\uc5ed\ud22c, OCR \uc870\uac01 \uacb0\ud569, \ubd80\uc790\uc5f0\uc2a4\ub7ec\uc6b4 \ubc18\ubcf5\uc740 \uc790\uc5f0\uc2a4\ub7fd\uac8c \uace0\uce5c\ub2e4.
5. \uce90\ub9ad\ud130 \uc774\ub984/\uace0\uc720\uba85\uc0ac\ub294 \ud504\ub85c\uc81d\ud2b8\uc5d0\uc11c \uc774\ubbf8 \uc4f0\ub294 \ud45c\uae30\ub97c \uc720\uc9c0\ud55c\ub2e4.
6. `<br>`, `<KOFF>`, `<KON>` \uc81c\uc5b4 \ud1a0\ud070\uc740 `original_control_sequence`\uc640 \uac1c\uc218/\uc21c\uc11c\ub97c \ub9de\ucd98\ub2e4.
7. \uc77c\ubcf8\uc5b4 \uc6d0\ubb38 \ubc14\uc774\ud2b8 \uae38\uc774\uc5d0 \ub9de\ucd9c \ud544\uc694\ub294 \uc5c6\ub2e4.
8. \ub2e4\ub9cc \uc2e4\uc81c \ub300\ud654\ucc3d \ud3ed\uc744 \uace0\ub824\ud574 \ubd88\ud544\uc694\ud558\uac8c \uc7a5\ud669\ud558\uac8c \ub298\uc774\uc9c0 \uc54a\ub294\ub2e4.
9. \uc55e\ub4a4 \ubb38\uc7a5\uc774 \uc774\uc5b4\uc9c0\ub294 \uacbd\uc6b0 `previous_context`, `next_context`\ub97c \ubcf8\ub2e4.
10. OCR\uc758 \ud654\uc790/\ubb38\uc7a5 \uc870\uac01\uc774 \uc758\uc2ec\ub418\uba74 JP/EN\uc744 \uae30\uc900\uc73c\ub85c \uace0\uce5c\ub2e4.

## \ucd9c\ucc98 \ud074\ub798\uc2a4

- `OCR_REUSE_DRAFT`: OCR \uae30\ubc18 \ucd08\uc548. \ubc18\ub4dc\uc2dc \uc6d0\ubb38\uacfc \uc7ac\ub300\uc870.
- `OCR_REUSE_TECH_FIX_DRAFT`: OCR \uae30\ubc18 + \uae30\uc220 \ubb38\uc790 \uc218\uc815. \uc758\ubbf8 \uac80\uc218\ub294 \ub3d9\uc77c.
- `JP_EN_DIRECT_DRAFT`: JP/EN\uc5d0\uc11c \uc0c8\ub85c \ub9cc\ub4e0 \ucd08\uc548.
- `TOPOLOGY_REWRITE_DRAFT`: \ubcd1\ud569/\ubd84\ud560 \ud6c4 \uc7ac\uc791\uc131\ud55c \ucd08\uc548.

\ub2e4\ub978 \uc5f4\uc740 \uc218\uc815\ud558\uc9c0 \ub9d0\uace0 `revised_korean`, \ud544\uc694\ud558\uba74 `review_note`\ub9cc \ucc44\uc6b4\ub2e4.
"""
    (out/"README_SUB31_REVIEW.md").write_text(readme,encoding="utf-8-sig")

    summary=[
        "Naruto PSP SUB31 - Full Semantic Translation Review Bundle",
        "",
        f"Rows={len(review)}",
        "AllRowsRequireSemanticReview=YES",
        "OCRIsReferenceOnly=YES",
        "SourceCounts="+json.dumps(dict(source_counts),ensure_ascii=False,sort_keys=True),
        f"PacketSize={PACKET_SIZE}",
        f"PacketCount={len(packet_files)}",
        "",
        "No game files were modified.",
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
