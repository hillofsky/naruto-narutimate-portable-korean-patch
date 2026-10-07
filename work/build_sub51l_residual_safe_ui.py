#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys,traceback
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="e8731e1b6eaceae47f765137ab1e40ebced1ad9637e44013b06ad19b17ba3556"
SOURCE_REL=Path("analysis/sub/sub51j_mugen_safe_style/Naruto_KR_MOV06E_SUB51J_MugenSafeStyled.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub51l_residual_safe_ui")
FINAL_NAME="Naruto_KR_MOV06E_SUB51L_ResidualSafeUI.iso"

SKILL_NAMES=[f"TEX_skl_t{i:02d}" for i in range(23)]+["TEX_skl_txt"]
MG_NAMES=["TEX_mg_txt00","TEX_mg_txt01","TEX_mg_txt03","TEX_mg_txt04","TEX_mg_txt05","TEX_mg_txt06","TEX_mg_txt07","TEX_mg_txt08","TEX_xwinner"]
GAUGE_NAMES=["TEX_start","TEX_mg_txt05","TEX_mg_txt07","TEX_gameover","TEX_xstart","TEX_xtext","TEX_xwinner"]

# Entire texture replacement is used only for dedicated text-only textures.
TARGETS={
 "cmnselect.ccs":{
   "TEX_xselect3":{"asset":"cmnselect__TEX_xselect3_KO.png","rects":[(82,8,256,116)]},
 },
 "mapsel1.ccs":{
   "TEX_haipure_s01":{"asset":"mapsel1__TEX_haipure_s01_KO.png","rects":[(245,55,450,135)]},
 },
 "mgn_skill.ccs":{name:{"asset":f"mgn_skill__{name}_KO.png","rects":None} for name in SKILL_NAMES},
 "mgselect.ccs":{name:{"asset":f"mgselect__{name}_KO.png","rects":None} for name in MG_NAMES},
 "title.ccs":{
   "TEX_panel":{"asset":"title__TEX_panel_KO.png","rects":[(0,0,240,172)]},
   "TEX_panel2":{"asset":"title__TEX_panel2_KO.png","rects":[(0,0,240,172)]},
   "TEX_panel3":{"asset":"title__TEX_panel3_KO.png","rects":[(0,0,240,172)]},
 },
 "rpggauge.ccs":{
   "TEX_rpgmenu02":{"asset":"rpggauge__TEX_rpgmenu02_KO.png","rects":None},
 },
 "gauge.ccs":{name:{"asset":f"gauge__{name}_KO.png","rects":None} for name in GAUGE_NAMES},
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
    if pc>10000 or nc>20000 or no+32*nc>len(b):raise RuntimeError("Bad CCS")
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
        return rgba
    raise RuntimeError("Palette missing")

def find_texture(b,name):
    names=ccs_names(b)
    if name not in names:raise RuntimeError("Texture missing "+name)
    wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if typ not in (0x13,0x14) or we>12 or he>12:continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture record missing "+name)

def decode_indices(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    return ix[::-1].copy()

def encode_indices(ix,t):
    ix=ix[::-1].copy()
    if t["type"]==0x13:raw=ix.astype(np.uint8).tobytes()
    else:
        flat=ix.reshape(-1)
        raw=((flat[0::2]&15)|((flat[1::2]&15)<<4)).astype(np.uint8).tobytes()
    if len(raw)!=t["data_len"]:raise RuntimeError("Encoded length mismatch")
    return raw

def nearest_palette_indices(im,pal):
    arr=np.asarray(im.convert("RGBA"),dtype=np.int32);flat=arr.reshape(-1,4)
    p=pal.astype(np.int32);out=np.empty(len(flat),dtype=np.uint8)
    weights=np.array([1,1,1,5],dtype=np.int32)
    for s in range(0,len(flat),4096):
        q=flat[s:s+4096];diff=q[:,None,:]-p[None,:,:]
        out[s:s+4096]=(((diff*diff)*weights).sum(axis=2)).argmin(axis=1).astype(np.uint8)
    return out.reshape(arr.shape[:2])

def patch_texture(ccs,name,png,rects):
    b=bytearray(ccs);t=find_texture(b,name);pal=find_palette(b,t["palette"])
    im=Image.open(png).convert("RGBA")
    if im.size!=(t["width"],t["height"]):raise RuntimeError(f"{name}: PNG size mismatch")
    old=decode_indices(b,t);target=nearest_palette_indices(im,pal);new=old.copy()
    if rects is None:
        new=target
        mask=np.ones(old.shape,dtype=bool)
    else:
        mask=np.zeros(old.shape,dtype=bool)
        for x0,y0,x1,y1 in rects:
            new[y0:y1,x0:x1]=target[y0:y1,x0:x1]
            mask[y0:y1,x0:x1]=True
        if np.any(new[~mask]!=old[~mask]):raise RuntimeError(name+" off-region change")
    raw=encode_indices(new,t);start=t["offset"]+36;b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=t["width"],height=t["height"],
                         rect_mode=("FULL" if rects is None else str(len(rects))),
                         changed_indexed_pixels=int(np.sum(new!=old)),
                         outside_region_changes=0,
                         new_payload_sha256=hashlib.sha256(raw).hexdigest())

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
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB51J authority missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:raise RuntimeError("SUB36 donor missing/SHA mismatch")
    p14=mod("sub51l_p14",root/"analysis/stage14/naruto_patcher.py")
    p15=mod("sub51l_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/8] Extract exact SUB51J DAT/IDX/BOOT",flush=True)
    dat=work/"naruto.dat";idx=work/"naruto.idx";boot=work/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    before_dat=work/"before.dat";shutil.copyfile(dat,before_dat)

    print("[2/8] Patch confirmed residual Japanese UI textures",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    replacements={};rows=[]
    for resource,spec in TARGETS.items():
        old=decode_primary(dat,table,resource,p14);new=old
        for tex,ts in spec.items():
            p=assetdir/ts["asset"]
            if not p.exists():raise RuntimeError("Missing asset "+str(p))
            new,row=patch_texture(new,tex,p,ts["rects"])
            row["resource"]=resource;row["asset_sha256"]=sha256_file(p);rows.append(row)
        if new==old:raise RuntimeError(resource+" unchanged")
        replacements[resource]=dict(original_sha256=p14.sha256(old),new_decoded=new)
    write_tsv(out/"sub51l_texture_patch.tsv",rows,
              ["resource","texture","width","height","rect_mode","changed_indexed_pixels",
               "outside_region_changes","new_payload_sha256","asset_sha256"])

    print("[3/8] Replace primary resources",flush=True)
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
    write_tsv(out/"sub51l_fsts_rebuild.tsv",fstsrows,["bundle","changes"])

    print("[5/8] Verify all non-target primary resources",flush=True)
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
            ("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
            ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot),
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
    write_tsv(out/"sub51l_core_verification.tsv",core,["iso_path","size","sha256","match"])
    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub51l_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51l_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub51l_sha256","match"])

    print("[8/8] Finalize",flush=True)
    report=dict(
        stage="SUB51L_RESIDUAL_SAFE_UI",
        source_sub51j_sha256=SOURCE_SHA,
        final_iso=str(final),final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        resources_changed=sorted(replacements),
        textures_changed=len(rows),
        all_partial_texture_outside_region_changes=0,
        non_target_primary_preserved=preserved,
        fsts_bundles_rebuilt=len(fstsrows),pmf_movies_preserved=len(movies),
        static_qa="PASS",runtime_qa="DEFERRED",
        intentionally_deferred=[
          "gauge.ccs shared TEX_red/TEX_white and complex instruction atlases",
          "mgselect.ccs TEX_mgselect/TEX_mgselect3 small instruction text"
        ],
        bc250_used=False,local_llm_used=False,
    )
    (out/"SUB51L_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51L - Residual Safe UI\n\n"
        f"SourceSUB51J_SHA256={SOURCE_SHA}\nFinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"ResourcesChanged={','.join(sorted(replacements))}\n"
        f"TexturesChanged={len(rows)}\n"
        "PartialTextureOutsideRegionChanges=0\n"
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
