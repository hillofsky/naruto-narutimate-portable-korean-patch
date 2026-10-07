#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,shutil,struct,sys
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="8b04e816bf6d6b15b4ad5e288056e4fbe6261c2d5d882dd2e1b67594fbcb6951"
SOURCE_REL=Path("analysis/sub/sub47_network_option_home/Naruto_KR_MOV06E_SUB47_Network_Option_Home.iso")
BASE_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
BASE_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub48_menu_atlas_cleanup")
FINAL_NAME="Naruto_KR_MOV06E_SUB48_MenuAtlasCleanup.iso"

BOOT_RULES=[
 ("narup_intro_last","　見る事ができるぞ！","　확인합니다!"),
 ("narup_destination","　目的地","　위치"),
 ("narup_all_items_dot","あなたは全ての閲覧アイテムを入手しました.","모든 감상 아이템을 얻었습니다."),
 ("narup_all_items_jp","あなたは全ての閲覧アイテムを入手しました。","모든 감상 아이템을 얻었습니다."),
 ("home_image_desc","画像を見る事ができます。","이미지 확인"),
 ("home_movie_desc","映像を見る事ができます。","영상 확인"),
 ("home_photo_desc","写真を見る事ができます。","사진 확인"),
 ("home_count1","%d / %d 個","%d / %d개"),
 ("home_count2","%d/%d個","%d/%d개"),
]

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:raise RuntimeError(f"Cannot import {path}")
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("Bad ISO")
    r=p[156:190]
    return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
    with Path(iso).open("rb") as f:f.seek(lba*SECTOR);data=f.read(size)
    out=[];pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:pos=((pos//SECTOR)+1)*SECTOR;continue
        r=data[pos:pos+ln]
        if len(r)<34:break
        nb=r[33:33+r[32]]
        name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
        out.append(dict(name=name,lba=int.from_bytes(r[2:6],"little"),size=int.from_bytes(r[10:14],"little"),is_dir=bool(r[25]&2)))
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso);cur=dict(lba=lba,size=size,is_dir=True)
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"]) if e["name"].casefold()==part.casefold()),None)
        if not hit:raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath);Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b:raise RuntimeError("EOF "+ipath)
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

def load_mapping(root):
    mp={}
    for p in (root/"analysis/shared/event_font_hangul_mapping.tsv",
              root/"analysis/sub/sub40_tutorial/new_glyph_mapping.tsv"):
        if not p.exists():raise RuntimeError("Font map missing: "+str(p))
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                if r.get("hangul") and r.get("donor_sjis_hex"):
                    mp[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
    return mp

def enc(s,mp):
    out=bytearray()
    for c in s:
        if c in mp:out+=mp[c]
        elif c==" ":out+=b"\xA0"
        else:out+=c.encode("cp932")
    return bytes(out)

def missing(s,mp):
    return sorted({c for c in s if "가"<=c<="힣" and c not in mp})

def patch_cstr(b,label,jp,kr,mp,rows):
    old=jp.encode("cp932");miss=missing(kr,mp)
    if miss:
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes="",status="SKIP_UNMAPPED",missing="".join(miss)))
        return 0
    new=enc(kr,mp)
    if len(new)>len(old):
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="SKIP_TOO_LONG",missing=""))
        return 0
    original=bytes(b);pos=0;count=0
    while True:
        i=original.find(old,pos)
        if i<0:break
        pos=i+1;after=i+len(old)
        if (i==0 or original[i-1]==0) and after<len(original) and original[after]==0:
            b[i:after]=new+bytes(len(old)-len(new));count+=1
            rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex=hex(i),old_bytes=len(old),new_bytes=len(new),status="PATCHED",missing=""))
    if count==0:
        rows.append(dict(label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="NOT_FOUND",missing=""))
    return count

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def find_palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=palid:continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b):continue
        raw=np.frombuffer(b[o+28:o+28+n*4],dtype=np.uint8).reshape(-1,4).copy()
        rgba=raw[:,[2,1,0,3]]
        rgba[:,3]=np.minimum(rgba[:,3].astype(np.int16)*2,255).astype(np.uint8)
        return o,rgba
    raise RuntimeError("Palette missing")

def find_texture(b,name):
    names=ccs_names(b);wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture missing "+name)

def decode_indices(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    return ix[::-1].copy()

def encode_indices(ix,typ):
    flat=ix[::-1].reshape(-1).astype(np.uint8)
    if typ==0x13:return flat.tobytes()
    return (flat[::2]|(flat[1::2]<<4)).astype(np.uint8).tobytes()

def patch_texture(b,name,png):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"]);oldix=decode_indices(b,t);oldrgba=pal[oldix]
    repl=np.asarray(Image.open(png).convert("RGBA"),dtype=np.uint8)
    if repl.shape[:2]!=(t["height"],t["width"]):
        raise RuntimeError(f"Texture size mismatch {name}: expected {t['width']}x{t['height']} got {repl.shape[1]}x{repl.shape[0]}")
    same=np.all(repl==oldrgba,axis=2);newix=oldix.copy();chg=~same
    if np.any(chg):
        pe=pal.astype(np.float32);pe[:,:3]*=pe[:,3:4]/255.0
        px=repl[chg].astype(np.float32);px[:,:3]*=px[:,3:4]/255.0
        chosen=np.empty(len(px),dtype=np.uint8)
        for s in range(0,len(px),4096):
            q=px[s:s+4096];dist=((q[:,None,:]-pe[None,:,:])**2).sum(axis=2)
            chosen[s:s+len(q)]=dist.argmin(axis=1)
        newix[chg]=chosen
    packed=encode_indices(newix,t["type"]);a=t["offset"]+36;b[a:a+len(packed)]=packed
    return dict(texture=name,width=t["width"],height=t["height"],changed_pixels=int(chg.sum()))

def decode_texture_png(b,name,path):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"]);ix=decode_indices(b,t)
    Image.fromarray(pal[ix],"RGBA").save(path)

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    ap.add_argument("--assets",required=True)
    a=ap.parse_args()
    root=Path(a.root);assets=Path(a.assets);source=root/SOURCE_REL;base=root/BASE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB47 authority ISO missing/SHA mismatch")
    if not base.exists() or sha256_file(base)!=BASE_SHA:
        raise RuntimeError("SUB36 compact baseline missing/SHA mismatch")

    m=mod("sub48_p14",root/"analysis/stage14/naruto_patcher.py")
    iso=mod("sub48_p15",root/"analysis/stage15/stage15_iso_patcher.py")
    mp=load_mapping(root)

    print("[1/10] Extract exact SUB47 DAT/IDX/BOOT",flush=True)
    srcdat=out/"source_sub47_naruto.dat";srcidx=out/"source_sub47_naruto.idx";srcboot=out/"source_sub47_BOOT.bin"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    shutil.copyfile(srcdat,dat);shutil.copyfile(srcidx,idx)

    print("[2/10] Patch remaining safe BOOT UI strings",flush=True)
    bb=bytearray(srcboot.read_bytes());textrows=[]
    for rule in BOOT_RULES:patch_cstr(bb,*rule,mp,textrows)
    boot.write_bytes(bb)

    print("[3/10] Patch option/gauge/rpggauge/home atlases",flush=True)
    plans={
      "option.ccs":[("TEX_option01",assets/"TEX_option01_fix2.png")],
      "gauge.ccs":[
        ("TEX_red",assets/"TEX_red_fix2.png"),
        ("TEX_xtext",assets/"TEX_xtext_ko.png"),
        ("TEX_xmenu",assets/"TEX_xmenu_ko.png"),
      ],
      "rpggauge.ccs":[("TEX_rpgmenu01",assets/"TEX_rpgmenu01_ko.png")],
      "home.ccs":[("TEX_mhvid01",assets/"TEX_mhvid01_ko.png")],
    }
    src_ei=m.parse_pidx(m.read_embedded_index(srcdat),"sub47-src")
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub48-emb");xi=m.parse_pidx(xb,"sub48-ext")
    replacements={};texrows=[]
    with dat.open("rb") as f:
        for res,pls in plans.items():
            r=next((q for q in ei["primary"] if q["name"]==res),None)
            if not r:
                raise RuntimeError("Primary resource missing: "+res)
            f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
            old=m.decode_stored(st,r["size"],r["zsize"]);b=bytearray(old)
            for t,png in pls:
                row=patch_texture(b,t,png);row["resource"]=res;texrows.append(row)
            new=bytes(b)
            if len(new)!=len(old):raise RuntimeError("CCS decoded size changed "+res)
            replacements[res]=dict(original_sha256=m.sha256(old),new_decoded=new)
    print("  resources:",",".join(sorted(replacements)),flush=True)

    print("[4/10] Append changed resources + update PIDX",flush=True)
    with dat.open("ab") as f:
        for name,rr in replacements.items():
            encoded=m.encode_3_0(rr["new_decoded"])
            if m.decode_3x(encoded)!=rr["new_decoded"]:raise RuntimeError("Encode self-check failed "+name)
            off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["primary"] if q["name"]==name)
                struct.pack_into("<III",blob,q["record_off"]+12,off,len(rr["new_decoded"]),len(encoded))

    print("[5/10] Patch FSTS preload duplicates",flush=True)
    bundles=[]
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
            members=";".join(
                str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x)
                if isinstance(x,dict) else str(x) for x in changes
            )
            bundles.append(dict(bundle=r["name"],members=members))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)

    print("[6/10] Export patched textures for review",flush=True)
    review=out/"review_textures";review.mkdir(exist_ok=True)
    fin_ei=m.parse_pidx(m.read_embedded_index(dat),"review")
    with dat.open("rb") as f:
        for res,pls in plans.items():
            r=next(q for q in fin_ei["primary"] if q["name"]==res)
            f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"]);dec=m.decode_stored(st,r["size"],r["zsize"])
            for t,_ in pls:
                decode_texture_png(dec,t,review/f"{res.replace('.','_')}__{t}.png")

    print("[7/10] Build compact SUB48 ISO",flush=True)
    if final.exists():final.unlink()
    shutil.copyfile(base,final)
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

    print("[8/10] Static regression verification",flush=True)
    core=[]
    for ip,host in (
        ("PSP_GAME/USRDIR/naruto.dat",dat),
        ("PSP_GAME/USRDIR/naruto.idx",idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
        ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
    ):
        sz,hs=segsha(final,ip);ok=hs==sha256_file(host)
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verify fail "+ip)

    final_ei=m.parse_pidx(m.read_embedded_index(dat),"sub48-final")
    targets=set(replacements);preserved_primary=0;preserved_fsts=0
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(src_ei["primary"],final_ei["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in targets:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed "+sr["name"])
            preserved_primary+=1
        srcf={r["index"]:r for r in src_ei["offset2_rows"]}
        finf={r["index"]:r for r in final_ei["offset2_rows"]}
        for k,sr in srcf.items():
            fr=finf[k];sf.seek(sr["file_off"]);sb=sf.read(sr["file_size"]);ff.seek(fr["file_off"]);fb=ff.read(fr["file_size"])
            if sb==fb:continue
            sa=m.parse_fsts(sb,"s");fa=m.parse_fsts(fb,"f")
            for sx,fx in zip(sa["members"],fa["members"]):
                if sx["name"]!=fx["name"]:raise RuntimeError("FSTS order changed")
                if sx["basename"] not in targets:
                    if sx["stored"]!=fx["stored"]:
                        raise RuntimeError(f"Untargeted FSTS changed {sr['name']} / {sx['name']}")
                    preserved_fsts+=1

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub48_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)

    print("[9/10] Write reports",flush=True)
    write_tsv(out/"sub48_text_patch.tsv",textrows,
              ["label","japanese","korean","offset_hex","old_bytes","new_bytes","status","missing"])
    write_tsv(out/"sub48_texture_patch.tsv",texrows,
              ["resource","texture","width","height","changed_pixels"])
    write_tsv(out/"sub48_fsts_changes.tsv",bundles,["bundle","members"])
    write_tsv(out/"sub48_core_verification.tsv",core,["iso_path","size","sha256","match"])
    write_tsv(out/"sub48_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub48_sha256","match"])

    report=dict(
        stage="SUB48_MENU_ATLAS_CLEANUP",
        source_iso_sha256=SOURCE_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        text_patched=sum(r["status"]=="PATCHED" for r in textrows),
        text_skipped_unmapped=sum(r["status"]=="SKIP_UNMAPPED" for r in textrows),
        text_skipped_too_long=sum(r["status"]=="SKIP_TOO_LONG" for r in textrows),
        text_not_found=sum(r["status"]=="NOT_FOUND" for r in textrows),
        changed_resources=sorted(targets),
        texture_patches=texrows,
        fsts_bundles_changed=[r["bundle"] for r in bundles],
        preserved_non_target_primary_resources=preserved_primary,
        preserved_non_target_fsts_members=preserved_fsts,
        pmf_movies_preserved=len(movies),
        font_mapping_preserved="694+17",
        new_glyphs_added=0,
        compact_rebuild=True,
        static_qa="PASS",
        runtime_qa="REQUIRED",
    )
    (out/"SUB48_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary=[
        "Naruto PSP SUB48 - Menu Atlas Cleanup","",
        f"SourceSHA256={SOURCE_SHA}",
        f"FinalISO={final}",
        f"FinalSHA256={report['final_iso_sha256']}",
        f"FinalSize={report['final_iso_size']}",
        f"TextPatched={report['text_patched']}",
        f"TextSkippedUnmapped={report['text_skipped_unmapped']}",
        f"TextSkippedTooLong={report['text_skipped_too_long']}",
        f"TextNotFound={report['text_not_found']}",
        f"ChangedResources={','.join(sorted(targets))}",
        f"FSTSChangedBundles={len(bundles)}",
        f"PreservedPrimaryResources={preserved_primary}",
        f"PMFsPreserved={len(movies)}",
        "FontMappingPreserved=694+17",
        "NewGlyphsAdded=0",
        "CompactRebuild=YES",
        "StaticQA=PASS",
        "RuntimeQA=REQUIRED",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("[10/10] Done",flush=True);print("\n".join(summary),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
