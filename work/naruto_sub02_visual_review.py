#!/usr/bin/env python3
# Naruto PSP SUB02 - visual review corrections + residual anomaly scan

from __future__ import annotations
import argparse, csv, re
from pathlib import Path
from collections import Counter, defaultdict

MANUAL = {
28:"시카마루\n후아아~ 피곤하다...",
31:"나루토\n오랜만에 맡은 임무, 재미있지 않았던 거야?",
34:"나루토\n에헴...!! 난 매일 단련하고 있으니까 말야!\n체력에는 꽤 자신이 있다니깐!",
37:"나루토\n헤헷! 난 일단 일락의 라면이나 실컷...",
320:"나루토\n켁...!",
326:"사쿠라\n켁! 이... 이노의 환영도 나왔어...!",
367:"네지\n헛... 그 점혈을 이용하면...",
395:"나루토\n헷... 그렇겠지!",
410:"여자아이\n저기 저기... 그 머리장식 뭐야?\n언니 지금까지 안했잖지?",
464:"나루토\n큭...! 포기할까보냐!",
523:"[EMPTY]",
535:"나루토\n흠... 왠지 잘 모르겠는걸.",
816:"나루토\n헤헤, 역시 카카시 선생님은 뭘 좀 안다니깐!",
880:"나루토\n큭...!",
901:"키리히메\n큭...!?",
915:"나루토\n헤헤...",
939:"[EMPTY]",
972:"키리히메\n큭...!! 아직이다!!",
1120:"나루토\n헤...헤헤헤... 적이... 아니니까...",
1139:"카부토\n(쳇... 나뭇잎 마을이 도움을 요청한 건가... 재빠르군...)",
1174:"키리히메\n큭...!",
1175:"가아라\n흥... 시시껄렁한 얘기를 계속할 셈이냐...",
1189:"카부토\n큭... 이 빚은 반드시... 갚겠다...",
1223:"나루토\n헤헤...!",
1233:"나루토\n헤헤... 누나는 그 쪽이 훨씬 낫다니까...!",
1241:"나루토\n놔둘까보냐!!",
1263:"나루토\n큭! 대체 어쩌란 말야!!",
1344:"오로치마루\n뭐... 네 힘이란 건 이정도겠지...",
1370:"나루토\n하아아아아아아아아아!!!!",
1372:"나루토\n우오오오오오오오오오!!!!",
1378:"오로치마루\n성에게 생기를 모조리 뺏겨...나뭇잎 마을은 멸망하는 거다.",
1382:"오로치마루\n실컷 소리쳐 보거라...",
1389:"나루토\n큭!!",
1396:"나루토\n크하아아아아아아아아아아!!!!",
1410:"나루토\n헤... 헤헤헤...!",
1442:"나루토\n헤헷... 난 당연한 걸 한 것 뿐이라고...",
1513:"지라이야\n취재... 어흠.\n조금 임무가 있어서 말야.",
1516:"츠나데\n흠... 뭐 좋아...\n분명히 네 말대로야...",
1524:"츠나데\n쳇...",
1588:"지라이야\n켁...!",
1595:"카스미\n후훗... 후후후... 히히힛!",
1614:"지라이야\n헉!!!",
1675:"카카시\n큭... 이건...",
1707:"지라이야\n카하하하하! 사양할 거 없다네!!\n난 이래봬도 잘나가는 작가니까 말야!",
1722:"지라이야\n어... 어흠!! 뭐... 그 뭐냐... 그게...\n그건 우연이다!",
1835:"지라이야\n쳇...",
1845:"츠나데\n큭...!",
1851:"츠나데\n꽤 내려왔군...",
1902:"3대 호카게\n밉다... 으으으...",
1913:"3대 호카게\n으어으어악...! 크후허우악...! 꾸흐응흥...",
1945:"오로치마루\n핫!!!",
1971:"3대 호카게\n정말이지...\n그 상태로는 나뭇잎 마을을 지킬 닌자가 되지 못한다고...",
2055:"츠나데\n큭!! 뭐지!?"
}

JP_EXCLUDE = {
47,117,146,253,287,293,329,379,407,475,502,558,835,856,950,1187,1459,1637
}

NORMALIZED_EXCLAMATIONS = {1370,1372,1396}
ASCII_RE = re.compile(r"[A-Za-z]")

def read_tsv(p):
    with open(p,"r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(p, rows, fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def write_csv(p, rows, fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def add_action(old,new):
    return (old+";" if old else "")+new

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.root)
    out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub01_ocr_cleanup"/"sub01_cleaned_2086.tsv"
    if not src.exists():
        raise SystemExit(f"SUB01 TSV not found: {src}")
    rows=read_tsv(src)
    if len(rows)!=2086:
        raise SystemExit(f"Expected 2086 rows, got {len(rows)}")

    corrections=[]
    final=[]
    for r in rows:
        rr=dict(r)
        g=int(rr["global_index"])

        if g in MANUAL:
            before=rr["cleaned_ocr"]
            after=MANUAL[g]
            rr["cleaned_ocr"]=after
            rr["review_reason"]=""

            if after=="[EMPTY]":
                rr["speaker"]=""
                rr["dialogue_text"]=""
                rr["class"]="EMPTY"
                rr["use_for_dialogue"]="NO"
                action="SUB02_VISUAL_EMPTY"
            else:
                lines=after.splitlines()
                rr["speaker"]=lines[0]
                rr["dialogue_text"]="\n".join(lines[1:])
                rr["class"]="KOREAN"
                rr["use_for_dialogue"]="YES"
                action=("SUB02_VISUAL_NORMALIZED_EXCLAMATION"
                        if g in NORMALIZED_EXCLAMATIONS else
                        "SUB02_VISUAL_CORRECTION")
            rr["auto_action"]=add_action(rr.get("auto_action",""),action)
            corrections.append({
                "global_index":g,
                "filename":rr["filename"],
                "before":before,
                "after":after,
                "action":action
            })

        elif g in JP_EXCLUDE:
            rr["use_for_dialogue"]="NO"
            rr["review_reason"]=""
            rr["auto_action"]=add_action(rr.get("auto_action",""),"SUB02_NON_KOREAN_EXCLUDED")
            corrections.append({
                "global_index":g,
                "filename":rr["filename"],
                "before":rr["cleaned_ocr"],
                "after":rr["cleaned_ocr"],
                "action":"SUB02_NON_KOREAN_EXCLUDED"
            })

        final.append(rr)

    # Residual anomaly scan across all currently accepted dialogue.
    remaining=[]
    for r in final:
        if r["use_for_dialogue"]!="YES":
            continue
        reasons=[]
        t=r["cleaned_ocr"]
        if ASCII_RE.search(t):
            reasons.append("ASCII_ALPHA")
        if "<OCR>" in t or "</OCR>" in t:
            reasons.append("OCR_TAG")
        if reasons:
            x=dict(r)
            x["sub02_review_reason"]=";".join(reasons)
            remaining.append(x)
            r["use_for_dialogue"]="REVIEW"
            r["review_reason"]=";".join(reasons)
            r["auto_action"]=add_action(r.get("auto_action",""),"SUB02_RESIDUAL_REVIEW")

    fields=list(final[0].keys())
    write_tsv(out/"sub02_reviewed_2086.tsv",final,fields)
    write_csv(out/"sub02_reviewed_2086.csv",final,fields)
    write_tsv(out/"sub02_manual_corrections.tsv",corrections,
              ["global_index","filename","before","after","action"])
    rem_fields=list(remaining[0].keys()) if remaining else fields+["sub02_review_reason"]
    write_tsv(out/"sub02_remaining_review.tsv",remaining,rem_fields)

    # Final Korean character frequency from YES rows only.
    cc=Counter(); cf=Counter(); ex=defaultdict(list)
    for r in final:
        if r["use_for_dialogue"]!="YES": continue
        t=r["dialogue_text"] if r["speaker"] else r["cleaned_ocr"]
        seen=set()
        for ch in t:
            if "\uac00" <= ch <= "\ud7a3":
                cc[ch]+=1; seen.add(ch)
                tag=f"g{r['global_index']}:{r['filename']}"
                if len(ex[ch])<3 and tag not in ex[ch]: ex[ch].append(tag)
        for ch in seen: cf[ch]+=1
    crows=[{
        "char":ch,"unicode":f"U+{ord(ch):04X}","count":cc[ch],
        "frame_count":cf[ch],"examples":" | ".join(ex[ch])
    } for ch in cc]
    crows.sort(key=lambda x:(-x["count"],ord(x["char"])))
    write_tsv(out/"sub02_char_frequency.tsv",crows,
              ["char","unicode","count","frame_count","examples"])
    (out/"sub02_unique_hangul.txt").write_text(
        "".join(sorted(cc,key=ord)),encoding="utf-8-sig")

    counts=Counter(r["use_for_dialogue"] for r in final)
    summary=[
        "Naruto PSP SUB02 - Visual Review Corrections",
        "",
        f"Rows={len(final)}",
        f"ManualVisualCorrections={len(MANUAL)}",
        f"NonKoreanExcluded={len(JP_EXCLUDE)}",
        f"UseYES={counts['YES']}",
        f"UseNO={counts['NO']}",
        f"UseREVIEW={counts['REVIEW']}",
        f"RemainingReview={len(remaining)}",
        f"UniqueHangulYES={len(cc)}",
        "",
        "Remaining indices:",
        "  "+(",".join(str(r["global_index"]) for r in remaining) if remaining else "NONE"),
        "",
        "Note:",
        "- g1370/g1372/g1396 are visually verified exclamations; repeated-vowel length was normalized.",
        "- raw_ocr is preserved unchanged.",
        "- Japanese-only UI/narration rows are excluded from the Korean subtitle corpus, not translated here."
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
