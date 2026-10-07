#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,math,re,shutil,struct,sys,traceback
import numpy as np
from PIL import Image,ImageDraw,ImageFont

SECTOR=2048
SOURCE_SHA="e8731e1b6eaceae47f765137ab1e40ebced1ad9637e44013b06ad19b17ba3556"
SOURCE_REL=Path("analysis/sub/sub51j_mugen_safe_style/Naruto_KR_MOV06E_SUB51J_MugenSafeStyled.iso")
OUT_REL=Path("analysis/sub/sub51k_residual_ui_sweep")

EXPLICIT=[
 "modesel1.ccs","option.ccs","setting.ccs","charsel1.ccs","mugen.ccs",
 "network.ccs","home.ccs","gauge.ccs","rpggauge.ccs",
 "cmnselect.ccs","mapsel1.ccs","mgn_skill.ccs","mgselect.ccs","title.ccs","xselect3.ccs",
]
KEYWORDS=("mode","select","sel","option","setting","menu","gauge","mugen","home",
          "network","map","title","skill","quiz","nazo","result","status","item","shop","char")
MAX_RESOURCES=36
MAX_TEXTURES_PER_RESOURCE=160
MAX_CONTACT_BYTES=60*1024*1024

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

def ccs_names(b):
    if len(b)<0x4c: return []
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    if pc>10000 or nc>20000 or no+32*nc>len(b):return []
    out=[]
    for i in range(nc):
        raw=b[no+32*i:no+32*i+30].split(b"\0",1)[0]
        out.append(raw.decode("cp932",errors="replace"))
    return out

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
    return None

def texture_records(b):
    names=ccs_names(b)
    if not names:return []
    magic=bytes.fromhex("0003cccc")
    out=[];seen=set()
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        idx=struct.unpack_from("<I",b,o+8)[0]
        if idx>=len(names) or idx in seen:continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if typ not in (0x13,0x14) or we>12 or he>12:continue
        w,h=1<<we,1<<he
        if w<8 or h<8 or w*h>4_194_304:continue
        dl=w*h if typ==0x13 else w*h//2
        if o+36+dl>len(b):continue
        out.append(dict(index=idx,name=names[idx],offset=o,palette=palid,type=typ,
                        width=w,height=h,data_len=dl))
        seen.add(idx)
    return out

def decode_texture(b,t):
    pal=find_palette(b,t["palette"])
    if pal is None:return None
    raw=np.frombuffer(b[t["offset"]+36:t["offset"]+36+t["data_len"]],dtype=np.uint8)
    if t["type"]==0x13:
        ix=raw.reshape(t["height"],t["width"]).copy()
    else:
        ix=np.stack((raw&15,raw>>4),axis=1).reshape(t["height"],t["width"]).copy()
    ix=ix[::-1].copy()
    return Image.fromarray(pal[ix],"RGBA")

def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r:return None,None
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"]),r

def save_contact(resource,decoded,records,outdir):
    thumbs=[];meta=[]
    for t in records[:MAX_TEXTURES_PER_RESOURCE]:
        im=decode_texture(decoded,t)
        if im is None:continue
        # Skip fully transparent textures.
        a=np.asarray(im)[:,:,3]
        if int(a.max())==0:continue
        box=Image.new("RGBA",(250,190),(28,28,28,255))
        thumb=im.copy()
        thumb.thumbnail((240,155),Image.Resampling.NEAREST)
        x=(250-thumb.width)//2;y=25+(155-thumb.height)//2
        box.alpha_composite(thumb,(x,y))
        d=ImageDraw.Draw(box)
        label=f"{t['name']}  {t['width']}x{t['height']}  {hex(t['type'])}"
        d.text((5,5),label,fill=(255,255,255,255))
        thumbs.append(box)
        meta.append((t,im))
    if not thumbs:return None,meta
    cols=4;rows=math.ceil(len(thumbs)/cols)
    sheet=Image.new("RGBA",(cols*250,rows*190),(18,18,18,255))
    for i,im in enumerate(thumbs):
        sheet.alpha_composite(im,((i%cols)*250,(i//cols)*190))
    p=outdir/(resource.replace(".ccs","")+"_contact.png")
    sheet.save(p,optimize=True)
    return p,meta

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    a=ap.parse_args()
    root=Path(a.root);source=root/SOURCE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    work=out/"_work"
    if work.exists():shutil.rmtree(work)
    work.mkdir()

    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB51J authority missing/SHA mismatch")
    m=mod("sub51k_p14",root/"analysis/stage14/naruto_patcher.py")

    print("[1/5] Extract SUB51J naruto.dat",flush=True)
    dat=work/"naruto.dat";extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    table=m.parse_pidx(m.read_embedded_index(dat),"sub51k")

    primary_names=[r["name"] for r in table["primary"] if not r.get("is_folder")]
    candidates=[]
    for n in EXPLICIT:
        if n in primary_names and n not in candidates:candidates.append(n)
    for n in primary_names:
        low=n.lower()
        if not low.endswith(".ccs"):continue
        if any(k in low for k in KEYWORDS) and n not in candidates:
            candidates.append(n)
    candidates=candidates[:MAX_RESOURCES]

    print(f"[2/5] Candidate UI CCS resources: {len(candidates)}",flush=True)
    cdir=out/"contact_sheets";cdir.mkdir(exist_ok=True)
    resources=[];textures=[];contact_bytes=0
    for i,name in enumerate(candidates,1):
        decoded,r=decode_primary(dat,table,name,m)
        if decoded is None:continue
        recs=texture_records(decoded)
        if not recs:
            resources.append(dict(resource=name,status="NO_SUPPORTED_TEXTURES",
                                  decoded_size=len(decoded),texture_count=0,contact_sheet=""))
            continue
        p,meta=save_contact(name,decoded,recs,cdir)
        if p and contact_bytes+p.stat().st_size>MAX_CONTACT_BYTES:
            p.unlink(missing_ok=True);p=None
        if p:contact_bytes+=p.stat().st_size
        resources.append(dict(resource=name,status="OK",decoded_size=len(decoded),
                              texture_count=len(recs),contact_sheet=(p.name if p else "SKIPPED_SIZE_CAP")))
        for t,im in meta:
            a=np.asarray(im)[:,:,3]
            textures.append(dict(resource=name,texture=t["name"],width=t["width"],height=t["height"],
                                 type=hex(t["type"]),palette=t["palette"],
                                 visible_pixels=int((a>0).sum()),
                                 contact_sheet=(p.name if p else "")))
        print(f"  {i:02d}/{len(candidates)} {name}: {len(recs)} textures",flush=True)

    write_tsv(out/"sub51k_ui_resources.tsv",resources,
              ["resource","status","decoded_size","texture_count","contact_sheet"])
    write_tsv(out/"sub51k_ui_textures.tsv",textures,
              ["resource","texture","width","height","type","palette","visible_pixels","contact_sheet"])

    print("[3/5] Build master contact index",flush=True)
    sheets=sorted(cdir.glob("*.png"))
    # Master is thumbnail-only to keep the upload small.
    cards=[]
    for p in sheets:
        im=Image.open(p).convert("RGBA")
        im.thumbnail((480,270),Image.Resampling.LANCZOS)
        card=Image.new("RGBA",(500,310),(24,24,24,255))
        card.alpha_composite(im,((500-im.width)//2,30))
        ImageDraw.Draw(card).text((5,5),p.stem,fill=(255,255,255,255))
        cards.append(card)
    if cards:
        cols=2;rows=math.ceil(len(cards)/cols)
        master=Image.new("RGBA",(cols*500,rows*310),(12,12,12,255))
        for i,c in enumerate(cards):master.alpha_composite(c,((i%cols)*500,(i//cols)*310))
        master.save(out/"SUB51K_master_contact.png",optimize=True)

    print("[4/5] Write summary",flush=True)
    summary=dict(
        stage="SUB51K_RESIDUAL_UI_SWEEP",
        source_sub51j_sha256=SOURCE_SHA,
        candidate_resources=len(candidates),
        resources_with_supported_textures=sum(1 for r in resources if r["status"]=="OK"),
        texture_records=len(textures),
        contact_sheets=len(sheets),
        contact_sheet_bytes=sum(p.stat().st_size for p in sheets),
        game_data_modified=False,
        ppsspp_executed=False,
        bc250_used=False,
        local_llm_used=False,
        next="Upload success ZIP. ChatGPT will visually inspect the contact sheets and patch only confirmed residual Japanese UI."
    )
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51K - Residual UI Sweep\n\n"
        f"SourceSUB51J_SHA256={SOURCE_SHA}\n"
        f"CandidateResources={summary['candidate_resources']}\n"
        f"ResourcesWithTextures={summary['resources_with_supported_textures']}\n"
        f"TextureRecords={summary['texture_records']}\n"
        f"ContactSheets={summary['contact_sheets']}\n"
        f"ContactSheetBytes={summary['contact_sheet_bytes']}\n"
        "GameDataModified=NO\nPPSSPPExecuted=NO\nBC250Used=NO\nLocalLLMUsed=NO\n",
        encoding="utf-8-sig")

    print("[5/5] Cleanup temp DAT",flush=True)
    shutil.rmtree(work,ignore_errors=True)
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
