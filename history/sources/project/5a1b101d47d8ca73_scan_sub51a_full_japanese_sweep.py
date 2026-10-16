#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,struct,sys,math,traceback
import numpy as np
from PIL import Image,ImageDraw,ImageFont

SECTOR=2048
SOURCE_SHA="5a750d02fc701c110106711dedfc3e19b34b32f1833ccbef811f3d55441f87b9"
SOURCE_REL=Path("analysis/sub/sub50_mugen_atlas_surgical_restore/Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso")
OUT_REL=Path("analysis/sub/sub51a_full_japanese_sweep")

JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")
UI_TERMS=(
    "mugen","gauge","rpggauge","option","setting","modesel","charsel","home",
    "network","menu","select","title","result","mission","load","save","status",
    "item","skill","mode","navi","map","room","common","cmn","battle","versus",
    "system","help","tutorial","stage","story","gallery","movie","music","photo"
)

HIGH_PRIORITY={
    "modesel1.ccs":{"TEX_mod_bg00","TEX_mod_bg01","TEX_mod_bg03","TEX_mod_bg04","TEX_mod_bg05","TEX_mod_bg06","TEX_mod_bg07","TEX_makimono"},
    "option.ccs":{"TEX_option01"},
    "setting.ccs":{"TEX_s_menu1"},
    "charsel1.ccs":{"TEX_sel"},
    "home.ccs":{"TEX_mhback01","TEX_mhrec01","TEX_mhvid01"},
    "network.ccs":{"TEX_network"},
    "gauge.ccs":{"TEX_red","TEX_white","TEX_xmenu","TEX_xtext","TEX_xselect","TEX_xselect2","TEX_xselect5","TEX_xsuccess","TEX_xwinner","TEX_gameover","TEX_start"},
    "mugen.ccs":{"TEX_mg_title","TEX_red","TEX_white","TEX_yellow","TEX_correct","TEX_mistake",
                 "TEX_prv_001","TEX_prv_002","TEX_prv_003","TEX_prv_004","TEX_prv_005","TEX_prv_006",
                 "TEX_prv_007","TEX_prv_008","TEX_prv_009","TEX_prv_010","TEX_prv_011","TEX_prv_012"},
    "rpggauge.ccs":{"TEX_rpgmenu01","TEX_rpgmenu02","TEX_rpgmenu03","TEX_rpgmenu04","TEX_konoha"},
}

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

def printable_ratio(s):
    if not s:return 0
    ok=sum(ch.isprintable() or ch in "\r\n\t" for ch in s)
    return ok/len(s)

def clean_text(s):
    s=s.replace("\r","\\r").replace("\n","\\n").replace("\t","\\t")
    return s.strip()

def scan_nul_strings(data,scope,minlen=2,maxlen=600):
    rows=[];start=0
    for chunk in data.split(b"\0"):
        pos=start;start+=len(chunk)+1
        if len(chunk)<minlen or len(chunk)>maxlen:continue
        try:s=chunk.decode("cp932")
        except UnicodeDecodeError:continue
        if not JP_RE.search(s):continue
        if printable_ratio(s)<0.80:continue
        st=clean_text(s)
        if not st or len(st)>500:continue
        rows.append(dict(scope=scope,offset_hex=hex(pos),kind="NUL",text=st,bytes=len(chunk)))
    return rows

def scan_lines(data,scope,maxlen=800):
    rows=[];off=0
    for raw in data.splitlines(keepends=True):
        body=raw.rstrip(b"\r\n")
        if 1<=len(body)<=maxlen:
            try:s=body.decode("cp932")
            except UnicodeDecodeError:s=""
            if s and JP_RE.search(s) and printable_ratio(s)>=0.80:
                rows.append(dict(scope=scope,offset_hex=hex(off),kind="LINE",text=clean_text(s),bytes=len(body)))
        off+=len(raw)
    return rows

def dedup_rows(rows):
    seen=set();out=[]
    for r in rows:
        k=(r["scope"],r["offset_hex"],r["kind"],r["text"])
        if k not in seen:
            seen.add(k);out.append(r)
    return out

def ccs_names(b):
    if len(b)<0x4c:return []
    try:pc,nc=struct.unpack_from("<II",b,0x44)
    except:return []
    if pc>4096 or nc>8192:return []
    no=0x4C+32*pc
    if no+32*nc>len(b):return []
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
    raise RuntimeError("palette missing")

def texture_records(b):
    names=ccs_names(b)
    if not names:return []
    magic=bytes.fromhex("0003cccc");out=[];seen=set()
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        wi=struct.unpack_from("<I",b,o+8)[0]
        if wi>=len(names):continue
        palid=struct.unpack_from("<I",b,o+12)[0]
        typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl>len(b):continue
        key=(names[wi],o)
        if key in seen:continue
        seen.add(key)
        out.append(dict(name=names[wi],offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl))
    return out

def decode_texture(b,t):
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:
        ix=raw.reshape(t["height"],t["width"]).copy()
    else:
        ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    ix=ix[::-1].copy();pal=find_palette(b,t["palette"])
    return pal[ix]

def font():
    for p in (Path(r"LOCAL_PATH"),Path(r"LOCAL_PATH")):
        if p.exists():
            return ImageFont.truetype(str(p),12)
    return ImageFont.load_default()

def contact_sheets(resource, decoded, records, outdir):
    if not records:return []
    fnt=font();cards=[]
    maxw=180;maxh=150
    for t in records:
        try:
            rgba=decode_texture(decoded,t)
            im=Image.fromarray(rgba,"RGBA")
            im.thumbnail((maxw-10,maxh-30),Image.Resampling.NEAREST)
            card=Image.new("RGBA",(maxw,maxh),(235,235,235,255))
            x=(maxw-im.width)//2;y=4+(maxh-28-im.height)//2
            card.alpha_composite(im,(x,y))
            d=ImageDraw.Draw(card)
            label=t["name"][:25]
            d.text((4,maxh-22),label,font=fnt,fill=(0,0,0,255))
            d.text((4,maxh-10),f'{t["width"]}x{t["height"]}',font=fnt,fill=(0,0,0,255))
            cards.append(card.convert("RGB"))
        except Exception:
            pass
    paths=[];per=24;cols=4
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',resource)
    for pi in range(0,len(cards),per):
        chunk=cards[pi:pi+per];rows=math.ceil(len(chunk)/cols)
        sheet=Image.new("RGB",(cols*maxw,rows*maxh),(255,255,255))
        for i,c in enumerate(chunk):
            sheet.paste(c,((i%cols)*maxw,(i//cols)*maxh))
        p=outdir/f"{safe}__sheet_{pi//per+1:02d}.jpg"
        sheet.save(p,quality=88,optimize=True)
        paths.append(p.name)
    return paths

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=r"PROJECT_ROOT")
    a=ap.parse_args();root=Path(a.root);source=root/SOURCE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB50 authority ISO missing/SHA mismatch")

    m=mod("sub51a_p14",root/"analysis/stage14/naruto_patcher.py")

    print("[1/7] Extract exact SUB50 DAT/IDX/BOOT",flush=True)
    dat=out/"source_sub50_naruto.dat";idx=out/"source_sub50_naruto.idx";boot=out/"source_sub50_BOOT.bin"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)

    print("[2/7] Scan BOOT Japanese strings",flush=True)
    bootrows=dedup_rows(scan_nul_strings(boot.read_bytes(),"BOOT.BIN"))
    write_tsv(out/"boot_japanese_strings.tsv",bootrows,["scope","offset_hex","kind","text","bytes"])

    print("[3/7] Scan all primary resources for Japanese strings",flush=True)
    ei=m.parse_pidx(m.read_embedded_index(dat),"sub50")
    textrows=[];resrows=[];decoded_cache={}
    with dat.open("rb") as f:
        for i,r in enumerate(ei["primary"]):
            if r.get("is_folder"):continue
            f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
            try:dec=m.decode_stored(stored,r["size"],r["zsize"])
            except Exception as e:
                resrows.append(dict(resource=r["name"],decoded_size="",status="DECODE_FAIL",jp_strings=0,textures=0,note=str(e)[:180]))
                continue
            decoded_cache[r["name"]]=dec
            rr=scan_nul_strings(dec,r["name"])
            if r["name"].lower().endswith((".tbl",".txt",".csv",".ini",".lst")):
                rr+=scan_lines(dec,r["name"])
            rr=dedup_rows(rr);textrows.extend(rr)
            resrows.append(dict(resource=r["name"],decoded_size=len(dec),status="OK",jp_strings=len(rr),textures="",note=""))
            if (i+1)%100==0:print(f"  scanned {i+1}/{len(ei['primary'])}",flush=True)
    write_tsv(out/"resource_japanese_strings.tsv",textrows,["scope","offset_hex","kind","text","bytes"])

    print("[4/7] Inventory every CCS texture",flush=True)
    texrows=[];candidate_resources=[]
    for rr in resrows:
        name=rr["resource"];dec=decoded_cache.get(name)
        if not dec or not name.lower().endswith(".ccs"):continue
        trs=texture_records(dec);rr["textures"]=len(trs)
        for t in trs:
            texrows.append(dict(resource=name,texture=t["name"],width=t["width"],height=t["height"],
                                format=hex(t["type"]),palette=t["palette"],offset_hex=hex(t["offset"])))
        low=name.lower()
        if any(term in low for term in UI_TERMS):
            candidate_resources.append(name)
    write_tsv(out/"all_ccs_texture_inventory.tsv",texrows,
              ["resource","texture","width","height","format","palette","offset_hex"])
    write_tsv(out/"primary_resource_scan.tsv",resrows,
              ["resource","decoded_size","status","jp_strings","textures","note"])

    print("[5/7] Build UI candidate contact sheets",flush=True)
    sheets=out/"contact_sheets";sheets.mkdir(exist_ok=True)
    sheetrows=[]
    for name in sorted(set(candidate_resources)):
        dec=decoded_cache[name];trs=texture_records(dec)
        paths=contact_sheets(name,dec,trs,sheets)
        sheetrows.append(dict(resource=name,textures=len(trs),sheets=";".join(paths)))
    write_tsv(out/"ui_contact_sheet_inventory.tsv",sheetrows,["resource","textures","sheets"])

    print("[6/7] Export high-priority full-resolution UI textures",flush=True)
    full=out/"priority_textures";full.mkdir(exist_ok=True);fullrows=[]
    for name,wanted in HIGH_PRIORITY.items():
        dec=decoded_cache.get(name)
        if not dec:
            fullrows.append(dict(resource=name,texture="",png="",status="RESOURCE_NOT_FOUND"))
            continue
        for t in texture_records(dec):
            if t["name"] not in wanted:continue
            try:
                rgba=decode_texture(dec,t)
                safe=re.sub(r'[^A-Za-z0-9_.-]+','_',t["name"])
                fn=f"{name.replace('.','_')}__{safe}.png"
                Image.fromarray(rgba,"RGBA").save(full/fn,optimize=True)
                fullrows.append(dict(resource=name,texture=t["name"],png=fn,status="EXPORTED"))
            except Exception as e:
                fullrows.append(dict(resource=name,texture=t["name"],png="",status="ERROR:"+str(e)[:120]))
    write_tsv(out/"priority_texture_inventory.tsv",fullrows,["resource","texture","png","status"])

    print("[7/7] Write summary",flush=True)
    unique_text=len({r["text"] for r in bootrows+textrows})
    jp_resources=len({r["scope"] for r in textrows})
    report=dict(
        stage="SUB51A_FULL_JAPANESE_SWEEP_INVENTORY",
        source_iso=str(source),source_iso_sha256=SOURCE_SHA,
        boot_japanese_occurrences=len(bootrows),
        resource_japanese_occurrences=len(textrows),
        unique_japanese_strings=unique_text,
        resources_with_japanese_strings=jp_resources,
        primary_resources_scanned=len([r for r in resrows if r["status"]=="OK"]),
        ccs_textures_inventory=len(texrows),
        ui_candidate_resources=len(set(candidate_resources)),
        contact_sheets=sum(len(r["sheets"].split(";")) if r["sheets"] else 0 for r in sheetrows),
        priority_textures_exported=sum(r["status"]=="EXPORTED" for r in fullrows),
        modifies_game_data=False,
        runtime_qa=False,
        purpose="Collect all residual Japanese before one full translation/build and one final runtime QA."
    )
    (out/"SUB51A_scan_summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51A - Full Japanese Sweep Inventory\n\n"
        f"SourceSHA256={SOURCE_SHA}\n"
        f"BootJapaneseOccurrences={len(bootrows)}\n"
        f"ResourceJapaneseOccurrences={len(textrows)}\n"
        f"UniqueJapaneseStrings={unique_text}\n"
        f"ResourcesWithJapaneseStrings={jp_resources}\n"
        f"PrimaryResourcesScanned={report['primary_resources_scanned']}\n"
        f"CCSTexturesInventoried={len(texrows)}\n"
        f"UICandidateResources={len(set(candidate_resources))}\n"
        f"ContactSheets={report['contact_sheets']}\n"
        f"PriorityTexturesExported={report['priority_textures_exported']}\n"
        "GameDataModified=NO\nRuntimeQA=NO\n",
        encoding="utf-8-sig")
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
