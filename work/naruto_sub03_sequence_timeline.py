#!/usr/bin/env python3
# Naruto PSP SUB03 FIX1 - finalized dialogue sequence / YouTube subtitle anchors
from __future__ import annotations
import argparse, csv, re
from pathlib import Path
from collections import Counter, defaultdict

FINAL_FIX = {
    1142: "[EMPTY]",
    1219: "[EMPTY]",
    1816: "[EMPTY]",
    2064: "지라이야\n훗...?",
}
MERGE_IDENTICAL_MAX_GAP_SEC = 5.0

def read_tsv(p: Path):
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(p: Path, rows, fields):
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_csv(p: Path, rows, fields):
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def ts_to_sec(ts: str) -> float:
    h,m,s = ts.split(":")
    return int(h)*3600 + int(m)*60 + float(s)

def sec_to_ts(sec: float) -> str:
    sec=max(0.0,float(sec))
    h=int(sec//3600); sec-=h*3600
    m=int(sec//60); sec-=m*60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"

def append_action(old: str, action: str) -> str:
    return (old+";" if old else "")+action

def apply_final_fix(r):
    g=int(r["global_index"])
    if g not in FINAL_FIX:
        return
    t=FINAL_FIX[g]
    r["cleaned_ocr"]=t
    r["review_reason"]=""
    if t=="[EMPTY]":
        r["speaker"]=""
        r["dialogue_text"]=""
        r["class"]="EMPTY"
        r["use_for_dialogue"]="NO"
        r["auto_action"]=append_action(r.get("auto_action",""),"SUB03_FINAL_VISUAL_EMPTY")
    else:
        lines=t.splitlines()
        r["speaker"]=lines[0]
        r["dialogue_text"]="\n".join(lines[1:])
        r["class"]="KOREAN"
        r["use_for_dialogue"]="YES"
        r["auto_action"]=append_action(r.get("auto_action",""),"SUB03_FINAL_VISUAL_CORRECTION")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shared", required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    shared=Path(args.shared)
    out.mkdir(parents=True, exist_ok=True)
    shared.mkdir(parents=True, exist_ok=True)

    src=root/"analysis"/"sub"/"sub02_visual_review"/"sub02_reviewed_2086.tsv"
    if not src.exists():
        raise SystemExit(f"SUB02 input not found: {src}")
    rows=read_tsv(src)
    if len(rows)!=2086:
        raise SystemExit(f"Expected 2086 rows, found {len(rows)}")

    rows=[dict(r) for r in rows]
    for r in rows:
        apply_final_fix(r)

    # Filter to useful Korean dialogue/narration anchors.
    filtered=[]
    excluded=[]
    for r in rows:
        g=int(r["global_index"])
        reason=""
        if r["use_for_dialogue"]!="YES":
            reason=f"USE_{r['use_for_dialogue']}"
        elif r["cleaned_ocr"]=="[EMPTY]" or not r["cleaned_ocr"].strip():
            reason="EMPTY"
        elif r["speaker"].strip() and not r["dialogue_text"].strip():
            reason="SPEAKER_ONLY"
        if reason:
            x=dict(r); x["sub03_exclude_reason"]=reason
            excluded.append(x)
            continue

        x=dict(r)
        x["_sec"]=ts_to_sec(r["timestamp"])
        x["entry_type"]="DIALOGUE" if r["speaker"].strip() else "NARRATION"
        filtered.append(x)

    filtered.sort(key=lambda r:(r["video_part"], int(r["part_index"])))

    # Merge only adjacent, exactly identical texts in same video part and within 5 sec.
    merged=[]
    for r in filtered:
        if merged:
            prev=merged[-1]
            gap=r["_sec"]-prev["_last_sec"]
            if (r["video_part"]==prev["video_part"]
                and r["cleaned_ocr"]==prev["full_text"]
                and 0 <= gap <= MERGE_IDENTICAL_MAX_GAP_SEC):
                prev["_last_sec"]=r["_sec"]
                prev["observed_last_timestamp"]=r["timestamp"]
                prev["source_global_indices"] += f",{r['global_index']}"
                prev["source_part_indices"] += f",{r['part_index']}"
                prev["source_files"] += f" | {r['filename']}"
                prev["merged_source_count"] += 1
                continue

        merged.append({
            "video_part":r["video_part"],
            "entry_type":r["entry_type"],
            "speaker":r["speaker"],
            "text":r["dialogue_text"] if r["speaker"].strip() else r["cleaned_ocr"],
            "full_text":r["cleaned_ocr"],
            "observed_first_timestamp":r["timestamp"],
            "observed_last_timestamp":r["timestamp"],
            "_first_sec":r["_sec"],
            "_last_sec":r["_sec"],
            "source_global_indices":str(r["global_index"]),
            "source_part_indices":str(r["part_index"]),
            "source_files":r["filename"],
            "merged_source_count":1,
        })

    # Add sequence numbers and anchor gaps without fabricating subtitle start/end times.
    by_part=defaultdict(list)
    for m in merged:
        by_part[m["video_part"]].append(m)

    final=[]
    global_seq=0
    for part in ("part1","part2"):
        arr=by_part.get(part,[])
        for i,m in enumerate(arr):
            global_seq+=1
            prev_sec=arr[i-1]["_last_sec"] if i>0 else None
            next_sec=arr[i+1]["_first_sec"] if i+1<len(arr) else None
            first=m["_first_sec"]; last=m["_last_sec"]
            final.append({
                "sequence":global_seq,
                "part_sequence":i+1,
                "video_part":part,
                "entry_type":m["entry_type"],
                "speaker":m["speaker"],
                "text":m["text"],
                "full_text":m["full_text"],
                "observed_first_timestamp":m["observed_first_timestamp"],
                "observed_last_timestamp":m["observed_last_timestamp"],
                "observed_first_sec":f"{first:.3f}",
                "observed_last_sec":f"{last:.3f}",
                "observed_span_sec":f"{last-first:.3f}",
                "gap_from_prev_sec":"" if prev_sec is None else f"{first-prev_sec:.3f}",
                "gap_to_next_sec":"" if next_sec is None else f"{next_sec-last:.3f}",
                "source_global_indices":m["source_global_indices"],
                "source_part_indices":m["source_part_indices"],
                "source_files":m["source_files"],
                "merged_source_count":m["merged_source_count"],
            })

    fields=[
        "sequence","part_sequence","video_part","entry_type","speaker","text","full_text",
        "observed_first_timestamp","observed_last_timestamp",
        "observed_first_sec","observed_last_sec","observed_span_sec",
        "gap_from_prev_sec","gap_to_next_sec",
        "source_global_indices","source_part_indices","source_files","merged_source_count"
    ]
    write_tsv(out/"sub03_dialogue_sequence.tsv",final,fields)
    write_csv(out/"sub03_dialogue_sequence.csv",final,fields)
    write_tsv(shared/"youtube_subtitle_anchors.tsv",final,fields)

    excl_fields=list(excluded[0].keys()) if excluded else [
        "global_index","sub03_exclude_reason"
    ]
    write_tsv(out/"sub03_excluded_rows.tsv",excluded,excl_fields)

    # Text-only corpus, one entry separated by a blank line.
    blocks=[]
    for r in final:
        if r["speaker"]:
            blocks.append(r["speaker"]+"\n"+r["text"])
        else:
            blocks.append(r["text"])
    (out/"sub03_dialogue_corpus.txt").write_text(
        "\n\n".join(blocks)+"\n", encoding="utf-8-sig"
    )

    # Final char frequency from sequence text + speaker names.
    cc=Counter(); cf=Counter(); ex=defaultdict(list)
    for r in final:
        s=(r["speaker"]+"\n" if r["speaker"] else "")+r["text"]
        seen=set()
        for ch in s:
            if "\uac00" <= ch <= "\ud7a3":
                cc[ch]+=1; seen.add(ch)
                if len(ex[ch])<3:
                    tag=f"seq{r['sequence']}:{r['source_global_indices']}"
                    if tag not in ex[ch]:
                        ex[ch].append(tag)
        for ch in seen:
            cf[ch]+=1
    crows=[{
        "char":ch,"unicode":f"U+{ord(ch):04X}","count":cc[ch],
        "entry_count":cf[ch],"examples":" | ".join(ex[ch])
    } for ch in cc]
    crows.sort(key=lambda x:(-x["count"],ord(x["char"])))
    write_tsv(out/"sub03_char_frequency.tsv",crows,
              ["char","unicode","count","entry_count","examples"])
    (out/"sub03_unique_hangul.txt").write_text(
        "".join(sorted(cc,key=ord)),encoding="utf-8-sig"
    )

    counts=Counter(r["entry_type"] for r in final)
    excl=Counter(r["sub03_exclude_reason"] for r in excluded)
    merge_count=sum(int(r["merged_source_count"])-1 for r in final)

    summary=[
        "Naruto PSP SUB03 - Final Dialogue Sequence / YouTube Anchors",
        "",
        f"InputRows=2086",
        f"FinalEntries={len(final)}",
        f"DialogueEntries={counts['DIALOGUE']}",
        f"NarrationEntries={counts['NARRATION']}",
        f"ExactDuplicateSourceRowsMerged={merge_count}",
        f"UniqueHangul={len(cc)}",
        "",
        "Final visual fixes:",
        "  g1142=[EMPTY]",
        "  g1219=[EMPTY]",
        "  g1816=[EMPTY]",
        "  g2064=지라이야 / 훗...?",
        "",
        "Excluded:",
    ]
    for k,v in excl.most_common():
        summary.append(f"  {k}={v}")
    summary += [
        "",
        "Timing policy:",
        "- observed timestamps are anchors from the YouTube gameplay capture.",
        "- no synthetic subtitle start/end times are invented here.",
        "- identical consecutive text is merged only when observations are <=5 sec apart.",
        "- MOV track can map these anchors to PMF-local time using frame matching.",
        "",
        f"Shared handoff={shared / 'youtube_subtitle_anchors.tsv'}"
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
