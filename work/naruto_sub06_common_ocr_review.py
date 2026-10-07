#!/usr/bin/env python3
# Naruto PSP SUB06 - Common/systematic OCR residual visual review collector

from __future__ import annotations
import argparse, csv, shutil
from pathlib import Path

PATTERNS = [
    "나두토","니루토","나우토","나못잎","나못없",
    "오로치마족","모로치마루","시카마우",
    "담자","애기","종오","희안하","시터","쓰려졌다","니자를",
    "거짓장소의 솔","솔이 걸려","겹이 다른","척도","둘기",
    "패나 강력","이단 거","혹시건","앞으로 라니","나지 않겠어",
    "잠아","공지 있는","군게","달혀","합락"
]

def read_tsv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

def first_global_index(s: str):
    for x in (s or "").split(","):
        x=x.strip()
        if x.isdigit():
            return int(x)
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sub05=root/"analysis"/"sub"/"sub05_corrected_anchors"/"sub05_corrected_sequence.tsv"
    sub02=root/"analysis"/"sub"/"sub02_visual_review"/"sub02_reviewed_2086.tsv"
    if not sub05.exists():
        raise SystemExit(f"Missing SUB05: {sub05}")
    if not sub02.exists():
        raise SystemExit(f"Missing SUB02: {sub02}")

    rows=read_tsv(sub05)
    src_rows=read_tsv(sub02)
    src_map={int(r["global_index"]):r for r in src_rows}

    candidates=[]
    for r in rows:
        hits=[p for p in PATTERNS if p in r["full_text"]]
        if not hits:
            continue
        g=first_global_index(r.get("source_global_indices",""))
        source_path=""
        if g is not None and g in src_map:
            source_path=src_map[g].get("source_path","")
        x={
            "sequence":r["sequence"],
            "video_part":r["video_part"],
            "global_index":"" if g is None else g,
            "timestamp":r["observed_first_timestamp"],
            "speaker":r["speaker"],
            "text":r["text"],
            "full_text":r["full_text"],
            "matched_patterns":"|".join(hits),
            "source_global_indices":r["source_global_indices"],
            "source_files":r["source_files"],
            "source_path":source_path,
        }
        candidates.append(x)

    candidates.sort(key=lambda r:int(r["sequence"]))

    fields=[
        "sequence","video_part","global_index","timestamp","speaker","text","full_text",
        "matched_patterns","source_global_indices","source_files","source_path"
    ]
    write_tsv(out/"sub06_review_queue.tsv", candidates, fields)

    imgdir=out/"review_images"
    imgdir.mkdir(exist_ok=True)
    manifest=[]
    missing=[]
    for r in candidates:
        src=Path(r["source_path"]) if r["source_path"] else None
        if not src or not src.exists():
            missing.append(r)
            continue
        dst=imgdir/f"seq{int(r['sequence']):04d}_g{int(r['global_index']):04d}_{src.name}"
        shutil.copy2(src,dst)
        manifest.append({
            "image":dst.name,
            "sequence":r["sequence"],
            "global_index":r["global_index"],
            "timestamp":r["timestamp"],
            "matched_patterns":r["matched_patterns"],
            "current_text":r["full_text"],
        })

    write_tsv(out/"review_image_manifest.tsv",manifest,
              ["image","sequence","global_index","timestamp","matched_patterns","current_text"])
    if missing:
        write_tsv(out/"missing_review_images.tsv",missing,fields)

    # Pattern counts.
    counts=[]
    for p in PATTERNS:
        n=sum(1 for r in candidates if p in r["matched_patterns"].split("|"))
        if n:
            counts.append({"pattern":p,"rows":n})
    write_tsv(out/"pattern_counts.tsv",counts,["pattern","rows"])

    summary=[
        "Naruto PSP SUB06 - Common/Systematic OCR Residual Review",
        "",
        f"InputEntries={len(rows)}",
        f"ReviewRows={len(candidates)}",
        f"ImagesCopied={len(manifest)}",
        f"ImagesMissing={len(missing)}",
        "",
        "Purpose:",
        "- Catch recurring OCR errors that rare-character review cannot detect.",
        "- Do not auto-correct based on language/context alone.",
        "- Every candidate is visually reviewed against its source frame.",
        "",
        "Patterns:"
    ]
    for c in counts:
        summary.append(f"  {c['pattern']}={c['rows']}")
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
