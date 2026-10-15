#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,math,re,shutil,struct,sys,traceback
import ctypes
from ctypes import wintypes

SECTOR=2048
SOURCE_REL=Path("Naruto_KR_MOV06E_SUB51P_FIX13_FullAtlas.iso")
OUT_REL=Path(r"analysis\sub\sub52d2_fix2_static_text_apply")
FINAL_NAME="Naruto_KR_MOV06E_SUB52D2_FIX2_StaticText.iso"

FONT_SIZE=16
FONT_FACE="Malgun Gothic"
CANVAS_W=18
CANVAS_H=18
DRAW_X=1
DRAW_Y=-4
GLYPH_SIZE=162
FONT_FILE_OFFSET=0x39CD04

ACTIVE={"TRANSLATED_CHATGPT","TRANSLATED_EXISTING"}
TOKEN_RE=re.compile(r"<[^>]+>|%[-+0-9.#]*[sdif]")
JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError(f"Cannot import {path}")
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("Bad ISO")
    r=p[156:190]
    return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR);data=f.read(size)
    out=[];pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//SECTOR)+1)*SECTOR;continue
        r=data[pos:pos+ln]
        if len(r)<34:break
        nb=r[33:33+r[32]]
        name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
        out.append(dict(name=name,lba=int.from_bytes(r[2:6],"little"),
                        size=int.from_bytes(r[10:14],"little"),is_dir=bool(r[25]&2)))
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso);cur=dict(lba=lba,size=size,is_dir=True)
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"])
                  if e["name"].casefold()==part.casefold()),None)
        if not hit: raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath);Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b:raise RuntimeError("ISO EOF")
            fo.write(b);rem-=len(b)

def segsha(iso,ipath):
    e=findiso(iso,ipath);h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=f.read(min(rem,1024*1024))
            if not b:raise RuntimeError("ISO EOF")
            h.update(b);rem-=len(b)
    return e["size"],h.hexdigest()

def walk_pmfs(iso):
    out=[]
    def walk(path):
        e=findiso(iso,path) if path else None
        lba,size=(iso_root(iso) if not path else (e["lba"],e["size"]))
        for q in dirents(iso,lba,size):
            if q["name"] in (".",".."):continue
            p=(path+"/"+q["name"]).strip("/")
            if q["is_dir"]:walk(p)
            elif p.lower().endswith(".pmf"):out.append(p)
    walk("");return sorted(out)

def read_tsv(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def load_authoritative_mapping(root):
    candidates=[
        root/r"analysis\sub\sub51d_full_text_apply\combined_hangul_mapping_sub51d.tsv",
        root/r"analysis\shared\event_font_hangul_mapping.tsv",
    ]
    rows=[]
    # Prefer SUB51D combined map because the source ISO descends from that build.
    if candidates[0].exists():
        rr=read_tsv(candidates[0])
        for r in rr:
            rows.append(dict(
                hangul=r["hangul"],
                donor_sjis_hex=r["donor_sjis_hex"].replace(" ","").upper(),
                glyph_index=int(r["glyph_index"]),
                source=str(candidates[0])
            ))
        return rows
    # Fallback: merge Stage35 + tutorial additions.
    for p in [
        root/r"analysis\shared\event_font_hangul_mapping.tsv",
        root/r"analysis\sub\sub40_tutorial\new_glyph_mapping.tsv",
    ]:
        if not p.exists():continue
        for r in read_tsv(p):
            ch=r.get("hangul") or r.get("char")
            code=(r.get("donor_sjis_hex") or r.get("sjis") or "").replace(" ","").upper()
            gi=r.get("glyph_index") or r.get("glyph")
            if ch and code and gi not in (None,""):
                rows.append(dict(hangul=ch,donor_sjis_hex=code,glyph_index=int(gi),source=str(p)))
    if not rows:raise RuntimeError("No authoritative Hangul mapping found")
    # dedupe exact chars, reject conflicts
    by={}
    for r in rows:
        if r["hangul"] in by:
            if (by[r["hangul"]]["donor_sjis_hex"],by[r["hangul"]]["glyph_index"]) != (r["donor_sjis_hex"],r["glyph_index"]):
                raise RuntimeError("Mapping conflict: "+r["hangul"])
            continue
        by[r["hangul"]]=r
    return list(by.values())

def find_slot_inventory(root):
    candidates=[
        root/r"analysis\stage35r\stage35r_slot_inventory.tsv",
        root/r"analysis\stage35r_slot_inventory.tsv",
    ]
    for p in candidates:
        if p.exists():return p
    hits=list((root/"analysis").rglob("stage35r_slot_inventory.tsv"))
    if hits:return hits[0]
    raise RuntimeError("stage35r_slot_inventory.tsv not found")

def render_glyph(ch,font_unused=None):
    """Render one 18x18 grayscale glyph with Windows GDI, no Pillow dependency."""
    if sys.platform != "win32":
        raise RuntimeError("SUB52D2 FIX1 GDI glyph renderer requires Windows")

    gdi32=ctypes.WinDLL("gdi32",use_last_error=True)
    user32=ctypes.WinDLL("user32",use_last_error=True)

    BI_RGB=0
    DIB_RGB_COLORS=0
    TRANSPARENT=1
    ANTIALIASED_QUALITY=4
    FW_BOLD=700
    DEFAULT_CHARSET=1
    OUT_TT_PRECIS=4
    CLIP_DEFAULT_PRECIS=0
    DEFAULT_PITCH=0
    FF_DONTCARE=0
    BLACKNESS=0x00000042

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_=[
            ("biSize",wintypes.DWORD),
            ("biWidth",wintypes.LONG),
            ("biHeight",wintypes.LONG),
            ("biPlanes",wintypes.WORD),
            ("biBitCount",wintypes.WORD),
            ("biCompression",wintypes.DWORD),
            ("biSizeImage",wintypes.DWORD),
            ("biXPelsPerMeter",wintypes.LONG),
            ("biYPelsPerMeter",wintypes.LONG),
            ("biClrUsed",wintypes.DWORD),
            ("biClrImportant",wintypes.DWORD),
        ]
    class BITMAPINFO(ctypes.Structure):
        _fields_=[("bmiHeader",BITMAPINFOHEADER),("bmiColors",wintypes.DWORD*3)]

    gdi32.CreateCompatibleDC.argtypes=[wintypes.HDC]
    gdi32.CreateCompatibleDC.restype=wintypes.HDC
    gdi32.CreateDIBSection.argtypes=[wintypes.HDC,ctypes.POINTER(BITMAPINFO),wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_void_p),wintypes.HANDLE,wintypes.DWORD]
    gdi32.CreateDIBSection.restype=wintypes.HBITMAP
    gdi32.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ]
    gdi32.SelectObject.restype=wintypes.HGDIOBJ
    gdi32.CreateFontW.argtypes=[
        ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,
        wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,
        wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.LPCWSTR
    ]
    gdi32.CreateFontW.restype=wintypes.HFONT
    gdi32.SetBkMode.argtypes=[wintypes.HDC,ctypes.c_int]
    gdi32.SetBkMode.restype=ctypes.c_int
    gdi32.SetTextColor.argtypes=[wintypes.HDC,wintypes.COLORREF]
    gdi32.SetTextColor.restype=wintypes.COLORREF
    gdi32.TextOutW.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int,wintypes.LPCWSTR,ctypes.c_int]
    gdi32.TextOutW.restype=wintypes.BOOL
    gdi32.PatBlt.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.DWORD]
    gdi32.PatBlt.restype=wintypes.BOOL
    gdi32.DeleteObject.argtypes=[wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype=wintypes.BOOL
    gdi32.DeleteDC.argtypes=[wintypes.HDC]
    gdi32.DeleteDC.restype=wintypes.BOOL

    bmi=BITMAPINFO()
    bmi.bmiHeader.biSize=ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth=CANVAS_W
    bmi.bmiHeader.biHeight=-CANVAS_H  # top-down
    bmi.bmiHeader.biPlanes=1
    bmi.bmiHeader.biBitCount=32
    bmi.bmiHeader.biCompression=BI_RGB
    bmi.bmiHeader.biSizeImage=CANVAS_W*CANVAS_H*4

    hdc=gdi32.CreateCompatibleDC(None)
    if not hdc:
        raise ctypes.WinError(ctypes.get_last_error())
    bits=ctypes.c_void_p()
    hbmp=gdi32.CreateDIBSection(hdc,ctypes.byref(bmi),DIB_RGB_COLORS,ctypes.byref(bits),None,0)
    if not hbmp:
        gdi32.DeleteDC(hdc)
        raise ctypes.WinError(ctypes.get_last_error())

    oldbmp=gdi32.SelectObject(hdc,hbmp)
    # GDI uses logical height. Negative requests character height rather than cell height.
    hfont=gdi32.CreateFontW(
        -FONT_SIZE,0,0,0,FW_BOLD,
        0,0,0,DEFAULT_CHARSET,
        OUT_TT_PRECIS,CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY,DEFAULT_PITCH|FF_DONTCARE,FONT_FACE
    )
    if not hfont:
        gdi32.SelectObject(hdc,oldbmp)
        gdi32.DeleteObject(hbmp);gdi32.DeleteDC(hdc)
        raise ctypes.WinError(ctypes.get_last_error())
    oldfont=gdi32.SelectObject(hdc,hfont)

    try:
        if not gdi32.PatBlt(hdc,0,0,CANVAS_W,CANVAS_H,BLACKNESS):
            raise ctypes.WinError(ctypes.get_last_error())
        gdi32.SetBkMode(hdc,TRANSPARENT)
        gdi32.SetTextColor(hdc,0x00FFFFFF)
        if not gdi32.TextOutW(hdc,DRAW_X,DRAW_Y,ch,1):
            raise ctypes.WinError(ctypes.get_last_error())

        raw=ctypes.string_at(bits,CANVAS_W*CANVAS_H*4)
        vals=[]
        # 32bpp DIB is BGRA. GDI antialiasing can vary slightly by channel,
        # so use the brightest channel as grayscale coverage.
        for i in range(0,len(raw),4):
            b,g,r,a=raw[i:i+4]
            gray=max(r,g,b)
            vals.append(min(15,(gray+8)//17))

        out=bytearray()
        for i in range(0,len(vals),2):
            out.append(vals[i] | (vals[i+1]<<4))
        if len(out)!=GLYPH_SIZE or not any(out):
            raise RuntimeError("Bad/empty GDI glyph render: "+ch)
        return bytes(out), None
    finally:
        gdi32.SelectObject(hdc,oldfont)
        gdi32.SelectObject(hdc,oldbmp)
        gdi32.DeleteObject(hfont)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)

def make_preview(entries,path):
    # Preview is optional and intentionally omitted in FIX1 to keep the build
    # completely dependency-free. Glyph SHA256 values remain in the TSV.
    return

def encode_text(s,cmap):
    out=bytearray()
    for ch in s:
        if ch in cmap:
            out.extend(bytes.fromhex(cmap[ch]));continue
        if ch=="·":
            out.extend(b"/");continue
        try:out.extend(ch.encode("cp932"))
        except UnicodeEncodeError:
            raise RuntimeError(f"Cannot encode U+{ord(ch):04X} {ch!r} in {s!r}")
    return bytes(out)

def decode_primary(dat_path,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:raise RuntimeError("Primary resource missing: "+name)
    with Path(dat_path).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def patch_table(original,rows,cmap,resource):
    """
    Patch records by their validated absolute byte offsets in the decoded TBL.
    SUB52D1 proved that these offsets point to the beginning of raw_record
    (usually the '=' inside a larger config line), NOT necessarily to the
    beginning of a newline-delimited line.
    """
    items=sorted(rows,key=lambda r:int(r["offset"]))
    offsets=[int(r["offset"]) for r in items]
    if len(offsets)!=len(set(offsets)):
        raise RuntimeError(resource+": duplicate offsets")

    out=bytearray()
    cursor=0
    log=[]

    for idx,r in enumerate(items):
        off=int(r["offset"])
        raw=r["raw_record"]
        src=r["source_japanese"]
        expected=raw.encode("cp932")

        if off < cursor:
            raise RuntimeError(
                f"{resource}@{off:#x}: overlapping patch; cursor={cursor:#x}"
            )
        actual=original[off:off+len(expected)]
        if actual!=expected:
            raise RuntimeError(
                f"{resource}@{off:#x} exact mismatch\n"
                f"expected={expected[:180]!r}\nactual={actual[:180]!r}"
            )

        # The validation worklist is defined as raw_record = prefix + source.
        # In practice prefix is normally '='. Preserve it exactly.
        if src and raw.endswith(src):
            prefix_text=raw[:-len(src)]
        else:
            eq=raw.find("=")
            if eq < 0:
                raise RuntimeError(f"{resource}@{off:#x}: cannot derive record prefix")
            prefix_text=raw[:eq+1]

        # Preserve the record's original line terminator, if any.
        end=off+len(expected)
        if original[end:end+2]==b"\r\n":
            eol=b"\r\n"; after=end+2
        elif original[end:end+1]==b"\n":
            eol=b"\n"; after=end+1
        elif original[end:end+1]==b"\r":
            eol=b"\r"; after=end+1
        else:
            eol=b""; after=end

        # Copy untouched bytes from the previous source position to this exact
        # record offset. This includes any key/config bytes before '='.
        out.extend(original[cursor:off])

        prefix=prefix_text.encode("cp932")
        enc=encode_text(r["korean"],cmap)
        replacement=prefix+enc
        out.extend(replacement)
        out.extend(eol)

        log.append(dict(
            entry=resource,offset=off,source=src,korean=r["korean"],
            old_bytes=len(expected),new_bytes=len(replacement),
            source_sha256=hashlib.sha256(expected).hexdigest(),
            replacement_sha256=hashlib.sha256(replacement).hexdigest(),
            status="PATCHED"
        ))
        cursor=after

    out.extend(original[cursor:])

    if len(log)!=len(items):
        raise RuntimeError(f"{resource}: patched {len(log)}/{len(items)} rows")
    return bytes(out),log

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    ap.add_argument("--translations",required=True)
    a=ap.parse_args()
    root=Path(a.root)
    source=root/SOURCE_REL
    out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    work=out/"_work"
    if work.exists():shutil.rmtree(work)
    work.mkdir()

    if not source.exists():raise RuntimeError("FIX13 source ISO missing: "+str(source))
    p14=root/r"analysis\stage14\naruto_patcher.py"
    p15=root/r"analysis\stage15\stage15_iso_patcher.py"
    if not p14.exists():raise RuntimeError("Missing "+str(p14))
    if not p15.exists():raise RuntimeError("Missing "+str(p15))

    trans=read_tsv(a.translations)
    active=[r for r in trans if r.get("status") in ACTIVE]
    if len(active)!=608:raise RuntimeError(f"Expected 608 active rows, got {len(active)}")
    for r in active:
        if not r.get("korean"):raise RuntimeError("Blank translation")
        if JP_RE.search(r["korean"]):raise RuntimeError("Japanese remains: "+r["korean"])
        if TOKEN_RE.findall(r["source_japanese"])!=TOKEN_RE.findall(r["korean"]):
            raise RuntimeError("Control token mismatch: "+r["source_japanese"])

    print("=== SUB52D2 FIX2 STATIC TEXT APPLY ===",flush=True)
    print("Source:",source,flush=True)
    print("SHA256:",sha256_file(source),flush=True)
    print("[1/9] Load current mapping / allocate missing Hangul",flush=True)

    existing=load_authoritative_mapping(root)
    cmap={r["hangul"]:r["donor_sjis_hex"] for r in existing}
    used_codes={r["donor_sjis_hex"] for r in existing}
    used_glyphs={r["glyph_index"] for r in existing}
    required=sorted({ch for r in active for ch in r["korean"] if "\uac00"<=ch<="\ud7a3"})
    missing=[ch for ch in required if ch not in cmap]

    inv_path=find_slot_inventory(root)
    inv=read_tsv(inv_path)
    pool=[]
    for r in inv:
        if r.get("strict_safe")!="1" or r.get("special_intercept")!="0":continue
        code=(r.get("standard_sjis") or "").replace(" ","").upper()
        try:gi=int(r["glyph"])
        except:continue
        if not code or code in used_codes or gi in used_glyphs:continue
        pool.append(r)
    pool.sort(key=lambda r:(0 if r.get("bitmap_empty")=="1" else 1,-int(r["glyph"])))
    if len(pool)<len(missing):
        raise RuntimeError(f"Not enough strict-safe slots: need {len(missing)}, have {len(pool)}")

    font=None
    extension=[];rendered=[]
    for ch,slot in zip(missing,pool[:len(missing)]):
        code=slot["standard_sjis"].replace(" ","").upper()
        gi=int(slot["glyph"])
        block,im=render_glyph(ch,font)
        extension.append(dict(hangul=ch,unicode=f"U+{ord(ch):04X}",
                              donor_sjis_hex=code,glyph_index=gi,
                              font_file_offset=f"0x{FONT_FILE_OFFSET+gi*GLYPH_SIZE:X}",
                              strict_safe_before=slot["strict_safe"],
                              bitmap_empty_before=slot.get("bitmap_empty",""),
                              bitmap_sha256=hashlib.sha256(block).hexdigest()))
        cmap[ch]=code;used_codes.add(code);used_glyphs.add(gi)
        rendered.append(dict(char=ch,glyph=gi,block=block,image=im))
    write_tsv(out/"new_glyph_mapping_sub52d2.tsv",extension,
              ["hangul","unicode","donor_sjis_hex","glyph_index","font_file_offset",
               "strict_safe_before","bitmap_empty_before","bitmap_sha256"])
    combined=[dict(hangul=r["hangul"],donor_sjis_hex=r["donor_sjis_hex"],
                   glyph_index=r["glyph_index"],source=r["source"]) for r in existing]
    combined += [dict(hangul=r["hangul"],donor_sjis_hex=r["donor_sjis_hex"],
                      glyph_index=r["glyph_index"],source="SUB52D2_FIX2") for r in extension]
    write_tsv(out/"combined_hangul_mapping_sub52d2.tsv",combined,
              ["hangul","donor_sjis_hex","glyph_index","source"])
    make_preview(rendered,out/"sub52d2_new_glyph_preview.png")
    print(f"  existing={len(existing)} required={len(required)} new={len(extension)} combined={len(combined)}",flush=True)

    print("[2/9] Extract DAT/IDX/BOOT from FIX13",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)

    print("[3/9] Patch new font glyphs",flush=True)
    boot_bytes=bytearray(boot.read_bytes())
    for e in rendered:
        off=FONT_FILE_OFFSET+e["glyph"]*GLYPH_SIZE
        if off<0 or off+GLYPH_SIZE>len(boot_bytes):raise RuntimeError("Glyph outside BOOT")
        boot_bytes[off:off+GLYPH_SIZE]=e["block"]
    boot.write_bytes(bytes(boot_bytes))

    print("[4/9] Patch 5 static TBL resources",flush=True)
    m=mod("sub52d2_p14",p14)
    ei=m.parse_pidx(m.read_embedded_index(dat),"sub52d2-src")
    by_resource={}
    for r in active:by_resource.setdefault(r["entry"],[]).append(r)

    replacements={};patch_rows=[]
    for resource,rr in sorted(by_resource.items()):
        olddec=decode_primary(dat,ei,resource,m)
        newdec,logs=patch_table(olddec,rr,cmap,resource)
        if olddec==newdec:raise RuntimeError("No change in "+resource)
        replacements[resource]=dict(original_sha256=m.sha256(olddec),new_decoded=newdec)
        patch_rows.extend(logs)
        print(f"  {resource}: {len(rr)} rows",flush=True)
    write_tsv(out/"sub52d2_tbl_patch.tsv",patch_rows,
              ["entry","offset","source","korean","old_bytes","new_bytes","source_sha256","replacement_sha256","status"])

    print("[5/9] Rebuild DAT primary + FSTS duplicates",flush=True)
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub52d2-emb");xi=m.parse_pidx(xb,"sub52d2-ext")
    primaryrows=[]
    with dat.open("ab") as f:
        for name,repl in replacements.items():
            new=repl["new_decoded"];encoded=m.encode_3_0(new)
            if m.decode_3x(encoded)!=new:raise RuntimeError("Encode self-check failed "+name)
            off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["primary"] if q["name"]==name)
                struct.pack_into("<III",blob,q["record_off"]+12,off,len(new),len(encoded))
            primaryrows.append(dict(resource=name,decoded_size=len(new),stored_size=len(encoded),
                                    new_offset=off,status="REPLACED"))
    fstsrows=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]);bundle=f.read(r["file_size"])
            rebuilt,changes=m.rebuild_fsts(bundle,r["name"],replacements)
            if not changes:continue
            f.seek(0,2);off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,off,len(rebuilt))
            members=[]
            for x in changes:
                if isinstance(x,dict):members.append(str(x.get("name") or x.get("member") or x))
                else:members.append(str(x))
            fstsrows.append(dict(bundle=r["name"],members=";".join(members)))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub52d2_primary_rebuild.tsv",primaryrows,
              ["resource","decoded_size","stored_size","new_offset","status"])
    write_tsv(out/"sub52d2_fsts_rebuild.tsv",fstsrows,["bundle","members"])

    print("[6/9] Verify rebuilt resources",flush=True)
    fin=m.parse_pidx(m.read_embedded_index(dat),"sub52d2-fin")
    for name,repl in replacements.items():
        got=decode_primary(dat,fin,name,m)
        if got!=repl["new_decoded"]:raise RuntimeError("Final decoded mismatch "+name)

    print("[7/9] Build ISO by appending patched core files",flush=True)
    iso=mod("sub52d2_p15",p15)
    final=out/FINAL_NAME
    if final.exists():final.unlink()
    shutil.copyfile(source,final)
    with final.open("r+b") as f:
        vds=iso.read_volume_descriptors(f)
        for ip,host in (
            ("PSP_GAME/USRDIR/naruto.dat",dat),
            ("PSP_GAME/USRDIR/naruto.idx",idx),
            ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
            ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
        ):
            recs=[iso.find_path(f,vd,ip.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext=iso.append_file_sector_aligned(f,host,host.name)
            for q in recs:
                if q:iso.patch_directory_record(f,q["record_offset"],ext["lba"],ext["size"])
        f.seek(0,2);iso.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print("[8/9] Static verification",flush=True)
    core=[]
    for ip,host in (
        ("PSP_GAME/USRDIR/naruto.dat",dat),
        ("PSP_GAME/USRDIR/naruto.idx",idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
        ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
    ):
        sz,hs=segsha(final,ip);ok=hs==sha256_file(host)
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verification failed "+ip)
    write_tsv(out/"sub52d2_core_verification.tsv",core,["iso_path","size","sha256","match"])

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub52d2_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub52d2_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub52d2_sha256","match"])

    for r in active:encode_text(r["korean"],cmap)

    print("[9/9] Finalize",flush=True)
    report=dict(
        stage="SUB52D2_FIX2_STATIC_TEXT_APPLY",
        source_iso=str(source),
        source_sha256=sha256_file(source),
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        translated_rows=len(active),
        tbl_resources=len(replacements),
        existing_mapping_chars=len(existing),
        new_mapping_chars=len(extension),
        combined_mapping_chars=len(combined),
        pmfs_preserved=len(movies),
        static_qa="PASS",
        runtime_qa="DEFERRED_UNTIL_IMAGE_BATCH_COMPLETE",
    )
    (out/"SUB52D2_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB52D2 FIX2 - Static Text Apply\n\n"
        +"\n".join(f"{k}={v}" for k,v in report.items())
        +"\n",encoding="utf-8-sig")
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
