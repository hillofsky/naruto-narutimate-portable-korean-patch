#!/usr/bin/env python3
# Naruto PSP SUB15 - Rebuild donor mapping from the ACTUAL runtime SJIS->glyph logic
#
# Recovered from BOOT:
#   0x088D5640 : 2-byte lead classifier
#   0x088D568C : 163-code special lookup
#   0x088D56EC : 2-byte SJIS -> glyph conversion
#
# Key discovery:
#   The event font does NOT use the naive full JIS 94x94 linear index.
#   Standard font layout is effectively:
#     JIS rows 0x21..0x25 -> glyphs 0..469 (last 6 positions are aliases/unused)
#     JIS rows 0x30..0x4F53 -> glyphs 464..3428
#   Runtime formula removes the unused JIS block and six unused positions.
#
# Read-only with respect to BOOT/ISO.
# Produces a corrected frozen mapping in analysis/shared.

from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

BASE_FONT_OFFSET = 0x39CD04
GLYPH_SIZE = 162
GLYPH_COUNT = 3600
STANDARD_MAX_GLYPH = 3428
SPECIAL_GLYPH_BASE = 3429
SPECIAL_COUNT = 163
SPECIAL_FILE_OFFSET = 0x2DE964
EXPECTED_HANGUL = 694

EXPECTED_BOOT_SHA256 = "1083ba42327f187cd81fe6b31c9975857d271373d4a907d1b7f35d38bc7fc4c8"
EXPECTED_SUB09_UNIQUE = 694

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

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def write_tsv(path: Path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

def read_tsv(path: Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def is_two_byte_lead(b: int) -> bool:
    # Exact 0x088D5640 behavior.
    return (0x81 <= b < 0xA0) or (0xE0 <= b < 0xFD)

def valid_trail(b: int) -> bool:
    return (0x40 <= b <= 0x7E) or (0x80 <= b <= 0xFC)

def runtime_sjis_to_jis(code: int):
    lead=(code>>8)&0xFF
    trail=code&0xFF

    if not (0x81 <= lead < 0xA0):
        return None
    if not valid_trail(trail):
        return None

    t1=lead-0x81
    t1*=2

    if 0x40 <= trail <= 0x7E:
        t0=trail-0x40
    elif 0x80 <= trail <= 0x9E:
        t0=trail-0x41
    elif 0x9F <= trail <= 0xFC:
        t0=trail-0x9F
        t1+=1
    else:
        return None

    # Matches 0x088D57B8..57CC.
    packed=((t1+1)<<8)+t0
    jis=packed+0x2021
    return jis

def runtime_normal_glyph(code: int):
    """
    Exact normal-path arithmetic from 0x088D573C..0x088D5860
    for valid 0x81..0x98 standard candidates.

    Returns the runtime glyph index. This deliberately preserves the
    event-font compression, unlike the old naive (row-0x21)*94 formula.
    """
    jis=runtime_sjis_to_jis(code)
    if jis is None:
        return None

    # 0x088D57D0..57F4 range/fallback behavior.
    if not (0x2121 <= jis < 0x4F54):
        jis=0x2223

    row=(jis>>8)&0xFF
    cell=jis&0xFF

    if row < 0x26:
        # 0x088D5840 branch
        a0=row-0x21
        glyph=a0*94 + (cell-0x21)
    else:
        # 0x088D5810 branch:
        # ((row - 0x2B) * 94) + (cell - 0x21) - 6
        a0=row-0x2B
        glyph=a0*94 + (cell-0x21) - 6

    return glyph

def read_special_table(raw: bytes):
    end=SPECIAL_FILE_OFFSET+SPECIAL_COUNT*2
    if end>len(raw):
        raise RuntimeError("special table exceeds BOOT")
    block=raw[SPECIAL_FILE_OFFSET:end]

    # Runtime lookup compares raw bytes, so each two-byte table entry is
    # represented in byte order as it appears in the text stream.
    candidates=[]
    for endian in ("big","little"):
        codes=[
            int.from_bytes(block[i:i+2],endian)
            for i in range(0,len(block),2)
        ]
        # Stage34 known tail validation.
        tail_expected=[
            0xE1C9,0xE5BF,0xE7B2,0x9DDF,0xFBFC,
            0xE290,0x9E8A,0xE165,0xE18F,0x9CB1,
        ]
        score=sum(a==b for a,b in zip(codes[-10:],tail_expected))
        candidates.append((score,endian,codes))

    candidates.sort(key=lambda x:(-x[0],x[1]))
    score,endian,codes=candidates[0]
    if score!=10:
        raise RuntimeError(f"special table validation failed: tail={score}/10")

    return endian,{
        code:SPECIAL_GLYPH_BASE+i
        for i,code in enumerate(codes)
    },codes

def runtime_glyph(code: int, special_map: dict[int,int]):
    lead=(code>>8)&0xFF
    trail=code&0xFF

    # Exact dispatch condition from 0x088D56F8..573C:
    # lookup special table for lead >= 0x99, and for 0x98 with trail >= 0x80.
    if lead >= 0x99 or (lead==0x98 and trail>=0x80):
        if code in special_map:
            return special_map[code]
        # Not found => normal function continues, but high leads fall into
        # the built-in fallback. We emulate that only for usage accounting.
        # Canonical donor codes never use this high unsupported region.

    # For the standard canonical pool we only trust the range that actually
    # maps all standard font glyphs uniquely.
    g=runtime_normal_glyph(code)
    if g is not None:
        return g

    # Unsupported/high code fallback in the real routine resolves to JIS 0x2223,
    # which is normal glyph 96.
    if is_two_byte_lead(lead):
        return 96

    return None

def build_canonical_standard_map():
    """
    Produce exactly one runtime-valid raw SJIS code for every glyph 0..3428.

    We deliberately exclude JIS rows 0x26..0x2F because the font omits those
    rows. The six invalid row-0x25 tail aliases (83 99..9E) are also excluded
    in favor of the real first-kanji codes 88 9F..A4 for glyphs 464..469.
    """
    candidates=defaultdict(list)

    for lead in range(0x81,0x99):  # normal runtime region through 0x98
        for trail in list(range(0x40,0x7F))+list(range(0x80,0xFD)):
            code=(lead<<8)|trail
            jis=runtime_sjis_to_jis(code)
            if jis is None:
                continue
            row=(jis>>8)&0xFF
            cell=jis&0xFF

            allowed=(
                0x21 <= row <= 0x25
                or 0x30 <= row < 0x4F
                or (row==0x4F and cell<=0x53)
            )
            if not allowed:
                continue

            g=runtime_normal_glyph(code)
            if g is None or not (0<=g<=STANDARD_MAX_GLYPH):
                continue

            # Prefer the real kanji row when a row-0x25 invalid tail aliases it.
            pref=0 if row>=0x30 else 1
            candidates[g].append((pref,code,jis))

    glyph_to_code={}
    code_to_glyph={}

    for glyph in range(STANDARD_MAX_GLYPH+1):
        opts=candidates.get(glyph,[])
        if not opts:
            raise RuntimeError(f"no canonical runtime code for glyph {glyph}")
        opts.sort(key=lambda x:(x[0],x[1]))
        _,code,jis=opts[0]
        glyph_to_code[glyph]=code
        if code in code_to_glyph:
            raise RuntimeError(f"duplicate canonical code {code:04X}")
        code_to_glyph[code]=glyph

    if len(glyph_to_code)!=3429 or len(code_to_glyph)!=3429:
        raise RuntimeError("canonical map size mismatch")

    # Hard vectors from Stage36R and SUB13 diagnosis.
    vectors={
        0x81EC:171,
        0x81EE:173,
        0x81EF:174,
        0x8241:189,
        0x8248:196,
        0x824A:198,
        0x825C:216,
        0x825E:218,
        0x82F5:368,
        0x82F7:370,
        0x889F:464,
        0x88E5:534,
        0x9872:3428,
    }
    for code,expected in vectors.items():
        actual=runtime_normal_glyph(code)
        if actual!=expected:
            raise RuntimeError(
                f"runtime formula vector failed {code:04X}: {actual} != {expected}"
            )

    return glyph_to_code,code_to_glyph

def parse_pairs_runtime(data: bytes):
    """
    Approximate the event parser's byte consumption conservatively:
    every lead byte classified as two-byte consumes the following byte.
    """
    i=0
    while i<len(data):
        b=data[i]
        if is_two_byte_lead(b) and i+1<len(data):
            yield (b<<8)|data[i+1]
            i+=2
        else:
            i+=1

def decode_usage(data: bytes, special_map):
    cc=Counter()
    gg=Counter()
    for code in parse_pairs_runtime(data):
        cc[code]+=1
        g=runtime_glyph(code,special_map)
        if g is not None and 0<=g<GLYPH_COUNT:
            gg[g]+=1
    return cc,gg

def collect_tbl_usage(root: Path,special_map):
    code_counts=Counter()
    glyph_counts=Counter()
    coverage=[]
    tbl_root=root/"analysis"/"stage3"/"extracted"/"kr"

    sources=sorted(tbl_root.glob("*.tbl")) if tbl_root.exists() else []

    for p in sources:
        data=p.read_bytes()
        cc,gg=decode_usage(data,special_map)
        code_counts.update(cc)
        glyph_counts.update(gg)
        coverage.append({
            "kind":"KR_STAGE3_TBL",
            "path":str(p),
            "bytes":len(data),
            "pair_occurrences":sum(cc.values()),
            "unique_codes":len(cc),
            "unique_glyphs":len(gg),
            "samples":"",
        })

    return code_counts,glyph_counts,coverage

def collect_ui_usage(root: Path,special_map):
    code_counts=Counter()
    glyph_counts=Counter()
    coverage=[]
    p=root/"analysis"/"stage9"/"kr_ccs_japanese_scan.tsv"
    if not p.exists():
        return code_counts,glyph_counts,coverage

    samples=0
    with p.open("r",encoding="utf-8-sig",errors="replace",newline="") as f:
        reader=csv.DictReader(f,delimiter="\t")
        for row in reader:
            sample=row.get("sample") or ""
            if not sample:
                continue
            try:
                raw=sample.encode("cp932",errors="strict")
            except UnicodeEncodeError:
                raw=sample.encode("cp932",errors="ignore")
            cc,gg=decode_usage(raw,special_map)
            code_counts.update(cc)
            glyph_counts.update(gg)
            samples+=1

    coverage.append({
        "kind":"KR_CCS_TEXT_SAMPLES",
        "path":str(p),
        "bytes":p.stat().st_size,
        "pair_occurrences":sum(code_counts.values()),
        "unique_codes":len(code_counts),
        "unique_glyphs":len(glyph_counts),
        "samples":samples,
    })
    return code_counts,glyph_counts,coverage

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

    boot=root/"kr_extracted"/"PSP_GAME"/"SYSDIR"/"BOOT.BIN"
    unique_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_unique_hangul.txt"
    freq_path=root/"analysis"/"sub"/"sub09_final_speaker_corpus"/"sub09_final_char_frequency.tsv"
    old_map=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"

    for p in (boot,unique_path,freq_path):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    boot_sha=sha256_file(boot)
    if boot_sha.lower()!=EXPECTED_BOOT_SHA256:
        raise RuntimeError(f"BOOT SHA256 mismatch: {boot_sha}")

    chars="".join(
        ch for ch in unique_path.read_text(encoding="utf-8-sig")
        if "\uAC00"<=ch<="\uD7A3"
    )
    if len(chars)!=EXPECTED_SUB09_UNIQUE or len(set(chars))!=EXPECTED_SUB09_UNIQUE:
        raise RuntimeError(
            f"SUB09 unique Hangul mismatch: chars={len(chars)} unique={len(set(chars))}"
        )
    char_set=set(chars)

    freq_rows=read_tsv(freq_path)
    freq={r["char"]:int(r["count"]) for r in freq_rows}

    raw=boot.read_bytes()
    special_endian,special_map,special_codes=read_special_table(raw)
    glyph_to_code,code_to_glyph=build_canonical_standard_map()

    # Canonical map must agree with Stage36R fixed codes.
    for ch,(code_hex,glyph) in FIXED.items():
        code=int(code_hex,16)
        if runtime_glyph(code,special_map)!=glyph:
            raise RuntimeError(
                f"fixed runtime mapping mismatch {ch}: {code_hex} -> "
                f"{runtime_glyph(code,special_map)} expected {glyph}"
            )
        if glyph_to_code[glyph]!=code:
            raise RuntimeError(
                f"canonical code differs from Stage36R fixed {ch}: "
                f"{glyph_to_code[glyph]:04X} != {code_hex}"
            )

    tbl_codes,tbl_glyphs,tbl_cov=collect_tbl_usage(root,special_map)
    ui_codes,ui_glyphs,ui_cov=collect_ui_usage(root,special_map)
    coverage=tbl_cov+ui_cov

    if not tbl_cov:
        raise RuntimeError(
            "Stage3 KR TBL sources were not found; refusing to classify donors as STRICT"
        )

    # Bitmap properties.
    glyph_empty={}
    glyph_nonzero={}
    for glyph in range(GLYPH_COUNT):
        off=BASE_FONT_OFFSET+glyph*GLYPH_SIZE
        block=raw[off:off+GLYPH_SIZE]
        if len(block)!=GLYPH_SIZE:
            raise RuntimeError(f"short glyph block {glyph}")
        glyph_empty[glyph]=int(not any(block))
        glyph_nonzero[glyph]=sum(1 for b in block if b)

    slots=[]
    for glyph in range(STANDARD_MAX_GLYPH+1):
        code=glyph_to_code[glyph]
        tbl_use=tbl_glyphs[glyph]
        ui_use=ui_glyphs[glyph]
        strict_safe=(tbl_use==0 and ui_use==0)

        jis=runtime_sjis_to_jis(code)
        slots.append({
            "glyph":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "runtime_sjis":f"{code:04X}",
            "sjis_hex":f"{code>>8:02X} {code&0xFF:02X}",
            "jis":f"{jis:04X}" if jis is not None else "",
            "font_file_offset":f"0x{BASE_FONT_OFFSET+glyph*GLYPH_SIZE:X}",
            "bitmap_empty":glyph_empty[glyph],
            "bitmap_nonzero_bytes":glyph_nonzero[glyph],
            "kr_tbl_usage":tbl_use,
            "ui_sample_usage":ui_use,
            "strict_safe":int(strict_safe),
        })

    strict=[r for r in slots if r["strict_safe"]]

    # Preserve the 10 already runtime-proven fixed slots.
    fixed_glyphs={g for _,g in FIXED.values()}
    fixed_codes={int(c,16) for c,_ in FIXED.values()}

    for ch,(code_hex,glyph) in FIXED.items():
        slot=slots[glyph]
        if not slot["strict_safe"]:
            raise RuntimeError(
                f"Stage36R fixed slot is no longer STRICT under actual runtime usage: "
                f"{ch} {code_hex} glyph{glyph} tbl={slot['kr_tbl_usage']} ui={slot['ui_sample_usage']}"
            )

    usable=[
        r for r in strict
        if int(r["glyph"]) not in fixed_glyphs
        and int(r["runtime_sjis"],16) not in fixed_codes
    ]

    # Same conservative preference as Stage35R: empty bitmaps first,
    # then high glyphs, but now with runtime-correct codes.
    usable.sort(key=lambda r:(0 if r["bitmap_empty"] else 1,-int(r["glyph"])))

    remaining=sorted((ch for ch in char_set if ch not in FIXED),key=ord)
    if len(remaining)!=684:
        raise RuntimeError(f"expected 684 non-fixed chars, got {len(remaining)}")
    if len(usable)<len(remaining):
        raise RuntimeError(
            f"actual-runtime STRICT capacity insufficient: need=684 usable={len(usable)}"
        )

    mapping=[]
    for ch in sorted(char_set,key=ord):
        if ch not in FIXED:
            continue
        code_hex,glyph=FIXED[ch]
        slot=slots[glyph]
        mapping.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "frequency":freq.get(ch,0),
            "donor_sjis_hex":code_hex,
            "donor_byte1":code_hex[:2],
            "donor_byte2":code_hex[2:],
            "glyph_index":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "font_file_offset":slot["font_file_offset"],
            "tier":"FIXED_STAGE36R_VERIFIED",
            "stage36r_runtime_verified":"YES",
            "kr_tbl_usage_before":slot["kr_tbl_usage"],
            "ui_sample_usage":slot["ui_sample_usage"],
        })

    for ch,slot in zip(remaining,usable):
        code_hex=slot["runtime_sjis"]
        glyph=int(slot["glyph"])
        mapping.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "frequency":freq.get(ch,0),
            "donor_sjis_hex":code_hex,
            "donor_byte1":code_hex[:2],
            "donor_byte2":code_hex[2:],
            "glyph_index":glyph,
            "glyph_hex":f"0x{glyph:X}",
            "font_file_offset":slot["font_file_offset"],
            "tier":"STRICT_ACTUAL_RUNTIME",
            "stage36r_runtime_verified":"NO",
            "kr_tbl_usage_before":slot["kr_tbl_usage"],
            "ui_sample_usage":slot["ui_sample_usage"],
        })

    mapping.sort(key=lambda r:ord(r["hangul"]))

    # Hard validation through the actual recovered function.
    if len(mapping)!=EXPECTED_HANGUL:
        raise RuntimeError(f"mapping row mismatch: {len(mapping)}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_HANGUL:
        raise RuntimeError("duplicate Hangul")
    if len({r["donor_sjis_hex"] for r in mapping})!=EXPECTED_HANGUL:
        raise RuntimeError("duplicate donor SJIS")
    if len({int(r["glyph_index"]) for r in mapping})!=EXPECTED_HANGUL:
        raise RuntimeError("duplicate donor glyph")

    for r in mapping:
        code=int(r["donor_sjis_hex"],16)
        expected=int(r["glyph_index"])
        actual=runtime_glyph(code,special_map)
        if actual!=expected:
            raise RuntimeError(
                f"runtime self-check failed {r['hangul']} "
                f"{r['donor_sjis_hex']} -> {actual}, expected {expected}"
            )
        if expected>STANDARD_MAX_GLYPH:
            raise RuntimeError("special glyph allocated")

    fields=[
        "hangul","unicode","frequency","donor_sjis_hex","donor_byte1","donor_byte2",
        "glyph_index","glyph_hex","font_file_offset","tier",
        "stage36r_runtime_verified","kr_tbl_usage_before","ui_sample_usage"
    ]

    new_map=out/"sub15_runtime_hangul_mapping.tsv"
    shared_map=shared/"event_font_hangul_mapping.tsv"
    write_tsv(new_map,mapping,fields)
    write_tsv(shared_map,mapping,fields)

    write_tsv(
        out/"sub15_runtime_slot_inventory.tsv",
        slots,
        [
            "glyph","glyph_hex","runtime_sjis","sjis_hex","jis","font_file_offset",
            "bitmap_empty","bitmap_nonzero_bytes","kr_tbl_usage","ui_sample_usage",
            "strict_safe"
        ]
    )

    write_tsv(
        out/"sub15_source_coverage.tsv",
        coverage,
        [
            "kind","path","bytes","pair_occurrences","unique_codes","unique_glyphs","samples"
        ]
    )

    # Special table report.
    special_rows=[]
    for i,code in enumerate(special_codes):
        special_rows.append({
            "index":i,
            "sjis":f"{code:04X}",
            "sjis_hex":f"{code>>8:02X} {code&0xFF:02X}",
            "glyph":SPECIAL_GLYPH_BASE+i,
            "file_offset":f"0x{SPECIAL_FILE_OFFSET+i*2:X}",
        })
    write_tsv(
        out/"sub15_special_table.tsv",
        special_rows,
        ["index","sjis","sjis_hex","glyph","file_offset"]
    )

    # Mapping vectors that explain SUB13.
    vectors=[]
    for code in [
        0x81EC,0x82F7,0x8399,0x889F,0x88E5,0x88E7,0x88EA,0x9872
    ]:
        g=runtime_glyph(code,special_map)
        old_naive=None
        jis=runtime_sjis_to_jis(code)
        if jis is not None:
            row=jis>>8; cell=jis&0xFF
            old_naive=(row-0x21)*94+(cell-0x21)
        vectors.append({
            "sjis":f"{code:04X}",
            "jis":f"{jis:04X}" if jis is not None else "",
            "actual_runtime_glyph":g,
            "old_naive_glyph":old_naive if old_naive is not None else "",
            "difference":(
                old_naive-g
                if old_naive is not None and g is not None
                else ""
            ),
        })
    write_tsv(
        out/"sub15_runtime_formula_vectors.tsv",
        vectors,
        ["sjis","jis","actual_runtime_glyph","old_naive_glyph","difference"]
    )

    # Compare old frozen mapping if present, for diagnosis only.
    compare=[]
    if old_map.exists():
        try:
            old_rows=read_tsv(old_map)
            old_by_char={r["hangul"]:r for r in old_rows}
            for r in mapping:
                ch=r["hangul"]
                old=old_by_char.get(ch,{})
                compare.append({
                    "hangul":ch,
                    "old_sjis":old.get("donor_sjis_hex",""),
                    "old_glyph":old.get("glyph_index",""),
                    "new_sjis":r["donor_sjis_hex"],
                    "new_glyph":r["glyph_index"],
                    "sjis_changed":int(old.get("donor_sjis_hex","")!=r["donor_sjis_hex"]),
                    "glyph_changed":int(str(old.get("glyph_index",""))!=str(r["glyph_index"])),
                })
            write_tsv(
                out/"sub15_vs_previous_mapping.tsv",
                compare,
                [
                    "hangul","old_sjis","old_glyph","new_sjis","new_glyph",
                    "sjis_changed","glyph_changed"
                ]
            )
        except Exception:
            pass

    new_sha=sha256_file(new_map)
    shared_sha=sha256_file(shared_map)
    if new_sha!=shared_sha:
        raise RuntimeError("local/shared mapping SHA mismatch")

    report={
        "stage":"SUB15",
        "boot_sha256":boot_sha,
        "special_table_endian":special_endian,
        "special_entries":len(special_codes),
        "canonical_standard_codes":len(glyph_to_code),
        "strict_standard_slots":len(strict),
        "fixed_stage36r":len(FIXED),
        "usable_strict_after_fixed":len(usable),
        "new_allocations":len(remaining),
        "unused_strict_after_allocation":len(usable)-len(remaining),
        "mapping_rows":len(mapping),
        "mapping_sha256":new_sha,
        "runtime_self_check_failures":0,
        "special_region_allocations":0,
        "tbl_files":len(tbl_cov),
        "ui_coverage_sources":len(ui_cov),
    }
    (out/"sub15_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB15 - Actual Runtime Donor Mapping",
        "",
        f"CanonicalStandardCodes={len(glyph_to_code)}",
        f"StrictStandardSlots={len(strict)}",
        f"FixedStage36R={len(FIXED)}",
        f"UsableStrictAfterFixed={len(usable)}",
        f"NewAllocations={len(remaining)}",
        f"UnusedStrictAfterAllocation={len(usable)-len(remaining)}",
        f"MappingRows={len(mapping)}",
        f"MappingSHA256={new_sha}",
        "RuntimeSelfCheckFailures=0",
        "SpecialRegionAllocations=0",
        "",
        "Recovered formula validation:",
        "  81EC -> glyph 171",
        "  82F7 -> glyph 370",
        "  889F -> glyph 464",
        "  88E5 -> glyph 534  (old naive formula said 1480)",
        "  9872 -> glyph 3428",
        "",
        f"SharedMapping={shared_map}",
        "",
        "No BOOT/ISO bytes were modified by SUB15.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",
        encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
