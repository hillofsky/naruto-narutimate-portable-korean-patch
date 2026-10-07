#!/usr/bin/env python3
# Naruto PSP SUB12 - Build all 694 Hangul glyph bitmaps and patched BOOT
#
# Recovered Stage34 renderer:
#   font: C:\Windows\Fonts\malgunbd.ttf
#   size: 16
#   canvas: 18x18 grayscale
#   draw: (1, -4), fill=255
#   quantize: value // 17 -> 0..15
#   pack: pixel0 low nibble | pixel1 high nibble
#   162 bytes / glyph
#
# Safety:
# - Original KR BOOT SHA256 must match Stage34 source hash.
# - SUB10 frozen mapping must be 694 rows and match its recorded SHA256.
# - Stage36R fixed 10 rendered bitmap SHA256 values must match 10/10.
# - Only mapped glyph blocks may change.
# - No ISO modification in SUB12.

from __future__ import annotations
import argparse, csv, hashlib, json, math, shutil, sys
from pathlib import Path
from collections import Counter

from PIL import Image, ImageDraw, ImageFont
import PIL

FONT_PATH = Path(r"C:\Windows\Fonts\malgunbd.ttf")
FONT_SIZE = 16
CANVAS_W = 18
CANVAS_H = 18
DRAW_X = 1
DRAW_Y = -4
BYTES_PER_GLYPH = 162
FONT_FILE_OFFSET = 0x39CD04
MAX_STANDARD_GLYPH = 3428
EXPECTED_MAPPING_ROWS = 694

EXPECTED_ORIGINAL_BOOT_SHA256 = (
    "1083ba42327f187cd81fe6b31c9975857d271373d4a907d1b7f35d38bc7fc4c8"
)
EXPECTED_SUB10_MAPPING_SHA256 = (
    "9c73cdb33eb812a813c78cfb5efcad80838322ab5a4da90c91eb3db6aaca056c"
)

FIXED_CHARS = "한글테스트가나다라마"

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def read_tsv(path: Path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path: Path, rows, fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def render_glyph(character: str, font):
    image=Image.new("L",(CANVAS_W,CANVAS_H),0)
    draw=ImageDraw.Draw(image)
    draw.text((DRAW_X,DRAW_Y),character,font=font,fill=255)

    raw=list(image.getdata())
    values=[v//17 for v in raw]
    if len(values)!=CANVAS_W*CANVAS_H:
        raise RuntimeError(f"unexpected pixel count for {character}: {len(values)}")

    packed=bytearray()
    for i in range(0,len(values),2):
        packed.append(values[i] | (values[i+1] << 4))

    if len(packed)!=BYTES_PER_GLYPH:
        raise RuntimeError(
            f"packed glyph size mismatch for {character}: {len(packed)}"
        )

    return bytes(packed), image

def decode_glyph(block: bytes):
    if len(block)!=BYTES_PER_GLYPH:
        raise ValueError("bad glyph block size")
    vals=[]
    for b in block:
        vals.append((b & 0x0F)*17)
        vals.append(((b >> 4) & 0x0F)*17)
    img=Image.new("L",(CANVAS_W,CANVAS_H),0)
    img.putdata(vals)
    return img

def verify_pack_roundtrip(block: bytes):
    img=decode_glyph(block)
    vals=[v//17 for v in img.getdata()]
    repacked=bytearray()
    for i in range(0,len(vals),2):
        repacked.append(vals[i] | (vals[i+1] << 4))
    return bytes(repacked)==block

def make_preview(entries, output: Path, scale=4, cols=28):
    rows=math.ceil(len(entries)/cols)
    sheet=Image.new("L",(cols*CANVAS_W,rows*CANVAS_H),0)

    for i,e in enumerate(entries):
        x=(i%cols)*CANVAS_W
        y=(i//cols)*CANVAS_H
        sheet.paste(decode_glyph(e["bitmap"]),(x,y))

    sheet=sheet.resize(
        (sheet.width*scale,sheet.height*scale),
        Image.Resampling.NEAREST,
    )
    sheet.save(output)

def verify_only_target_ranges(original: bytes, patched: bytes, glyphs):
    if len(original)!=len(patched):
        raise RuntimeError("BOOT length changed")

    intervals=sorted(
        (
            FONT_FILE_OFFSET + int(g)*BYTES_PER_GLYPH,
            FONT_FILE_OFFSET + (int(g)+1)*BYTES_PER_GLYPH,
        )
        for g in glyphs
    )

    # Make sure intervals don't overlap and are in file.
    last=0
    for start,end in intervals:
        if start<last:
            raise RuntimeError("target glyph intervals overlap/out of order")
        if start<0 or end>len(original):
            raise RuntimeError(f"glyph patch range outside BOOT: 0x{start:X}-0x{end:X}")
        last=end

    # Everything outside the approved blocks must remain byte-identical.
    pos=0
    for start,end in intervals:
        if original[pos:start] != patched[pos:start]:
            raise RuntimeError(
                f"off-target BOOT modification detected before 0x{start:X}"
            )
        pos=end
    if original[pos:] != patched[pos:]:
        raise RuntimeError("off-target BOOT modification detected after last glyph")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    root=Path(args.root)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    original_boot=root/"kr_extracted"/"PSP_GAME"/"SYSDIR"/"BOOT.BIN"
    mapping_path=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    stage36_map=root/"analysis"/"stage36r"/"stage36r_mapping.tsv"

    for p in (original_boot,mapping_path,stage36_map,FONT_PATH):
        if not p.exists():
            raise RuntimeError(f"required file missing: {p}")

    boot_sha=sha256_file(original_boot)
    if boot_sha.lower()!=EXPECTED_ORIGINAL_BOOT_SHA256:
        raise RuntimeError(
            "Original KR BOOT SHA256 mismatch.\n"
            f" expected={EXPECTED_ORIGINAL_BOOT_SHA256}\n"
            f" actual  ={boot_sha}"
        )

    mapping_sha=sha256_file(mapping_path)
    if mapping_sha.lower()!=EXPECTED_SUB10_MAPPING_SHA256:
        raise RuntimeError(
            "SUB10 frozen mapping SHA256 mismatch.\n"
            f" expected={EXPECTED_SUB10_MAPPING_SHA256}\n"
            f" actual  ={mapping_sha}"
        )

    mapping=read_tsv(mapping_path)
    if len(mapping)!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError(
            f"expected {EXPECTED_MAPPING_ROWS} mapping rows, got {len(mapping)}"
        )

    chars=[r["hangul"] for r in mapping]
    glyphs=[int(r["glyph_index"]) for r in mapping]
    codes=[r["donor_sjis_hex"].upper() for r in mapping]

    if len(set(chars))!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate Hangul in SUB10 mapping")
    if len(set(glyphs))!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate target glyph in SUB10 mapping")
    if len(set(codes))!=EXPECTED_MAPPING_ROWS:
        raise RuntimeError("duplicate SJIS donor in SUB10 mapping")
    if max(glyphs)>MAX_STANDARD_GLYPH:
        raise RuntimeError("special glyph region 3429+ appears in mapping")

    s36=read_tsv(stage36_map)
    fixed_hashes={r["char"]:r["bitmap_sha256"].lower() for r in s36}
    if set(fixed_hashes)!=set(FIXED_CHARS):
        raise RuntimeError(
            f"Stage36R fixed set mismatch: {sorted(fixed_hashes)}"
        )

    font=ImageFont.truetype(str(FONT_PATH),FONT_SIZE)
    font_sha=sha256_file(FONT_PATH)

    rendered=[]
    fixed_checks=[]

    for r in mapping:
        ch=r["hangul"]
        block,image=render_glyph(ch,font)

        if not verify_pack_roundtrip(block):
            raise RuntimeError(f"4bpp pack round-trip failed: {ch}")
        if not any(block):
            raise RuntimeError(f"rendered glyph is empty: {ch}")

        h=sha256_bytes(block)
        rendered.append({
            "char":ch,
            "glyph":int(r["glyph_index"]),
            "sjis":r["donor_sjis_hex"].upper(),
            "block":block,
            "image":image,
            "hash":h,
        })

        if ch in fixed_hashes:
            ok=(h==fixed_hashes[ch])
            fixed_checks.append({
                "char":ch,
                "generated_sha256":h,
                "stage36r_sha256":fixed_hashes[ch],
                "match":"YES" if ok else "NO",
            })

    if len(fixed_checks)!=10:
        raise RuntimeError(f"expected 10 fixed checks, got {len(fixed_checks)}")
    if any(r["match"]!="YES" for r in fixed_checks):
        bad=[r for r in fixed_checks if r["match"]!="YES"]
        raise RuntimeError(
            "Recovered Stage34 renderer does not reproduce Stage36R bitmaps: "
            + json.dumps(bad,ensure_ascii=False)
        )

    # Patch the original BOOT only in the 694 mapped glyph blocks.
    original=original_boot.read_bytes()
    patched=bytearray(original)

    manifest=[]
    original_blocks=bytearray()
    generated_blocks=bytearray()

    by_char={e["char"]:e for e in rendered}

    for r in mapping:
        ch=r["hangul"]
        e=by_char[ch]
        glyph=int(r["glyph_index"])
        off=FONT_FILE_OFFSET + glyph*BYTES_PER_GLYPH

        old=bytes(patched[off:off+BYTES_PER_GLYPH])
        new=e["block"]
        if len(old)!=BYTES_PER_GLYPH:
            raise RuntimeError(f"short donor block: {ch} glyph={glyph}")

        original_blocks.extend(old)
        generated_blocks.extend(new)
        patched[off:off+BYTES_PER_GLYPH]=new

        manifest.append({
            "hangul":ch,
            "unicode":f"U+{ord(ch):04X}",
            "donor_sjis_hex":r["donor_sjis_hex"].upper(),
            "glyph_index":glyph,
            "font_file_offset":f"0x{off:X}",
            "old_bitmap_sha256":sha256_bytes(old),
            "new_bitmap_sha256":sha256_bytes(new),
            "old_nonzero_bytes":sum(1 for b in old if b),
            "new_nonzero_bytes":sum(1 for b in new if b),
            "stage36r_fixed_verified":"YES" if ch in fixed_hashes else "NO",
        })

    patched_bytes=bytes(patched)
    verify_only_target_ranges(original,patched_bytes,glyphs)

    # Verify patched blocks exactly match generated data.
    for r in manifest:
        off=int(r["font_file_offset"],16)
        block=patched_bytes[off:off+BYTES_PER_GLYPH]
        if sha256_bytes(block)!=r["new_bitmap_sha256"]:
            raise RuntimeError(
                f"post-patch glyph verification failed: {r['hangul']}"
            )

    patched_boot=out/"BOOT_sub12_full_hangul.bin"
    patched_boot.write_bytes(patched_bytes)

    (out/"sub12_original_donor_blocks.bin").write_bytes(bytes(original_blocks))
    (out/"sub12_generated_glyph_blocks.bin").write_bytes(bytes(generated_blocks))

    write_tsv(
        out/"sub12_glyph_manifest.tsv",
        manifest,
        [
            "hangul","unicode","donor_sjis_hex","glyph_index","font_file_offset",
            "old_bitmap_sha256","new_bitmap_sha256",
            "old_nonzero_bytes","new_nonzero_bytes",
            "stage36r_fixed_verified",
        ]
    )
    write_tsv(
        out/"sub12_fixed10_hash_verification.tsv",
        fixed_checks,
        ["char","generated_sha256","stage36r_sha256","match"]
    )

    # Previews are built from the packed bytes after decoding, not directly from Pillow.
    make_preview(rendered,out/"sub12_all_694_preview.png",scale=4,cols=28)
    fixed_entries=[by_char[ch] for ch in FIXED_CHARS]
    make_preview(fixed_entries,out/"sub12_fixed10_preview.png",scale=8,cols=10)

    patched_sha=sha256_file(patched_boot)

    report={
        "stage":"SUB12",
        "renderer":{
            "font_path":str(FONT_PATH),
            "font_sha256":font_sha,
            "font_size":FONT_SIZE,
            "canvas":[CANVAS_W,CANVAS_H],
            "draw_xy":[DRAW_X,DRAW_Y],
            "fill":255,
            "quantize":"pixel // 17",
            "pack":"pixel0 low nibble | pixel1 high nibble",
            "bytes_per_glyph":BYTES_PER_GLYPH,
        },
        "mapping_rows":len(mapping),
        "fixed10_hash_matches":sum(1 for r in fixed_checks if r["match"]=="YES"),
        "original_boot_sha256":boot_sha,
        "patched_boot_sha256":patched_sha,
        "mapping_sha256":mapping_sha,
        "off_target_byte_changes":0,
        "font_file_offset":f"0x{FONT_FILE_OFFSET:X}",
        "max_target_glyph":max(glyphs),
        "special_region_allocations":sum(1 for g in glyphs if g>MAX_STANDARD_GLYPH),
    }
    (out/"sub12_build_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )

    summary=[
        "Naruto PSP SUB12 - Full 694 Hangul Glyph Build",
        "",
        f"MappingRows={len(mapping)}",
        f"Font={FONT_PATH}",
        f"FontSHA256={font_sha}",
        f"Renderer=malgunbd.ttf size16 canvas18x18 draw(1,-4)",
        "Quantize=pixel//17",
        "Pack=pixel0 low nibble | pixel1 high nibble",
        f"BytesPerGlyph={BYTES_PER_GLYPH}",
        f"Fixed10BitmapHashMatch={report['fixed10_hash_matches']}/10",
        f"OriginalBOOTSHA256={boot_sha}",
        f"PatchedBOOTSHA256={patched_sha}",
        f"MappingSHA256={mapping_sha}",
        "OffTargetByteChanges=0",
        f"MaxTargetGlyph={max(glyphs)}",
        "SpecialRegionAllocations=0",
        "",
        f"PatchedBOOT={patched_boot}",
        "",
        "No ISO was modified by SUB12.",
    ]
    (out/"SUMMARY.txt").write_text(
        "\n".join(summary)+"\n",
        encoding="utf-8-sig"
    )
    print("\n".join(summary))

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        sys.exit(1)
