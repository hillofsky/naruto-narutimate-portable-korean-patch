#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,shutil,struct,sys
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="0aa25f739c76d7143591f38991ff65a026d1d5ceae73075d4402d13664667264"
SOURCE_REL=Path("analysis/sub/sub44_ui_cleanup/Naruto_KR_MOV06E_SUB44_UITextCleanup.iso")
BASE_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
BASE_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub45_menu_followup")
FINAL_NAME="Naruto_KR_MOV06E_SUB45_MenuFollowup.iso"

PREVIEW_TITLES={
 "TEX_prv_001":"TEX_prv_001_ko.png",
 "TEX_prv_002":"TEX_prv_002_ko.png",
 "TEX_prv_003":"TEX_prv_003_ko.png",
 "TEX_prv_004":"TEX_prv_004_ko.png",
 "TEX_prv_005":"TEX_prv_005_ko.png",
 "TEX_prv_006":"TEX_prv_006_ko.png",
 "TEX_prv_007":"TEX_prv_007_ko.png",
 "TEX_prv_008":"TEX_prv_008_ko.png",
 "TEX_prv_009":"TEX_prv_009_ko.png",
 "TEX_prv_010":"TEX_prv_010_ko.png",
 "TEX_prv_011":"TEX_prv_011_ko.png",
 "TEX_prv_012":"TEX_prv_012_ko.png",
}

# Exact RHS replacements in line-oriented *.tbl resources.
GENERIC_TBL_RULES={
 "待機所に入る":"대기실 입장",
 "終了":"종료",
 "はい":"예",
 "いいえ":"아니요",
 "待機所にいる相手と通信対戦をします。":"대기실 상대와 통신 대전합니다.",
 "対戦を終了して待機所に戻ります。":"대전을 끝내고 대기실로 돌아갑니다.",
 "対戦を終了してゲームモード選択に戻りますか？":"대전을 끝내고 모드 선택으로 돌아갈까요?",
}
MUGEN_TBL_RULES={
 "操作方法　：　<iconKEY>移動　　　<iconTRIANGLE>メニュー":
     "조작: <iconKEY>이동  <iconTRIANGLE>메뉴",
 "操作方法　：　<iconKEY>移動　　　<iconTRIANGLE>メニュー　　<iconCIRCLE>階段を上がる":
     "조작: <iconKEY>이동  <iconTRIANGLE>메뉴  <iconCIRCLE>위층 계단",
 "操作方法　：　<iconKEY>移動　　　<iconTRIANGLE>メニュー　　<iconCIRCLE>階段を下りる":
     "조작: <iconKEY>이동  <iconTRIANGLE>메뉴  <iconCIRCLE>아래층 계단",
 "操作方法　：　<iconKEY>移動　　　<iconTRIANGLE>メニュー　　<iconCIRCLE>部屋に入る":
     "조작: <iconKEY>이동  <iconTRIANGLE>메뉴  <iconCIRCLE>방 입장",
 "この空間に部屋を口寄せしますか？　　<iconCIRCLE>はい　　<iconCROSS>いいえ":
     "이 공간에 방을 불러올까요?  <iconCIRCLE>예  <iconCROSS>아니요",
 "　<iconCIRCLE>はい　　　<iconCROSS>いいえ":
     "<iconCIRCLE>예  <iconCROSS>아니요",
 "　　　　　　　　　　　　　　　　　　<iconCIRCLE>はい　　<iconCROSS>いいえ":
     "<iconCIRCLE>예  <iconCROSS>아니요",
}

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
    with Path(iso).open("rb") as f:f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("Bad ISO")
    r=p[156:190];return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

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
        if not p.exists():raise RuntimeError(f"Font map missing: {p}")
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                if r.get("hangul") and r.get("donor_sjis_hex"):
                    mp[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
    return mp

def enc_ko(s,mp):
    out=bytearray()
    for c in s:
        if c in mp:out+=mp[c]
        elif c==" ":out+=b"\xA0"
        else:out+=c.encode("cp932")
    return bytes(out)

def missing_hangul(s,mp):
    return sorted({c for c in s if "가"<=c<="힣" and c not in mp})

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def find_palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic:continue
        if struct.unpack_from("<I",b,o+8)[0]!=palid:continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b):continue
        raw=np.frombuffer(b[o+28:o+28+n*4],dtype=np.uint8).reshape(-1,4).copy()
        rgba=raw[:,[2,1,0,3]];rgba[:,3]=np.minimum(rgba[:,3].astype(np.int16)*2,255).astype(np.uint8)
        return o,rgba
    raise RuntimeError(f"Palette {palid} missing")

def find_texture(b,name):
    names=ccs_names(b)
    if name not in names:raise RuntimeError(f"Texture name missing: {name}")
    wi=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        if struct.unpack_from("<I",b,o+8)[0]!=wi:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError(f"Texture record missing: {name}")

def decode_ix(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    return ix[::-1].copy()

def encode_ix(ix,typ):
    flat=ix[::-1].reshape(-1).astype(np.uint8)
    if typ==0x13:return flat.tobytes()
    return (flat[::2]|(flat[1::2]<<4)).astype(np.uint8).tobytes()

def patch_texture(b,name,png):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"]);oldix=decode_ix(b,t);oldrgba=pal[oldix]
    repl=np.asarray(Image.open(png).convert("RGBA"),dtype=np.uint8)
    if repl.shape[:2]!=(t["height"],t["width"]):raise RuntimeError(f"Size mismatch {name}")
    same=np.all(repl==oldrgba,axis=2);changed=~same;newix=oldix.copy()
    if np.any(changed):
        pe=pal.astype(np.float32);pe[:,:3]*=pe[:,3:4]/255.0
        px=repl[changed].astype(np.float32);px[:,:3]*=px[:,3:4]/255.0
        chosen=np.empty(len(px),dtype=np.uint8)
        for s in range(0,len(px),4096):
            q=px[s:s+4096];dist=((q[:,None,:]-pe[None,:,:])**2).sum(axis=2)
            chosen[s:s+len(q)]=dist.argmin(axis=1).astype(np.uint8)
        newix[changed]=chosen
    packed=encode_ix(newix,t["type"]);a=t["offset"]+36;b[a:a+len(packed)]=packed
    return dict(texture=name,width=t["width"],height=t["height"],format=hex(t["type"]),palette=t["palette"],changed_pixels=int(changed.sum()),replacement=Path(png).name)

def patch_table(decoded,name,rules,mp,rows):
    lookup={jp.encode("cp932"):(jp,kr) for jp,kr in rules.items()}
    out=[];count=0
    for line in decoded.splitlines(keepends=True):
        hit=re.match(rb'([^=\r\n]*=)(.*?)(\r*\n)?$',line)
        if hit and hit[2] in lookup:
            jp,kr=lookup[hit[2]]
            miss=missing_hangul(kr,mp)
            if miss:
                rows.append(dict(resource=name,japanese=jp,korean=kr,status="SKIP_UNMAPPED",missing="".join(miss)))
                out.append(line);continue
            out.append(hit[1]+enc_ko(kr,mp)+(hit[3] or b""))
            rows.append(dict(resource=name,japanese=jp,korean=kr,status="PATCHED",missing=""))
            count+=1
        else:out.append(line)
    return b"".join(out),count

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=r"D:\narutimate portable");ap.add_argument("--assets",default=None)
    a=ap.parse_args();root=Path(a.root);assets=Path(a.assets) if a.assets else Path(__file__).resolve().parent/"sub45_assets"
    source=root/SOURCE_REL;base=root/BASE_REL;out=root/OUT_REL;out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB44 authority ISO missing/SHA mismatch")
    if not base.exists() or sha256_file(base)!=BASE_SHA:raise RuntimeError("SUB36 compact baseline missing/SHA mismatch")
    p14=root/"analysis/stage14/naruto_patcher.py";p15=root/"analysis/stage15/stage15_iso_patcher.py"
    m=mod("sub45_p14",p14);iso=mod("sub45_p15",p15);mp=load_mapping(root)

    print("[1/8] Extract exact SUB44 DAT/IDX/BOOT",flush=True)
    srcdat=out/"source_sub44_naruto.dat";srcidx=out/"source_sub44_naruto.idx";srcboot=out/"source_sub44_BOOT.bin"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat);extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx);extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    shutil.copyfile(srcdat,dat);shutil.copyfile(srcidx,idx);shutil.copyfile(srcboot,boot)

    src_eb=m.read_embedded_index(srcdat);src_ei=m.parse_pidx(src_eb,"sub44-src")
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub45-emb");xi=m.parse_pidx(xb,"sub45-ext")

    replacements={};texture_rows=[];table_rows=[];discovery=[]
    print("[2/8] Patch 12 Mugen room preview titles",flush=True)
    rec=next((r for r in ei["primary"] if r["name"]=="mugen.ccs"),None)
    if not rec:raise RuntimeError("mugen.ccs missing")
    with dat.open("rb") as f:
        f.seek(rec["offset"]);stored=f.read(rec["zsize"] or rec["size"])
    old=m.decode_stored(stored,rec["size"],rec["zsize"]);bb=bytearray(old)
    for tex,pngname in PREVIEW_TITLES.items():
        png=assets/pngname
        if not png.exists():raise RuntimeError("Missing asset "+str(png))
        row=patch_texture(bb,tex,png);row["resource"]="mugen.ccs";texture_rows.append(row)
    replacements["mugen.ccs"]=dict(original_sha256=m.sha256(old),new_decoded=bytes(bb))

    print("[3/8] Patch remaining line-oriented TBL UI text",flush=True)
    for r in ei["primary"]:
        name=r["name"]
        if r.get("is_folder") or not name.lower().endswith(".tbl"):continue
        with dat.open("rb") as f:
            f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
        try:dec=m.decode_stored(st,r["size"],r["zsize"])
        except Exception as e:
            discovery.append(dict(resource=name,term="",hits=0,note="DECODE_FAIL"));continue
        rules=dict(GENERIC_TBL_RULES)
        if name=="mugen.tbl":rules.update(MUGEN_TBL_RULES)
        # Discovery counts before patch.
        for jp in rules:
            h=dec.count(jp.encode("cp932"))
            if h:discovery.append(dict(resource=name,term=jp,hits=h,note=""))
        new,cnt=patch_table(dec,name,rules,mp,table_rows)
        if cnt:
            replacements[name]=dict(original_sha256=m.sha256(dec),new_decoded=new)

    print("  changed resources:",", ".join(sorted(replacements)),flush=True)
    print("[4/8] Append changed primary resources + update PIDX",flush=True)
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

    print("[5/8] Patch FSTS preload duplicates",flush=True)
    changed_bundles=[]
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
            changed_bundles.append(dict(
                bundle=r["name"],
                members=";".join(
                    str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x)
                    if isinstance(x,dict) else str(x)
                    for x in changes
                )
            ))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)

    print("[6/8] Build compact SUB45 ISO from exact SUB36 MOV baseline",flush=True)
    if final.exists():final.unlink()
    shutil.copyfile(base,final)
    with final.open("r+b") as f:
        vds=iso.read_volume_descriptors(f)
        for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                        ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot)):
            recs=[iso.find_path(f,vd,ip.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext=iso.append_file_sector_aligned(f,host,host.name)
            for q in recs:
                if q:iso.patch_directory_record(f,q["record_offset"],ext["lba"],ext["size"])
        f.seek(0,2);iso.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print("[7/8] Static regression verification",flush=True)
    core=[]
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                    ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot)):
        sz,hs=segsha(final,ip);hh=sha256_file(host);ok=hs==hh
        core.append(dict(iso_path=ip,size=sz,match="YES" if ok else "NO",sha256=hs))
        if not ok:raise RuntimeError("Core verify fail "+ip)

    fin_ei=m.parse_pidx(m.read_embedded_index(dat),"sub45-final")
    target_names=set(replacements)
    preserved_primary=0;preserved_fsts=0
    with srcdat.open("rb") as sf,dat.open("rb") as ff:
        for sr,fr in zip(src_ei["primary"],fin_ei["primary"]):
            if sr["name"]!=fr["name"]:raise RuntimeError("Primary order changed")
            if sr.get("is_folder") or sr["name"] in target_names:continue
            sf.seek(sr["offset"]);sb=sf.read(sr["zsize"] or sr["size"])
            ff.seek(fr["offset"]);fb=ff.read(fr["zsize"] or fr["size"])
            if sb!=fb:raise RuntimeError("Untargeted primary changed: "+sr["name"])
            preserved_primary+=1
        srcf={r["index"]:r for r in src_ei["offset2_rows"]};finf={r["index"]:r for r in fin_ei["offset2_rows"]}
        for k,sr in srcf.items():
            fr=finf[k];sf.seek(sr["file_off"]);sb=sf.read(sr["file_size"]);ff.seek(fr["file_off"]);fb=ff.read(fr["file_size"])
            if sb==fb:continue
            sa=m.parse_fsts(sb,"s");fa=m.parse_fsts(fb,"f")
            for sx,fx in zip(sa["members"],fa["members"]):
                if sx["name"]!=fx["name"]:raise RuntimeError("FSTS order changed")
                if sx["basename"] not in target_names:
                    if sx["stored"]!=fx["stored"]:raise RuntimeError(f"Untargeted FSTS changed: {sr['name']} / {sx['name']}")
                    preserved_fsts+=1

    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip);_,b=segsha(final,ip);ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,sub45_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)

    # Verify changed decoded primary resources are exactly the intended outputs.
    verify=[]
    fei=m.parse_pidx(m.read_embedded_index(dat),"verify")
    with dat.open("rb") as f:
        for name,rr in replacements.items():
            r=next(q for q in fei["primary"] if q["name"]==name);f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
            dec=m.decode_stored(st,r["size"],r["zsize"]);ok=dec==rr["new_decoded"]
            verify.append(dict(resource=name,match="YES" if ok else "NO",decoded_sha256=m.sha256(dec)))
            if not ok:raise RuntimeError("Changed resource verify fail "+name)

    write_tsv(out/"sub45_texture_patch.tsv",texture_rows,["resource","texture","width","height","format","palette","changed_pixels","replacement"])
    write_tsv(out/"sub45_table_text_patch.tsv",table_rows,["resource","japanese","korean","status","missing"])
    write_tsv(out/"sub45_table_discovery.tsv",discovery,["resource","term","hits","note"])
    write_tsv(out/"sub45_fsts_changes.tsv",changed_bundles,["bundle","members"])
    write_tsv(out/"sub45_core_verification.tsv",core,["iso_path","size","match","sha256"])
    write_tsv(out/"sub45_changed_resource_verification.tsv",verify,["resource","match","decoded_sha256"])
    write_tsv(out/"sub45_movie_preservation.tsv",movies,["iso_path","source_sha256","sub45_sha256","match"])

    report=dict(
        stage="SUB45_FIX1_MENU_FOLLOWUP",
        source_iso=str(source),source_iso_sha256=SOURCE_SHA,
        compact_baseline=str(base),compact_baseline_sha256=BASE_SHA,
        final_iso=str(final),final_iso_size=final.stat().st_size,final_iso_sha256=sha256_file(final),
        changed_primary_resources=sorted(target_names),
        preview_textures_patched=len(texture_rows),
        table_lines_patched=sum(r["status"]=="PATCHED" for r in table_rows),
        table_lines_skipped_unmapped=sum(r["status"]=="SKIP_UNMAPPED" for r in table_rows),
        fsts_bundles_changed=[r["bundle"] for r in changed_bundles],
        preserved_non_target_primary_resources=preserved_primary,
        preserved_non_target_fsts_members=preserved_fsts,
        pmf_movies_preserved=len(movies),
        font_mapping_preserved="694+17",new_glyphs_added=0,
        compact_rebuild=True,static_qa="PASS",runtime_qa="REQUIRED",
    )
    (out/"SUB45_static_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary=[
        "Naruto PSP SUB45 FIX1 - Menu Follow-up","",
        f"SourceSHA256={SOURCE_SHA}",f"FinalISO={final}",f"FinalSHA256={report['final_iso_sha256']}",
        f"FinalSize={report['final_iso_size']}",f"PreviewTexturesPatched={len(texture_rows)}",
        f"TableLinesPatched={report['table_lines_patched']}",f"TableLinesSkippedUnmapped={report['table_lines_skipped_unmapped']}",
        f"ChangedPrimaryResources={','.join(sorted(target_names))}",f"FSTSChangedBundles={len(changed_bundles)}",
        f"PreservedPrimaryResources={preserved_primary}",f"PreservedPMFs={len(movies)}",
        "FontMappingPreserved=694+17","NewGlyphsAdded=0","CompactRebuild=YES","StaticQA=PASS","RuntimeQA=REQUIRED"
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("[8/8] Done",flush=True);print("\n".join(summary),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
