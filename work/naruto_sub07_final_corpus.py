#!/usr/bin/env python3
# Naruto PSP SUB07 - Apply SUB06 visual corrections and finalize subtitle corpus
from __future__ import annotations
import argparse, csv, re
from pathlib import Path
from collections import Counter, defaultdict

REPLACEMENTS = {157: [('그림', '그럼'), ('애기', '얘기')],
 158: [('애기', '얘기')],
 163: [('나못잎', '나뭇잎')],
 348: [('이단 거', '이딴 거')],
 392: [('나못없', '나뭇잎')],
 397: [('나못잎', '나뭇잎')],
 402: [('나못잎', '나뭇잎')],
 443: [('시터', '시녀')],
 525: [('나못잎', '나뭇잎'), ('농들이', '놈들이')],
 526: [('나못잎', '나뭇잎')],
 543: [('애기', '얘기')],
 551: [('종오', '증오')],
 583: [('애기', '얘기')],
 601: [('둘기', '돕기')],
 619: [('종오', '증오')],
 652: [('니루토', '나루토')],
 660: [('종오', '증오')],
 676: [('애기', '얘기')],
 678: [('담자인', '닌자인'), ('애기따위', '얘기따위')],
 685: [('나못없', '나뭇잎')],
 689: [('애기를', '얘기를')],
 743: [('애기가', '얘기가')],
 755: [('애기지', '얘기지')],
 771: [('나못없', '나뭇잎')],
 773: [('애기지', '얘기지')],
 807: [('군게 달혀있던', '굳게 닫혀있던')],
 859: [('애기를', '얘기를')],
 889: [('나못잎', '나뭇잎'), ('거였냐고!!', '거였냐고!!?')],
 1104: [('나못없', '나뭇잎')],
 1188: [('둘기나', '돕기나')],
 1361: [('쓰려졌다', '쓰러졌다')],
 1373: [('희안하군', '희한하군')],
 1381: [('니자를', '닌자를')],
 1388: [('나지 않겠어', '낫지 않겠어')],
 1401: [('담자는', '닌자는')],
 1479: [('거짓장소의 솔', '거짓장소의 술')],
 1480: [('거짓장소의 솔', '거짓장소의 술')],
 1494: [('거짓장소의 솔이', '거짓장소의 술이')],
 1505: [('애기는', '얘기는')],
 1564: [('나못잎', '나뭇잎')],
 1567: [('합락당했다고', '함락당했다고')],
 1587: [('패나 강력하게', '꽤나 강력하게')],
 1641: [('겹이 다른', '격이 다른')],
 1691: [('나못잎', '나뭇잎')],
 1706: [('척도', '쳐도')],
 1781: [('나못없', '나뭇잎')],
 1782: [('나못잎', '나뭇잎')],
 1795: [('잠아', '잖아')],
 1801: [('공지 있는', '긍지 있는')],
 1824: [('나못잎', '나뭇잎'), ('없잖아', '없잖냐')],
 1851: [('모로치마루', '오로치마루')]}
OVERRIDES = {189: '나루토\n!!?',
 211: '나루토\n...!?',
 400: '나루토\n!?',
 517: '나루토\n...!',
 520: '나루토\n...!!?',
 546: '나루토\n...!!',
 673: '나루토\n...!?',
 732: '시카마루\n!!',
 1064: '나루토\n!!!',
 1114: '나루토\n!!!',
 1125: '나루토\n...!!',
 1133: '나루토\n모두….',
 1166: '나루토\n보고 있으라고….',
 1171: '나루토\n!!?',
 1301: '나루토\n... 헤헤.',
 1761: '오로치마루\n100년은 이르다구!!!!!'}
VISUAL_UNCHANGED = {420: '앞으로 라니 — 화면 원문 그대로', 486: '혹시건 뭐건 — 화면 원문 그대로'}

BAD_PATTERNS = [
    "나두토","니루토","나우토","나못잎","나못없",
    "오로치마족","모로치마루","시카마우","담자","종오",
    "희안하","시터","쓰려졌다","니자를","거짓장소의 솔",
    "솔이 걸려","겹이 다른","척도","둘기","패나 강력",
    "이단 거","나지 않겠어","잠아","공지 있는","군게",
    "달혀","합락"
]

EXPECTED_ENTRIES=1900
EXPECTED_SUB06_REVIEW=69
EXPECTED_CHANGED=67
EXPECTED_UNCHANGED=2
EXPECTED_UNIQUE_HANGUL=694

def read_tsv(p):
    with open(p,"r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(p,rows,fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def write_csv(p,rows,fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--shared",required=True)
    a=ap.parse_args()

    root=Path(a.root); out=Path(a.out); shared=Path(a.shared)
    out.mkdir(parents=True,exist_ok=True)
    shared.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub05_corrected_anchors"/"sub05_corrected_sequence.tsv"
    sub06=root/"analysis"/"sub"/"sub06_common_ocr_review"/"sub06_review_queue.tsv"
    if not src.exists(): raise SystemExit(f"Missing SUB05: {src}")
    if not sub06.exists(): raise SystemExit(f"Missing SUB06: {sub06}")

    rows=read_tsv(src)
    review=read_tsv(sub06)
    if len(rows)!=EXPECTED_ENTRIES:
        raise SystemExit(f"Expected {EXPECTED_ENTRIES} entries, got {len(rows)}")
    if len(review)!=EXPECTED_SUB06_REVIEW:
        raise SystemExit(f"Expected {EXPECTED_SUB06_REVIEW} SUB06 rows, got {len(review)}")

    byseq={int(r["sequence"]):r for r in rows}
    review_seqs={int(r["sequence"]) for r in review}
    expected_review=set(REPLACEMENTS)|set(OVERRIDES)|set(VISUAL_UNCHANGED)
    if review_seqs != expected_review:
        raise SystemExit(
            f"SUB06 sequence mismatch missing={sorted(expected_review-review_seqs)} "
            f"extra={sorted(review_seqs-expected_review)}"
        )

    correction_log=[]
    audit=[]
    changed_count=0

    for seq in sorted(review_seqs):
        r=byseq[seq]
        before=r["full_text"]
        after=before
        action="VISUAL_CONFIRMED_UNCHANGED"

        if seq in OVERRIDES:
            after=OVERRIDES[seq]
            action="VISUAL_FULL_OVERRIDE"
        elif seq in REPLACEMENTS:
            for old,new in REPLACEMENTS[seq]:
                if old not in after:
                    raise SystemExit(
                        f"Replacement mismatch seq{seq}: expected {old!r} in {after!r}"
                    )
                after=after.replace(old,new)
            action="VISUAL_REPLACEMENT"

        if after != before:
            changed_count += 1
            r["full_text"]=after
            if "\n" in after:
                sp,body=after.split("\n",1)
                r["speaker"]=sp
                r["text"]=body
                r["entry_type"]="DIALOGUE"
            else:
                r["text"]=after

            correction_log.append({
                "sequence":seq,
                "source_global_indices":r["source_global_indices"],
                "before":before,
                "after":after,
                "action":action,
            })

        r["sub07_visual_status"]="VISUAL_VERIFIED"
        r["sub07_corpus_include"]=r.get("sub05_corpus_include","YES")

        audit.append({
            "sequence":seq,
            "source_global_indices":r["source_global_indices"],
            "action":action,
            "before":before,
            "after":after,
            "note":VISUAL_UNCHANGED.get(seq,""),
        })

    # Non-SUB06 rows still inherit the corpus status.
    for r in rows:
        if "sub07_visual_status" not in r:
            r["sub07_visual_status"]="NOT_SUB06_TARGET"
        if "sub07_corpus_include" not in r:
            r["sub07_corpus_include"]=r.get("sub05_corpus_include","YES")

    if changed_count != EXPECTED_CHANGED:
        raise SystemExit(f"Expected {EXPECTED_CHANGED} changed rows, got {changed_count}")
    if len(VISUAL_UNCHANGED) != EXPECTED_UNCHANGED:
        raise SystemExit("Unexpected visual-unchanged count")

    # Known systematic OCR corruption must be gone.
    residual=[]
    for r in rows:
        hits=[p for p in BAD_PATTERNS if p in r["full_text"]]
        if hits:
            x=dict(r); x["bad_patterns"]="|".join(hits); residual.append(x)

    if residual:
        write_tsv(out/"sub07_residual_bad_patterns.tsv",residual,
                  list(residual[0].keys()))
        raise SystemExit(f"Residual known OCR bad-pattern rows remain: {len(residual)}")

    # Final character frequency; unresolved g24 remains excluded via inherited status.
    cc=Counter(); ec=Counter(); examples=defaultdict(list)
    included_entries=0
    for r in rows:
        if r["sub07_corpus_include"]!="YES":
            continue
        included_entries += 1
        seen=set()
        for ch in r["full_text"]:
            if "\uac00" <= ch <= "\ud7a3":
                cc[ch]+=1; seen.add(ch)
                if len(examples[ch])<3:
                    tag=f"seq{r['sequence']}:g{r['source_global_indices']}"
                    if tag not in examples[ch]: examples[ch].append(tag)
        for ch in seen: ec[ch]+=1

    if len(cc)!=EXPECTED_UNIQUE_HANGUL:
        raise SystemExit(
            f"Expected {EXPECTED_UNIQUE_HANGUL} final unique Hangul, got {len(cc)}"
        )

    fields=list(rows[0].keys())
    write_tsv(out/"sub07_final_sequence.tsv",rows,fields)
    write_csv(out/"sub07_final_sequence.csv",rows,fields)
    write_tsv(out/"sub07_correction_log.tsv",correction_log,
              ["sequence","source_global_indices","before","after","action"])
    write_tsv(out/"sub07_visual_audit.tsv",audit,
              ["sequence","source_global_indices","action","before","after","note"])

    crows=[{
        "char":ch,
        "unicode":f"U+{ord(ch):04X}",
        "count":cc[ch],
        "entry_count":ec[ch],
        "examples":" | ".join(examples[ch]),
    } for ch in cc]
    crows.sort(key=lambda x:(-x["count"],ord(x["char"])))
    write_tsv(out/"sub07_final_char_frequency.tsv",crows,
              ["char","unicode","count","entry_count","examples"])

    unique="".join(sorted(cc,key=ord))
    (out/"sub07_final_unique_hangul.txt").write_text(unique,encoding="utf-8-sig")

    # Final plain-text corpus, preserving speaker + dialogue.
    blocks=[]
    for r in rows:
        if r["sub07_corpus_include"]!="YES": continue
        blocks.append(r["full_text"])
    (out/"sub07_final_dialogue_corpus.txt").write_text(
        "\n\n".join(blocks)+"\n",encoding="utf-8-sig")

    # Shared MOV handoff is updated with the corrected anchors.
    shared_out=shared/"youtube_subtitle_anchors.tsv"
    write_tsv(shared_out,rows,fields)

    excluded=[r for r in rows if r["sub07_corpus_include"]!="YES"]
    write_tsv(out/"sub07_excluded_from_char_corpus.tsv",excluded,fields)

    summary=[
        "Naruto PSP SUB07 - Final OCR-cleaned Subtitle Corpus",
        "",
        f"Entries={len(rows)}",
        f"SUB06VisualReviewRows={len(review)}",
        f"VisualCorrectionsApplied={changed_count}",
        f"VisualConfirmedUnchanged={len(VISUAL_UNCHANGED)}",
        f"ResidualKnownBadPatternRows=0",
        f"CorpusIncludedEntries={included_entries}",
        f"CorpusExcludedEntries={len(excluded)}",
        f"FinalUniqueHangul={len(cc)}",
        "",
        "Visually confirmed unchanged:",
        "  seq420: 앞으로 라니 — source image really says this",
        "  seq486: 혹시건 뭐건 — source image really says this",
        "",
        "Remaining intentional exclusion:",
        "  g24 title-style text is cropped at the top and remains excluded from character corpus.",
        "",
        f"SharedHandoff={shared_out}",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
