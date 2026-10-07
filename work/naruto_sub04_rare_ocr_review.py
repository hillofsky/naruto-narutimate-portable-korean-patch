#!/usr/bin/env python3
# Naruto PSP SUB04 - Rare/suspicious Hangul OCR review queue

from __future__ import annotations
import argparse, csv, re, shutil
from pathlib import Path
from collections import Counter, defaultdict

SUSPECT_TERMS = [
    "나못있","마판의","효성","어렸냐","빌리","쓰겁니까","솔식을",
    "승승님","승님이","초나데","회한한","1종","겪정","격정",
    "바울","광장히","멘버","상금닌자","말겨두고","여려모로",
    "페를","겹정","연제까지나","감놀","질어지고","췌지","초지",
    "쇼지","뚫하지","쓰스러워","염힘","농한테","있었나간",
    "없혀","않올래","쓰리니까","웃이니","짜응","말겨",
    "무식하게 큰 성","뭐나니깐","잃어내서","필은",
]

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")

def read_tsv(p):
    with open(p,"r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(p,rows,fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def natural_key(s):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)",s)]

def find_source(global_index:int, source_file:str, video_part:str, sub02_map):
    # Best source: SUB02's exact source_path.
    r=sub02_map.get(global_index)
    if r:
        p=Path(r.get("source_path",""))
        if p.exists():
            return p

    # Fallback known crop roots.
    roots=[]
    if video_part=="part1":
        roots=[Path(r"D:\narutimate portable\analysis\stage37")]
    elif video_part=="part2":
        roots=[Path(r"D:\narutimate portable\analysis\stage37b")]
    else:
        roots=[Path(r"D:\narutimate portable\analysis\stage37"),
               Path(r"D:\narutimate portable\analysis\stage37b")]

    for root in roots:
        if not root.exists(): continue
        direct=root/"crops"/source_file
        if direct.exists(): return direct
        hits=list(root.rglob(source_file))
        if hits: return hits[0]
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root); out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    seq_path=root/"analysis"/"sub"/"sub03_sequence_timeline"/"sub03_dialogue_sequence.tsv"
    freq_path=root/"analysis"/"sub"/"sub03_sequence_timeline"/"sub03_char_frequency.tsv"
    sub02_path=root/"analysis"/"sub"/"sub02_visual_review"/"sub02_reviewed_2086.tsv"
    if not seq_path.exists(): raise SystemExit(f"Missing {seq_path}")
    if not freq_path.exists(): raise SystemExit(f"Missing {freq_path}")
    if not sub02_path.exists(): raise SystemExit(f"Missing {sub02_path}")

    seq=read_tsv(seq_path)
    freq_rows=read_tsv(freq_path)
    sub02=read_tsv(sub02_path)
    sub02_map={int(r["global_index"]):r for r in sub02}

    char_freq={r["char"]:int(r["count"]) for r in freq_rows}
    singleton={c for c,n in char_freq.items() if n==1}
    rare3={c for c,n in char_freq.items() if n<=3}

    candidates=[]
    for i,r in enumerate(seq):
        full=r["full_text"]
        chars=set(HANGUL_RE.findall(full))
        single=sorted(chars & singleton)
        low3=sorted(chars & rare3)
        terms=[t for t in SUSPECT_TERMS if t in full]

        reasons=[]
        score=0
        if single:
            reasons.append("SINGLETON_CHAR:"+"".join(single))
            score+=3+len(single)
        if len(low3)>=2:
            reasons.append("MULTI_RARE_LE3:"+"".join(low3))
            score+=2+len(low3)
        if terms:
            reasons.append("SUSPECT_TERM:"+"|".join(terms))
            score+=6+2*len(terms)

        if not reasons:
            continue

        prev_text=seq[i-1]["full_text"] if i>0 and seq[i-1]["video_part"]==r["video_part"] else ""
        next_text=seq[i+1]["full_text"] if i+1<len(seq) and seq[i+1]["video_part"]==r["video_part"] else ""

        globals_=[int(x) for x in r["source_global_indices"].split(",") if x.strip().isdigit()]
        g=globals_[0] if globals_ else -1
        source_file=r["source_files"].split(" | ")[0]
        src=find_source(g,source_file,r["video_part"],sub02_map)

        candidates.append({
            "priority_score":score,
            "sequence":r["sequence"],
            "video_part":r["video_part"],
            "global_index":g,
            "timestamp":r["observed_first_timestamp"],
            "speaker":r["speaker"],
            "text":r["text"],
            "full_text":full,
            "review_reason":";".join(reasons),
            "singleton_chars":"".join(single),
            "rare_le3_chars":"".join(low3),
            "matched_terms":"|".join(terms),
            "prev_full_text":prev_text,
            "next_full_text":next_text,
            "source_file":source_file,
            "source_path":str(src) if src else "",
        })

    candidates.sort(key=lambda x:(-int(x["priority_score"]),int(x["sequence"])))

    fields=[
        "priority_score","sequence","video_part","global_index","timestamp",
        "speaker","text","full_text","review_reason","singleton_chars",
        "rare_le3_chars","matched_terms","prev_full_text","next_full_text",
        "source_file","source_path"
    ]
    write_tsv(out/"sub04_review_queue.tsv",candidates,fields)

    imgdir=out/"review_images"
    imgdir.mkdir(exist_ok=True)
    missing=[]
    copied=[]
    for c in candidates:
        p=Path(c["source_path"]) if c["source_path"] else None
        if not p or not p.exists():
            missing.append(c)
            continue
        dst=imgdir/f"seq{int(c['sequence']):04d}_g{int(c['global_index']):04d}_{p.name}"
        shutil.copy2(p,dst)
        copied.append((c,dst))

    # Mapping file makes visual review unambiguous.
    map_rows=[]
    for c,dst in copied:
        map_rows.append({
            "image":dst.name,
            "sequence":c["sequence"],
            "global_index":c["global_index"],
            "timestamp":c["timestamp"],
            "review_reason":c["review_reason"],
            "current_text":c["full_text"],
        })
    write_tsv(out/"review_image_manifest.tsv",map_rows,
              ["image","sequence","global_index","timestamp","review_reason","current_text"])

    if missing:
        write_tsv(out/"missing_review_images.tsv",missing,fields)

    # Character list driving this review.
    rare_rows=[]
    for r in freq_rows:
        n=int(r["count"])
        if n<=3:
            rare_rows.append(r)
    write_tsv(out/"rare_char_le3.tsv",rare_rows,list(freq_rows[0].keys()))

    reason_counts=Counter()
    for c in candidates:
        for reason in c["review_reason"].split(";"):
            reason_counts[reason.split(":",1)[0]]+=1

    summary=[
        "Naruto PSP SUB04 - Rare/Suspicious Hangul OCR Review",
        "",
        f"SUB03Entries={len(seq)}",
        f"UniqueHangul={len(char_freq)}",
        f"SingletonHangulChars={len(singleton)}",
        f"RareHangulCharsLE3={len(rare3)}",
        f"ReviewRows={len(candidates)}",
        f"ReviewImagesCopied={len(copied)}",
        f"ReviewImagesMissing={len(missing)}",
        "",
        "Candidate rules:",
        "- row contains a Hangul syllable appearing exactly once in SUB03",
        "- OR row contains at least 2 distinct Hangul syllables appearing <=3 times",
        "- OR row contains a known suspicious OCR term",
        "",
        "Reason counts:",
    ]
    for k,v in reason_counts.most_common():
        summary.append(f"  {k}={v}")
    summary += [
        "",
        "No text is modified in SUB04.",
        "This stage only builds a focused visual-review queue.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
