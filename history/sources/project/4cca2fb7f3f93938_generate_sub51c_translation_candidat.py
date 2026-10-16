#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,json,re,sys,time,urllib.request,urllib.error,hashlib,traceback

ROOT_DEFAULT=r"PROJECT_ROOT"
SOURCE_SHA="5a750d02fc701c110106711dedfc3e19b34b32f1833ccbef811f3d55441f87b9"
COLL_REL=Path("analysis/sub/sub51b_exact_source_collection")
OUT_REL=Path("analysis/sub/sub51c_translation_candidates")

TARGET_TBLS=("mugen.tbl","quiz1.tbl","quiz2.tbl","nazonazo.tbl","bunshin.tbl")
JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")
TOKEN_RE=re.compile(r"<[^>]+>|%[-+0-9.#]*[sdif]|\\n|\\r|\\t")
RUBY_RE=re.compile(r"<ruby([^|>]+)\|[^>]+>")
FULLWIDTH_SPACE="\u3000"

SYSTEM="""You are translating Japanese text from a Naruto PSP game into natural Korean.
Return only the translated Korean text, no explanation and no quotation marks.

Rules:
- Preserve every control token exactly, including <br>, <RED>, <BLUE>, <BLACK>, <KOFF>, <KON>, <icon...>, printf tokens such as %d/%s, and punctuation placeholders.
- Remove Japanese ruby markup by translating the visible base text: <ruby漢字|かな> becomes the Korean meaning/name only; do not output <ruby>.
- Preserve speaker/resource prefixes if they are part of the text.
- Use established Naruto Korean names where obvious: ナルト=나루토, サスケ=사스케, サクラ=사쿠라, カカシ=카카시, シカマル=시카마루, 綱手=츠나데, 自来也=지라이야, 大蛇丸=오로치마루, 我愛羅=가아라, テマリ=테마리, カンクロウ=칸쿠로, ネジ=네지, リー=리, ヒナタ=히나타, いの=이노, チョウジ=쵸지, キバ=키바, シノ=시노, テンテン=텐텐, シズネ=시즈네, カブト=카부토, イタチ=이타치, 鬼鮫=키사메, イルカ=이루카, エビス=에비스.
- Keep the meaning concise and suitable for a PSP UI.
- Do not leave Japanese characters in the result unless they are inside a required control token.
"""

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def load_mapping(coll):
    mp={}
    for p in (coll/"mappings"/"event_font_hangul_mapping.tsv",
              coll/"mappings"/"new_glyph_mapping.tsv"):
        if not p.exists():
            # ZIP extraction on some Windows/Python combinations may preserve backslashes.
            alt=coll/(("mappings\\"+p.name))
            p=alt if alt.exists() else p
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                if r.get("hangul") and r.get("donor_sjis_hex"):
                    mp[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
    return mp

def donor_decode(raw,rev):
    out=[];mapped=0;pairs=0;i=0
    while i<len(raw):
        if i+1<len(raw):
            pair=raw[i:i+2]
            if (0x81<=raw[i]<=0x9f or 0xe0<=raw[i]<=0xfc):
                pairs+=1
            if pair in rev:
                out.append(rev[pair]);mapped+=1;i+=2;continue
        ok=False
        for n in (1,2):
            try:
                out.append(raw[i:i+n].decode("cp932"));i+=n;ok=True;break
            except:pass
        if not ok:
            out.append("�");i+=1
    return "".join(out), mapped, pairs, mapped/max(1,pairs)

def find_coll_file(coll, rel):
    p=coll/rel
    if p.exists():return p
    p2=coll/str(rel).replace("/","\\")
    if p2.exists():return p2
    raise FileNotFoundError(str(rel))

def parse_tbl_candidates(coll, mapping):
    rev={v:k for k,v in mapping.items()}
    items=[]
    for name in TARGET_TBLS:
        p=find_coll_file(coll,Path("text_resources")/(name+".bin"))
        raw=p.read_bytes()
        off=0
        for line in raw.splitlines(keepends=True):
            body=line.rstrip(b"\r\n")
            eol=line[len(body):]
            if b"=" not in body:
                off+=len(line);continue
            left,right=body.split(b"=",1)
            # Comments are never translated.
            if left.lstrip().startswith(b";"):
                off+=len(line);continue
            try:jp=right.decode("cp932")
            except UnicodeDecodeError:
                off+=len(line);continue
            dd,mapped,pairs,density=donor_decode(right,rev)
            # Already-translated Korean donor text has high mapped-pair density.
            # Untouched Japanese has low density and coherent CP932 Japanese.
            has_jp=bool(JP_RE.search(jp))
            if has_jp and density < 0.45:
                items.append(dict(
                    key=f"TBL:{name}:{off:#x}",
                    scope=name,offset=off,prefix_hex=left.hex(),
                    source=jp,source_raw_hex=right.hex(),
                    donor_decoded=dd,donor_density=density,
                    kind="TBL_RHS"
                ))
            off+=len(line)
    return items

def parse_boot_candidates(coll,mapping):
    p=find_coll_file(coll,Path("boot_filtered_strings.tsv"))
    rows=[]
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            if r["status"]!="RESIDUAL_JP":continue
            s=r["cp932_text"]
            b=int(r["bytes"])
            # Remove obvious code false positives and tiny garbage.
            jp=len(JP_RE.findall(s));kana=len(re.findall(r"[ぁ-んァ-ヶー]",s))
            vis=sum(1 for c in s if c.isprintable() and not c.isspace())
            if b<8 or vis==0:continue
            if not ((kana>=2 and jp/vis>=0.35) or "<ruby" in s):continue
            rows.append(dict(
                key=f"BOOT:{r['offset_hex']}",
                scope="BOOT.BIN",offset=int(r["offset_hex"],16),
                source=s,source_raw_hex=r["raw_hex"],
                donor_decoded=r["donor_decoded"],
                donor_density=float(r["donor_density"]),
                kind="BOOT_CSTR"
            ))
    return rows

def get_models(base):
    try:
        req=urllib.request.Request(base+"/v1/models",headers={"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=3) as r:
            data=json.loads(r.read().decode("utf-8"))
        ids=[x.get("id","") for x in data.get("data",[]) if x.get("id")]
        return ids
    except Exception:
        return []

def autodetect():
    candidates=[
        "httLOCAL_PATH",
        "httLOCAL_PATH",
        "httLOCAL_PATH",
        "httLOCAL_PATH",
    ]
    found=[]
    for b in candidates:
        ids=get_models(b)
        for mid in ids:
            found.append((b,mid))
    if not found:
        raise RuntimeError(
            "No OpenAI-compatible llama.cpp server detected on ports 8080/8081. "
            "Start translate_gemma4_sub (preferred) or another chat model and rerun."
        )
    # Prefer a translation/Gemma model, then anything non-VL/coder.
    def score(x):
        n=x[1].lower()
        s=0
        if "translate" in n:s+=100
        if "gemma" in n:s+=50
        if "coder" in n:s-=20
        if "vl" in n:s-=30
        return -s
    found.sort(key=score)
    return found[0],found

def chat(base,model,user,temperature=0.05,max_tokens=800):
    payload=json.dumps({
        "model":model,
        "messages":[{"role":"system","content":SYSTEM},{"role":"user","content":user}],
        "temperature":temperature,
        "max_tokens":max_tokens,
        "stream":False
    },ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(base+"/v1/chat/completions",data=payload,
                               headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=240) as r:
        d=json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()

def controls(s):
    return TOKEN_RE.findall(s)

def jp_left(s):
    # Ignore Japanese punctuation only; actual Japanese letters/kanji are not allowed.
    return bool(JP_RE.search(s))

def missing_hangul(s,mapping):
    return sorted({c for c in s if "가"<=c<="힣" and c not in mapping})

def normalize_answer(s):
    s=s.strip()
    if s.startswith("```") and s.endswith("```"):
        s=re.sub(r"^```[^\n]*\n?","",s)
        s=re.sub(r"\n?```$","",s)
    if len(s)>=2 and s[0]==s[-1] and s[0] in "\"'":
        s=s[1:-1]
    return s.strip()

def translate_one(item,base,model,mapping):
    source=item["source"]
    prompt="Japanese sourcLOCAL_PATH"+source
    last=""
    for attempt in range(4):
        extra=""
        if attempt:
            miss=missing_hangul(last,mapping)
            allowed="".join(sorted(mapping))
            extra=(
                "\n\nYour previous answer could not be used."
                f"\nPrevious: {last}"
                f"\nMissing Hangul syllables: {''.join(miss)}"
                "\nRewrite naturally using ONLY Hangul syllables from this allowed set "
                "(ASCII/control tokens are also allowed):\n"+allowed
            )
        ans=normalize_answer(chat(base,model,prompt+extra))
        last=ans
        if controls(ans)!=controls(source):
            continue
        if jp_left(ans):
            continue
        if missing_hangul(ans,mapping):
            continue
        return ans,"OK",attempt+1
    return last,"NEEDS_REVIEW",4

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=ROOT_DEFAULT)
    ap.add_argument("--limit",type=int,default=0,help="debug only; 0=all")
    a=ap.parse_args()
    root=Path(a.root);coll=root/COLL_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)

    summ=find_coll_file(coll,Path("SUB51B_collection_summary.json"))
    meta=json.loads(summ.read_text(encoding="utf-8"))
    if meta["source_iso_sha256"]!=SOURCE_SHA:
        raise RuntimeError("SUB51B authority SHA mismatch")

    mapping=load_mapping(coll)
    items=parse_tbl_candidates(coll,mapping)+parse_boot_candidates(coll,mapping)
    # Stable de-dup by exact source text. One translation can serve repeated strings.
    uniq=[];seen={}
    for it in items:
        k=it["source"]
        if k not in seen:
            seen[k]=len(uniq);uniq.append(it)
    if a.limit:uniq=uniq[:a.limit]

    (chosen,all_models)=autodetect()
    base,model=chosen
    print("Detected models:")
    for b,m in all_models:print(" ",b,m)
    print("Using:",base,model)
    print("Candidates:",len(items),"unique:",len(uniq),"mapping chars:",len(mapping))

    cache_path=out/"translation_cache.jsonl"
    existing={}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            try:
                r=json.loads(line);existing[r["source"]]=r
            except:pass

    results=[]
    for i,it in enumerate(uniq,1):
        if it["source"] in existing and existing[it["source"]].get("status")=="OK":
            r=existing[it["source"]]
        else:
            try:
                ko,status,tries=translate_one(it,base,model,mapping)
                r=dict(source=it["source"],korean=ko,status=status,tries=tries,
                       missing="".join(missing_hangul(ko,mapping)),
                       source_controls="|".join(controls(it["source"])),
                       korean_controls="|".join(controls(ko)))
            except Exception as e:
                r=dict(source=it["source"],korean="",status="ERROR",tries=0,
                       missing="",source_controls="|".join(controls(it["source"])),
                       korean_controls="",error=repr(e))
            with cache_path.open("a",encoding="utf-8") as f:
                f.write(json.dumps(r,ensure_ascii=False)+"\n")
        results.append(r)
        print(f"[{i}/{len(uniq)}] {r['status']} {it['source'][:55]} -> {r.get('korean','')[:55]}",flush=True)

    bysrc={r["source"]:r for r in results}
    occurrence=[]
    for it in items:
        r=bysrc.get(it["source"],{})
        q=dict(it)
        q.update(korean=r.get("korean",""),status=r.get("status","MISSING"),
                 missing=r.get("missing",""))
        occurrence.append(q)

    write_tsv(out/"translation_candidates.tsv",results,
              ["source","korean","status","tries","missing","source_controls","korean_controls","error"])
    write_tsv(out/"translation_occurrences.tsv",occurrence,
              ["key","kind","scope","offset","source","korean","status","missing",
               "donor_density","source_raw_hex","donor_decoded"])

    report=dict(
        stage="SUB51C_TRANSLATION_CANDIDATES",
        source_sub50_sha256=SOURCE_SHA,
        model_base=base,model=model,
        occurrences=len(items),unique_sources=len(uniq),
        translated_ok=sum(r["status"]=="OK" for r in results),
        needs_review=sum(r["status"]=="NEEDS_REVIEW" for r in results),
        errors=sum(r["status"]=="ERROR" for r in results),
        mapping_chars=len(mapping),
        modifies_game_data=False,runtime_qa=False
    )
    (out/"SUB51C_summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51C - Translation Candidates\n\n"
        f"SourceSUB50SHA256={SOURCE_SHA}\n"
        f"Model={model}\n"
        f"Occurrences={report['occurrences']}\nUniqueSources={report['unique_sources']}\n"
        f"TranslatedOK={report['translated_ok']}\nNeedsReview={report['needs_review']}\n"
        f"Errors={report['errors']}\nMappingChars={len(mapping)}\n"
        "GameDataModified=NO\nRuntimeQA=NO\n",
        encoding="utf-8-sig"
    )
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"))

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
