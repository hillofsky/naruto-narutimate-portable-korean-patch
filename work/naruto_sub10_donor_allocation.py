#!/usr/bin/env python3
# Naruto PSP SUB10 - Final Hangul -> verified standard donor allocation
#
# Safety:
# - Requires SUB09 final 694 Hangul corpus.
# - Preserves Stage36R visually verified 10 mappings.
# - Allocates all remaining Hangul ONLY from rows explicitly classified STRICT.
# - Uses glyph index 0..3428 only.
# - Never uses special glyph region 3429+.
# - No BOOT/ISO modification in this stage.

from __future__ import annotations
import argparse, csv, json, re, shutil
from pathlib import Path
from collections import Counter

EXPECTED_HANGUL = 694
MAX_STANDARD_GLYPH = 3428

FIXED = {
    "한": ("82F7", 370),
    "글": ("82F5", 368),
    "테": ("825E", 218),
    "스": ("825C", 216),
    "트": ("824A", 198),
    "가": ("8248", 196),
    "나": ("8241", 189),
    "다": ("81EF", 174),
    "라": ("81EE", 173),
    "마": ("81EC", 171),
}

TEXT_EXTS = {".tsv",".csv",".txt",".log",".json",".md",".py"}
MAX_COPY_BYTES = 4 * 1024 * 1024

GLYPH_NAMES = {
    "glyph","glyph_index","glyphidx","glyph_id","glyphid","index","idx"
}
CODE_NAMES = {
    "sjis","sjis_hex","shiftjis","shift_jis","shift-jis",
    "code","code_hex","char_code","sjis_code","encoded_code"
}
STATUS_NAMES = {
    "status","tier","class","category","pool","kind","donor_class","donor_tier"
}

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+","_",str(s).strip().lower()).strip("_")

def read_tsv(path: Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows: w.writerow(r)

def detect_delim(path: Path):
    if path.suffix.lower()==".tsv": return "\t"
    if path.suffix.lower()==".csv": return ","
    try:
        sample=path.read_text(encoding="utf-8-sig",errors="replace")[:4096]
        if sample.count("\t") > sample.count(","): return "\t"
        if sample.count(",") > 0: return ","
    except Exception:
        pass
    return None

def parse_int(v):
    if v is None: return None
    s=str(v).strip()
    if not s: return None
    try:
        if s.lower().startswith("0x"): return int(s,16)
        return int(s)
    except Exception:
        m=re.search(r"(?i)\b(?:glyph\s*)?(\d{1,5})\b",s)
        return int(m.group(1)) if m else None

def parse_code(v):
    if v is None: return None
    s=str(v).strip().upper().replace("0X","")
    s=re.sub(r"[^0-9A-F]","",s)
    if len(s)==4:
        return s
    return None

def find_column(fieldnames, candidates):
    normmap={norm(x):x for x in fieldnames if x is not None}
    for c in candidates:
        if c in normmap: return normmap[c]
    # fuzzy fallback
    for n,orig in normmap.items():
        if any(c in n for c in candidates):
            return orig
    return None

def candidate_roots(root: Path):
    analysis=root/"analysis"
    roots=[]
    if analysis.exists():
        for p in analysis.iterdir():
            if p.is_dir() and re.search(r"(?i)stage35|stage36r",p.name):
                roots.append(p)
    # Also include root-level files/directories explicitly named stage35/stage36r.
    for p in root.iterdir():
        if re.search(r"(?i)stage35|stage36r",p.name):
            roots.append(p)
    # unique
    seen=set(); out=[]
    for p in roots:
        rp=str(p.resolve()).lower()
        if rp not in seen:
            seen.add(rp); out.append(p)
    return out

def inventory_sources(root: Path, evidence_dir: Path):
    roots=candidate_roots(root)
    rows=[]
    files=[]
    for rr in roots:
        if rr.is_file():
            iterable=[rr]
        else:
            iterable=[p for p in rr.rglob("*") if p.is_file()]
        for p in iterable:
            if p.suffix.lower() not in TEXT_EXTS: continue
            try: size=p.stat().st_size
            except Exception: continue
            rel=str(p.relative_to(root)) if root in p.parents else str(p)
            hit=False
            snippet=""
            try:
                txt=p.read_text(encoding="utf-8-sig",errors="replace")
                up=txt.upper()
                hit=("STRICT" in up or "RECLAIM" in up or "82F7" in up or "STAGE36R" in up)
                if hit:
                    pos=min([x for x in [up.find("STRICT"),up.find("82F7"),up.find("STAGE36R")] if x>=0] or [0])
                    snippet=txt[max(0,pos-120):pos+500].replace("\r"," ").replace("\n"," ")
            except Exception:
                pass
            rows.append({
                "path":rel,
                "bytes":size,
                "contains_donor_keywords":"YES" if hit else "NO",
                "snippet":snippet[:600],
            })
            files.append(p)
            if hit and size <= MAX_COPY_BYTES:
                dst=evidence_dir/rel.replace(":","_")
                dst.parent.mkdir(parents=True,exist_ok=True)
                try: shutil.copy2(p,dst)
                except Exception: pass
    return roots,files,rows

def parse_strict_table(path: Path):
    delim=detect_delim(path)
    if not delim: return None
    try:
        with path.open("r",encoding="utf-8-sig",errors="replace",newline="") as f:
            reader=csv.DictReader(f,delimiter=delim)
            fields=reader.fieldnames or []
            if len(fields)<2: return None
            glyph_col=find_column(fields,GLYPH_NAMES)
            code_col=find_column(fields,CODE_NAMES)
            status_col=find_column(fields,STATUS_NAMES)
            if not glyph_col or not code_col or not status_col:
                return None

            strict=[]
            values=Counter()
            for row in reader:
                status=str(row.get(status_col,"")).strip()
                if not status: continue
                values[status]+=1
                # Only explicit STRICT. Do not infer SAFE/UNUSED as strict.
                if "STRICT" not in status.upper():
                    continue
                glyph=parse_int(row.get(glyph_col))
                code=parse_code(row.get(code_col))
                if glyph is None or code is None: continue
                if not (0 <= glyph <= MAX_STANDARD_GLYPH): continue
                strict.append({
                    "glyph_index":glyph,
                    "sjis_hex":code,
                    "status":status,
                    "source_file":str(path),
                    "glyph_column":glyph_col,
                    "code_column":code_col,
                    "status_column":status_col,
                })
            if not strict:
                return None
            return {
                "path":path,
                "strict":strict,
                "status_values":dict(values),
                "columns":{
                    "glyph":glyph_col,"code":code_col,"status":status_col
                }
            }
    except Exception:
        return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--shared",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    shared=Path(args.shared)
    out.mkdir(parents=True,exist_ok=True)
    shared.mkdir(parents=True,exist_ok=True)
    evidence=out/"stage35_36r_evidence"
    evidence.mkdir(exist_ok=True)

    unique_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_unique_hangul.txt"
    freq_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_char_frequency.tsv"
    if not unique_path.exists(): raise SystemExit(f"Missing SUB09 unique Hangul: {unique_path}")
    if not freq_path.exists(): raise SystemExit(f"Missing SUB09 frequency: {freq_path}")

    chars="".join(ch for ch in unique_path.read_text(encoding="utf-8-sig") if "\uac00" <= ch <= "\ud7a3")
    if len(chars)!=EXPECTED_HANGUL or len(set(chars))!=EXPECTED_HANGUL:
        raise SystemExit(f"Expected {EXPECTED_HANGUL} unique Hangul, got chars={len(chars)} unique={len(set(chars))}")

    freq_rows=read_tsv(freq_path)
    freq={r["char"]:int(r["count"]) for r in freq_rows}

    missing_fixed=sorted(set(FIXED)-set(chars))
    if missing_fixed:
        raise SystemExit(f"Stage36R fixed Hangul missing from final corpus: {missing_fixed}")

    # Discover and preserve evidence.
    roots,files,inventory=inventory_sources(root,evidence)
    write_tsv(out/"sub10_source_inventory.tsv",inventory,
              ["path","bytes","contains_donor_keywords","snippet"])

    if not roots:
        raise SystemExit(
            "Stage35/Stage36R 로컬 분석 폴더를 찾지 못했습니다. "
            "analysis 아래 stage35*/stage36r* 결과가 필요합니다."
        )

    parsed=[]
    for p in files:
        if p.suffix.lower() not in {".tsv",".csv",".txt"}: continue
        t=parse_strict_table(p)
        if t: parsed.append(t)

    parse_report=[]
    for t in parsed:
        parse_report.append({
            "source_file":str(t["path"]),
            "strict_rows":len(t["strict"]),
            "glyph_column":t["columns"]["glyph"],
            "code_column":t["columns"]["code"],
            "status_column":t["columns"]["status"],
            "status_values_json":json.dumps(t["status_values"],ensure_ascii=False,sort_keys=True),
        })
    write_tsv(out/"sub10_parsed_donor_sources.tsv",parse_report,
              ["source_file","strict_rows","glyph_column","code_column","status_column","status_values_json"])

    if not parsed:
        raise SystemExit(
            "Stage35/36R 파일은 찾았지만 glyph/code/status 열을 가진 STRICT donor 표를 자동 식별하지 못했습니다. "
            "sub10_source_inventory.tsv와 evidence 파일을 업로드해 형식을 확인해야 합니다."
        )

    # Prefer a source with the largest STRICT pool, then stable path.
    parsed.sort(key=lambda x:(-len(x["strict"]),str(x["path"]).lower()))
    chosen=parsed[0]

    # Deduplicate strictly by glyph and code and reject contradictions.
    by_glyph={}
    by_code={}
    contradictions=[]
    for d in chosen["strict"]:
        g=d["glyph_index"]; c=d["sjis_hex"]
        if g in by_glyph and by_glyph[g]["sjis_hex"]!=c:
            contradictions.append(f"glyph {g}: {by_glyph[g]['sjis_hex']} vs {c}")
        if c in by_code and by_code[c]["glyph_index"]!=g:
            contradictions.append(f"code {c}: glyph {by_code[c]['glyph_index']} vs {g}")
        by_glyph[g]=d
        by_code[c]=d
    if contradictions:
        raise SystemExit("Chosen STRICT table has contradictory glyph/code rows: " + "; ".join(contradictions[:20]))

    strict=list(by_glyph.values())
    strict.sort(key=lambda d:d["glyph_index"])

    fixed_glyphs={g for _,g in FIXED.values()}
    fixed_codes={c for c,_ in FIXED.values()}

    # Fixed mappings must stay in standard region and unique.
    if any(g>MAX_STANDARD_GLYPH for _,g in FIXED.values()):
        raise SystemExit("Fixed Stage36R mapping contains special-region glyph")
    if len(fixed_glyphs)!=len(FIXED) or len(fixed_codes)!=len(FIXED):
        raise SystemExit("Fixed Stage36R mappings are not unique")

    usable=[
        d for d in strict
        if d["glyph_index"] not in fixed_glyphs and d["sjis_hex"] not in fixed_codes
    ]

    remaining=[ch for ch in sorted(chars,key=ord) if ch not in FIXED]
    if len(usable)<len(remaining):
        raise SystemExit(
            f"Not enough explicit STRICT standard donors: need {len(remaining)}, have {len(usable)} "
            f"(chosen source: {chosen['path']})"
        )

    mapping=[]
    for ch in sorted(chars,key=ord):
        if ch in FIXED:
            code,glyph=FIXED[ch]
            mapping.append({
                "hangul":ch,
                "unicode":f"U+{ord(ch):04X}",
                "frequency":freq.get(ch,0),
                "donor_sjis_hex":code,
                "donor_byte1":code[:2],
                "donor_byte2":code[2:],
                "glyph_index":glyph,
                "tier":"FIXED_STAGE36R_VERIFIED",
                "source_file":"Stage36R verified runtime test",
                "fixed_verified":"YES",
            })

    for ch,d in zip(remaining,usable):
        code=d["sjis_hex"]
        mapping.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "frequency":freq.get(ch,0),
            "donor_sjis_hex":code,
            "donor_byte1":code[:2],
            "donor_byte2":code[2:],
            "glyph_index":d["glyph_index"],
            "tier":"STRICT",
            "source_file":str(chosen["path"]),
            "fixed_verified":"NO",
        })

    mapping.sort(key=lambda r:ord(r["hangul"]))

    # Final validation.
    if len(mapping)!=EXPECTED_HANGUL:
        raise SystemExit(f"Mapping count mismatch: {len(mapping)}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate Hangul in mapping")
    if len({r["glyph_index"] for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate glyph index in mapping")
    if len({r["donor_sjis_hex"] for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate SJIS donor code in mapping")
    if max(int(r["glyph_index"]) for r in mapping)>MAX_STANDARD_GLYPH:
        raise SystemExit("Special glyph region accidentally allocated")

    for ch,(code,glyph) in FIXED.items():
        r=next(x for x in mapping if x["hangul"]==ch)
        if r["donor_sjis_hex"]!=code or int(r["glyph_index"])!=glyph:
            raise SystemExit(f"Fixed mapping changed for {ch}")

    fields=[
        "hangul","unicode","frequency","donor_sjis_hex","donor_byte1","donor_byte2",
        "glyph_index","tier","source_file","fixed_verified"
    ]
    write_tsv(out/"sub10_hangul_donor_mapping.tsv",mapping,fields)
    write_tsv(shared/"event_font_hangul_mapping.tsv",mapping,fields)

    # Donor pool snapshot.
    pool_rows=[]
    allocated_glyph={int(r["glyph_index"]) for r in mapping}
    allocated_code={r["donor_sjis_hex"] for r in mapping}
    for d in strict:
        pool_rows.append({
            "glyph_index":d["glyph_index"],
            "sjis_hex":d["sjis_hex"],
            "status":d["status"],
            "allocated":"YES" if d["glyph_index"] in allocated_glyph or d["sjis_hex"] in allocated_code else "NO",
            "chosen_source":str(chosen["path"]),
        })
    write_tsv(out/"sub10_strict_pool_snapshot.tsv",pool_rows,
              ["glyph_index","sjis_hex","status","allocated","chosen_source"])

    fixed_rows=[]
    for ch,(code,glyph) in FIXED.items():
        fixed_rows.append({
            "hangul":ch,"sjis_hex":code,"glyph_index":glyph,
            "verification":"Stage36R PPSSPP runtime rendered correctly"
        })
    write_tsv(out/"sub10_fixed_stage36r.tsv",fixed_rows,
              ["hangul","sjis_hex","glyph_index","verification"])

    summary=[
        "Naruto PSP SUB10 - Final Hangul Donor Allocation",
        "",
        f"FinalHangul={len(chars)}",
        f"FixedStage36R={len(FIXED)}",
        f"NewStrictAllocations={len(remaining)}",
        f"ChosenStrictSource={chosen['path']}",
        f"ChosenStrictRows={len(strict)}",
        f"UsableStrictAfterFixedExclusion={len(usable)}",
        f"MaxAllocatedGlyph={max(int(r['glyph_index']) for r in mapping)}",
        f"SpecialRegionAllocations=0",
        f"DuplicateHangul=0",
        f"DuplicateGlyph=0",
        f"DuplicateSJIS=0",
        "",
        "Fixed Stage36R mappings:",
    ]
    for ch,(code,glyph) in FIXED.items():
        summary.append(f"  {ch} {code} glyph{glyph}")
    summary += [
        "",
        f"SharedMapping={shared/'event_font_hangul_mapping.tsv'}",
        "",
        "No BOOT/ISO bytes were modified by SUB10.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
