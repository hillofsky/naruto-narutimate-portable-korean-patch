#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,math,re,shutil,struct,sys,traceback
from PIL import Image,ImageDraw,ImageFont

SECTOR=2048
SOURCE_SHA="5a750d02fc701c110106711dedfc3e19b34b32f1833ccbef811f3d55441f87b9"
SOURCE_REL=Path("analysis/sub/sub50_mugen_atlas_surgical_restore/Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub51d_full_text_apply")
FINAL_NAME="Naruto_KR_MOV06E_SUB51D_FullText.iso"

EXPECTED_TRANSLATION_SHA="b451ddf17bb6dac2d6bc5773772479a485dbadafae1d80cda6a8634da9f8da52"
EXPECTED_OCCURRENCE_SHA="9cc35f507b24654972a5da182412a905ccb382f08f37c1e3fe3a5e6ff32155b2"

FONT_PATH=Path(r"C:\Windows\Fonts\malgunbd.ttf")
FONT_SIZE=16
CANVAS_W=18
CANVAS_H=18
DRAW_X=1
DRAW_Y=-4
GLYPH_SIZE=162
FONT_FILE_OFFSET=0x39CD04

# <ruby...> is Japanese furigana markup; Korean translations intentionally remove it.
# Preserve actual runtime tags such as <RED>/<BLACK>/<br>/<KON>/<KOFF> and printf placeholders.
TOKEN_RE=re.compile(r"<(?!ruby)[^>]+>|%[-+0-9.#]*[sdif]")
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
            if not b: raise RuntimeError("EOF "+ipath)
            fo.write(b);rem-=len(b)

def segsha(iso,ipath):
    e=findiso(iso,ipath);h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=f.read(min(rem,1024*1024));h.update(b);rem-=len(b)
    return e["size"],h.hexdigest()

def walk_pmfs(iso,path="PSP_GAME/USRDIR"):
    out=[]
    def walk(p):
        d=findiso(iso,p)
        for e in dirents(iso,d["lba"],d["size"]):
            if e["name"] in (".",".."):continue
            q=p+"/"+e["name"]
            if e["is_dir"]:walk(q)
            elif e["name"].lower().endswith(".pmf"):out.append(q)
    walk(path);return sorted(out)

def read_tsv(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def load_maps(root):
    files=[
        root/"analysis/shared/event_font_hangul_mapping.tsv",
        root/"analysis/sub/sub40_tutorial/new_glyph_mapping.tsv",
    ]
    entries=[];seen_ch=set();seen_code=set();seen_glyph=set()
    for p in files:
        if not p.exists():raise RuntimeError("Mapping missing: "+str(p))
        for r in read_tsv(p):
            ch=r.get("hangul") or r.get("char")
            code=(r.get("donor_sjis_hex") or r.get("sjis") or "").replace(" ","").upper()
            glyph=r.get("glyph_index") or r.get("glyph")
            if not ch or not code or glyph in (None,""):
                raise RuntimeError("Bad mapping row in "+str(p))
            gi=int(str(glyph))
            if ch in seen_ch:raise RuntimeError("Duplicate mapped Hangul: "+ch)
            if code in seen_code:raise RuntimeError("Duplicate mapped SJIS: "+code)
            if gi in seen_glyph:raise RuntimeError("Duplicate mapped glyph: "+str(gi))
            seen_ch.add(ch);seen_code.add(code);seen_glyph.add(gi)
            entries.append(dict(hangul=ch,donor_sjis_hex=code,glyph_index=gi,source=p.name))
    return entries

def render_glyph(ch,font):
    im=Image.new("L",(CANVAS_W,CANVAS_H),0)
    d=ImageDraw.Draw(im);d.text((DRAW_X,DRAW_Y),ch,font=font,fill=255)
    vals=[v//17 for v in im.getdata()]
    out=bytearray()
    for i in range(0,len(vals),2):out.append(vals[i] | (vals[i+1]<<4))
    if len(out)!=GLYPH_SIZE or not any(out):raise RuntimeError("Bad glyph render: "+ch)
    return bytes(out),im

def encode_text(s,cmap):
    out=bytearray()
    for ch in s:
        if ch in cmap:
            out.extend(bytes.fromhex(cmap[ch]));continue
        # U+00B7 occurs only as a separator in four translated UI strings.
        # Use ASCII slash so it cannot collide with a repurposed CP932 donor glyph.
        if ch=="·":
            out.extend(b"/");continue
        try:out.extend(ch.encode("cp932"))
        except UnicodeEncodeError:
            raise RuntimeError(f"Cannot encode character U+{ord(ch):04X} {ch!r} in: {s}")
    return bytes(out)

def decode_primary(dat_path,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:raise RuntimeError("Primary resource missing: "+name)
    with Path(dat_path).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def patch_text_resource(original, occs, trans_by_id, cmap, resource):
    by_off={}
    for o in occs:
        by_off.setdefault(int(o["offset"],16),[]).append(o)
    out=bytearray();pos=0;rows=[]
    for line in original.splitlines(keepends=True):
        start=pos;pos+=len(line)
        if start not in by_off:
            out.extend(line);continue
        if len(by_off[start])!=1:
            raise RuntimeError(f"{resource} offset {start:#x}: expected one occurrence")
        o=by_off[start][0]
        body=line;eol=b""
        if body.endswith(b"\r\n"):body,eol=body[:-2],b"\r\n"
        elif body.endswith(b"\n"):body,eol=body[:-1],b"\n"
        elif body.endswith(b"\r"):body,eol=body[:-1],b"\r"
        prefix=bytes.fromhex(o.get("prefix_hex",""))
        old=bytes.fromhex(o["source_raw_hex"])
        expected=prefix+b"="+old
        if body!=expected:
            raise RuntimeError(
                f"{resource} exact line mismatch at {start:#x}\n"
                f"expected={expected[:100]!r}\nactual={body[:100]!r}"
            )
        tr=trans_by_id[o["candidate_id"]]["korean"]
        enc=encode_text(tr,cmap)
        out.extend(prefix+b"="+enc+eol)
        rows.append(dict(candidate_id=o["candidate_id"],scope=resource,offset=hex(start),
                         source=trans_by_id[o["candidate_id"]]["source"],korean=tr,
                         old_bytes=len(old),new_bytes=len(enc),status="PATCHED"))
    patched_offsets={int(r["offset"],16) for r in rows}
    missing=set(by_off)-patched_offsets
    if missing:raise RuntimeError(f"{resource}: missing line offsets {sorted(missing)[:10]}")
    return bytes(out),rows

def make_preview(entries,path):
    if not entries:return
    cols=16;scale=5;rows=math.ceil(len(entries)/cols)
    sheet=Image.new("L",(cols*CANVAS_W,rows*CANVAS_H),0)
    for i,e in enumerate(entries):
        sheet.paste(e["image"],((i%cols)*CANVAS_W,(i//cols)*CANVAS_H))
    sheet.resize((sheet.width*scale,sheet.height*scale),Image.Resampling.NEAREST).save(path)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    ap.add_argument("--inventory",required=True)
    ap.add_argument("--translated",required=True)
    ap.add_argument("--occurrences",required=True)
    a=ap.parse_args()
    root=Path(a.root);source=root/SOURCE_REL;donor=root/DONOR_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    work=out/"_work"
    if work.exists():shutil.rmtree(work)
    work.mkdir()

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB50 authority ISO missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:
        raise RuntimeError("SUB36 compact donor ISO missing/SHA mismatch")
    if not FONT_PATH.exists():raise RuntimeError("Font missing: "+str(FONT_PATH))
    if sha256_file(a.translated)!=EXPECTED_TRANSLATION_SHA:
        raise RuntimeError("Bundled ChatGPT translation TSV SHA mismatch")
    if sha256_file(a.occurrences)!=EXPECTED_OCCURRENCE_SHA:
        raise RuntimeError("Bundled occurrence TSV SHA mismatch")

    trans=read_tsv(a.translated);occ=read_tsv(a.occurrences)
    trans_by_id={r["id"]:r for r in trans}
    active={k:v for k,v in trans_by_id.items() if v.get("review_status")=="TRANSLATED_CHATGPT"}
    if len(active)!=1140:raise RuntimeError(f"Expected 1140 ChatGPT translations, got {len(active)}")
    for r in active.values():
        if not r.get("korean"):raise RuntimeError("Blank translation: "+r["id"])
        if JP_RE.search(r["korean"]):raise RuntimeError("Japanese remains in translation: "+r["id"])
        if TOKEN_RE.findall(r["source"])!=TOKEN_RE.findall(r["korean"]):
            raise RuntimeError("Control token mismatch: "+r["id"])

    print("[1/10] Load current mappings and allocate all missing Hangul",flush=True)
    existing=load_maps(root)
    if len(existing)!=711:
        raise RuntimeError(f"Expected current mapping 711 chars (694+17), got {len(existing)}")
    cmap={r["hangul"]:r["donor_sjis_hex"] for r in existing}
    used_codes={r["donor_sjis_hex"] for r in existing};used_glyphs={r["glyph_index"] for r in existing}
    used_hangul=sorted({ch for r in active.values() for ch in r["korean"] if "\uac00"<=ch<="\ud7a3"})
    missing=[ch for ch in used_hangul if ch not in cmap]
    inv=read_tsv(Path(a.inventory))
    pool=[]
    for r in inv:
        if r.get("strict_safe")!="1" or r.get("special_intercept")!="0":continue
        code=(r.get("standard_sjis") or "").replace(" ","").upper()
        gi=int(r["glyph"])
        if code in used_codes or gi in used_glyphs:continue
        pool.append(r)
    pool.sort(key=lambda r:(0 if r.get("bitmap_empty")=="1" else 1,-int(r["glyph"])))
    if len(pool)<len(missing):
        raise RuntimeError(f"Not enough strict-safe slots: need {len(missing)}, have {len(pool)}")
    selected=pool[:len(missing)]

    extension=[]
    font=ImageFont.truetype(str(FONT_PATH),FONT_SIZE)
    rendered=[]
    for ch,slot in zip(missing,selected):
        code=slot["standard_sjis"].replace(" ","").upper()
        gi=int(slot["glyph"])
        block,im=render_glyph(ch,font)
        extension.append(dict(hangul=ch,unicode=f"U+{ord(ch):04X}",
                              donor_sjis_hex=code,glyph_index=gi,
                              font_file_offset=f"0x{FONT_FILE_OFFSET+gi*GLYPH_SIZE:X}",
                              strict_safe_before=slot["strict_safe"],
                              bitmap_empty_before=slot["bitmap_empty"],
                              bitmap_sha256=hashlib.sha256(block).hexdigest()))
        cmap[ch]=code;used_codes.add(code);used_glyphs.add(gi)
        rendered.append(dict(char=ch,glyph=gi,block=block,image=im))
    write_tsv(out/"new_glyph_mapping_sub51d.tsv",extension,
              ["hangul","unicode","donor_sjis_hex","glyph_index","font_file_offset",
               "strict_safe_before","bitmap_empty_before","bitmap_sha256"])
    combined=[dict(hangul=r["hangul"],donor_sjis_hex=r["donor_sjis_hex"],glyph_index=r["glyph_index"],
                   source=r["source"]) for r in existing]
    combined += [dict(hangul=r["hangul"],donor_sjis_hex=r["donor_sjis_hex"],
                      glyph_index=r["glyph_index"],source="SUB51D") for r in extension]
    write_tsv(out/"combined_hangul_mapping_sub51d.tsv",combined,
              ["hangul","donor_sjis_hex","glyph_index","source"])
    make_preview(rendered,out/"sub51d_new_glyph_preview.png")
    print(f"  existing={len(existing)} new={len(extension)} combined={len(combined)}",flush=True)

    print("[2/10] Extract exact SUB50 DAT/IDX/BOOT",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    original_boot=boot.read_bytes()

    print("[3/10] Patch new glyph bitmaps into SUB50 BOOT",flush=True)
    font_boot=bytearray(original_boot)
    for e in rendered:
        off=FONT_FILE_OFFSET+e["glyph"]*GLYPH_SIZE
        if off<0 or off+GLYPH_SIZE>len(font_boot):raise RuntimeError("Glyph range outside BOOT")
        font_boot[off:off+GLYPH_SIZE]=e["block"]
    font_boot=bytes(font_boot)
    allowed_ranges=sorted((FONT_FILE_OFFSET+e["glyph"]*GLYPH_SIZE,
                           FONT_FILE_OFFSET+(e["glyph"]+1)*GLYPH_SIZE) for e in rendered)
    pos=0
    for s,e in allowed_ranges:
        if original_boot[pos:s]!=font_boot[pos:s]:raise RuntimeError("Off-target glyph patch")
        pos=e
    if original_boot[pos:]!=font_boot[pos:]:raise RuntimeError("Off-target glyph patch tail")

    print("[4/10] Apply all ChatGPT BOOT string translations",flush=True)
    boot_occ=[o for o in occ if o["kind"]=="BOOT_CSTR" and o["candidate_id"] in active]
    patched=bytearray(font_boot);bootrows=[];seen_offsets=set()
    for o in sorted(boot_occ,key=lambda r:int(r["offset"],16)):
        off=int(o["offset"],16)
        if off in seen_offsets:raise RuntimeError(f"Duplicate BOOT occurrence offset {off:#x}")
        seen_offsets.add(off)
        old=bytes.fromhex(o["source_raw_hex"]);maxb=int(o["max_bytes"])
        if len(old)!=maxb:raise RuntimeError(f"{o['candidate_id']} old/max byte mismatch")
        if original_boot[off:off+len(old)]!=old:
            raise RuntimeError(f"{o['candidate_id']} BOOT source mismatch at {off:#x}")
        tr=active[o["candidate_id"]]["korean"];enc=encode_text(tr,cmap)
        if len(enc)>maxb:
            raise RuntimeError(f"{o['candidate_id']} exact byte overflow {len(enc)}>{maxb}: {tr}")
        patched[off:off+maxb]=enc+b"\0"*(maxb-len(enc))
        bootrows.append(dict(candidate_id=o["candidate_id"],offset=hex(off),
                             source=active[o["candidate_id"]]["source"],korean=tr,
                             max_bytes=maxb,new_bytes=len(enc),status="PATCHED"))
    boot.write_bytes(bytes(patched))
    write_tsv(out/"sub51d_boot_text_patch.tsv",bootrows,
              ["candidate_id","offset","source","korean","max_bytes","new_bytes","status"])

    print("[5/10] Apply translated RHS lines to decoded TBL resources",flush=True)
    m=mod("sub51d_p14",root/"analysis/stage14/naruto_patcher.py")
    ei=m.parse_pidx(m.read_embedded_index(dat),"sub51d-src")
    by_resource={}
    for o in occ:
        if o["kind"]=="TEXT_RHS" and o["candidate_id"] in active:
            by_resource.setdefault(o["scope"],[]).append(o)
    replacements={};tblrows=[]
    for resource,olist in sorted(by_resource.items()):
        olddec=decode_primary(dat,ei,resource,m)
        newdec,rows=patch_text_resource(olddec,olist,active,cmap,resource)
        if olddec==newdec:raise RuntimeError("No change in "+resource)
        replacements[resource]=dict(original_sha256=m.sha256(olddec),new_decoded=newdec)
        tblrows.extend(rows)
    write_tsv(out/"sub51d_tbl_text_patch.tsv",tblrows,
              ["candidate_id","scope","offset","source","korean","old_bytes","new_bytes","status"])

    print("[6/10] Rebuild DAT primary resources and FSTS duplicates",flush=True)
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub51d-emb");xi=m.parse_pidx(xb,"sub51d-ext")
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
                if isinstance(x,dict):members.append(str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x))
                else:members.append(str(x))
            fstsrows.append(dict(bundle=r["name"],members=";".join(members)))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub51d_primary_rebuild.tsv",primaryrows,
              ["resource","decoded_size","stored_size","new_offset","status"])
    write_tsv(out/"sub51d_fsts_rebuild.tsv",fstsrows,["bundle","members"])

    print("[7/10] Verify target resources and untouched primary resources",flush=True)
    fin=m.parse_pidx(m.read_embedded_index(dat),"sub51d-fin")
    for name,repl in replacements.items():
        got=decode_primary(dat,fin,name,m)
        if got!=repl["new_decoded"]:raise RuntimeError("Final decoded mismatch "+name)
    preserved=0
    srcdat=work/"source_before_patch.dat"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat)
    srct=m.parse_pidx(m.read_embedded_index(srcdat),"sub51d-source-verify")
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(srct["primary"],fin["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in replacements:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed "+sr["name"])
            preserved+=1
    srcdat.unlink()

    print("[8/10] Compact-build final ISO from SUB36 donor",flush=True)
    iso=mod("sub51d_p15",root/"analysis/stage15/stage15_iso_patcher.py")
    final=out/FINAL_NAME
    if final.exists():final.unlink()
    shutil.copyfile(donor,final)
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

    print("[9/10] Static verification: core files, movies, encoding",flush=True)
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
    write_tsv(out/"sub51d_core_verification.tsv",core,["iso_path","size","sha256","match"])

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub51d_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51d_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub51d_sha256","match"])

    for r in active.values():
        encode_text(r["korean"],cmap)

    print("[10/10] Finalize reports and remove temporary build files",flush=True)
    report=dict(
        stage="SUB51D_FULL_TEXT_APPLY",
        source_sub50_sha256=SOURCE_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        chatgpt_translations=1140,
        boot_occurrences_patched=len(bootrows),
        tbl_occurrences_patched=len(tblrows),
        tbl_resources_rebuilt=len(replacements),
        existing_mapping_chars=len(existing),
        new_mapping_chars=len(extension),
        combined_mapping_chars=len(combined),
        strict_safe_slots_available_before=len(pool),
        non_target_primary_preserved=preserved,
        pmf_movies_preserved=len(movies),
        translation_engine="ChatGPT",
        bc250_used=False,
        local_llm_used=False,
        game_text_static_qa="PASS",
        runtime_qa="DEFERRED_UNTIL_UI_IMAGE_SWEEP_COMPLETE",
        note="All 1140 ChatGPT-translated candidates applied. U+00B7 separator is emitted as ASCII slash to avoid any CP932 donor-glyph collision."
    )
    (out/"SUB51D_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51D - Full Text Apply\n\n"
        f"SourceSUB50SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"FinalSize={report['final_iso_size']}\n"
        f"ChatGPTTranslations={report['chatgpt_translations']}\n"
        f"BOOTOccurrencesPatched={len(bootrows)}\n"
        f"TBLOccurrencesPatched={len(tblrows)}\n"
        f"TBLResourcesRebuilt={len(replacements)}\n"
        f"ExistingMappingChars={len(existing)}\n"
        f"NewMappingChars={len(extension)}\n"
        f"CombinedMappingChars={len(combined)}\n"
        f"PMFsPreserved={len(movies)}\n"
        "BC250Used=NO\nLocalLLMUsed=NO\n"
        "StaticQA=PASS\nRuntimeQA=DEFERRED\n",
        encoding="utf-8-sig")
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
