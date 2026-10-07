#!/usr/bin/env python3
# Naruto PSP SUB08 - speaker structure audit / ambiguous speaker image collector

from __future__ import annotations
import argparse, csv, shutil
from pathlib import Path

EXACT_SPEAKER_LINES = {
    "이노","쵸지","리","오로치마루","일동"
}

AMBIGUOUS_SEQUENCES = {
    325: "short first line '김' - likely speaker OCR",
    401: "short first line '길' - likely speaker OCR",
    474: "short first line '길' - likely speaker OCR",
    494: "short first line '길' - likely speaker OCR",
    602: "first line '모르지마족' - likely character-name OCR",
    1239: "first line '모로치마우' - likely 오로치마루 OCR",
}

def read_tsv(p: Path):
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(p: Path, rows, fields):
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def first_global(s: str):
    for x in (s or "").split(","):
        x=x.strip()
        if x.isdigit():
            return int(x)
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub07_final_corpus"/"sub07_final_sequence.tsv"
    sub02=root/"analysis"/"sub"/"sub02_visual_review"/"sub02_reviewed_2086.tsv"
    if not src.exists():
        raise SystemExit(f"Missing SUB07: {src}")
    if not sub02.exists():
        raise SystemExit(f"Missing SUB02 source map: {sub02}")

    rows=read_tsv(src)
    srcrows=read_tsv(sub02)
    srcmap={int(r["global_index"]):r for r in srcrows}

    exact=[]
    ambiguous=[]

    for r in rows:
        seq=int(r["sequence"])
        if r["entry_type"]!="NARRATION":
            continue
        full=r["full_text"]
        lines=[x.strip() for x in full.splitlines() if x.strip()]
        if len(lines)<2:
            continue
        first=lines[0]

        if first in EXACT_SPEAKER_LINES:
            exact.append({
                "sequence":seq,
                "global_index":first_global(r["source_global_indices"]),
                "timestamp":r["observed_first_timestamp"],
                "first_line":first,
                "full_text":full,
                "recommended_action":"REPARSE_SPEAKER_METADATA",
            })

        if seq in AMBIGUOUS_SEQUENCES:
            g=first_global(r["source_global_indices"])
            spath=""
            if g is not None and g in srcmap:
                spath=srcmap[g].get("source_path","")
            ambiguous.append({
                "sequence":seq,
                "global_index":"" if g is None else g,
                "timestamp":r["observed_first_timestamp"],
                "first_line":first,
                "full_text":full,
                "reason":AMBIGUOUS_SEQUENCES[seq],
                "source_path":spath,
            })

    exact.sort(key=lambda x:x["sequence"])
    ambiguous.sort(key=lambda x:x["sequence"])

    write_tsv(
        out/"sub08_exact_structure_rows.tsv",
        exact,
        ["sequence","global_index","timestamp","first_line","full_text","recommended_action"]
    )
    write_tsv(
        out/"sub08_ambiguous_speaker_rows.tsv",
        ambiguous,
        ["sequence","global_index","timestamp","first_line","full_text","reason","source_path"]
    )

    imgdir=out/"review_images"
    imgdir.mkdir(exist_ok=True)
    manifest=[]
    missing=[]

    for r in ambiguous:
        srcp=Path(r["source_path"]) if r["source_path"] else None
        if not srcp or not srcp.exists():
            missing.append(r)
            continue
        dst=imgdir/f"seq{int(r['sequence']):04d}_g{int(r['global_index']):04d}_{srcp.name}"
        shutil.copy2(srcp,dst)
        manifest.append({
            "image":dst.name,
            "sequence":r["sequence"],
            "global_index":r["global_index"],
            "timestamp":r["timestamp"],
            "current_first_line":r["first_line"],
            "current_full_text":r["full_text"],
        })

    write_tsv(
        out/"review_image_manifest.tsv",
        manifest,
        ["image","sequence","global_index","timestamp","current_first_line","current_full_text"]
    )
    if missing:
        write_tsv(
            out/"missing_review_images.tsv",
            missing,
            ["sequence","global_index","timestamp","first_line","full_text","reason","source_path"]
        )

    expected_exact = {296,306,338,611,1185,1604,1779,1848}
    got_exact = {int(r["sequence"]) for r in exact}
    if got_exact != expected_exact:
        raise SystemExit(
            f"Exact speaker-structure set changed. expected={sorted(expected_exact)} got={sorted(got_exact)}"
        )

    expected_amb=set(AMBIGUOUS_SEQUENCES)
    got_amb={int(r["sequence"]) for r in ambiguous}
    if got_amb != expected_amb:
        raise SystemExit(
            f"Ambiguous set changed. expected={sorted(expected_amb)} got={sorted(got_amb)}"
        )

    summary=[
        "Naruto PSP SUB08 - Speaker Structure Audit",
        "",
        f"InputEntries={len(rows)}",
        f"ExactSpeakerMetadataRows={len(exact)}",
        f"AmbiguousSpeakerRows={len(ambiguous)}",
        f"ReviewImagesCopied={len(manifest)}",
        f"ReviewImagesMissing={len(missing)}",
        "",
        "Exact metadata-only candidates:",
    ]
    for r in exact:
        summary.append(f"  seq{r['sequence']} g{r['global_index']} first={r['first_line']}")
    summary += [
        "",
        "Ambiguous visual-review candidates:",
    ]
    for r in ambiguous:
        summary.append(f"  seq{r['sequence']} g{r['global_index']} first={r['first_line']}")
    summary += [
        "",
        "No subtitle text or shared handoff is modified by SUB08.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
