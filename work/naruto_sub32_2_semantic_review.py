#!/usr/bin/env python3
# -*- coding: ascii -*-
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from pathlib import Path

EXPECTED_PACKET_SHA="1ca830ff7cbbb2a1aa1b61a9b3689b8ea3fa600fe93e4f0221119b1c542d9c57"
EXPECTED_FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
EXPECTED_ROWS=200
EXPECTED_CHANGED=144

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def controls(s):
    return re.findall(r"<[^>]+>",s or "")

def load_font(path):
    rows=read_tsv(path)
    return {r["hangul"] for r in rows if r.get("hangul") and len(r["hangul"])==1}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root);out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub31_full_semantic_review"/"sub31_review_0201_0400.tsv"
    font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    rev_path=Path(__file__).with_name("sub32_2_revisions_0201_0400.json")

    if not src.exists():raise RuntimeError(f"source packet missing: {src}")
    if sha256_file(src).lower()!=EXPECTED_PACKET_SHA:
        raise RuntimeError(f"source packet SHA mismatch: {sha256_file(src)}")
    if not font.exists():raise RuntimeError(f"font mapping missing: {font}")
    if sha256_file(font).lower()!=EXPECTED_FONT_SHA:
        raise RuntimeError(f"font mapping SHA mismatch: {sha256_file(font)}")
    if not rev_path.exists():raise RuntimeError(f"revision JSON missing: {rev_path}")

    rows=read_tsv(src)
    if len(rows)!=EXPECTED_ROWS:raise RuntimeError(f"row count={len(rows)}")

    blob=json.loads(rev_path.read_text(encoding="ascii"))
    rev={int(k):v for k,v in blob["revisions"].items()}
    notes={int(k):v for k,v in blob.get("notes",{}).items()}
    if set(rev)!=set(range(201,401)):
        raise RuntimeError("revision indices incomplete")

    font_chars=load_font(font)
    changed=[]
    control_errors=[]
    missing=set()
    japanese=[]
    out_rows=[]

    for r in rows:
        idx=int(r["review_index"])
        new=rev[idx]
        if controls(new)!=controls(r["japanese"]):
            control_errors.append(idx)
        missing |= {c for c in new if 0xAC00<=ord(c)<=0xD7A3 and c not in font_chars}
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]",new):
            japanese.append(idx)

        old=r["current_sub29_korean"]
        rr=dict(r)
        rr["review_status"]="REVIEWED_JP_PRIMARY_EN_SECONDARY_OCR_REFERENCE_ONLY"
        rr["revised_korean"]=new
        rr["review_note"]=notes.get(
            idx,
            "JP/EN semantic review; wording revised." if new!=old
            else "JP/EN semantic review; existing wording retained."
        )
        out_rows.append(rr)

        if new!=old:
            changed.append({
                "review_index":idx,
                "game_key":r["game_key"],
                "speaker_code":r["speaker_code"],
                "japanese":r["japanese"],
                "english":r["english"],
                "ocr_korean_reference":r["ocr_korean_reference"],
                "before":old,
                "after":new,
                "review_note":rr["review_note"],
            })

    if control_errors:raise RuntimeError(f"control mismatches: {control_errors}")
    if missing:raise RuntimeError("new Hangul glyphs required: "+"".join(sorted(missing)))
    if japanese:raise RuntimeError(f"Japanese letters remain in revised Korean rows: {japanese}")
    if len(changed)!=EXPECTED_CHANGED:
        raise RuntimeError(f"changed={len(changed)} expected={EXPECTED_CHANGED}")

    fields=list(rows[0].keys())
    write_tsv(out/"sub32_2_review_0201_0400_completed.tsv",out_rows,fields)
    write_tsv(
        out/"sub32_2_changed_rows.tsv",changed,
        ["review_index","game_key","speaker_code","japanese","english",
         "ocr_korean_reference","before","after","review_note"]
    )

    report={
        "stage":"SUB32_2",
        "rows_reviewed":len(out_rows),
        "changed_rows":len(changed),
        "retained_rows":len(out_rows)-len(changed),
        "control_exact_rows":len(out_rows),
        "control_mismatches":0,
        "new_hangul_required":0,
        "ocr_authoritative":False,
        "japanese_primary":True,
        "english_secondary":True,
        "game_files_modified":False,
    }
    (out/"sub32_2_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB32-2 - Semantic Review 0201-0400",
        "",
        "RowsReviewed=200",
        f"ChangedRows={len(changed)}",
        f"RetainedRows={200-len(changed)}",
        "ControlExactRows=200",
        "ControlMismatches=0",
        "NewHangulRequired=0",
        "OCRAuthoritative=NO",
        "JapanesePrimary=YES",
        "EnglishSecondary=YES",
        "",
        "No game files were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
