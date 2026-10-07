#!/usr/bin/env python3
# Naruto PSP SUB11 - Recover Stage34/36R glyph-generation pipeline
#
# Read-only diagnostic/recovery stage.
# Does not modify BOOT/EBOOT/ISO.
# Does not copy or package OS font files.

from __future__ import annotations
import argparse, csv, hashlib, re, shutil
from pathlib import Path

TEXT_EXTS={".py",".ps1",".tsv",".csv",".txt",".log",".json",".md",".bat",".cmd"}
MAX_TEXT_COPY=4*1024*1024
MAX_HASH_BYTES=16*1024*1024

KEYWORDS=[
    "39CD04","0x39CD04","42A7C0","0x42A7C0",
    "162","18x18","18 x 18","4bpp",
    "ImageFont","truetype","glyph","font_file_offset",
    "stage36r_mapping","82F7","82F5","825E","825C","824A",
    "8248","8241","81EF","81EE","81EC",
    "08BA0CB0","0x08BA0CB0","3600"
]

FIXED={
    "한":("82F7",370),
    "글":("82F5",368),
    "테":("825E",218),
    "스":("825C",216),
    "트":("824A",198),
    "가":("8248",196),
    "나":("8241",189),
    "다":("81EF",174),
    "라":("81EE",173),
    "마":("81EC",171),
}

FONT_BASE=0x39CD04
GLYPH_BYTES=162

def sha256_file(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def write_tsv(path,rows,fields):
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def safe_rel(root,p):
    try:
        return str(p.relative_to(root))
    except Exception:
        return str(p)

def candidate_roots(root):
    out=[]
    analysis=root/"analysis"
    if analysis.exists():
        for p in analysis.iterdir():
            if p.is_dir() and re.search(r"(?i)^stage(34|35|36)",p.name):
                out.append(p)
    for p in root.iterdir():
        if re.search(r"(?i)stage(34|35|36)",p.name):
            out.append(p)
    seen=set()
    ans=[]
    for p in out:
        k=str(p.resolve()).lower()
        if k not in seen:
            seen.add(k)
            ans.append(p)
    return ans

def text_hits(text):
    low=text.lower()
    hits=[]
    for k in KEYWORDS:
        if k.lower() in low:
            hits.append(k)
    return sorted(set(hits),key=str.lower)

def extract_context(text,hits,limit=2500):
    chunks=[]
    low=text.lower()
    for h in hits[:10]:
        pos=low.find(h.lower())
        if pos<0:
            continue
        s=max(0,pos-180)
        e=min(len(text),pos+420)
        chunks.append(text[s:e].replace("\r",""))
    return "\n---\n".join(chunks)[:limit]

def find_font_refs(text):
    refs=set()
    patterns=[
        r'(?i)[A-Z]:\\[^"\r\n]+?\.(?:ttf|otf|ttc)',
        r"(?i)/[^'\r\n\"]+?\.(?:ttf|otf|ttc)",
        r'(?i)["\']([^"\']+\.(?:ttf|otf|ttc))["\']',
    ]
    for pat in patterns:
        for m in re.finditer(pat,text):
            val=m.group(1) if m.lastindex else m.group(0)
            refs.add(val)
    return sorted(refs)

def scan_scripts(root,out):
    roots=candidate_roots(root)
    inv=[]
    hits_rows=[]
    font_refs=[]
    evidence=out/"text_evidence"
    evidence.mkdir(exist_ok=True)
    found_files=[]

    for rr in roots:
        files=[rr] if rr.is_file() else [p for p in rr.rglob("*") if p.is_file()]
        for p in files:
            found_files.append(p)
            try:
                size=p.stat().st_size
            except Exception:
                continue
            digest=sha256_file(p) if size<=MAX_HASH_BYTES else ""
            inv.append({
                "path":safe_rel(root,p),
                "bytes":size,
                "suffix":p.suffix.lower(),
                "sha256":digest,
            })

            if p.suffix.lower() in TEXT_EXTS and size<=MAX_TEXT_COPY:
                try:
                    txt=p.read_text(encoding="utf-8-sig",errors="replace")
                except Exception:
                    continue
                hs=text_hits(txt)
                refs=find_font_refs(txt)
                for ref in refs:
                    font_refs.append({
                        "source_file":safe_rel(root,p),
                        "font_reference":ref,
                    })
                if hs:
                    hits_rows.append({
                        "path":safe_rel(root,p),
                        "bytes":size,
                        "keywords":"|".join(hs),
                        "context":extract_context(txt,hs),
                    })
                    dst=evidence/safe_rel(root,p).replace(":","_")
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(p,dst)

    write_tsv(out/"sub11_stage34_36_inventory.tsv",inv,
              ["path","bytes","suffix","sha256"])
    write_tsv(out/"sub11_keyword_hits.tsv",hits_rows,
              ["path","bytes","keywords","context"])
    write_tsv(out/"sub11_font_references.tsv",font_refs,
              ["source_file","font_reference"])
    return roots,found_files,inv,hits_rows,font_refs

def find_named(root,name):
    hits=[]
    analysis=root/"analysis"
    if analysis.exists():
        for p in analysis.rglob(name):
            if p.is_file():
                hits.append(p)
    return sorted(hits,key=lambda p:(len(str(p)),str(p).lower()))

def inspect_candidate_boots(root,out,found_files):
    candidates=[]
    known_kr_sizes={6170192,6170528}
    search=list(found_files)

    kr=root/"kr_extracted"/"PSP_GAME"/"SYSDIR"
    if kr.exists():
        for n in ["BOOT.BIN","EBOOT.BIN"]:
            p=kr/n
            if p.exists():
                search.append(p)

    seen=set()
    for p in search:
        try:
            size=p.stat().st_size
        except Exception:
            continue
        key=str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        name=p.name.lower()
        if size in known_kr_sizes or "boot" in name or "eboot" in name:
            if size < FONT_BASE + 3600*GLYPH_BYTES:
                continue
            candidates.append(p)

    meta=[]
    glyphdir=out/"verified_glyph_blocks"
    glyphdir.mkdir(exist_ok=True)

    for idx,p in enumerate(candidates):
        label=f"cand{idx:02d}_{p.name}"
        blocks=[]
        with p.open("rb") as f:
            for ch,(code,glyph) in FIXED.items():
                f.seek(FONT_BASE+glyph*GLYPH_BYTES)
                b=f.read(GLYPH_BYTES)
                blocks.append((ch,code,glyph,b))
                safech=f"U{ord(ch):04X}"
                (glyphdir/f"{label}_g{glyph}_{safech}.bin").write_bytes(b)

        concat=hashlib.sha256(b"".join(b for _,_,_,b in blocks)).hexdigest()
        meta.append({
            "candidate":label,
            "path":safe_rel(root,p),
            "bytes":p.stat().st_size,
            "sha256":sha256_file(p),
            "fixed10_concat_sha256":concat,
        })

    write_tsv(out/"sub11_boot_candidates.tsv",meta,
              ["candidate","path","bytes","sha256","fixed10_concat_sha256"])
    return candidates,meta

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    roots,files,inv,hits,fontrefs=scan_scripts(root,out)
    candidates,bootmeta=inspect_candidate_boots(root,out,files)

    authority=[]
    for name in [
        "stage36r_mapping.tsv",
        "stage35r_slot_inventory.tsv",
        "stage35r_summary.txt",
        "stage35r_summary.json",
    ]:
        hs=find_named(root,name)
        for p in hs[:3]:
            authority.append({
                "name":name,
                "path":safe_rel(root,p),
                "sha256":sha256_file(p),
                "bytes":p.stat().st_size,
            })
    write_tsv(out/"sub11_authority_files.tsv",authority,
              ["name","path","sha256","bytes"])

    scored=[]
    for r in hits:
        kws=r["keywords"].split("|") if r["keywords"] else []
        score=0
        for k in kws:
            kl=k.lower()
            if "39cd04" in kl:
                score+=8
            elif "imagefont" in kl or "truetype" in kl:
                score+=6
            elif "4bpp" in kl:
                score+=5
            elif "18x18" in kl or "18 x 18" in kl:
                score+=5
            elif "82f7" in kl:
                score+=5
            elif kl=="162":
                score+=3
            elif "glyph" in kl:
                score+=2
            else:
                score+=1
        scored.append({
            "score":score,
            "path":r["path"],
            "keywords":r["keywords"],
        })
    scored.sort(key=lambda r:(-r["score"],r["path"].lower()))
    write_tsv(out/"sub11_likely_pipeline_files.tsv",scored,
              ["score","path","keywords"])

    summary=[
        "Naruto PSP SUB11 - Stage34/36R Glyph Pipeline Recovery",
        "",
        f"CandidateStageRoots={len(roots)}",
        f"InventoryFiles={len(inv)}",
        f"KeywordHitFiles={len(hits)}",
        f"FontReferencesFound={len(fontrefs)}",
        f"BOOTLikeCandidates={len(bootmeta)}",
        "",
        "Top likely pipeline files:",
    ]
    for r in scored[:20]:
        summary.append(f"  score={r['score']} {r['path']} [{r['keywords']}]")
    summary += [
        "",
        "Font references are recorded as path strings only.",
        "No TTF/OTF/TTC font files are copied.",
        "No BOOT/EBOOT/ISO bytes are modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
