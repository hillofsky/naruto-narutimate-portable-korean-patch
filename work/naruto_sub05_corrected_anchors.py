#!/usr/bin/env python3
# Naruto PSP SUB05 - Apply SUB04 visual corrections and finalize corrected anchors

from __future__ import annotations
import argparse, csv, re, shutil
from pathlib import Path
from collections import Counter, defaultdict

CORRECTIONS = {5: [('나못있', '나뭇잎')],
 32: [('어렸냐', '어딨냐')],
 36: [('빌리 돌아가서 폭 쉬고', '빨리 돌아가서 푹 쉬고')],
 45: [('초나데 님', '츠나데 님')],
 49: [('뭐나니깐', '뭐냐니깐')],
 51: [('나못있', '나뭇잎')],
 61: [('쓰겁니까', '쓴겁니까')],
 68: [('솔식을', '술식을')],
 81: [('승승님', '스승님')],
 87: [('회한한', '희한한')],
 103: [('1종', '1층')],
 111: [('뭐나니깐', '뭐냐니깐')],
 120: [('겪정되었던', '걱정되었던')],
 138: [('격정돼서', '걱정돼서')],
 142: [('바울 수도', '놔둘 수도')],
 175: [('승승님', '스승님')],
 177: [('승님이', '스승님이')],
 179: [('기역', '기억'), ('잃어내서', '읽어내서')],
 191: [('상금닌자들에게', '상급닌자들에게'), ('말겨두고', '맡겨두고')],
 196: [('멘버에', '멤버에')],
 207: [('행!', '헹!')],
 212: [('광장히', '굉장히')],
 233: [('웃이니', '옷이니')],
 243: [('행!', '헹!')],
 249: [('이상한 차크라가 없혀….', '이상한 차크라가 얽혀 있어…')],
 254: [('않올래', '않을래')],
 258: [('여려모로', '여러모로'), ('페를', '폐를')],
 271: [('겹정해줘서', '걱정해줘서')],
 273: [('연제까지나', '언제까지나')],
 296: [('감놀', '깜놀')],
 311: [('질어지고', '짙어지고')],
 318: [('췌지', '쵸지')],
 325: [('초지의', '쵸지의')],
 335: [('쇼지랑', '쵸지랑')],
 338: [('이만 거', '이딴 거')],
 340: [('이노시카죠', '이노시카쵸')],
 346: [('뚫 뚫하지', '뚱뚱하지')],
 350: [('초지', '쵸지')],
 352: [('올 필은', '올 필요')],
 353: [('쓰스러워', '쑥스러워')],
 366: [('염힘', '얽힘')],
 377: [('농한테', '놈한테'), ('있었나간', '있었다니깐')],
 389: [('길\n', '리\n'), ('질은 안개', '짙은 안개'), ('흩싸여버려서', '휩싸여버려서'), ('뿜뿜이', '뿔뿔이')],
 420: [('광장히', '굉장히')],
 503: [('다른 어쩐 일로', '다들 어쩐 일로')],
 551: [('악질 환영놈! 더더욱 레벨업했군!! !', '악질 환영놈! 더더욱 레벨업했군!!!')],
 586: [('말기마', '맡기마')],
 600: [('나못있다', '나뭇잎이다'), ('나못잎', '나뭇잎'), ('담자다', '닌자다')],
 613: [('나못있', '나뭇잎')],
 620: [('뭐나니깐', '뭐냐니깐')],
 658: [('나못있', '나뭇잎')],
 692: [('나못있', '나뭇잎'), ('뚝같이', '똑같이')],
 694: [('올며', '울며')],
 697: [('오로치마옥', '오로치마루')],
 729: [('흙막', '흑막')],
 934: [('격정했던', '걱정했던')],
 936: [('말겨두라고', '맡겨두라고')],
 1080: [('빌리 처리해', '빨리 처리해')],
 1084: [('총성을 맺세했다', '충성을 맹세했다')],
 1125: [('나못있류다', '나뭇잎류다')],
 1183: [('엮매여', '얽매여'), ('년 나에게', '넌 나에게')],
 1200: [('어렸냐고', '어딨냐고')],
 1217: [('빠와서', '주워서')],
 1224: [('짝 맡겨두시라니깐', '팍 맡겨두시라니깐')],
 1261: [('있을을', '있을')],
 1269: [('앉만', '앞만')],
 1328: [('모로치마속', '오로치마루'), ('패나 미움을', '꽤나 미움을')],
 1338: [('떨 하겠다는', '뭘 하겠다는')],
 1368: [('협소리군', '헛소리군')],
 1387: [('빌리 수정을', '빨리 수정을')],
 1409: [('나못있', '나뭇잎')],
 1426: [('어둠고', '어둡고')],
 1462: [('초나데님', '츠나데님')],
 1494: [('핑장해', '굉장해')],
 1523: [('초나데님', '츠나데님'), ('블렸습니다', '틀렸습니다')],
 1537: [('초나데', '츠나데')],
 1557: [('한 명의닌자', '한 명의 닌자'), ('초나데', '츠나데')],
 1615: [('초나데', '츠나데'), ('그려나', '그러나')],
 1731: [('시간이 흩어', '시간이 흘러'), ('듣었지', '들었지')],
 1735: [('나못있', '나뭇잎')],
 1783: [('초나데님', '츠나데님'), ('옮니다', '옵니다')],
 1788: [('봉인이 폴린', '봉인이 풀린')],
 1802: [('초나데', '츠나데')],
 1823: [('초나데님', '츠나데님')],
 1826: [('홍,', '흥,'), ('따월', '따윌')],
 1836: [('세 님자의 쌈움을', '세 닌자의 싸움을')],
 1869: [('높는다는', '늙는다는')],
 1875: [('초나데', '츠나데')],
 1876: [('초나데', '츠나데')],
 1908: [('밑… 다', '밉… 다')],
 1916: [('초나데', '츠나데')],
 1920: [('초나데', '츠나데')],
 1923: [('초나데', '츠나데')],
 1930: [('초나데', '츠나데')],
 1948: [('첫…, 저 향아리에', '쳇…, 저 항아리에')],
 1958: [('쿼…!', '큭…!')],
 1959: [('오토치마우', '오로치마루')],
 1966: [('나못있', '나뭇잎')],
 1974: [('책!', '쳇!'), ('숨법', '술법')],
 1975: [('숨법', '술법'), ('익히는 결론', '익히는 걸론')],
 1980: [('나못있', '나뭇잎')],
 2007: [('나못있', '나뭇잎')],
 2028: [('뻗하잡아', '뻔하잖아')],
 2030: [('일봉', '일동'), ('나못있', '나뭇잎')],
 2032: [('초나데', '츠나데')],
 2034: [('솔법', '술법')],
 2041: [('첫... 향아리가', '쳇... 항아리가')],
 2085: [('학 말겨두라고', '팍 맡겨두라고')]}

UNRESOLVED = {
    24: "TITLE_CROP_INCOMPLETE"
}

KNOWN_BAD_PATTERNS = [
    "나못있","나못잎","초나데","오토치마우","오로치마옥","모로치마속",
    "광장히","겪정","격정","염힘","멘버","말겨두고","췌지","쇼지랑",
    "향아리","흙막","협소리군","쌈움","엮매여","뚫 뚫하지",
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

def write_csv(p,rows,fields):
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def parse_globals(s):
    out=[]
    for x in (s or "").split(","):
        x=x.strip()
        if x.isdigit(): out.append(int(x))
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--shared",required=True)
    args=ap.parse_args()
    root=Path(args.root); out=Path(args.out); shared=Path(args.shared)
    out.mkdir(parents=True,exist_ok=True)
    shared.mkdir(parents=True,exist_ok=True)

    src=root/"analysis"/"sub"/"sub03_sequence_timeline"/"sub03_dialogue_sequence.tsv"
    sub04=root/"analysis"/"sub"/"sub04_rare_ocr_review"/"sub04_review_queue.tsv"
    if not src.exists(): raise SystemExit(f"Missing SUB03: {src}")
    if not sub04.exists(): raise SystemExit(f"Missing SUB04: {sub04}")

    rows=read_tsv(src)
    review=read_tsv(sub04)
    reviewed_globals={int(r["global_index"]) for r in review}
    if len(rows)!=1900:
        raise SystemExit(f"Expected 1900 SUB03 entries, got {len(rows)}")
    if len(review)!=206:
        raise SystemExit(f"Expected 206 SUB04 review rows, got {len(review)}")

    correction_log=[]
    touched=set()

    for r in rows:
        gs=parse_globals(r.get("source_global_indices",""))
        applicable=[g for g in gs if g in CORRECTIONS]
        before=r["full_text"]
        text=before

        for g in applicable:
            for old,new in CORRECTIONS[g]:
                if old not in text:
                    raise SystemExit(
                        f"Correction mismatch g{g} seq{r['sequence']}: "
                        f"expected substring {old!r} in {text!r}"
                    )
                text=text.replace(old,new)
            touched.add(g)

        if text!=before:
            r["full_text"]=text
            if r.get("speaker",""):
                lines=text.splitlines()
                r["speaker"]=lines[0] if lines else ""
                r["text"]="\n".join(lines[1:]) if len(lines)>1 else ""
            else:
                r["text"]=text

            correction_log.append({
                "sequence":r["sequence"],
                "source_global_indices":r["source_global_indices"],
                "before":before,
                "after":text,
            })

        quality="OK"
        corpus="YES"
        status="VISUAL_REVIEWED" if any(g in reviewed_globals for g in gs) else "NOT_VISUAL_REVIEWED"
        unresolved=[g for g in gs if g in UNRESOLVED]
        if unresolved:
            quality="UNRESOLVED_VISUAL"
            corpus="NO"
            status="VISUAL_REVIEWED_UNRESOLVED"

        r["sub05_review_status"]=status
        r["sub05_quality_status"]=quality
        r["sub05_corpus_include"]=corpus

    expected=set(CORRECTIONS)
    if touched != expected:
        missing=sorted(expected-touched)
        extra=sorted(touched-expected)
        raise SystemExit(f"Correction coverage mismatch missing={missing} extra={extra}")

    # Residual known-bad token scan after corrections.
    residual=[]
    for r in rows:
        hits=[p for p in KNOWN_BAD_PATTERNS if p in r["full_text"]]
        if hits:
            x=dict(r)
            x["bad_patterns"]="|".join(hits)
            residual.append(x)

    fields=list(rows[0].keys())
    write_tsv(out/"sub05_corrected_sequence.tsv",rows,fields)
    write_csv(out/"sub05_corrected_sequence.csv",rows,fields)
    write_tsv(out/"sub05_correction_log.tsv",correction_log,
              ["sequence","source_global_indices","before","after"])

    unresolved_rows=[]
    for r in rows:
        if r["sub05_quality_status"]!="OK":
            unresolved_rows.append(r)
    write_tsv(out/"sub05_unresolved.tsv",unresolved_rows,fields)

    if residual:
        rfields=list(residual[0].keys())
    else:
        rfields=fields+["bad_patterns"]
    write_tsv(out/"sub05_residual_bad_patterns.tsv",residual,rfields)

    # Character set from corrected, non-unresolved rows.
    cc=Counter(); ec=Counter(); examples=defaultdict(list)
    for r in rows:
        if r["sub05_corpus_include"]!="YES": continue
        s=r["full_text"]
        seen=set()
        for ch in s:
            if "\uac00" <= ch <= "\ud7a3":
                cc[ch]+=1
                seen.add(ch)
                if len(examples[ch])<3:
                    tag=f"seq{r['sequence']}:g{r['source_global_indices']}"
                    if tag not in examples[ch]: examples[ch].append(tag)
        for ch in seen: ec[ch]+=1

    crows=[{
        "char":ch,
        "unicode":f"U+{ord(ch):04X}",
        "count":cc[ch],
        "entry_count":ec[ch],
        "examples":" | ".join(examples[ch]),
    } for ch in cc]
    crows.sort(key=lambda x:(-x["count"],ord(x["char"])))
    write_tsv(out/"sub05_char_frequency.tsv",crows,
              ["char","unicode","count","entry_count","examples"])
    (out/"sub05_unique_hangul.txt").write_text(
        "".join(sorted(cc,key=ord)),encoding="utf-8-sig")

    # Shared MOV handoff. Keep all anchors, but expose quality/corpus flags.
    shared_out=shared/"youtube_subtitle_anchors.tsv"
    write_tsv(shared_out,rows,fields)

    # Compact reviewed set for auditing.
    reviewed=[]
    for r in rows:
        if r["sub05_review_status"].startswith("VISUAL_REVIEWED"):
            reviewed.append(r)
    write_tsv(out/"sub05_visual_reviewed_entries.tsv",reviewed,fields)

    summary=[
        "Naruto PSP SUB05 - Corrected Subtitle Anchors",
        "",
        f"InputEntries={len(rows)}",
        f"SUB04VisualReviewRows={len(review)}",
        f"CorrectedGlobalRows={len(CORRECTIONS)}",
        f"CorrectedSequenceEntries={len(correction_log)}",
        f"UnresolvedRows={len(unresolved_rows)}",
        f"ResidualKnownBadPatternRows={len(residual)}",
        f"UniqueHangulCorrected={len(cc)}",
        "",
        "Unresolved:",
        "  g24 = title-style text cropped at top; preserved but excluded from character corpus",
        "",
        f"SharedHandoff={shared_out}",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

    if residual:
        print("")
        print("WARNING: residual known bad patterns remain:")
        for r in residual[:30]:
            print(f"  seq{r['sequence']} g{r['source_global_indices']} {r['bad_patterns']} :: {r['full_text']!r}")

if __name__=="__main__":
    main()
