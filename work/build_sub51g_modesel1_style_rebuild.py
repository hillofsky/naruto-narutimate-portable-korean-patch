#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys,traceback
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="7138f8c35bacaafab85ff50c12daf0620030cb9b44e7b7bf242168c20c91e845"
SOURCE_REL=Path("analysis/sub/sub51d_full_text_apply/Naruto_KR_MOV06E_SUB51D_FullText.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub51g_modesel1_style_rebuild")
FINAL_NAME="Naruto_KR_MOV06E_SUB51G_ModeSelectStyled.iso"
TARGET_RESOURCE="modesel1.ccs"

ASSET_NAMES=[
"TEX_mod_bg00","TEX_mod_bg01","TEX_mod_bg03","TEX_mod_bg04",
"TEX_mod_bg05","TEX_mod_bg06","TEX_mod_bg07"
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
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"])
                  if e["name"].casefold()==part.casefold()),None)
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

def nearest_palette_indices(im,pal):
    arr=np.asarray(im.convert("RGBA"),dtype=np.int16)
    # Fully transparent pixels prefer the most transparent palette entries.
    flat=arr.reshape(-1,4)
    out=np.empty(len(flat),dtype=np.uint8)
    chunk=4096
    p=pal.astype(np.int16)
    # Alpha weighted more heavily so transparent edges remain clean.
    weights=np.array([1,1,1,3],dtype=np.int32)
    for s in range(0,len(flat),chunk):
        q=flat[s:s+chunk].astype(np.int32)
        diff=q[:,None,:]-p[None,:,:].astype(np.int32)
        dist=((diff*diff)*weights).sum(axis=2)
        out[s:s+chunk]=dist.argmin(axis=1).astype(np.uint8)
    return out.reshape(arr.shape[:2])

def replace_texture_payload(ccs,name,png):
    b=bytearray(ccs);t=find_texture(b,name);_,pal=find_palette(b,t["palette"])
    im=Image.open(png).convert("RGBA")
    if im.size!=(t["width"],t["height"]):
        raise RuntimeError(f"{name}: PNG size {im.size} != {(t['width'],t['height'])}")
    ix=nearest_palette_indices(im,pal)
    ix=ix[::-1].copy()
    if t["type"]==0x13:
        raw=ix.astype(np.uint8).tobytes()
    else:
        flat=ix.reshape(-1)
        if len(flat)%2:raise RuntimeError("4bpp odd pixel count")
        raw=((flat[0::2]&15)|((flat[1::2]&15)<<4)).astype(np.uint8).tobytes()
    if len(raw)!=t["data_len"]:raise RuntimeError("Encoded size mismatch")
    start=t["offset"]+36
    b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=t["width"],height=t["height"],
                         type=hex(t["type"]),palette=t["palette"],
                         payload_sha256=hashlib.sha256(raw).hexdigest())

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

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB51D authority missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:raise RuntimeError("SUB36 donor missing/SHA mismatch")

    p14=mod("sub51g_p14",root/"analysis/stage14/naruto_patcher.py")
    p15=mod("sub51g_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/8] Extract exact SUB51D DAT/IDX/BOOT",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)

    original_dat_copy=work/"source_naruto.dat"
    shutil.copyfile(dat,original_dat_copy)

    print("[2/8] Decode current modesel1.ccs and replace seven image payloads",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"sub51g-src")
    oldccs=decode_primary(dat,table,TARGET_RESOURCE,p14)
    newccs=oldccs
    texrows=[]
    for name in ASSET_NAMES:
        png=assetdir/(name+"_KO_STYLED.png")
        if not png.exists():raise RuntimeError("Missing asset "+str(png))
        newccs,row=replace_texture_payload(newccs,name,png)
        row["png_sha256"]=sha256_file(png)
        texrows.append(row)
    if newccs==oldccs:raise RuntimeError("modesel1 unchanged")
    write_tsv(out/"sub51g_texture_patch.tsv",texrows,
              ["texture","width","height","type","palette","payload_sha256","png_sha256"])

    print("[3/8] Replace primary modesel1 resource",flush=True)
    eb=bytearray(p14.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(eb,"sub51g-emb");xi=p14.parse_pidx(xb,"sub51g-ext")
    encoded=p14.encode_3_0(newccs)
    if p14.decode_3x(encoded)!=newccs:raise RuntimeError("CCS encode self-check failed")
    with dat.open("ab") as f:
        off=p14.align_up(f.tell())
        if off>f.tell():f.write(bytes(off-f.tell()))
        f.write(encoded)
    for blob,tab in ((eb,ei),(xb,xi)):
        r=next(r for r in tab["primary"] if r["name"]==TARGET_RESOURCE)
        struct.pack_into("<III",blob,r["record_off"]+12,off,len(newccs),len(encoded))

    print("[4/8] Rebuild FSTS duplicates containing modesel1.ccs",flush=True)
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
    write_tsv(out/"sub51g_fsts_rebuild.tsv",fstsrows,["bundle","changes"])

    print("[5/8] Verify only target primary resource changed",flush=True)
    before=p14.parse_pidx(p14.read_embedded_index(original_dat_copy),"before")
    after=p14.parse_pidx(p14.read_embedded_index(dat),"after")
    preserved=0
    with original_dat_copy.open("rb") as bf,dat.open("rb") as af:
        for br,ar in zip(before["primary"],after["primary"]):
            if br["name"]!=ar["name"]:raise RuntimeError("Primary order changed")
            if br.get("is_folder") or br["name"]==TARGET_RESOURCE:continue
            bf.seek(br["offset"]);bb=bf.read(br["zsize"] or br["size"])
            af.seek(ar["offset"]);ab=af.read(ar["zsize"] or ar["size"])
            if bb!=ab:raise RuntimeError("Off-target primary changed: "+br["name"])
            preserved+=1
    finaltab=p14.parse_pidx(p14.read_embedded_index(dat),"final")
    if decode_primary(dat,finaltab,TARGET_RESOURCE,p14)!=newccs:
        raise RuntimeError("Final target CCS mismatch")

    print("[6/8] Compact-build final ISO from SUB36 donor",flush=True)
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

    print("[7/8] Verify core files and all PMFs",flush=True)
    core=[]
    for ip,host in (
        ("PSP_GAME/USRDIR/naruto.dat",dat),
        ("PSP_GAME/USRDIR/naruto.idx",idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),
        ("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
    ):
        sz,hs=segsha(final,ip);ok=(hs==sha256_file(host))
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verify failed "+ip)
    write_tsv(out/"sub51g_core_verification.tsv",core,["iso_path","size","sha256","match"])

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=(a==b)
        movies.append(dict(iso_path=ip,source_sha256=a,sub51g_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51g_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub51g_sha256","match"])

    print("[8/8] Finalize",flush=True)
    report=dict(
        stage="SUB51G_MODESEL1_STYLE_REBUILD",
        source_sub51d_sha256=SOURCE_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        resource_changed=TARGET_RESOURCE,
        textures_changed=ASSET_NAMES,
        non_target_primary_preserved=preserved,
        fsts_bundles_rebuilt=len(fstsrows),
        pmf_movies_preserved=len(movies),
        static_qa="PASS",
        runtime_qa="DEFERRED",
        bc250_used=False,
        local_llm_used=False,
    )
    (out/"SUB51G_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51G - Mode Select Style Rebuild\n\n"
        f"SourceSUB51D_SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"TexturesChanged={len(ASSET_NAMES)}\n"
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
