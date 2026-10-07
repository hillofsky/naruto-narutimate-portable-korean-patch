#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys

SECTOR=2048
SOURCE_SHA="5ace9a1a17cd978579c79abf141bda7e5448c58fcc3638182c2525453fd9bad9"
SOURCE_REL=Path("analysis/sub/sub49_safe_atlas_rollback/Naruto_KR_MOV06E_SUB49_SafeAtlasRollback.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub50_mugen_atlas_surgical_restore")
FINAL_NAME="Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso"
TARGET_RESOURCE="mugen.ccs"
TARGET_TEXTURES=("TEX_red","TEX_white")

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

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def get_decoded(dat_path,table,name,m):
    r=next((q for q in table["primary"] if q["name"]==name),None)
    if not r:raise RuntimeError("Resource missing: "+name)
    with Path(dat_path).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44)
    no=0x4C+32*pc
    return [
        b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace")
        for i in range(nc)
    ]

def find_texture(b,name):
    names=ccs_names(b)
    if name not in names:raise RuntimeError("CCS name not found: "+name)
    wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    candidates=[]
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        if struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0]
        typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he
        dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            candidates.append(dict(offset=o,palette=palid,type=typ,width=w,height=h,
                                   data_off=o+36,data_len=dl))
    if len(candidates)!=1:
        raise RuntimeError(f"{name}: expected 1 texture, found {len(candidates)}")
    return candidates[0]

def payload_sha(b,t):
    return hashlib.sha256(b[t["data_off"]:t["data_off"]+t["data_len"]]).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    a=ap.parse_args()
    root=Path(a.root);source=root/SOURCE_REL;donor=root/DONOR_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB49 authority ISO missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:
        raise RuntimeError("SUB36 donor ISO missing/SHA mismatch")

    m=mod("sub50_p14",root/"analysis/stage14/naruto_patcher.py")
    iso=mod("sub50_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/9] Extract exact SUB49 source + SUB36 donor",flush=True)
    srcdat=out/"source_sub49_naruto.dat";srcidx=out/"source_sub49_naruto.idx";srcboot=out/"source_sub49_BOOT.bin"
    dondat=out/"donor_sub36_naruto.dat"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    extract(donor,"PSP_GAME/USRDIR/naruto.dat",dondat)
    shutil.copyfile(srcdat,dat);shutil.copyfile(srcidx,idx);shutil.copyfile(srcboot,boot)

    print("[2/9] Load current/donor mugen.ccs",flush=True)
    src_ei=m.parse_pidx(m.read_embedded_index(srcdat),"sub49-src")
    don_ei=m.parse_pidx(m.read_embedded_index(dondat),"sub36-donor")
    current=get_decoded(srcdat,src_ei,TARGET_RESOURCE,m)
    donor_mugen=get_decoded(dondat,don_ei,TARGET_RESOURCE,m)
    if len(current)!=len(donor_mugen):
        raise RuntimeError(f"mugen.ccs decoded size mismatch current={len(current)} donor={len(donor_mugen)}")

    print("[3/9] Surgically restore TEX_red/TEX_white payload bytes only",flush=True)
    new=bytearray(current);rows=[];allowed=[]
    for name in TARGET_TEXTURES:
        ct=find_texture(current,name);dt=find_texture(donor_mugen,name)
        meta=("type","width","height","data_len","palette")
        mism=[k for k in meta if ct[k]!=dt[k]]
        if mism:
            raise RuntimeError(f"{name} texture metadata mismatch: {mism}")
        a=ct["data_off"];b=a+ct["data_len"]
        da=dt["data_off"];db=da+dt["data_len"]
        before=bytes(new[a:b]);after=donor_mugen[da:db]
        new[a:b]=after
        allowed.append((a,b,name))
        rows.append(dict(
            texture=name,
            width=ct["width"],height=ct["height"],type=hex(ct["type"]),
            palette=ct["palette"],data_len=ct["data_len"],
            source_payload_sha256=hashlib.sha256(before).hexdigest(),
            donor_payload_sha256=hashlib.sha256(after).hexdigest(),
            changed="YES" if before!=after else "NO",
            final_payload_sha256=hashlib.sha256(bytes(new[a:b])).hexdigest(),
        ))
    new=bytes(new)

    # Prove every changed decoded byte is inside only the two target payload ranges.
    diff=[i for i,(a,b) in enumerate(zip(current,new)) if a!=b]
    outside=[]
    for i in diff:
        if not any(lo<=i<hi for lo,hi,_ in allowed):outside.append(i)
    if outside:
        raise RuntimeError(f"Unexpected mugen.ccs byte changes outside targets: first={outside[0]:#x}")
    print("  changed decoded bytes:",len(diff),flush=True)
    write_tsv(out/"sub50_texture_payload_restore.tsv",rows,
              ["texture","width","height","type","palette","data_len",
               "source_payload_sha256","donor_payload_sha256","changed","final_payload_sha256"])

    print("[4/9] Append surgically repaired mugen.ccs + update PIDX",flush=True)
    replacements={TARGET_RESOURCE:dict(original_sha256=m.sha256(current),new_decoded=new)}
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub50-emb");xi=m.parse_pidx(xb,"sub50-ext")
    with dat.open("ab") as f:
        encoded=m.encode_3_0(new)
        if m.decode_3x(encoded)!=new:raise RuntimeError("mugen.ccs encode self-check failed")
        off=m.align_up(f.tell())
        if off>f.tell():f.write(bytes(off-f.tell()))
        f.write(encoded)
        for blob,table in ((eb,ei),(xb,xi)):
            q=next(q for q in table["primary"] if q["name"]==TARGET_RESOURCE)
            struct.pack_into("<III",blob,q["record_off"]+12,off,len(new),len(encoded))

    print("[5/9] Patch mugen.ccs FSTS preload duplicates",flush=True)
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
    write_tsv(out/"sub50_fsts_changes.tsv",bundles,["bundle","members"])

    print("[6/9] Build compact SUB50 ISO",flush=True)
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

    print("[7/9] Verify surgical restore and all non-target data",flush=True)
    fin_ei=m.parse_pidx(m.read_embedded_index(dat),"sub50-final")
    final_mugen=get_decoded(dat,fin_ei,TARGET_RESOURCE,m)
    if final_mugen!=new:raise RuntimeError("Final mugen.ccs decoded mismatch")

    vr=[]
    for row in rows:
        n=row["texture"];ft=find_texture(final_mugen,n);dt=find_texture(donor_mugen,n)
        got=final_mugen[ft["data_off"]:ft["data_off"]+ft["data_len"]]
        exp=donor_mugen[dt["data_off"]:dt["data_off"]+dt["data_len"]]
        ok=got==exp
        vr.append(dict(texture=n,match_donor_payload="YES" if ok else "NO",
                       final_payload_sha256=hashlib.sha256(got).hexdigest(),
                       donor_payload_sha256=hashlib.sha256(exp).hexdigest()))
        if not ok:raise RuntimeError("Donor payload mismatch "+n)
    write_tsv(out/"sub50_texture_restore_verification.tsv",vr,
              ["texture","match_donor_payload","final_payload_sha256","donor_payload_sha256"])

    # Whole mugen.ccs must differ from SUB49 only inside the two target payload ranges.
    fin_diff=[i for i,(a,b) in enumerate(zip(current,final_mugen)) if a!=b]
    if fin_diff!=diff:raise RuntimeError("Final mugen diff set changed unexpectedly")

    targets={TARGET_RESOURCE};preserved_primary=0;preserved_fsts=0
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(src_ei["primary"],fin_ei["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in targets:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed "+sr["name"])
            preserved_primary+=1

        srcf={r["index"]:r for r in src_ei["offset2_rows"]}
        finf={r["index"]:r for r in fin_ei["offset2_rows"]}
        for k,sr in srcf.items():
            fr=finf[k]
            sf.seek(sr["file_off"]);sb=sf.read(sr["file_size"])
            ff.seek(fr["file_off"]);fb=ff.read(fr["file_size"])
            if sb==fb:continue
            sa=m.parse_fsts(sb,"src");fa=m.parse_fsts(fb,"fin")
            for sx,fx in zip(sa["members"],fa["members"]):
                if sx["name"]!=fx["name"]:raise RuntimeError("FSTS order changed")
                if sx["basename"] not in targets:
                    if sx["stored"]!=fx["stored"]:
                        raise RuntimeError(f"Untargeted FSTS changed {sr['name']} / {sx['name']}")
                    preserved_fsts+=1

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
    write_tsv(out/"sub50_core_verification.tsv",core,["iso_path","size","sha256","match"])

    print("[8/9] Verify all PMFs preserved",flush=True)
    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub50_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub50_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub50_sha256","match"])

    report=dict(
        stage="SUB50_MUGEN_ATLAS_SURGICAL_RESTORE",
        source_sub49_sha256=SOURCE_SHA,
        donor_sub36_sha256=DONOR_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        target_resource=TARGET_RESOURCE,
        restored_texture_payloads=list(TARGET_TEXTURES),
        mugen_decoded_changed_bytes=len(diff),
        changes_outside_target_payloads=0,
        whole_mugen_other_data_preserved_from_sub49=True,
        boot_preserved_from_sub49=True,
        preserved_non_target_primary_resources=preserved_primary,
        preserved_non_target_fsts_members=preserved_fsts,
        pmf_movies_preserved=len(movies),
        static_qa="PASS",
        runtime_qa="REQUIRED",
        note="Only TEX_red/TEX_white texture index payload bytes were restored from SUB36."
    )
    (out/"SUB50_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB50 - Mugen Atlas Surgical Restore\n\n"
        f"SourceSUB49SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"FinalSize={report['final_iso_size']}\n"
        "TargetResource=mugen.ccs\n"
        "RestoredTextures=TEX_red,TEX_white\n"
        f"MugenDecodedChangedBytes={len(diff)}\n"
        "ChangesOutsideTargetPayloads=0\n"
        f"PreservedPrimaryResources={preserved_primary}\n"
        f"PMFsPreserved={len(movies)}\n"
        "StaticQA=PASS\nRuntimeQA=REQUIRED\n",
        encoding="utf-8-sig"
    )
    print("[9/9] Done",flush=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
