#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse, csv, hashlib, importlib.util, json, math, shutil, struct, sys, traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SECTOR=2048
KR_ISO_SHA="6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7"
SUB51D_SHA="7138f8c35bacaafab85ff50c12daf0620030cb9b44e7b7bf242168c20c91e845"

RESOURCES={
    "modesel1.ccs":["TEX_mod_bg00","TEX_mod_bg01","TEX_mod_bg03","TEX_mod_bg04","TEX_mod_bg05","TEX_mod_bg06","TEX_mod_bg07"],
    "option.ccs":["TEX_option01"],
    "setting.ccs":["TEX_s_menu1"],
    "charsel1.ccs":["TEX_sel"],
    "mugen.ccs":["TEX_name","TEX_yellow","TEX_white","TEX_red","TEX_mg_icon"]+[f"TEX_prv_{i:03d}" for i in range(1,13)],
    "network.ccs":["TEX_network"],
    "home.ccs":["TEX_mhvid01"],
    "gauge.ccs":["TEX_red","TEX_white"],
    "rpggauge.ccs":["TEX_rpgmenu01","TEX_rpgmenu02","TEX_rpgmenu03","TEX_rpgmenu04"],
}

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

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
        if not hit:raise RuntimeError("ISO missing "+path+" at "+part)
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

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    if pc>10000 or nc>10000 or no+32*nc>len(b):
        raise RuntimeError("Bad CCS name table")
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
    if name not in names:raise KeyError(name)
    wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture record missing "+name)

def decode_texture(b,name):
    t=find_texture(b,name);_,pal=find_palette(b,t["palette"])
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:ix=raw.reshape(t["height"],t["width"]).copy()
    else:ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    ix=ix[::-1].copy()
    return Image.fromarray(pal[ix],"RGBA"),t

def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:raise RuntimeError("Primary resource missing: "+name)
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def make_pair(jp,kr,label,out):
    # Keep exact 1:1 pixels; simply place JP/KR side by side.
    w=max(jp.width,kr.width);h=max(jp.height,kr.height)
    sheet=Image.new("RGBA",(w*2,h),(24,24,24,255))
    sheet.alpha_composite(jp,(0,0));sheet.alpha_composite(kr,(w,0))
    sheet.save(out)

def make_modes_contact(rows,output):
    imgs=[]
    for r in rows:
        if r["resource"]!="modesel1.ccs" or r["status"]!="OK":continue
        jp=Image.open(r["jp_png"]).convert("RGBA");kr=Image.open(r["kr_png"]).convert("RGBA")
        imgs.append((r["texture"],jp,kr))
    if not imgs:return
    W=1024;H=256
    sheet=Image.new("RGBA",(W,len(imgs)*H),(20,20,20,255))
    for i,(_,jp,kr) in enumerate(imgs):
        sheet.alpha_composite(jp,(0,i*H))
        sheet.alpha_composite(kr,(512,i*H))
    sheet.save(output)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"PROJECT_ROOT")
    ap.add_argument("--jp-bundle",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.root);bundle=Path(a.jp_bundle);out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)

    kr_iso=root/"kr"/"Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso"
    sub51d=root/"analysis/sub/sub51d_full_text_apply/Naruto_KR_MOV06E_SUB51D_FullText.iso"
    patcher=root/"analysis/stage14/naruto_patcher.py"
    if not kr_iso.exists():raise RuntimeError("Official Korean ISO missing: "+str(kr_iso))
    if not patcher.exists():raise RuntimeError("Stage14 patcher missing: "+str(patcher))

    krsha=sha256_file(kr_iso)
    print("Official KR ISO SHA256:",krsha,flush=True)
    if krsha!=KR_ISO_SHA:raise RuntimeError("Official Korean ISO SHA mismatch")
    if not sub51d.exists():raise RuntimeError("SUB51D ISO missing")
    dsha=sha256_file(sub51d)
    if dsha!=SUB51D_SHA:raise RuntimeError("SUB51D SHA mismatch: "+dsha)

    m=mod("sub51f_stage14",patcher)
    work=out/"_work";work.mkdir(exist_ok=True)
    krdat=work/"kr_naruto.dat"
    print("[1/5] Extract official Korean naruto.dat",flush=True)
    extract(kr_iso,"PSP_GAME/USRDIR/naruto.dat",krdat)
    table=m.parse_pidx(m.read_embedded_index(krdat),"sub51f-kr")

    print("[2/5] Decode official Korean UI CCS resources",flush=True)
    krccsdir=out/"official_kr_ccs";krccsdir.mkdir(exist_ok=True)
    jpccsdir=out/"pristine_jp_ccs";jpccsdir.mkdir(exist_ok=True)
    for res in RESOURCES:
        dec=decode_primary(krdat,table,res,m)
        (krccsdir/res).write_bytes(dec)
        src=bundle/res
        if not src.exists():raise RuntimeError("Bundled pristine JP CCS missing: "+res)
        shutil.copy2(src,jpccsdir/res)

    print("[3/5] Decode requested textures and compare JP vs official KR",flush=True)
    jp_png_dir=out/"jp_png";kr_png_dir=out/"official_kr_png";pair_dir=out/"pairs"
    for d in (jp_png_dir,kr_png_dir,pair_dir):d.mkdir(exist_ok=True)
    rows=[]
    for res,texnames in RESOURCES.items():
        jpb=(jpccsdir/res).read_bytes();krb=(krccsdir/res).read_bytes()
        jnames=set(ccs_names(jpb));knames=set(ccs_names(krb))
        for tex in texnames:
            row={"resource":res,"texture":tex}
            if tex not in jnames or tex not in knames:
                row.update(status="MISSING",jp_present=str(tex in jnames),kr_present=str(tex in knames))
                rows.append(row);continue
            try:
                jpi,jt=decode_texture(jpb,tex);kri,kt=decode_texture(krb,tex)
            except Exception as e:
                row.update(status="DECODE_FAIL",error=str(e))
                rows.append(row);continue
            safe=(res.replace(".ccs","")+"__"+tex)
            jpp=jp_png_dir/(safe+"_JP.png");krp=kr_png_dir/(safe+"_KR.png");pp=pair_dir/(safe+"_JP_vs_KR.png")
            jpi.save(jpp);kri.save(krp);make_pair(jpi,kri,safe,pp)
            arrj=np.asarray(jpi);arrk=np.asarray(kri)
            same_shape=arrj.shape==arrk.shape
            changed=int(np.any(arrj!=arrk,axis=2).sum()) if same_shape else -1
            row.update(
                status="OK",
                jp_present="True",kr_present="True",
                jp_width=jt["width"],jp_height=jt["height"],jp_type=hex(jt["type"]),
                kr_width=kt["width"],kr_height=kt["height"],kr_type=hex(kt["type"]),
                dimensions_match=str((jt["width"],jt["height"])==(kt["width"],kt["height"])),
                changed_pixels=changed,
                jp_png=str(jpp),kr_png=str(krp),pair_png=str(pp),
                jp_ccs_sha256=hashlib.sha256(jpb).hexdigest(),
                kr_ccs_sha256=hashlib.sha256(krb).hexdigest(),
            )
            rows.append(row)

    fields=["resource","texture","status","jp_present","kr_present",
            "jp_width","jp_height","jp_type","kr_width","kr_height","kr_type",
            "dimensions_match","changed_pixels","jp_png","kr_png","pair_png",
            "jp_ccs_sha256","kr_ccs_sha256","error"]
    write_tsv(out/"official_kr_ui_texture_comparison.tsv",rows,fields)

    print("[4/5] Build main-menu JP/KR contact sheet",flush=True)
    make_modes_contact(rows,out/"modesel1_official_JP_vs_KR.png")

    ok=[r for r in rows if r["status"]=="OK"]
    modes=[r for r in ok if r["resource"]=="modesel1.ccs"]
    modes_compatible=(len(modes)==7 and all(r["dimensions_match"]=="True" for r in modes))
    summary={
        "stage":"SUB51F_OFFICIAL_KR_UI_DONOR_DISCOVERY",
        "official_kr_iso_sha256":krsha,
        "sub51d_sha256":dsha,
        "resources_decoded":len(RESOURCES),
        "textures_requested":sum(len(v) for v in RESOURCES.values()),
        "textures_decoded":len(ok),
        "modesel1_textures_decoded":len(modes),
        "modesel1_dimensions_compatible":modes_compatible,
        "game_data_modified":False,
        "ppsspp_executed":False,
        "bc250_used":False,
        "local_llm_used":False,
        "next":"Use official KR textures as style/texture donors when compatible; patch into SUB51D only after review."
    }
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto SUB51F - Official Korean UI Donor Discovery\n\n"
        f"OfficialKRISO_SHA256={krsha}\n"
        f"SUB51D_SHA256={dsha}\n"
        f"ResourcesDecoded={len(RESOURCES)}\n"
        f"TexturesDecoded={len(ok)}/{sum(len(v) for v in RESOURCES.values())}\n"
        f"ModeSelDecoded={len(modes)}/7\n"
        f"ModeSelDimensionsCompatible={'YES' if modes_compatible else 'NO'}\n"
        "GameDataModified=NO\nPPSSPPExecuted=NO\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig"
    )
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
