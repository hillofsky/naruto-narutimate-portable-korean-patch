#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,sys

SECTOR=2048
SOURCE_SHA="7bd72351ac14fc5d7a0774e04290ffaf88b67e1239493938793f037e8530bc92"
SOURCE_REL=Path("analysis/sub/sub48_menu_atlas_cleanup/Naruto_KR_MOV06E_SUB48_MenuAtlasCleanup.iso")
DONOR_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
DONOR_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub49_safe_atlas_rollback")
FINAL_NAME="Naruto_KR_MOV06E_SUB49_SafeAtlasRollback.iso"

# These three atlases were proven unsafe by SUB48 runtime QA.
ROLLBACK_RESOURCES=("option.ccs","gauge.ccs","rpggauge.ccs")

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

def get_decoded_resource(dat_path, table, name, patcher):
    r=next((q for q in table["primary"] if q["name"]==name),None)
    if not r:raise RuntimeError("Resource missing: "+name)
    with Path(dat_path).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return patcher.decode_stored(stored,r["size"],r["zsize"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    a=ap.parse_args()
    root=Path(a.root);source=root/SOURCE_REL;donor=root/DONOR_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB48 authority ISO missing/SHA mismatch")
    if not donor.exists() or sha256_file(donor)!=DONOR_SHA:
        raise RuntimeError("SUB36 donor ISO missing/SHA mismatch")

    p14=mod("sub49_p14",root/"analysis/stage14/naruto_patcher.py")
    p15=mod("sub49_p15",root/"analysis/stage15/stage15_iso_patcher.py")

    print("[1/8] Extract exact SUB48 source and SUB36 donor core",flush=True)
    srcdat=out/"source_sub48_naruto.dat"
    srcidx=out/"source_sub48_naruto.idx"
    srcboot=out/"source_sub48_BOOT.bin"
    dondat=out/"donor_sub36_naruto.dat"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"

    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    extract(donor,"PSP_GAME/USRDIR/naruto.dat",dondat)

    shutil.copyfile(srcdat,dat)
    shutil.copyfile(srcidx,idx)
    shutil.copyfile(srcboot,boot)

    print("[2/8] Prepare exact donor replacements for unsafe shared atlases",flush=True)
    src_ei=p14.parse_pidx(p14.read_embedded_index(srcdat),"sub48-src")
    don_ei=p14.parse_pidx(p14.read_embedded_index(dondat),"sub36-donor")
    eb=bytearray(p14.read_embedded_index(dat))
    xb=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(eb,"sub49-emb")
    xi=p14.parse_pidx(xb,"sub49-ext")

    replacements={}
    rows=[]
    for name in ROLLBACK_RESOURCES:
        srcdec=get_decoded_resource(srcdat,src_ei,name,p14)
        dondec=get_decoded_resource(dondat,don_ei,name,p14)
        replacements[name]=dict(original_sha256=p14.sha256(srcdec),new_decoded=dondec)
        rows.append(dict(
            resource=name,
            sub48_decoded_sha256=p14.sha256(srcdec),
            donor_sub36_decoded_sha256=p14.sha256(dondec),
            changed="YES" if srcdec!=dondec else "NO",
            action="RESTORE_SUB36_EXACT",
        ))
    write_tsv(out/"sub49_rollback_resources.tsv",rows,
              ["resource","sub48_decoded_sha256","donor_sub36_decoded_sha256","changed","action"])

    print("[3/8] Append donor resources and update PIDX",flush=True)
    with dat.open("ab") as f:
        for name,rr in replacements.items():
            encoded=p14.encode_3_0(rr["new_decoded"])
            if p14.decode_3x(encoded)!=rr["new_decoded"]:
                raise RuntimeError("Encode self-check failed "+name)
            off=p14.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["primary"] if q["name"]==name)
                struct.pack_into("<III",blob,q["record_off"]+12,
                                 off,len(rr["new_decoded"]),len(encoded))

    print("[4/8] Restore FSTS preload duplicates",flush=True)
    bundles=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]);bundle=f.read(r["file_size"])
            rebuilt,changes=p14.rebuild_fsts(bundle,r["name"],replacements)
            if not changes:continue
            f.seek(0,2);off=p14.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(q for q in table["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,off,len(rebuilt))
            members=";".join(
                str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x)
                if isinstance(x,dict) else str(x) for x in changes)
            bundles.append(dict(bundle=r["name"],members=members))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub49_fsts_restore.tsv",bundles,["bundle","members"])

    print("[5/8] Build compact SUB49 ISO",flush=True)
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

    print("[6/8] Verify rollback exactness + source preservation",flush=True)
    fin_ei=p14.parse_pidx(p14.read_embedded_index(dat),"sub49-final")
    verify=[]
    for name in ROLLBACK_RESOURCES:
        got=get_decoded_resource(dat,fin_ei,name,p14)
        exp=get_decoded_resource(dondat,don_ei,name,p14)
        ok=got==exp
        verify.append(dict(resource=name,match_donor="YES" if ok else "NO",
                           final_sha256=p14.sha256(got),donor_sha256=p14.sha256(exp)))
        if not ok:raise RuntimeError("Rollback mismatch "+name)
    write_tsv(out/"sub49_rollback_verification.tsv",verify,
              ["resource","match_donor","final_sha256","donor_sha256"])

    targets=set(ROLLBACK_RESOURCES);preserved=0;preserved_fsts=0
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(src_ei["primary"],fin_ei["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in targets:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed "+sr["name"])
            preserved+=1

        srcf={r["index"]:r for r in src_ei["offset2_rows"]}
        finf={r["index"]:r for r in fin_ei["offset2_rows"]}
        for k,sr in srcf.items():
            fr=finf[k]
            sf.seek(sr["file_off"]);sb=sf.read(sr["file_size"])
            ff.seek(fr["file_off"]);fb=ff.read(fr["file_size"])
            if sb==fb:continue
            sa=p14.parse_fsts(sb,"src");fa=p14.parse_fsts(fb,"fin")
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
        if not ok:raise RuntimeError("Core verify fail "+ip)
    write_tsv(out/"sub49_core_verification.tsv",core,["iso_path","size","sha256","match"])

    print("[7/8] Verify all PMFs preserved",flush=True)
    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub49_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub49_movie_preservation.tsv",movies,
              ["iso_path","source_sha256","sub49_sha256","match"])

    report=dict(
        stage="SUB49_SAFE_ATLAS_ROLLBACK",
        source_sub48_sha256=SOURCE_SHA,
        donor_sub36_sha256=DONOR_SHA,
        final_iso=str(final),
        final_iso_size=final.stat().st_size,
        final_iso_sha256=sha256_file(final),
        restored_resources=list(ROLLBACK_RESOURCES),
        boot_source="SUB48_UNCHANGED",
        safe_sub48_text_improvements_preserved=True,
        preserved_non_target_primary_resources=preserved,
        preserved_non_target_fsts_members=preserved_fsts,
        pmf_movies_preserved=len(movies),
        font_mapping="UNCHANGED_FROM_SUB48",
        static_qa="PASS",
        runtime_qa="REQUIRED",
        note="Rollback only visually unsafe shared atlases. No new translation applied."
    )
    (out/"SUB49_static_verification.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB49 - Safe Atlas Rollback\n\n"
        f"SourceSUB48SHA256={SOURCE_SHA}\n"
        f"FinalISO={final}\n"
        f"FinalSHA256={report['final_iso_sha256']}\n"
        f"FinalSize={report['final_iso_size']}\n"
        f"RestoredResources={','.join(ROLLBACK_RESOURCES)}\n"
        "BOOT=SUB48 preserved\n"
        f"PreservedPrimaryResources={preserved}\n"
        f"PMFsPreserved={len(movies)}\n"
        "StaticQA=PASS\nRuntimeQA=REQUIRED\n",
        encoding="utf-8-sig"
    )
    print("[8/8] Done",flush=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
