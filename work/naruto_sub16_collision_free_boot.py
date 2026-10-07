#!/usr/bin/env python3
# Naruto PSP SUB16 - Collision-free actual-runtime mapping + full Hangul BOOT
#
# SUB15 correctly recovered the actual runtime mapping and assigned 684 new
# Hangul to STRICT slots, but five Stage36R-pinned mappings still occupy
# non-STRICT glyphs due alias SJIS codes used by original KR content.
#
# SUB16 keeps all already-safe mappings and reassigns ONLY:
#   한 글 스 나 마
# to previously unused STRICT actual-runtime slots.
#
# Then rebuilds the full 694-glyph BOOT from the ORIGINAL KR BOOT.
# No ISO is modified.

from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EXPECTED_SUB15_SHA256 = "caf832677e92da62cc659a9b9e57922ece478f93babab02936a848a3b48adc21"
EXPECTED_ORIGINAL_BOOT_SHA256 = "1083ba42327f187cd81fe6b31c9975857d271373d4a907d1b7f35d38bc7fc4c8"
EXPECTED_ROWS = 694
EXPECTED_STRICT_SLOTS = 792
EXPECTED_UNSAFE = {"한","글","스","나","마"}
EXPECTED_SAFE_STAGE36 = {"테","트","가","다","라"}

FONT_PATH = Path(r"C:\Windows\Fonts\malgunbd.ttf")
FONT_SIZE = 16
CANVAS_W = 18
CANVAS_H = 18
DRAW_X = 1
DRAW_Y = -4
BYTES_PER_GLYPH = 162
FONT_FILE_OFFSET = 0x39CD04
MAX_STANDARD_GLYPH = 3428

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def read_tsv(path: Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def runtime_sjis_to_jis(code: int):
    lead=(code>>8)&0xFF
    trail=code&0xFF
    if not (0x81 <= lead < 0xA0):
        return None
    if not ((0x40 <= trail <= 0x7E) or (0x80 <= trail <= 0xFC)):
        return None

    t1=(lead-0x81)*2
    if 0x40 <= trail <= 0x7E:
        t0=trail-0x40
    elif 0x80 <= trail <= 0x9E:
        t0=trail-0x41
    else:
        t0=trail-0x9F
        t1+=1

    return (((t1+1)<<8)+t0)+0x2021

def runtime_normal_glyph(code: int):
    jis=runtime_sjis_to_jis(code)
    if jis is None:
        return None
    if not (0x2121 <= jis < 0x4F54):
        jis=0x2223

    row=(jis>>8)&0xFF
    cell=jis&0xFF
    if row < 0x26:
        return (row-0x21)*94 + (cell-0x21)
    return (row-0x2B)*94 + (cell-0x21) - 6

def render_glyph(ch: str, font):
    img=Image.new("L",(CANVAS_W,CANVAS_H),0)
    draw=ImageDraw.Draw(img)
    draw.text((DRAW_X,DRAW_Y),ch,font=font,fill=255)
    vals=[v//17 for v in img.getdata()]
    packed=bytearray()
    for i in range(0,len(vals),2):
        packed.append(vals[i] | (vals[i+1]<<4))
    if len(packed)!=BYTES_PER_GLYPH:
        raise RuntimeError(f"bad rendered block size for {ch}: {len(packed)}")
    return bytes(packed)

def decode_glyph(block: bytes):
    vals=[]
    for b in block:
        vals.append((b&0x0F)*17)
        vals.append(((b>>4)&0x0F)*17)
    img=Image.new("L",(CANVAS_W,CANVAS_H),0)
    img.putdata(vals)
    return img

def make_preview(entries, path: Path, cols=28, scale=4):
    rows=math.ceil(len(entries)/cols)
    sheet=Image.new("L",(cols*CANVAS_W,rows*CANVAS_H),0)
    for i,e in enumerate(entries):
        x=(i%cols)*CANVAS_W
        y=(i//cols)*CANVAS_H
        sheet.paste(decode_glyph(e["block"]),(x,y))
    sheet=sheet.resize(
        (sheet.width*scale,sheet.height*scale),
        Image.Resampling.NEAREST
    )
    sheet.save(path)

def verify_only_target_ranges(original: bytes, patched: bytes, glyphs):
    intervals=sorted(
        (
            FONT_FILE_OFFSET+g*BYTES_PER_GLYPH,
            FONT_FILE_OFFSET+(g+1)*BYTES_PER_GLYPH,
        )
        for g in glyphs
    )
    if len(original)!=len(patched):
        raise RuntimeError("BOOT length changed")

    pos=0
    for start,end in intervals:
        if start<pos:
            raise RuntimeError("overlapping target intervals")
        if original[pos:start]!=patched[pos:start]:
            raise RuntimeError(f"off-target modification before 0x{start:X}")
        pos=end
    if original[pos:]!=patched[pos:]:
        raise RuntimeError("off-target modification after final glyph")

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

    sub15_map=root/"analysis"/"sub"/"sub15_actual_runtime_mapping"/"sub15_runtime_hangul_mapping.tsv"
    slot_path=root/"analysis"/"sub"/"sub15_actual_runtime_mapping"/"sub15_runtime_slot_inventory.tsv"
    stage36_map=root/"analysis"/"stage36r"/"stage36r_mapping.tsv"
    original_boot=root/"kr_extracted"/"PSP_GAME"/"SYSDIR"/"BOOT.BIN"
    shared_map=shared/"event_font_hangul_mapping.tsv"

    for p in (sub15_map,slot_path,stage36_map,original_boot,FONT_PATH):
        if not p.exists():
            raise RuntimeError(f"required input missing: {p}")

    if sha256_file(sub15_map).lower()!=EXPECTED_SUB15_SHA256:
        raise RuntimeError(
            f"SUB15 mapping SHA mismatch: {sha256_file(sub15_map)}"
        )
    if sha256_file(original_boot).lower()!=EXPECTED_ORIGINAL_BOOT_SHA256:
        raise RuntimeError(
            f"original BOOT SHA mismatch: {sha256_file(original_boot)}"
        )

    mapping=read_tsv(sub15_map)
    slots=read_tsv(slot_path)
    if len(mapping)!=EXPECTED_ROWS:
        raise RuntimeError(f"SUB15 mapping rows={len(mapping)}")
    if len({r["hangul"] for r in mapping})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate Hangul in SUB15 mapping")

    slot_by_glyph={int(r["glyph"]):r for r in slots}
    strict=[r for r in slots if r["strict_safe"]=="1"]
    if len(strict)!=EXPECTED_STRICT_SLOTS:
        raise RuntimeError(
            f"STRICT slot count changed: {len(strict)} != {EXPECTED_STRICT_SLOTS}"
        )

    unsafe=[]
    for r in mapping:
        g=int(r["glyph_index"])
        slot=slot_by_glyph[g]
        if slot["strict_safe"]!="1":
            unsafe.append(r)

    unsafe_chars={r["hangul"] for r in unsafe}
    if unsafe_chars!=EXPECTED_UNSAFE:
        raise RuntimeError(
            f"unexpected non-STRICT mapped chars: {sorted(unsafe_chars)}"
        )

    # All non-unsafe mappings are retained exactly.
    used_safe_glyphs={
        int(r["glyph_index"])
        for r in mapping
        if r["hangul"] not in EXPECTED_UNSAFE
    }
    used_safe_codes={
        r["donor_sjis_hex"].upper()
        for r in mapping
        if r["hangul"] not in EXPECTED_UNSAFE
    }

    unused_strict=[
        r for r in strict
        if int(r["glyph"]) not in used_safe_glyphs
        and r["runtime_sjis"].upper() not in used_safe_codes
    ]
    # Deterministic preference: empty bitmap first, then highest glyph.
    unused_strict.sort(
        key=lambda r:(0 if r["bitmap_empty"]=="1" else 1,-int(r["glyph"]))
    )

    if len(unused_strict)<len(EXPECTED_UNSAFE):
        raise RuntimeError("not enough unused STRICT slots for five reassignments")

    # Reassign only the five unsafe Stage36R-pinned mappings.
    # Stable order follows their original SUB15 mapping order.
    reassigned={}
    for old,slot in zip(unsafe,unused_strict[:len(unsafe)]):
        reassigned[old["hangul"]]=slot

    final=[]
    changes=[]
    for r in mapping:
        x=dict(r)
        ch=r["hangul"]
        if ch in reassigned:
            slot=reassigned[ch]
            code=slot["runtime_sjis"].upper()
            glyph=int(slot["glyph"])
            changes.append({
                "hangul":ch,
                "old_sjis":r["donor_sjis_hex"],
                "old_glyph":r["glyph_index"],
                "old_kr_tbl_usage":r["kr_tbl_usage_before"],
                "old_ui_sample_usage":r["ui_sample_usage"],
                "new_sjis":code,
                "new_glyph":glyph,
                "new_kr_tbl_usage":slot["kr_tbl_usage"],
                "new_ui_sample_usage":slot["ui_sample_usage"],
                "new_bitmap_empty":slot["bitmap_empty"],
                "reason":"OLD_PINNED_GLYPH_NOT_STRICT",
            })
            x["donor_sjis_hex"]=code
            x["donor_byte1"]=code[:2]
            x["donor_byte2"]=code[2:]
            x["glyph_index"]=str(glyph)
            x["glyph_hex"]=f"0x{glyph:X}"
            x["font_file_offset"]=slot["font_file_offset"]
            x["tier"]="STRICT_ACTUAL_RUNTIME_REASSIGNED"
            x["stage36r_runtime_verified"]="NO"
            x["kr_tbl_usage_before"]=slot["kr_tbl_usage"]
            x["ui_sample_usage"]=slot["ui_sample_usage"]
        elif ch in EXPECTED_SAFE_STAGE36:
            x["tier"]="STRICT_STAGE36R_VERIFIED"
        final.append(x)

    # Every final mapping must now occupy a STRICT slot.
    bad=[]
    for r in final:
        g=int(r["glyph_index"])
        slot=slot_by_glyph[g]
        if slot["strict_safe"]!="1":
            bad.append((r["hangul"],r["donor_sjis_hex"],g))
        code=int(r["donor_sjis_hex"],16)
        actual=runtime_normal_glyph(code)
        if actual!=g:
            raise RuntimeError(
                f"runtime mapping mismatch {r['hangul']} {code:04X}: "
                f"{actual} != {g}"
            )

    if bad:
        raise RuntimeError(f"non-STRICT final mappings remain: {bad}")

    if len(final)!=EXPECTED_ROWS:
        raise RuntimeError("final mapping count mismatch")
    if len({r["hangul"] for r in final})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate final Hangul")
    if len({r["donor_sjis_hex"] for r in final})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate final donor SJIS")
    if len({int(r["glyph_index"]) for r in final})!=EXPECTED_ROWS:
        raise RuntimeError("duplicate final glyph")
    if max(int(r["glyph_index"]) for r in final)>MAX_STANDARD_GLYPH:
        raise RuntimeError("special glyph allocated")

    final_fields=list(final[0].keys())
    local_map=out/"sub16_collision_free_hangul_mapping.tsv"
    write_tsv(local_map,final,final_fields)
    write_tsv(shared_map,final,final_fields)
    write_tsv(
        out/"sub16_reassigned_five.tsv",
        changes,
        [
            "hangul","old_sjis","old_glyph","old_kr_tbl_usage",
            "old_ui_sample_usage","new_sjis","new_glyph",
            "new_kr_tbl_usage","new_ui_sample_usage","new_bitmap_empty","reason"
        ]
    )

    # Stage36R proves the bitmap renderer itself for all ten characters.
    stage36=read_tsv(stage36_map)
    stage36_hash={r["char"]:r["bitmap_sha256"].lower() for r in stage36}
    if len(stage36_hash)!=10:
        raise RuntimeError(f"Stage36R hash rows={len(stage36_hash)}")

    font=ImageFont.truetype(str(FONT_PATH),FONT_SIZE)
    font_sha=sha256_file(FONT_PATH)

    render_checks=[]
    rendered=[]
    for r in final:
        ch=r["hangul"]
        block=render_glyph(ch,font)
        h=sha256_bytes(block)
        rendered.append({
            "char":ch,
            "glyph":int(r["glyph_index"]),
            "sjis":r["donor_sjis_hex"],
            "block":block,
            "hash":h,
        })
        if ch in stage36_hash:
            render_checks.append({
                "char":ch,
                "generated_sha256":h,
                "stage36r_sha256":stage36_hash[ch],
                "bitmap_match":"YES" if h==stage36_hash[ch] else "NO",
                "mapping_reassigned":"YES" if ch in EXPECTED_UNSAFE else "NO",
            })

    if len(render_checks)!=10 or any(r["bitmap_match"]!="YES" for r in render_checks):
        raise RuntimeError(f"Stage36R bitmap reproduction failure: {render_checks}")

    # Build patched BOOT from ORIGINAL BOOT, never from SUB12.
    original=original_boot.read_bytes()
    patched=bytearray(original)
    manifest=[]
    by_char={e["char"]:e for e in rendered}

    for r in final:
        ch=r["hangul"]
        g=int(r["glyph_index"])
        off=FONT_FILE_OFFSET+g*BYTES_PER_GLYPH
        old=bytes(patched[off:off+BYTES_PER_GLYPH])
        new=by_char[ch]["block"]
        if len(old)!=BYTES_PER_GLYPH:
            raise RuntimeError(f"short original glyph block {g}")
        patched[off:off+BYTES_PER_GLYPH]=new
        manifest.append({
            "hangul":ch,
            "donor_sjis_hex":r["donor_sjis_hex"],
            "glyph_index":g,
            "font_file_offset":f"0x{off:X}",
            "strict_safe":"1",
            "old_bitmap_sha256":sha256_bytes(old),
            "new_bitmap_sha256":sha256_bytes(new),
            "sub16_reassigned":"YES" if ch in EXPECTED_UNSAFE else "NO",
        })

    patched_bytes=bytes(patched)
    final_glyphs=[int(r["glyph_index"]) for r in final]
    verify_only_target_ranges(original,patched_bytes,final_glyphs)

    # Post-write block verification.
    for r in manifest:
        off=int(r["font_file_offset"],16)
        if sha256_bytes(patched_bytes[off:off+BYTES_PER_GLYPH])!=r["new_bitmap_sha256"]:
            raise RuntimeError(f"post-patch verification failed: {r['hangul']}")

    patched_boot=out/"BOOT_sub16_collision_free_hangul.bin"
    patched_boot.write_bytes(patched_bytes)

    write_tsv(
        out/"sub16_glyph_manifest.tsv",
        manifest,
        [
            "hangul","donor_sjis_hex","glyph_index","font_file_offset",
            "strict_safe","old_bitmap_sha256","new_bitmap_sha256","sub16_reassigned"
        ]
    )
    write_tsv(
        out/"sub16_stage36r_bitmap_verification.tsv",
        render_checks,
        [
            "char","generated_sha256","stage36r_sha256",
            "bitmap_match","mapping_reassigned"
        ]
    )

    make_preview(rendered,out/"sub16_all_694_preview.png",cols=28,scale=4)

    final_strict_used=len(final)
    unused_after=len(strict)-final_strict_used
    if unused_after!=98:
        raise RuntimeError(f"unexpected remaining STRICT capacity: {unused_after}")

    mapping_sha=sha256_file(local_map)
    if mapping_sha!=sha256_file(shared_map):
        raise RuntimeError("local/shared mapping SHA mismatch")

    boot_sha=sha256_file(patched_boot)

    report={
        "stage":"SUB16",
        "input_sub15_mapping_sha256":EXPECTED_SUB15_SHA256,
        "final_mapping_rows":len(final),
        "final_mapping_sha256":mapping_sha,
        "strict_slots_total":len(strict),
        "final_strict_mappings":len(final),
        "unsafe_mappings_remaining":0,
        "reassigned_chars":sorted(EXPECTED_UNSAFE),
        "reassigned_count":len(EXPECTED_UNSAFE),
        "preserved_mapping_rows":len(final)-len(EXPECTED_UNSAFE),
        "unused_strict_slots":unused_after,
        "runtime_self_check_failures":0,
        "special_region_allocations":0,
        "stage36r_bitmap_hash_matches":10,
        "original_boot_sha256":sha256_file(original_boot),
        "patched_boot_sha256":boot_sha,
        "off_target_byte_changes":0,
        "font_path":str(FONT_PATH),
        "font_sha256":font_sha,
    }
    (out/"sub16_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB16 - Collision-Free Runtime Mapping + BOOT",
        "",
        f"FinalMappingRows={len(final)}",
        f"StrictSlotsTotal={len(strict)}",
        f"FinalStrictMappings={len(final)}",
        "UnsafeMappingsRemaining=0",
        f"ReassignedCount={len(EXPECTED_UNSAFE)}",
        "ReassignedChars=한,글,스,나,마",
        f"PreservedMappingRows={len(final)-len(EXPECTED_UNSAFE)}",
        f"UnusedStrictSlots={unused_after}",
        "RuntimeSelfCheckFailures=0",
        "SpecialRegionAllocations=0",
        "Stage36RBitmapHashMatch=10/10",
        "OffTargetByteChanges=0",
        f"FinalMappingSHA256={mapping_sha}",
        f"PatchedBOOTSHA256={boot_sha}",
        "",
        "Only five unsafe Stage36R donor MAPPINGS were moved.",
        "Their Hangul bitmap renderer remains byte-identical to Stage36R.",
        "",
        f"SharedMapping={shared_map}",
        f"PatchedBOOT={patched_boot}",
        "",
        "No ISO was modified by SUB16.",
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
