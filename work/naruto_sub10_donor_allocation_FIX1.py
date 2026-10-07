#!/usr/bin/env python3
# Naruto PSP SUB10 FIX1 - Final Hangul -> Stage35R STRICT donor allocation
#
# Uses the actual Stage35R schema:
# stage35r_slot_candidates.tsv:
#   glyph, glyph_hex, status, donor_code, donor_class, strict_safe, reclaim_safe
#
# Also understands stage35r_code_usage.tsv fallback:
#   sjis_hex, byte1, byte2, glyph, source, status, frequency, donor_class
#
# Safety:
# - SUB09 final 694 Hangul required.
# - Preserve Stage36R verified 10 mappings exactly.
# - New mappings use only explicit strict_safe truthy / donor_class STRICT rows.
# - glyph 0..3428 only.
# - no special region 3429+.
# - no RECLAIM allocation.
# - no BOOT/ISO modification.

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

TRUTHY = {"1","TRUE","YES","Y","T","SAFE","STRICT"}

def read_tsv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def parse_int(v):
    if v is None: return None
    s=str(v).strip()
    if not s: return None
    try:
        if s.lower().startswith("0x"): return int(s,16)
        return int(s)
    except Exception:
        m=re.search(r"(?i)\b(\d{1,5})\b",s)
        return int(m.group(1)) if m else None

def parse_code(v):
    if v is None: return None
    s=str(v).strip().upper().replace("0X","")
    m=re.search(r"(?i)\b([0-9A-F]{4})\b",s)
    return m.group(1).upper() if m else None

def is_truthy(v):
    if v is None: return False
    return str(v).strip().upper() in TRUTHY

def find_stage35r_file(root: Path, basename: str):
    candidates=[]
    analysis=root/"analysis"
    search_roots=[analysis, root]
    for sr in search_roots:
        if not sr.exists(): continue
        for p in sr.rglob(basename):
            if p.is_file():
                score=0
                low=str(p).lower()
                if "stage35r" in low: score+=100
                if "analysis" in low: score+=10
                candidates.append((score, len(str(p)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda x:(-x[0],x[1],str(x[2]).lower()))
    return candidates[0][2]

def parse_slot_candidates(path: Path):
    rows=read_tsv(path)
    if not rows: raise SystemExit(f"Empty Stage35R slot candidate table: {path}")
    fields=set(rows[0].keys())
    required={"glyph","donor_code","strict_safe"}
    if not required.issubset(fields):
        raise SystemExit(
            f"Unexpected stage35r_slot_candidates.tsv schema: {sorted(fields)}; "
            f"required={sorted(required)}"
        )

    strict=[]
    all_parsed=[]
    for i,r in enumerate(rows, start=2):
        glyph=parse_int(r.get("glyph"))
        code=parse_code(r.get("donor_code"))
        strict_safe=is_truthy(r.get("strict_safe"))
        donor_class=(r.get("donor_class") or "").strip()
        status=(r.get("status") or "").strip()

        # Some rows may intentionally have no donor_code.
        if glyph is None or code is None:
            continue

        rec={
            "glyph_index":glyph,
            "sjis_hex":code,
            "status":status,
            "donor_class":donor_class,
            "strict_safe_raw":r.get("strict_safe",""),
            "reclaim_safe_raw":r.get("reclaim_safe",""),
            "source_line":i,
        }
        all_parsed.append(rec)

        explicit_strict = strict_safe or donor_class.upper()=="STRICT"
        if explicit_strict and 0 <= glyph <= MAX_STANDARD_GLYPH:
            strict.append(rec)

    return rows,all_parsed,strict

def parse_code_usage_fallback(path: Path):
    rows=read_tsv(path)
    if not rows: return []
    fields=set(rows[0].keys())
    if not {"sjis_hex","glyph","donor_class"}.issubset(fields):
        return []

    strict=[]
    for i,r in enumerate(rows,start=2):
        glyph=parse_int(r.get("glyph"))
        code=parse_code(r.get("sjis_hex"))
        donor_class=(r.get("donor_class") or "").strip()
        status=(r.get("status") or "").strip()
        if glyph is None or code is None: continue
        if donor_class.upper()=="STRICT" and 0 <= glyph <= MAX_STANDARD_GLYPH:
            strict.append({
                "glyph_index":glyph,
                "sjis_hex":code,
                "status":status,
                "donor_class":donor_class,
                "strict_safe_raw":"",
                "reclaim_safe_raw":"",
                "source_line":i,
            })
    return strict

def dedupe_and_validate(pool):
    by_glyph={}
    by_code={}
    contradictions=[]
    for d in pool:
        g=d["glyph_index"]; c=d["sjis_hex"]
        if g in by_glyph and by_glyph[g]["sjis_hex"]!=c:
            contradictions.append(
                f"glyph {g}: {by_glyph[g]['sjis_hex']} vs {c}"
            )
        if c in by_code and by_code[c]["glyph_index"]!=g:
            contradictions.append(
                f"code {c}: glyph {by_code[c]['glyph_index']} vs {g}"
            )
        by_glyph[g]=d
        by_code[c]=d

    if contradictions:
        raise SystemExit(
            "STRICT donor table contradiction: " + "; ".join(contradictions[:30])
        )

    out=list(by_glyph.values())
    out.sort(key=lambda x:x["glyph_index"])
    return out

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

    unique_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_unique_hangul.txt"
    freq_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_char_frequency.tsv"
    if not unique_path.exists():
        raise SystemExit(f"Missing SUB09 unique Hangul: {unique_path}")
    if not freq_path.exists():
        raise SystemExit(f"Missing SUB09 char frequency: {freq_path}")

    chars="".join(
        ch for ch in unique_path.read_text(encoding="utf-8-sig")
        if "\uac00" <= ch <= "\ud7a3"
    )
    if len(chars)!=EXPECTED_HANGUL or len(set(chars))!=EXPECTED_HANGUL:
        raise SystemExit(
            f"Expected {EXPECTED_HANGUL} unique Hangul, "
            f"got chars={len(chars)} unique={len(set(chars))}"
        )

    freq_rows=read_tsv(freq_path)
    freq={r["char"]:int(r["count"]) for r in freq_rows}

    missing_fixed=sorted(set(FIXED)-set(chars))
    if missing_fixed:
        raise SystemExit(
            f"Stage36R fixed characters absent from SUB09 corpus: {missing_fixed}"
        )

    slot_path=find_stage35r_file(root,"stage35r_slot_candidates.tsv")
    code_usage_path=find_stage35r_file(root,"stage35r_code_usage.tsv")
    allocation_path=find_stage35r_file(root,"stage35r_allocation.json")
    summary_path=find_stage35r_file(root,"stage35r_summary.txt")

    source_rows=[]
    for label,p in [
        ("slot_candidates",slot_path),
        ("code_usage",code_usage_path),
        ("allocation_json",allocation_path),
        ("summary",summary_path),
    ]:
        source_rows.append({
            "kind":label,
            "path":str(p) if p else "",
            "found":"YES" if p else "NO"
        })
    write_tsv(out/"sub10_source_files.tsv",source_rows,["kind","path","found"])

    if not slot_path and not code_usage_path:
        raise SystemExit(
            "stage35r_slot_candidates.tsv / stage35r_code_usage.tsv를 찾지 못했습니다."
        )

    raw_count=0
    strict=[]
    source_kind=""
    chosen_path=None

    if slot_path:
        raw,parsed,strict0=parse_slot_candidates(slot_path)
        raw_count=len(raw)
        strict=dedupe_and_validate(strict0)
        chosen_path=slot_path
        source_kind="stage35r_slot_candidates.tsv: strict_safe/donor_class"
    else:
        strict0=parse_code_usage_fallback(code_usage_path)
        strict=dedupe_and_validate(strict0)
        chosen_path=code_usage_path
        source_kind="stage35r_code_usage.tsv: donor_class=STRICT"

    # Sanity: known Stage35R work had roughly ~980 strict donors.
    # Allow a broad range so an earlier compatible Stage35R revision still works,
    # but reject accidental tiny/wrong tables.
    if not (800 <= len(strict) <= 1200):
        raise SystemExit(
            f"STRICT donor count looks wrong: {len(strict)} "
            f"(expected roughly 980; source={chosen_path})"
        )

    fixed_glyphs={g for _,g in FIXED.values()}
    fixed_codes={c for c,_ in FIXED.values()}

    # Fixed donor mapping is authoritative from Stage36R runtime verification.
    if len(fixed_glyphs)!=len(FIXED) or len(fixed_codes)!=len(FIXED):
        raise SystemExit("Duplicate fixed Stage36R donor mapping")
    if any(g<0 or g>MAX_STANDARD_GLYPH for g in fixed_glyphs):
        raise SystemExit("Stage36R fixed mapping escaped standard glyph range")

    usable=[
        d for d in strict
        if d["glyph_index"] not in fixed_glyphs
        and d["sjis_hex"] not in fixed_codes
    ]

    remaining=sorted((ch for ch in chars if ch not in FIXED), key=ord)
    if len(remaining)!=684:
        raise SystemExit(f"Expected 684 non-fixed Hangul, got {len(remaining)}")
    if len(usable)<len(remaining):
        raise SystemExit(
            f"Not enough STRICT standard donors: need={len(remaining)} usable={len(usable)}"
        )

    # Deterministic allocation by ascending glyph index.
    # This makes reruns reproduce the same mapping exactly.
    mapping=[]

    for ch in sorted(FIXED,key=ord):
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
            "source": "Stage36R runtime test",
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
            "source":str(chosen_path),
            "fixed_verified":"NO",
        })

    mapping.sort(key=lambda r:ord(r["hangul"]))

    # Hard final checks.
    if len(mapping)!=EXPECTED_HANGUL:
        raise SystemExit(f"Mapping count mismatch: {len(mapping)}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate Hangul mapping")
    if len({int(r["glyph_index"]) for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate glyph mapping")
    if len({r["donor_sjis_hex"] for r in mapping})!=EXPECTED_HANGUL:
        raise SystemExit("Duplicate SJIS donor mapping")
    if max(int(r["glyph_index"]) for r in mapping)>MAX_STANDARD_GLYPH:
        raise SystemExit("Special region 3429+ allocated")

    for ch,(code,glyph) in FIXED.items():
        r=next(x for x in mapping if x["hangul"]==ch)
        if r["donor_sjis_hex"]!=code or int(r["glyph_index"])!=glyph:
            raise SystemExit(f"Stage36R fixed mapping changed: {ch}")

    fields=[
        "hangul","unicode","frequency","donor_sjis_hex","donor_byte1",
        "donor_byte2","glyph_index","tier","source","fixed_verified"
    ]
    write_tsv(out/"sub10_hangul_donor_mapping.tsv",mapping,fields)
    write_tsv(shared/"event_font_hangul_mapping.tsv",mapping,fields)

    # Snapshot the entire strict pool and mark allocations.
    alloc_glyphs={int(r["glyph_index"]) for r in mapping}
    alloc_codes={r["donor_sjis_hex"] for r in mapping}
    pool_rows=[]
    for d in strict:
        pool_rows.append({
            "glyph_index":d["glyph_index"],
            "sjis_hex":d["sjis_hex"],
            "status":d["status"],
            "donor_class":d["donor_class"],
            "strict_safe_raw":d["strict_safe_raw"],
            "reclaim_safe_raw":d["reclaim_safe_raw"],
            "allocated":"YES" if (
                d["glyph_index"] in alloc_glyphs or d["sjis_hex"] in alloc_codes
            ) else "NO",
            "source_line":d["source_line"],
        })
    write_tsv(
        out/"sub10_strict_pool_snapshot.tsv",
        pool_rows,
        [
            "glyph_index","sjis_hex","status","donor_class",
            "strict_safe_raw","reclaim_safe_raw","allocated","source_line"
        ]
    )

    fixed_rows=[]
    for ch,(code,glyph) in FIXED.items():
        fixed_rows.append({
            "hangul":ch,
            "sjis_hex":code,
            "glyph_index":glyph,
            "verification":"Stage36R PPSSPP runtime rendered correctly",
        })
    write_tsv(
        out/"sub10_fixed_stage36r.tsv",
        fixed_rows,
        ["hangul","sjis_hex","glyph_index","verification"]
    )

    # Preserve small Stage35R metadata for review.
    evidence=out/"source_evidence"
    evidence.mkdir(exist_ok=True)
    for p in [slot_path,code_usage_path,allocation_path,summary_path]:
        if p and p.exists() and p.stat().st_size <= 8*1024*1024:
            shutil.copy2(p,evidence/p.name)

    unused=len(usable)-len(remaining)

    summary=[
        "Naruto PSP SUB10 FIX1 - Final Hangul Donor Allocation",
        "",
        f"FinalHangul={len(chars)}",
        f"FixedStage36R={len(FIXED)}",
        f"NewStrictAllocations={len(remaining)}",
        f"DonorSource={chosen_path}",
        f"DonorSourceMode={source_kind}",
        f"SourceRawRows={raw_count}",
        f"StrictStandardDonors={len(strict)}",
        f"UsableStrictAfterFixedExclusion={len(usable)}",
        f"UnusedUsableStrictAfterAllocation={unused}",
        f"MaxAllocatedGlyph={max(int(r['glyph_index']) for r in mapping)}",
        "SpecialRegionAllocations=0",
        "RECLAIMAllocations=0",
        "DuplicateHangul=0",
        "DuplicateGlyph=0",
        "DuplicateSJIS=0",
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

    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",
        encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    main()
