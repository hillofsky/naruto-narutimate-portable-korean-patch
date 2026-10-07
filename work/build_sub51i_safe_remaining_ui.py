#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys,traceback
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="eea17dc56d1078c450fa8d61b4f0af6615a140682e15a8d950f586af16873c61"
SOURCE_REL=Path("analysis/sub/sub51h_option_style_rebuild/Naruto_KR_MOV06E_SUB51H_OptionStyled.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub51i_safe_remaining_ui")
FINAL_NAME="Naruto_KR_MOV06E_SUB51I_SafeRemainingUI.iso"

TARGETS={
    "rpggauge.ccs":{
        "TEX_rpgmenu01":{
            "asset":"TEX_rpgmenu01_KO_STYLED.png",
            "rects":[
                (176,3,282,30),(299,3,412,30),
                (166,35,285,62),(293,35,413,62),
                (190,67,278,94),(316,67,395,94),
                (192,99,277,126),(316,99,396,126),
                (164,132,286,160),(293,132,414,160),
                (184,164,280,191),(309,164,403,191),
                (26,135,117,158),(15,165,111,188),(15,197,111,220),
                (10,230,140,253),(425,5,508,28),(420,38,509,61),
                (421,130,507,163),(420,169,508,190),(128,160,160,224),
            ],
        },
    },
    "home.ccs":{
        "TEX_mhvid01":{
            "asset":"TEX_mhvid01_KO_STYLED.png",
            "rects":[(145,24,162,79)],
        },
    },
}

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
    if pc>10000 or nc>10000 or no+32*nc>len(b):raise RuntimeError("Bad CCS")
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
    if name not in names:raise RuntimeError("Texture missing "+name)
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
    if len(raw)!=t["data_len"]:raise RuntimeError("Encoded length mismatch")
    return raw

def nearest_palette_indices(im,pal):
    arr=np.asarray(im.convert("RGBA"),dtype=np.int32);flat=arr.reshape(-1,4)
    p=pal.astype(np.int32);out=np.empty(len(flat),dtype=np.uint8)
    weights=np.array([1,1,1,4],dtype=np.int32)
    for s in range(0,len(flat),4096):
        q=flat[s:s+4096];diff=q[:,None,:]-p[None,:,:]
        out[s:s+4096]=(((diff*diff)*weights).sum(axis=2)).argmin(axis=1).astype(np.uint8)
    return out.reshape(arr.shape[:2])

def patch_texture(ccs,name,png,rects):
    b=bytearray(ccs);t=find_texture(b,name);_,pal=find_palette(b,t["palette"])
    im=Image.open(png).convert("RGBA")
    if im.size!=(t["width"],t["height"]):raise RuntimeError(f"{name} PNG size mismatch")
    old=decode_indices(b,t);target=nearest_palette_indices(im,pal);new=old.copy()
    mask=np.zeros(old.shape,dtype=bool)
    for x0,y0,x1,y1 in rects:
        new[y0:y1,x0:x1]=target[y0:y1,x0:x1];mask[y0:y1,x0:x1]=True
    if np.any(new[~mask]!=old[~mask]):raise RuntimeError(name+" off-region change")
    raw=encode_indices(new,t);start=t["offset"]+36;b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=t["width"],height=t["height"],
                         changed_indexed_pixels=int(np.sum(new!=old)),
                         outside_region_changes=0,payload_sha256=hashlib.sha256(raw).hexdigest())

def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:raise RuntimeError("Primary missing "+name)
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
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB51H authority missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:raise RuntimeError("SUB36 donor missing/SHA mismatch")
    p14=mod("sub51i_p14",root/"analysis/stage14/naruto_patcher.py")
    p15=mod("sub51i_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/8] Extract SUB51H DAT/IDX/BOOT",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    before_dat=work/"before.dat";shutil.copyfile(dat,before_dat)

    print("[2/8] Patch safe exact regions in home/rpggauge",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    replacements={};rows=[]
    for resource,spec in TARGETS.items():
        old=decode_primary(dat,table,resource,p14);new=old
        for tex,ts in spec.items():
            new,row=patch_texture(new,tex,assetdir/ts["asset"],ts["rects"])
            row["resource"]=resource;row["rect_count"]=len(ts["rects"]);rows.append(row)
        if new==old:raise RuntimeError(resource+" unchanged")
        replacements[resource]=dict(original_sha256=p14.sha256(old),new_decoded=new)
    write_tsv(out/"sub51i_texture_patch.tsv",rows,
              ["resource","texture","width","height","rect_count","changed_indexed_pixels",
               "outside_region_changes","payload_sha256"])

    print("[3/8] Replace target primary resources",flush=True)
    eb=bytearray(p14.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(eb,"emb");xi=p14.parse_pidx(xb,"ext")
    with dat.open("ab") as f:
        for name,repl in replacements.items():
            encoded=p14.encode_3_0(repl["new_decoded"])
            if p14.decode_3x(encoded)!=repl["new_decoded"]:raise RuntimeError("Encode check "+name)
            off=p14.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,tab in ((eb,ei),(xb,xi)):
                r=next(r for r in tab["primary"] if r["name"]==name)
                struct.pack_into("<III",blob,r["record_off"]+12,off,len(repl["new_decoded"]),len(encoded))

    print("[4/8] Rebuild FSTS duplicates",flush=True)
    fstsrows=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]);bundle=f.read(r["file_size"])
            rebuilt,changes=p14.rebuild_fsts(bundle,r["name"],replacements)
            if not changes:continue
            f.seek(0,2);off=p14.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,tab in ((eb,ei),(xb,xi)):
                q=next(q for q in tab["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,off,len(rebuilt))
            fstsrows.append(dict(bundle=r["name"],changes=str(changes)))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub51i_fsts_rebuild.tsv",fstsrows,["bundle","changes"])

    print("[5/8] Verify non-target primary preservation",flush=True)
    before=p14.parse_pidx(p14.read_embedded_index(before_dat),"before")
    after=p14.parse_pidx(p14.read_embedded_index(dat),"after")
    preserved=0
    with before_dat.open("rb") as bf,dat.open("rb") as af:
        for br,ar in zip(before["primary"],after["primary"]):
            if br["name"]!=ar["name"]:raise RuntimeError("Primary order changed")
            if br.get("is_folder") or br["name"] in replacements:continue
            bf.seek(br["offset"]);bb=bf.read(br["zsize"] or br["size"])
            af.seek(ar["offset"]);ab=af.read(ar["zsize"] or ar["size"])
            if bb!=ab:raise RuntimeError("Off-target primary changed "+br["name"])
            preserved+=1
    finaltab=p14.parse_pidx(p14.read_embedded_index(dat),"final")
    for name,repl in replacements.items():
        if decode_primary(dat,finaltab,name,p14)!=repl["new_decoded"]:
            raise RuntimeError("Final decoded mismatch "+name)

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
        ("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
    ):
        sz,hs=segsha(final,ip);ok=hs==sha256_file(host)
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("Core verify failed "+ip)
    write_tsv(out/"sub51i_core_verification.tsv",core,["iso_path","size","sha256","match"])

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub51i_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51i_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub51i_sha256","match"])

    print("[8/8] Finalize",flush=True)
    report=dict(
        stage="SUB51I_SAFE_REMAINING_UI",
        source_sub51h_sha256=SOURCE_SHA,
        final_iso=str(final),final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        resources_changed=sorted(replacements),
        texture_regions_changed=sum(r["rect_count"] for r in rows),
        outside_region_indexed_pixel_changes=0,
        non_target_primary_preserved=preserved,
        fsts_bundles_rebuilt=len(fstsrows),pmf_movies_preserved=len(movies),
        static_qa="PASS",runtime_qa="DEFERRED",
        bc250_used=False,local_llm_used=False,
    )
    (out/"SUB51I_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51I - Safe Remaining UI\n\n"
        f"SourceSUB51H_SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\nFinalSHA256={report['final_iso_sha256']}\n"
        "ResourcesChanged=home.ccs,rpggauge.ccs\n"
        f"ExactRegionsChanged={report['texture_regions_changed']}\n"
        "OutsideRegionIndexedPixelChanges=0\n"
        f"FSTSBundlesRebuilt={len(fstsrows)}\nPMFsPreserved={len(movies)}\n"
        "StaticQA=PASS\nRuntimeQA=DEFERRED\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig")
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
