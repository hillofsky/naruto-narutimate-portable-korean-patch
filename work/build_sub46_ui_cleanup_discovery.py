#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,shutil,struct,sys
import numpy as np
from PIL import Image

SECTOR=2048
SOURCE_SHA="d2d913344aeb83bed9ac16910fdbe2371996eba58f376c981e29e9c1a92dae41"
SOURCE_REL=Path("analysis/sub/sub45_menu_followup/Naruto_KR_MOV06E_SUB45_MenuFollowup.iso")
BASE_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
BASE_REL=Path("analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso")
OUT_REL=Path("analysis/sub/sub46_ui_cleanup_discovery")
FINAL_NAME="Naruto_KR_MOV06E_SUB46_UICleanup.iso"

BOOT_RULES=[
 ("home_narup_help",
  'ここでは<RED>“ナルＰロード”<BLACK>で入手した<br>閲覧アイテムを見る事ができます。',
  '<RED>“나루P 로드”<BLACK>에서 얻은<br>감상 아이템을 확인합니다.'),
 ("net_exit_to_mode",
  '対戦を終了してゲームモード選択に戻りますか？',
  '대전을 끝내고 모드 선택으로 돌아갈까요?'),
 ("net_exit_to_lobby",
  '対戦を終了して待機所に戻ります。',
  '대전 종료 후 대기실로 돌아갑니다.'),
 ("net_retry",'再戦する','재대전'),
 ("net_change_char",'キャラクターを変更する','캐릭터 변경'),
 ("net_exit_battle",'対戦を終了する','대전 종료'),
 ("net_same_settings",'同じ設定で対戦します。','같은 설정으로 대전'),
 ("net_change_and_battle",'キャラクターを変更して対戦します。','캐릭터 변경 후 대전'),
 ("net_1p_select",'<RED>１Ｐ<BLACK>が選択しています。','<RED>1P<BLACK>가 선택 중입니다.'),
 ("net_choose_opponent",'対戦する相手を選んで下さい。','대전할 상대를 선택하세요.'),
 ("yes_spaced",'は　い','예'),
 ("no_plain",'いいえ','아니요'),
]

NETWORK_RESOURCE_RULES=[
 ("waiting_room_enter",'待機所に入る','대기실 입장'),
 ("waiting_room_label",'待機所','대기실'),
 ("yes_spaced",'は　い','예'),
 ("no_plain",'いいえ','아니요'),
]

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

def patch_exact_cstr(b,label,jp,kr,mp,rows,scope="BOOT"):
    old=jp.encode("cp932"); miss=missing_hangul(kr,mp)
    if miss:
        rows.append(dict(scope=scope,label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes="",status="SKIP_UNMAPPED",missing="".join(miss)))
        return 0
    new=enc_ko(kr,mp)
    if len(new)>len(old):
        rows.append(dict(scope=scope,label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="SKIP_TOO_LONG",missing=""))
        return 0
    original=bytes(b);pos=0;count=0
    while True:
        i=original.find(old,pos)
        if i<0:break
        pos=i+1;after=i+len(old)
        before_ok=i==0 or original[i-1]==0
        after_ok=after<len(original) and original[after]==0
        if before_ok and after_ok:
            b[i:after]=new+bytes(len(old)-len(new))
            rows.append(dict(scope=scope,label=label,japanese=jp,korean=kr,offset_hex=hex(i),old_bytes=len(old),new_bytes=len(new),status="PATCHED",missing=""))
            count+=1
    if count==0:
        rows.append(dict(scope=scope,label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(old),new_bytes=len(new),status="NOT_FOUND",missing=""))
    return count

def patch_network_decoded(data,name,mp,rows):
    b=bytearray(data);hits=0; waiting_positions=[]
    for label,jp,kr in NETWORK_RESOURCE_RULES:
        before=len(rows);c=patch_exact_cstr(b,label,jp,kr,mp,rows,scope=name)
        hits+=c
        if label=="waiting_room_enter" and c:
            # Recover patched offsets from newly added report rows.
            waiting_positions += [int(r["offset_hex"],16) for r in rows[before:] if r["status"]=="PATCHED" and r["offset_hex"]]
    # If this resource contains the waiting-room menu label, patch nearby standalone 終了 only.
    if waiting_positions:
        old="終了".encode("cp932")
        miss=missing_hangul("종료",mp);new=enc_ko("종료",mp) if not miss else b""
        original=bytes(b)
        for wp in waiting_positions:
            lo=max(0,wp-512);hi=min(len(b),wp+512);pos=lo
            while True:
                i=original.find(old,pos,hi)
                if i<0:break
                pos=i+1;after=i+len(old)
                if after<len(original) and original[after]==0 and (i==0 or original[i-1]==0):
                    if not miss and len(new)<=len(old):
                        b[i:after]=new+bytes(len(old)-len(new))
                        rows.append(dict(scope=name,label="nearby_network_end",japanese="終了",korean="종료",offset_hex=hex(i),old_bytes=len(old),new_bytes=len(new),status="PATCHED",missing=""))
                        hits+=1
                    break
    return bytes(b),hits

def patch_tbl_rhs(data,name,rules,mp,rows):
    lookup={jp.encode("cp932"):(label,jp,kr) for label,jp,kr in rules}
    out=[];count=0
    for line in data.splitlines(keepends=True):
        m=re.match(rb'([^=\r\n]*=)(.*?)(\r*\n)?$',line)
        if m and m[2] in lookup:
            label,jp,kr=lookup[m[2]];miss=missing_hangul(kr,mp)
            if miss:
                rows.append(dict(scope=name,label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(m[2]),new_bytes="",status="SKIP_UNMAPPED",missing="".join(miss)))
                out.append(line);continue
            new=enc_ko(kr,mp)
            out.append(m[1]+new+(m[3] or b""));count+=1
            rows.append(dict(scope=name,label=label,japanese=jp,korean=kr,offset_hex="",old_bytes=len(m[2]),new_bytes=len(new),status="PATCHED_RHS",missing=""))
        else:out.append(line)
    return b"".join(out),count

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

def texture_records(b):
    names=ccs_names(b);magic=bytes.fromhex("0003cccc");out=[]
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        wi=struct.unpack_from("<I",b,o+8)[0]
        if wi>=len(names):continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            out.append(dict(name=names[wi],offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl))
    # Keep first record per name.
    seen=set();ret=[]
    for x in out:
        if x["name"] in seen:continue
        seen.add(x["name"]);ret.append(x)
    return ret

def decode_rgba(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    ix=ix[::-1].copy()
    _,pal=find_palette(b,t["palette"])
    return pal[ix]

def save_ccs_textures(decoded,resource,outdir,inventory,only_names=None):
    outdir.mkdir(parents=True,exist_ok=True)
    try:trs=texture_records(decoded)
    except Exception as e:
        inventory.append(dict(resource=resource,texture="",width="",height="",format="",palette="",png="",note="PARSE_FAIL:"+str(e)));return
    for t in trs:
        if only_names and t["name"] not in only_names:continue
        try:
            rgba=decode_rgba(decoded,t)
            safe=re.sub(r'[^A-Za-z0-9_.-]+','_',t["name"]) or "texture"
            fn=f"{resource.replace('.','_')}__{safe}.png"
            Image.fromarray(rgba,"RGBA").save(outdir/fn)
            inventory.append(dict(resource=resource,texture=t["name"],width=t["width"],height=t["height"],format=hex(t["type"]),palette=t["palette"],png=fn,note=""))
        except Exception as e:
            inventory.append(dict(resource=resource,texture=t["name"],width=t["width"],height=t["height"],format=hex(t["type"]),palette=t["palette"],png="",note="DECODE_FAIL:"+str(e)))

def write_tsv(path,rows,fields):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=r"D:\narutimate portable")
    a=ap.parse_args();root=Path(a.root);source=root/SOURCE_REL;base=root/BASE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True);final=out/FINAL_NAME
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:raise RuntimeError("SUB45 authority ISO missing/SHA mismatch")
    if not base.exists() or sha256_file(base)!=BASE_SHA:raise RuntimeError("SUB36 compact baseline missing/SHA mismatch")
    p14=root/"analysis/stage14/naruto_patcher.py";p15=root/"analysis/stage15/stage15_iso_patcher.py"
    m=mod("sub46_p14",p14);iso=mod("sub46_p15",p15);mp=load_mapping(root)

    print("[1/9] Extract exact SUB45 DAT/IDX/BOOT",flush=True)
    srcdat=out/"source_sub45_naruto.dat";srcidx=out/"source_sub45_naruto.idx";srcboot=out/"source_sub45_BOOT.bin"
    dat=out/"naruto.dat";idx=out/"naruto.idx";boot=out/"BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",srcdat);extract(source,"PSP_GAME/USRDIR/naruto.idx",srcidx);extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",srcboot)
    shutil.copyfile(srcdat,dat);shutil.copyfile(srcidx,idx)

    print("[2/9] Patch confirmed BOOT UI strings",flush=True)
    oldboot=srcboot.read_bytes();bb=bytearray(oldboot);text_rows=[]
    for rule in BOOT_RULES:patch_exact_cstr(bb,*rule,mp,text_rows,scope="BOOT")
    newboot=bytes(bb);boot.write_bytes(newboot)

    print("[3/9] Load PIDX and patch mugen.tbl spaced Yes",flush=True)
    src_ei=m.parse_pidx(m.read_embedded_index(srcdat),"sub45-src")
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,"sub46-emb");xi=m.parse_pidx(xb,"sub46-ext")
    replacements={};discovery=[]

    # Patch exact RHS used by the Mugen confirmation dialog.
    for r in ei["primary"]:
        if r.get("is_folder") or r["name"]!="mugen.tbl":continue
        with dat.open("rb") as f:f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
        dec=m.decode_stored(st,r["size"],r["zsize"])
        new,cnt=patch_tbl_rhs(dec,"mugen.tbl",[
            ("mugen_yes_spaced","は　い","예"),
            ("mugen_no","いいえ","아니요"),
        ],mp,text_rows)
        if cnt:replacements["mugen.tbl"]=dict(original_sha256=m.sha256(dec),new_decoded=new)

    print("[4/9] Inspect/patch network.ccs if text strings are embedded",flush=True)
    texture_inventory=[];discdir=out/"discovery_textures"
    network_found=False
    option_found=False
    for r in ei["primary"]:
        if r.get("is_folder"):continue
        name=r["name"]
        if name not in ("network.ccs","option.ccs"):continue
        with dat.open("rb") as f:f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
        try:dec=m.decode_stored(st,r["size"],r["zsize"])
        except Exception as e:
            discovery.append(dict(resource=name,term="",hits=0,note="DECODE_FAIL:"+str(e)));continue
        if name=="network.ccs":
            network_found=True
            for term in ("待機所に入る","待機所","終了","は　い","いいえ"):
                discovery.append(dict(resource=name,term=term,hits=dec.count(term.encode("cp932")),note=""))
            new,cnt=patch_network_decoded(dec,name,mp,text_rows)
            if cnt:replacements[name]=dict(original_sha256=m.sha256(dec),new_decoded=new)
            save_ccs_textures(new if cnt else dec,name,discdir,texture_inventory,only_names={"TEX_network"})
        else:
            option_found=True
            save_ccs_textures(dec,name,discdir,texture_inventory,only_names={"TEX_option01"})

    print("  network.ccs:",network_found," option.ccs:",option_found,flush=True)
    print("  changed primary resources:",",".join(sorted(replacements)) or "(BOOT only)",flush=True)

    print("[5/9] Append changed resources + update PIDX",flush=True)
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

    print("[6/9] Patch FSTS duplicates",flush=True)
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
            changed_bundles.append(dict(bundle=r["name"],members=";".join(
                str(x.get("name") or x.get("member") or x.get("basename") or x.get("resource") or x)
                if isinstance(x,dict) else str(x) for x in changes)))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)

    print("[7/9] Build compact SUB46 ISO from SUB36 MOV baseline",flush=True)
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

    print("[8/9] Static regression verification",flush=True)
    core=[]
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                    ("PSP_GAME/SYSDIR/BOOT.BIN",boot),("PSP_GAME/SYSDIR/EBOOT.BIN",boot)):
        sz,hs=segsha(final,ip);hh=sha256_file(host);ok=hs==hh
        core.append(dict(iso_path=ip,size=sz,match="YES" if ok else "NO",sha256=hs))
        if not ok:raise RuntimeError("Core verify fail "+ip)

    fin_ei=m.parse_pidx(m.read_embedded_index(dat),"sub46-final");target_names=set(replacements)
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
        movies.append(dict(iso_path=ip,source_sha256=a,sub46_sha256=b,match="YES" if ok else "NO"))
        if not ok:raise RuntimeError("PMF changed "+ip)

    # Changed resources decode exactly to intended bytes.
    verify=[];vei=m.parse_pidx(m.read_embedded_index(dat),"verify")
    with dat.open("rb") as f:
        for name,rr in replacements.items():
            r=next(q for q in vei["primary"] if q["name"]==name);f.seek(r["offset"]);st=f.read(r["zsize"] or r["size"])
            dec=m.decode_stored(st,r["size"],r["zsize"]);ok=dec==rr["new_decoded"]
            verify.append(dict(resource=name,match="YES" if ok else "NO",decoded_sha256=m.sha256(dec)))
            if not ok:raise RuntimeError("Changed resource verify fail "+name)

    write_tsv(out/"sub46_text_patch.tsv",text_rows,["scope","label","japanese","korean","offset_hex","old_bytes","new_bytes","status","missing"])
    write_tsv(out/"sub46_network_discovery.tsv",discovery,["resource","term","hits","note"])
    write_tsv(out/"sub46_texture_inventory.tsv",texture_inventory,["resource","texture","width","height","format","palette","png","note"])
    write_tsv(out/"sub46_fsts_changes.tsv",changed_bundles,["bundle","members"])
    write_tsv(out/"sub46_core_verification.tsv",core,["iso_path","size","match","sha256"])
    write_tsv(out/"sub46_changed_resource_verification.tsv",verify,["resource","match","decoded_sha256"])
    write_tsv(out/"sub46_movie_preservation.tsv",movies,["iso_path","source_sha256","sub46_sha256","match"])

    report=dict(
        stage="SUB46_UI_CLEANUP_DISCOVERY",
        source_iso=str(source),source_iso_sha256=SOURCE_SHA,
        final_iso=str(final),final_iso_size=final.stat().st_size,final_iso_sha256=sha256_file(final),
        boot_or_resource_text_patches=sum(r["status"].startswith("PATCHED") for r in text_rows),
        skipped_unmapped=sum(r["status"]=="SKIP_UNMAPPED" for r in text_rows),
        changed_primary_resources=sorted(target_names),
        network_ccs_found=network_found,option_ccs_found=option_found,
        discovery_textures=len([x for x in texture_inventory if x["png"]]),
        fsts_bundles_changed=[x["bundle"] for x in changed_bundles],
        preserved_non_target_primary_resources=preserved_primary,
        preserved_non_target_fsts_members=preserved_fsts,
        pmf_movies_preserved=len(movies),
        font_mapping_preserved="694+17",new_glyphs_added=0,
        compact_rebuild=True,static_qa="PASS",runtime_qa="REQUIRED",
        known_pending=[
            "Wireless menu image if TEX_network contains the Japanese menu labels.",
            "Option difficulty atlas UV/layout remains pending until extracted/current texture is reviewed.",
        ],
    )
    (out/"SUB46_static_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary=[
        "Naruto PSP SUB46 - UI Cleanup + Network Discovery","",
        f"SourceSHA256={SOURCE_SHA}",f"FinalISO={final}",f"FinalSHA256={report['final_iso_sha256']}",
        f"FinalSize={report['final_iso_size']}",f"TextPatches={report['boot_or_resource_text_patches']}",
        f"SkippedUnmapped={report['skipped_unmapped']}",
        f"ChangedPrimaryResources={','.join(sorted(target_names)) if target_names else '(none)'}",
        f"NetworkCCSFound={network_found}",f"OptionCCSFound={option_found}",
        f"DiscoveryTextures={report['discovery_textures']}",f"FSTSChangedBundles={len(changed_bundles)}",
        f"PreservedPrimaryResources={preserved_primary}",f"PreservedPMFs={len(movies)}",
        "FontMappingPreserved=694+17","NewGlyphsAdded=0","CompactRebuild=YES","StaticQA=PASS","RuntimeQA=REQUIRED"
    ]
    (out/"SUMMARY.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")
    print("[9/9] Done",flush=True);print("\n".join(summary),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
