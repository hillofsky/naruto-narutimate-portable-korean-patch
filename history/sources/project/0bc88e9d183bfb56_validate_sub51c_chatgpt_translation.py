#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,json,re,hashlib,sys,traceback

EXPECTED_SOURCE_FP="f5003873e57c2352311346c647111e2904527f1e9a89ed75ad02a6d56a763237"
CTRL_RE=re.compile(r"<(?!ruby)[^>]+>|%[-+0-9.#]*[sdif]")
JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")

def load_map(root):
    mp={}
    paths=[
        root/"analysis/shared/event_font_hangul_mapping.tsv",
        root/"analysis/sub/sub40_tutorial/new_glyph_mapping.tsv",
    ]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError("Mapping missing: "+str(p))
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                h=r.get("hangul","")
                x=r.get("donor_sjis_hex","")
                if h and x:
                    mp[h]=bytes.fromhex(x)
    return mp,paths

def exact_encode(s,mp):
    out=bytearray(); missing=[]
    i=0
    while i<len(s):
        ch=s[i]
        if "가"<=ch<="힣":
            b=mp.get(ch)
            if b is None:
                missing.append(ch)
            else:
                out += b
            i+=1
            continue
        try:
            out += ch.encode("cp932")
        except UnicodeEncodeError:
            missing.append(ch)
        i+=1
    return bytes(out),missing

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"PROJECT_ROOT")
    ap.add_argument("--translation",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.root);tp=Path(a.translation);out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)

    mp,map_paths=load_map(root)
    with tp.open("r",encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f,delimiter="\t"))

    fp=hashlib.sha256("".join(f"{r['id']}\0{r['source']}\n" for r in rows).encode("utf-8")).hexdigest()
    if fp!=EXPECTED_SOURCE_FP:
        raise RuntimeError("Candidate source fingerprint mismatch")

    issues=[]
    used=set()
    translated=0
    for r in rows:
        if r.get("review_status")!="TRANSLATED_CHATGPT":
            continue
        translated+=1
        src=r.get("source",""); ko=r.get("korean","")
        used.update(c for c in ko if "가"<=c<="힣")

        if not ko:
            issues.append(dict(id=r["id"],type="EMPTY_TRANSLATION",detail="",source=src,korean=ko))
        if JP_RE.search(ko):
            issues.append(dict(id=r["id"],type="JAPANESE_RESIDUAL",detail="",source=src,korean=ko))
        sc=CTRL_RE.findall(src); kc=CTRL_RE.findall(ko)
        if sc!=kc:
            issues.append(dict(id=r["id"],type="CONTROL_TOKEN_MISMATCH",
                               detail=f"source={sc!r}; korean={kc!r}",source=src,korean=ko))
        enc,missing=exact_encode(ko,mp)
        if missing:
            issues.append(dict(id=r["id"],type="MISSING_MAPPING",
                               detail="".join(sorted(set(missing))),source=src,korean=ko))
        mb=(r.get("max_bytes") or "").strip()
        if mb.isdigit() and not missing and len(enc)>int(mb):
            issues.append(dict(id=r["id"],type="BYTE_OVERFLOW",
                               detail=f"{len(enc)}>{mb}",source=src,korean=ko))

    missing_chars=sorted({c for q in issues if q["type"]=="MISSING_MAPPING" for c in q["detail"]})
    counts={}
    for q in issues: counts[q["type"]]=counts.get(q["type"],0)+1

    fields=["id","type","detail","source","korean"]
    with (out/"validation_issues.tsv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t");w.writeheader();w.writerows(issues)

    report={
        "stage":"SUB51C_CHATGPT_TRANSLATION_EXACT_VALIDATION",
        "candidate_source_fingerprint":fp,
        "translation_file":str(tp),
        "translated_rows":translated,
        "mapping_chars":len(mp),
        "used_hangul_chars":len(used),
        "missing_mapping_chars":"".join(missing_chars),
        "missing_mapping_char_count":len(missing_chars),
        "issues_total":len(issues),
        "issue_counts":counts,
        "status":"PASS" if not issues else "NEEDS_FIX",
        "translation_engine":"ChatGPT",
        "bc250_used":False,
        "local_llm_used":False,
        "mapping_files":[str(p) for p in map_paths],
    }
    (out/"validation_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51C ChatGPT Translation Validation\n\n"
        f"TranslatedRows={translated}\n"
        f"MappingChars={len(mp)}\n"
        f"UsedHangulChars={len(used)}\n"
        f"MissingMappingChars={len(missing_chars)}\n"
        f"Issues={len(issues)}\n"
        f"Status={report['status']}\n"
        "BC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig"
    )
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),end="")
    if missing_chars:
        print("Missing glyphs:", "".join(missing_chars))
    # A validation problem is a reportable result, not a script crash.
    return 0

if __name__=="__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
