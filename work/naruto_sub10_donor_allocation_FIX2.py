#!/usr/bin/env python3
# Naruto PSP SUB10 FIX2 - Final 694 Hangul -> Stage35R standard STRICT donors
#
# Authoritative local sources:
#   analysis\stage35r\stage35r_slot_inventory.tsv
#   analysis\stage35r\stage35r_summary.txt/json
#   analysis\stage36r\stage36r_mapping.tsv
#
# The Stage35R summary reports 987 STRICT slots in the whole 3600-glyph font.
# Restricting to the normal renderer range glyph 0..3428 leaves 980 STRICT slots.
# Stage36R already verified 10 of those mappings in PPSSPP.
# Therefore 970 standard STRICT donors remain available for 684 new Hangul chars,
# leaving 286 unused.
#
# This stage only freezes the mapping. It does NOT patch BOOT or ISO.

from __future__ import annotations
import argparse, csv, hashlib, json, re, shutil
from pathlib import Path
from collections import Counter

EXPECTED_HANGUL = 694
EXPECTED_STRICT_ALL = 987
EXPECTED_STRICT_STANDARD = 980
EXPECTED_FIXED = 10
EXPECTED_USABLE_AFTER_FIXED = 970
EXPECTED_NEW = 684
EXPECTED_UNUSED = 286
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

def read_tsv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

def sha256_file(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_int(v):
    s=str(v or "").strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except Exception:
        return None

def parse_code(v):
    s=str(v or "").strip().upper().replace("0X","")
    s=re.sub(r"[^0-9A-F]", "", s)
    return s if len(s)==4 else None

def find_authoritative(root: Path, relative: str, basename: str):
    direct=root/relative
    if direct.exists():
        return direct
    hits=[]
    analysis=root/"analysis"
    if analysis.exists():
        for p in analysis.rglob(basename):
            if p.is_file():
                score=0
                lp=str(p).lower()
                if "stage35r" in lp and "stage35r" in relative.lower(): score+=100
                if "stage36r" in lp and "stage36r" in relative.lower(): score+=100
                hits.append((score,len(str(p)),str(p).lower(),p))
    if not hits:
        return None
    hits.sort(key=lambda x:(-x[0],x[1],x[2]))
    return hits[0][3]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shared", required=True)
    a=ap.parse_args()

    root=Path(a.root)
    out=Path(a.out)
    shared=Path(a.shared)
    out.mkdir(parents=True, exist_ok=True)
    shared.mkdir(parents=True, exist_ok=True)

    unique_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_unique_hangul.txt"
    freq_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_char_frequency.tsv"

    slot_path=find_authoritative(
        root,
        r"analysis\stage35r\stage35r_slot_inventory.tsv",
        "stage35r_slot_inventory.tsv"
    )
    stage36_map=find_authoritative(
        root,
        r"analysis\stage36r\stage36r_mapping.tsv",
        "stage36r_mapping.tsv"
    )
    summary_txt=find_authoritative(
        root,
        r"analysis\stage35r\stage35r_summary.txt",
        "stage35r_summary.txt"
    )
    summary_json=find_authoritative(
        root,
        r"analysis\stage35r\stage35r_summary.json",
        "stage35r_summary.json"
    )
    old_seed=find_authoritative(
        root,
        r"analysis\stage35r\stage35r_allocation_strict.tsv",
        "stage35r_allocation_strict.tsv"
    )

    required=[
        ("SUB09 unique Hangul",unique_path),
        ("SUB09 char frequency",freq_path),
        ("Stage35R slot inventory",slot_path),
        ("Stage36R verified mapping",stage36_map),
    ]
    missing=[name for name,p in required if not p or not Path(p).exists()]
    if missing:
        raise SystemExit("Required source missing: "+", ".join(missing))

    # Preserve exact source provenance.
    source_rows=[]
    for kind,p in [
        ("sub09_unique_hangul",unique_path),
        ("sub09_char_frequency",freq_path),
        ("stage35r_slot_inventory",slot_path),
        ("stage35r_summary_txt",summary_txt),
        ("stage35r_summary_json",summary_json),
        ("stage35r_old_seed_allocation_NOT_USED",old_seed),
        ("stage36r_verified_mapping",stage36_map),
    ]:
        source_rows.append({
            "kind":kind,
            "path":str(p) if p else "",
            "found":"YES" if p and Path(p).exists() else "NO",
            "sha256":sha256_file(Path(p)) if p and Path(p).exists() else "",
        })
    write_tsv(out/"sub10_source_files.tsv",source_rows,["kind","path","found","sha256"])

    # Final corpus.
    chars="".join(
        ch for ch in unique_path.read_text(encoding="utf-8-sig")
        if "\uac00" <= ch <= "\ud7a3"
    )
    if len(chars)!=EXPECTED_HANGUL or len(set(chars))!=EXPECTED_HANGUL:
        raise SystemExit(
            f"SUB09 Hangul mismatch: chars={len(chars)} unique={len(set(chars))}, "
            f"expected={EXPECTED_HANGUL}"
        )
    char_set=set(chars)

    freq_rows=read_tsv(freq_path)
    freq={r["char"]:int(r["count"]) for r in freq_rows}

    # Stage35R actual pool: 3600 rows, strict_safe flag.
    slot_rows=read_tsv(slot_path)
    required_cols={
        "glyph","standard_sjis","sjis_hex","font_file_offset",
        "special_intercept","strict_safe"
    }
    got_cols=set(slot_rows[0].keys()) if slot_rows else set()
    if not required_cols.issubset(got_cols):
        raise SystemExit(
            "Unexpected Stage35R slot inventory schema. "
            f"missing={sorted(required_cols-got_cols)} got={sorted(got_cols)}"
        )
    if len(slot_rows)!=3600:
        raise SystemExit(f"Expected 3600 font slots, got {len(slot_rows)}")

    parsed=[]
    for r in slot_rows:
        glyph=parse_int(r["glyph"])
        code=parse_code(r["standard_sjis"])
        if glyph is None or code is None:
            continue
        parsed.append({
            "glyph_index":glyph,
            "sjis_hex":code,
            "sjis_display":r.get("sjis_hex",""),
            "font_file_offset":r.get("font_file_offset",""),
            "special_intercept":r.get("special_intercept",""),
            "strict_safe":r.get("strict_safe",""),
            "kr_tbl_usage":r.get("kr_tbl_usage",""),
            "ui_sample_usage":r.get("ui_sample_usage",""),
            "bitmap_empty":r.get("bitmap_empty",""),
        })

    strict_all=[r for r in parsed if str(r["strict_safe"]).strip()=="1"]
    strict_standard=[
        r for r in strict_all
        if 0 <= int(r["glyph_index"]) <= MAX_STANDARD_GLYPH
    ]

    if len(strict_all)!=EXPECTED_STRICT_ALL:
        raise SystemExit(
            f"Stage35R total STRICT changed: {len(strict_all)} "
            f"(expected {EXPECTED_STRICT_ALL})"
        )
    if len(strict_standard)!=EXPECTED_STRICT_STANDARD:
        raise SystemExit(
            f"Stage35R standard-range STRICT changed: {len(strict_standard)} "
            f"(expected {EXPECTED_STRICT_STANDARD})"
        )

    # Stage36R file is the authority for the already runtime-tested 10 mappings.
    s36=read_tsv(stage36_map)
    actual_fixed={}
    for r in s36:
        ch=r.get("char","")
        code=parse_code(r.get("sjis"))
        glyph=parse_int(r.get("target_glyph"))
        if ch and code and glyph is not None:
            actual_fixed[ch]=(code,glyph)

    if actual_fixed != FIXED:
        raise SystemExit(
            "Stage36R verified mapping does not match the frozen SUB10 baseline.\n"
            f"actual={actual_fixed}\nexpected={FIXED}"
        )

    missing_fixed=sorted(set(FIXED)-char_set)
    if missing_fixed:
        raise SystemExit(f"Fixed Stage36R chars missing from SUB09: {missing_fixed}")

    # Every fixed mapping must itself be in the Stage35R standard STRICT pool.
    strict_by_pair={(r["sjis_hex"],int(r["glyph_index"])):r for r in strict_standard}
    for ch,(code,glyph) in FIXED.items():
        if (code,glyph) not in strict_by_pair:
            raise SystemExit(
                f"Stage36R fixed mapping is not standard STRICT: {ch} {code} glyph{glyph}"
            )

    fixed_glyphs={g for _,g in FIXED.values()}
    fixed_codes={c for c,_ in FIXED.values()}

    usable=[
        r for r in strict_standard
        if int(r["glyph_index"]) not in fixed_glyphs
        and r["sjis_hex"] not in fixed_codes
    ]
    usable.sort(key=lambda r:int(r["glyph_index"]))

    if len(usable)!=EXPECTED_USABLE_AFTER_FIXED:
        raise SystemExit(
            f"Usable standard STRICT after fixed exclusion={len(usable)}, "
            f"expected={EXPECTED_USABLE_AFTER_FIXED}"
        )

    remaining=sorted((ch for ch in char_set if ch not in FIXED), key=ord)
    if len(remaining)!=EXPECTED_NEW:
        raise SystemExit(f"New Hangul count={len(remaining)}, expected={EXPECTED_NEW}")
    if len(usable)-len(remaining)!=EXPECTED_UNUSED:
        raise SystemExit(
            f"Unused capacity={len(usable)-len(remaining)}, expected={EXPECTED_UNUSED}"
        )

    # Freeze deterministic mapping:
    # - 10 existing Stage36R mappings preserved.
    # - remaining Hangul sorted by Unicode code point.
    # - donor slots sorted by glyph index.
    mapping=[]
    for ch in sorted(char_set,key=ord):
        if ch in FIXED:
            code,glyph=FIXED[ch]
            src=str(stage36_map)
            tier="FIXED_STAGE36R_VERIFIED"
            verified="YES"
        else:
            continue
        slot=strict_by_pair[(code,glyph)]
        mapping.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "frequency":freq.get(ch,0),
            "donor_sjis_hex":code,
            "donor_byte1":code[:2],
            "donor_byte2":code[2:],
            "glyph_index":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "font_file_offset":slot["font_file_offset"],
            "tier":tier,
            "stage36r_runtime_verified":verified,
            "source":src,
        })

    for ch,slot in zip(remaining,usable):
        code=slot["sjis_hex"]
        glyph=int(slot["glyph_index"])
        mapping.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "frequency":freq.get(ch,0),
            "donor_sjis_hex":code,
            "donor_byte1":code[:2],
            "donor_byte2":code[2:],
            "glyph_index":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "font_file_offset":slot["font_file_offset"],
            "tier":"STRICT_STANDARD_NEW",
            "stage36r_runtime_verified":"NO",
            "source":str(slot_path),
        })

    mapping.sort(key=lambda r:ord(r["hangul"]))

    # Hard uniqueness / range checks.
    checks={
        "mapping_rows":len(mapping),
        "unique_hangul":len({r["hangul"] for r in mapping}),
        "unique_sjis":len({r["donor_sjis_hex"] for r in mapping}),
        "unique_glyph":len({int(r["glyph_index"]) for r in mapping}),
    }
    if any(v!=EXPECTED_HANGUL for v in checks.values()):
        raise SystemExit(f"Mapping uniqueness failure: {checks}")
    if max(int(r["glyph_index"]) for r in mapping)>MAX_STANDARD_GLYPH:
        raise SystemExit("Special region 3429+ was allocated")

    for ch,(code,glyph) in FIXED.items():
        r=next(x for x in mapping if x["hangul"]==ch)
        if r["donor_sjis_hex"]!=code or int(r["glyph_index"])!=glyph:
            raise SystemExit(f"Fixed mapping changed: {ch}")

    mapping_fields=[
        "hangul","unicode","frequency","donor_sjis_hex","donor_byte1","donor_byte2",
        "glyph_index","glyph_hex","font_file_offset","tier",
        "stage36r_runtime_verified","source"
    ]
    local_mapping=out/"sub10_hangul_donor_mapping.tsv"
    shared_mapping=shared/"event_font_hangul_mapping.tsv"
    write_tsv(local_mapping,mapping,mapping_fields)
    write_tsv(shared_mapping,mapping,mapping_fields)

    # Full strict pool snapshot.
    allocated_pairs={(r["donor_sjis_hex"],int(r["glyph_index"])) for r in mapping}
    pool_rows=[]
    for r in strict_all:
        glyph=int(r["glyph_index"])
        in_standard=(glyph<=MAX_STANDARD_GLYPH)
        pool_rows.append({
            "glyph_index":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "sjis_hex":r["sjis_hex"],
            "font_file_offset":r["font_file_offset"],
            "strict_safe":"1",
            "standard_range":"YES" if in_standard else "NO",
            "special_intercept":r["special_intercept"],
            "kr_tbl_usage":r["kr_tbl_usage"],
            "ui_sample_usage":r["ui_sample_usage"],
            "allocated":"YES" if (r["sjis_hex"],glyph) in allocated_pairs else "NO",
        })
    write_tsv(
        out/"sub10_strict_pool_snapshot.tsv",
        pool_rows,
        [
            "glyph_index","glyph_hex","sjis_hex","font_file_offset","strict_safe",
            "standard_range","special_intercept","kr_tbl_usage","ui_sample_usage","allocated"
        ]
    )

    fixed_rows=[]
    for ch,(code,glyph) in FIXED.items():
        fixed_rows.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "sjis_hex":code,
            "glyph_index":glyph,
            "verification":"Stage36R PPSSPP runtime rendered correctly",
        })
    write_tsv(
        out/"sub10_fixed_stage36r.tsv",
        fixed_rows,
        ["hangul","unicode","sjis_hex","glyph_index","verification"]
    )

    capacity=[{
        "font_slots_total":len(slot_rows),
        "strict_all_3600":len(strict_all),
        "strict_standard_0_3428":len(strict_standard),
        "fixed_stage36r":len(FIXED),
        "usable_strict_after_fixed":len(usable),
        "new_hangul_needed":len(remaining),
        "unused_strict_after_allocation":len(usable)-len(remaining),
        "reclaim_used":0,
        "special_region_used":0,
    }]
    write_tsv(
        out/"sub10_capacity_report.tsv",
        capacity,
        [
            "font_slots_total","strict_all_3600","strict_standard_0_3428",
            "fixed_stage36r","usable_strict_after_fixed","new_hangul_needed",
            "unused_strict_after_allocation","reclaim_used","special_region_used"
        ]
    )

    # Small source evidence copies.
    evidence=out/"source_evidence"
    evidence.mkdir(exist_ok=True)
    for p in [slot_path,stage36_map,summary_txt,summary_json,old_seed]:
        if p and Path(p).exists() and Path(p).stat().st_size <= 8*1024*1024:
            shutil.copy2(Path(p), evidence/Path(p).name)

    manifest={
        "stage":"SUB10_FIX2",
        "final_hangul":EXPECTED_HANGUL,
        "fixed_stage36r":EXPECTED_FIXED,
        "new_strict_allocations":EXPECTED_NEW,
        "strict_all_3600":len(strict_all),
        "strict_standard_0_3428":len(strict_standard),
        "usable_after_fixed":len(usable),
        "unused_after_allocation":len(usable)-len(remaining),
        "reclaim_allocations":0,
        "special_region_allocations":0,
        "mapping_sha256":sha256_file(local_mapping),
        "shared_mapping_sha256":sha256_file(shared_mapping),
        "source_slot_inventory_sha256":sha256_file(slot_path),
        "source_stage36r_mapping_sha256":sha256_file(stage36_map),
    }
    if manifest["mapping_sha256"] != manifest["shared_mapping_sha256"]:
        raise SystemExit("Local/shared mapping SHA256 mismatch")

    (out/"sub10_mapping_manifest.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB10 FIX2 - Final Hangul Donor Allocation",
        "",
        f"FinalHangul={EXPECTED_HANGUL}",
        f"Stage35RStrictAll3600={len(strict_all)}",
        f"Stage35RStrictStandard0_3428={len(strict_standard)}",
        f"FixedStage36R={len(FIXED)}",
        f"UsableStrictAfterFixed={len(usable)}",
        f"NewStrictAllocations={len(remaining)}",
        f"UnusedStrictAfterAllocation={len(usable)-len(remaining)}",
        "RECLAIMAllocations=0",
        "SpecialRegionAllocations=0",
        f"MappingSHA256={manifest['mapping_sha256']}",
        "",
        f"SlotInventory={slot_path}",
        f"Stage36RMapping={stage36_map}",
        f"SharedMapping={shared_mapping}",
        "",
        "IMPORTANT:",
        "- stage35r_allocation_strict.tsv is old 10-char seed output and was NOT used as the donor pool.",
        "- donor pool came from stage35r_slot_inventory.tsv strict_safe=1.",
        "- no BOOT/ISO bytes were modified.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("\n".join(summary))

if __name__=="__main__":
    main()
