#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,json,re,sys,hashlib,traceback,collections

ROOT_DEFAULT=r"PROJECT_ROOT"
SOURCE_SHA="5a750d02fc701c110106711dedfc3e19b34b32f1833ccbef811f3d55441f87b9"
COLL_REL=Path("analysis/sub/sub51b_exact_source_collection")
OUT_REL=Path("analysis/sub/sub51c_fix1_chatgpt_candidates")

JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")
KANA_RE=re.compile(r"[ぁ-んァ-ヶー]")
TOKEN_RE=re.compile(r"<[^>]+>|%[-+0-9.#]*[sdif]|\\n|\\r|\\t")

def load_mapping(coll):
    mp={}
    for name in ("event_font_hangul_mapping.tsv","new_glyph_mapping.tsv"):
        p=coll/"mappings"/name
        if not p.exists():
            p=coll/("mappings\\"+name)
        if not p.exists():
            raise FileNotFoundError(f"Mapping missing: {name}")
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
                out.append(raw[i:i+n].decode("cp932"))
                i+=n;ok=True;break
            except Exception:
                pass
        if not ok:
            out.append("�");i+=1
    return "".join(out),mapped,pairs,mapped/max(1,pairs)

def find_coll_file(coll,rel):
    p=coll/rel
    if p.exists():return p
    p2=coll/str(rel).replace("/","\\")
    if p2.exists():return p2
    raise FileNotFoundError(str(rel))

def plausible_jp(s):
    if not JP_RE.search(s): return False
    if any(0xE000<=ord(ch)<=0xF8FF for ch in s): return False
    if any(0xFF61<=ord(ch)<=0xFF9F for ch in s): return False
    jp=len(JP_RE.findall(s))
    kana=len(KANA_RE.findall(s))
    vis=sum(1 for c in s if c.isprintable() and not c.isspace())
    if vis==0 or jp<2:return False
    return (kana>=1 and jp/vis>=0.30) or ("<ruby" in s and jp>=2)

def scan_boot(coll):
    p=find_coll_file(coll,Path("boot_filtered_strings.tsv"))
    out=[]
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            if r.get("status")!="RESIDUAL_JP":continue
            s=r.get("cp932_text","")
            if not plausible_jp(s):continue
            b=int(r.get("bytes") or 0)
            if b<4:continue
            out.append(dict(
                key=f"BOOT:{r['offset_hex']}",
                kind="BOOT_CSTR",
                scope="BOOT.BIN",
                offset=r["offset_hex"],
                source=s,
                source_raw_hex=r.get("raw_hex",""),
                donor_decoded=r.get("donor_decoded",""),
                donor_density=r.get("donor_density",""),
                max_bytes=b,
            ))
    return out

def resolve_text_resource_dirs(coll):
    # Normal directory first.
    d=coll/"text_resources"
    if d.is_dir():return [d]
    # Some old ZIP extraction layouts can preserve backslashes in filenames.
    return [coll]

def iter_text_bins(coll):
    seen=set()
    for d in resolve_text_resource_dirs(coll):
        if d==coll:
            for p in coll.iterdir():
                n=p.name
                if not n.startswith("text_resources\\") or not n.endswith(".bin"):
                    continue
                resource=n.split("\\",1)[1][:-4]
                if (resource,p) not in seen:
                    seen.add((resource,p));yield resource,p
        else:
            for p in sorted(d.glob("*.bin")):
                resource=p.name[:-4]
                if (resource,p) not in seen:
                    seen.add((resource,p));yield resource,p

def scan_text_resources(coll,mapping):
    rev={v:k for k,v in mapping.items()}
    out=[]
    for resource,p in iter_text_bins(coll):
        raw=p.read_bytes()
        off=0
        for line in raw.splitlines(keepends=True):
            body=line.rstrip(b"\r\n")
            if not body:
                off+=len(line);continue

            # TBL-like: translate RHS only, preserve key/prefix.
            if b"=" in body:
                left,right=body.split(b"=",1)
                if left.lstrip().startswith((b";",b"#")):
                    off+=len(line);continue
                try:s=right.decode("cp932")
                except UnicodeDecodeError:
                    off+=len(line);continue
                dd,mapped,pairs,density=donor_decode(right,rev)
                if JP_RE.search(s) and density<0.45 and plausible_jp(s):
                    out.append(dict(
                        key=f"TEXT:{resource}:{off:#x}",
                        kind="TEXT_RHS",
                        scope=resource,
                        offset=hex(off),
                        source=s,
                        source_raw_hex=right.hex(),
                        prefix_hex=left.hex(),
                        donor_decoded=dd,
                        donor_density=f"{density:.3f}",
                        max_bytes="",
                    ))
            else:
                # Plain text lines: only include strong residual Japanese.
                if body.lstrip().startswith((b";",b"#")):
                    off+=len(line);continue
                try:s=body.decode("cp932")
                except UnicodeDecodeError:
                    off+=len(line);continue
                dd,mapped,pairs,density=donor_decode(body,rev)
                if JP_RE.search(s) and density<0.45 and plausible_jp(s):
                    out.append(dict(
                        key=f"TEXT:{resource}:{off:#x}",
                        kind="TEXT_LINE",
                        scope=resource,
                        offset=hex(off),
                        source=s,
                        source_raw_hex=body.hex(),
                        prefix_hex="",
                        donor_decoded=dd,
                        donor_density=f"{density:.3f}",
                        max_bytes="",
                    ))
            off+=len(line)
    return out

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=ROOT_DEFAULT)
    a=ap.parse_args()
    root=Path(a.root);coll=root/COLL_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)

    meta=json.loads(find_coll_file(coll,Path("SUB51B_collection_summary.json")).read_text(encoding="utf-8"))
    if meta.get("source_iso_sha256")!=SOURCE_SHA:
        raise RuntimeError("SUB51B authority SHA mismatch")

    mapping=load_mapping(coll)
    occ=scan_text_resources(coll,mapping)+scan_boot(coll)

    # Exact-source de-dup: ChatGPT translates one source once, then it is reused.
    groups=collections.OrderedDict()
    for r in occ:
        groups.setdefault(r["source"],[]).append(r)

    candidates=[]
    for i,(src,rs) in enumerate(groups.items(),1):
        kinds=sorted({r["kind"] for r in rs})
        scopes=sorted({r["scope"] for r in rs})
        boot_limits=[int(r["max_bytes"]) for r in rs if str(r.get("max_bytes","")).isdigit()]
        candidates.append(dict(
            id=f"C{i:05d}",
            source=src,
            korean="",
            review_status="PENDING_CHATGPT",
            occurrences=len(rs),
            kinds=";".join(kinds),
            scopes=";".join(scopes),
            max_bytes=min(boot_limits) if boot_limits else "",
            control_tokens="|".join(TOKEN_RE.findall(src)),
            notes="",
        ))

    id_by_source={r["source"]:r["id"] for r in candidates}
    for r in occ:
        r["candidate_id"]=id_by_source[r["source"]]

    write_tsv(out/"translation_candidates_for_chatgpt.tsv",candidates,
              ["id","source","korean","review_status","occurrences","kinds","scopes",
               "max_bytes","control_tokens","notes"])
    write_tsv(out/"translation_occurrences.tsv",occ,
              ["candidate_id","key","kind","scope","offset","source","source_raw_hex",
               "prefix_hex","donor_decoded","donor_density","max_bytes"])

    report=dict(
        stage="SUB51C_FIX1_CHATGPT_CANDIDATE_EXPORT",
        source_sub50_sha256=SOURCE_SHA,
        translation_engine="NONE",
        local_llm_used=False,
        bc250_used=False,
        game_data_modified=False,
        runtime_qa=False,
        mapping_chars=len(mapping),
        occurrences=len(occ),
        unique_sources=len(candidates),
        output="translation_candidates_for_chatgpt.tsv",
        next_step="Upload this package to ChatGPT; ChatGPT fills Korean translations."
    )
    (out/"SUB51C_FIX1_summary.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51C FIX1 - ChatGPT Candidate Export\n\n"
        f"SourceSUB50SHA256={SOURCE_SHA}\n"
        f"Occurrences={len(occ)}\n"
        f"UniqueSources={len(candidates)}\n"
        f"MappingChars={len(mapping)}\n"
        "TranslationEngine=NONE\n"
        "BC250Used=NO\n"
        "LocalLLMUsed=NO\n"
        "GameDataModified=NO\n"
        "RuntimeQA=NO\n"
        "Next=Upload result ZIP to ChatGPT for translation\n",
        encoding="utf-8-sig"
    )
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
