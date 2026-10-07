#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys,traceback
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="d06152d10691852c9cacd7097a29404f3e0175345b45b5b74d0f66054a6eb85b"
SOURCE_REL=Path("analysis/sub/sub51g_modesel1_style_rebuild/Naruto_KR_MOV06E_SUB51G_ModeSelectStyled.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub51h_option_style_rebuild")
FINAL_NAME="Naruto_KR_MOV06E_SUB51H_OptionStyled.iso"
TARGET_RESOURCE="option.ccs"
TARGET_TEXTURE="TEX_option01"

# Exact text-only atlas boxes. Outside these boxes the original indexed pixels are preserved byte-for-byte.
RECTS=[
    (0,0,108,32),      # 難易度設定 black
    (108,0,220,32),    # 難易度設定 blue
    (220,0,268,32),    # 終了 black
    (268,0,318,32),    # 終了 blue
    (0,34,105,68),     # 操作設定 black
    (108,34,212,68),   # 操作設定 blue
    (0,70,105,102),    # 音量設定 black
    (108,70,212,102),  # 音量設定 blue
    (0,103,105,132),   # やさしい
    (110,103,175,132), # ふつう
    (170,103,315,132), # むずかしい
    (320,103,410,132), # 激むず
]

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("Bad ISO")
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
            if not b:raise RuntimeError("EOF")
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

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    if pc>10000 or nc>10000 or no+32*nc>len(b):raise RuntimeError("Bad CCS names")
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
    names=ccs_names(b)
    if name not in names:raise RuntimeError("Texture name missing "+name)
    wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture record missing "+name)

def decode_indices(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:
        ix=raw.reshape(t["height"],t["width"]).copy()
    else:
        ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    return ix[::-1].copy()

def encode_indices(ix,t):
    ix=ix[::-1].copy()
    if t["type"]==0x13:
        raw=ix.astype(np.uint8).tobytes()
    else:
        flat=ix.reshape(-1)
        raw=((flat[0::2]&15)|((flat[1::2]&15)<<4)).astype(np.uint8).tobytes()
    if len(raw)!=t["data_len"]:raise RuntimeError("Index encode size mismatch")
    return raw

def nearest_palette_indices(im,pal):
    arr=np.asarray(im.convert("RGBA"),dtype=np.int32)
    flat=arr.reshape(-1,4)
    p=pal.astype(np.int32)
    out=np.empty(len(flat),dtype=np.uint8)
    weights=np.array([1,1,1,4],dtype=np.int32)
    for s in range(0,len(flat),4096):
        q=flat[s:s+4096]
        diff=q[:,None,:]-p[None,:,:]
        dist=((diff*diff)*weights).sum(axis=2)
        out[s:s+4096]=dist.argmin(axis=1).astype(np.uint8)
    return out.reshape(arr.shape[:2])

def patch_regions(ccs,name,png):
    b=bytearray(ccs);t=find_texture(b,name);_,pal=find_palette(b,t["palette"])
    im=Image.open(png).convert("RGBA")
    if im.size!=(t["width"],t["height"]):raise RuntimeError("PNG size mismatch")
    old_ix=decode_indices(b,t);target_ix=nearest_palette_indices(im,pal)
    new_ix=old_ix.copy()
    region_mask=np.zeros(old_ix.shape,dtype=bool)
    for x0,y0,x1,y1 in RECTS:
        new_ix[y0:y1,x0:x1]=target_ix[y0:y1,x0:x1]
        region_mask[y0:y1,x0:x1]=True
    if np.any(new_ix[~region_mask]!=old_ix[~region_mask]):
        raise RuntimeError("Off-region indexed pixels changed")
    changed=int(np.sum(new_ix!=old_ix))
    raw=encode_indices(new_ix,t)
    start=t["offset"]+36
    b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=t["width"],height=t["height"],type=hex(t["type"]),
                         palette=t["palette"],changed_indexed_pixels=changed,
                         outside_region_changes=0,payload_sha256=hashlib.sha256(raw).hexdigest())

def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:raise RuntimeError("Missing primary "+name)
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    ap.add_argument("--assets",required=True)
    a=ap.parse_args()
    root=Path(a.root);assetdir=Path(a.assets);source=root/SOURCE_REL;donor=root/DONOR_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    work=out/"_work"
    if work.exists():shutil.rmtree(work)
    work.mkdir()

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB51G authority missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:raise RuntimeError("SUB36 donor missing/SHA mismatch")

    p14=mod("sub51h_p14",root/"analysis/stage14/naruto_patcher.py")
    p15=mod("sub51h_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/8] Extract exact SUB51G DAT/IDX/BOOT",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    before_dat=work/"before.dat";shutil.copyfile(dat,before_dat)

    print("[2/8] Patch only exact text boxes in option.ccs/TEX_option01",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"sub51h-src")
    oldccs=decode_primary(dat,table,TARGET_RESOURCE,p14)
    png=assetdir/"TEX_option01_KO_STYLED.png"
    newccs,row=patch_regions(oldccs,TARGET_TEXTURE,png)
    if newccs==oldccs:raise RuntimeError("option.ccs unchanged")
    row["png_sha256"]=sha256_file(png)
    write_tsv(out/"sub51h_texture_patch.tsv",[row],
              ["texture","width","height","type","palette","changed_indexed_pixels",
               "outside_region_changes","payload_sha256","png_sha256"])

    print("[3/8] Replace primary option.ccs",flush=True)
    eb=bytearray(p14.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(eb,"sub51h-emb");xi=p14.parse_pidx(xb,"sub51h-ext")
    encoded=p14.encode_3_0(newccs)
    if p14.decode_3x(encoded)!=newccs:raise RuntimeError("CCS encode self-check failed")
    with dat.open("ab") as f:
        off=p14.align_up(f.tell())
        if off>f.tell():f.write(bytes(off-f.tell()))
        f.write(encoded)
    for blob,tab in ((eb,ei),(xb,xi)):
        r=next(r for r in tab["primary"] if r["name"]==TARGET_RESOURCE)
        struct.pack_into("<III",blob,r["record_off"]+12,off,len(newccs),len(encoded))

    print("[4/8] Rebuild FSTS duplicates containing option.ccs",flush=True)
    replacements={TARGET_RESOURCE:dict(original_sha256=p14.sha256(oldccs),new_decoded=newccs)}
    fstsrows=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]);bundle=f.read(r["file_size"])
            rebuilt,changes=p14.rebuild_fsts(bundle,r["name"],replacements)
            if not changes:continue
            f.seek(0,2);boff=p14.align_up(f.tell())
            if boff>f.tell():f.write(bytes(boff-f.tell()))
            f.write(rebuilt)
            for blob,tab in ((eb,ei),(xb,xi)):
                q=next(q for q in tab["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,boff,len(rebuilt))
            fstsrows.append(dict(bundle=r["name"],changes=str(changes)))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub51h_fsts_rebuild.tsv",fstsrows,["bundle","changes"])

    print("[5/8] Verify non-target primary resources are byte-identical",flush=True)
    before=p14.parse_pidx(p14.read_embedded_index(before_dat),"before")
    after=p14.parse_pidx(p14.read_embedded_index(dat),"after")
    preserved=0
    with before_dat.open("rb") as bf,dat.open("rb") as af:
        for br,ar in zip(before["primary"],after["primary"]):
            if br["name"]!=ar["name"]:raise RuntimeError("Primary order changed")
            if br.get("is_folder") or br["name"]==TARGET_RESOURCE:continue
            bf.seek(br["offset"]);bb=bf.read(br["zsize"] or br["size"])
            af.seek(ar["offset"]);ab=af.read(ar["zsize"] or ar["size"])
            if bb!=ab:raise RuntimeError("Off-target primary changed: "+br["name"])
            preserved+=1
    finaltab=p14.parse_pidx(p14.read_embedded_index(dat),"final")
    if decode_primary(dat,finaltab,TARGET_RESOURCE,p14)!=newccs:
        raise RuntimeError("Final option.ccs mismatch")

    print("[6/8] Compact-build ISO",flush=True)
    final=out/FINAL_NAME
    if final.exists():final.unlink()
    shutil.copyfile(donor,final)
    with final.open("r+b") as f:
        vds=p15.read_volume_descriptors(f)
        for ip,host in (
            ("PSP_GAME/USRDIR/naruto.dat",dat),
            ("PSP_GAME/USRDIR/naruto.idx",idx),
            ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
            ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
        ):
            recs=[p15.find_path(f,vd,ip.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext=p15.append_file_sector_aligned(f,host,host.name)
            for q in recs:
                if q:p15.patch_directory_record(f,q["record_offset"],ext["lba"],ext["size"])
        f.seek(0,2);p15.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print("[7/8] Verify core files and PMFs",flush=True)
    core=[]
    for ip,host in (
        ("PSP_GAME/USRDIR/naruto.dat",dat),
        ("PSP_GAME/USRDIR/naruto.idx",idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
        ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
    ):
        sz,hs=segsha(final,ip);ok=hs==sha256_file(host)
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verify failed "+ip)
    write_tsv(out/"sub51h_core_verification.tsv",core,["iso_path","size","sha256","match"])

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub51h_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51h_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub51h_sha256","match"])

    print("[8/8] Finalize report",flush=True)
    report=dict(
        stage="SUB51H_OPTION_STYLE_REBUILD",
        source_sub51g_sha256=SOURCE_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        resource_changed=TARGET_RESOURCE,
        texture_changed=TARGET_TEXTURE,
        exact_region_count=len(RECTS),
        outside_region_indexed_pixel_changes=0,
        changed_indexed_pixels=row["changed_indexed_pixels"],
        non_target_primary_preserved=preserved,
        fsts_bundles_rebuilt=len(fstsrows),
        pmf_movies_preserved=len(movies),
        static_qa="PASS",
        runtime_qa="DEFERRED",
        bc250_used=False,
        local_llm_used=False,
    )
    (out/"SUB51H_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51H - Option Style Rebuild\n\n"
        f"SourceSUB51G_SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"ExactTextRegions={len(RECTS)}\n"
        f"ChangedIndexedPixels={row['changed_indexed_pixels']}\n"
        "OutsideRegionIndexedPixelChanges=0\n"
        f"FSTSBundlesRebuilt={len(fstsrows)}\n"
        f"PMFsPreserved={len(movies)}\n"
        "StaticQA=PASS\nRuntimeQA=DEFERRED\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig")
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
