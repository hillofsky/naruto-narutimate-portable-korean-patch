#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,math,re,shutil,struct,sys,traceback,zipfile,zlib,binascii
from PIL import Image,ImageDraw,ImageFont

ROOT_DEFAULT=Path(r"D:\narutimate portable")
SOURCE_NAME="Naruto_KR_MOV06E_SUB52E_StaticImages.iso"
SOURCE_SHA="3e58fd4abb76f32c5d4df52e4faf73a5a67189534d671c4d5866331def210254"
OUT_REL=Path(r"analysis\sub\sub52f_final_static_residual_sweep")
SECTOR=2048

# These resources are known to contain already-translated/custom-encoded text and
# should not be treated as Japanese residuals by generic CP932 scanning.
EXCLUDE_TEXT_RE=re.compile(r"^(event\d+|map\d+)\.tbl$",re.I)
JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")
TEXTLIKE_RE=re.compile(
    r"(name|txt|text|title|winner|select|white|red|blue|hanyou|st_|slot|pop|"
    r"info|help|msg|menu|command|button|xpanel|mode|stage|mission|caption|"
    r"rule|condition|win|lose|clear|ready|start|goal|record|rank|point|"
    r"option|network|home|mg|quiz|nazo|narup)",
    re.I
)

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError("Cannot import "+str(path))
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
            if not b:raise RuntimeError("ISO EOF")
            fo.write(b);rem-=len(b)

def ccs_names(b):
    if len(b)<0x4C:raise RuntimeError("CCS small")
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    if pc>10000 or nc>50000 or no+32*nc>len(b):raise RuntimeError("Bad CCS")
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def ccs_textures(b):
    names=ccs_names(b);out=[];magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        nid=struct.unpack_from("<I",b,o+8)[0];palid=struct.unpack_from("<I",b,o+12)[0]
        typ=b[o+21];we,he=b[o+24:o+26]
        if nid>=len(names) or typ not in (0x13,0x14) or we>12 or he>12:continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            out.append(dict(offset=o,name=names[nid],palette=palid,type=typ,width=w,height=h,data_len=dl))
    return out

def palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=palid:continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b):continue
        p=[]
        for i in range(n):
            bo,go,ro,ao=struct.unpack_from("BBBB",b,o+28+i*4)
            p.append((ro,go,bo,min(ao*2,255)))
        return p
    raise RuntimeError("Palette missing")

def tex_indices(b,t):
    raw=b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    vals=[]
    if t["type"]==0x13:vals=list(raw)
    else:
        for v in raw:vals.extend((v&15,(v>>4)&15))
    rows=[vals[y*t["width"]:(y+1)*t["width"]] for y in range(t["height"])]
    rows.reverse();return rows

def to_image(rows,pal):
    h=len(rows);w=len(rows[0]);im=Image.new("RGBA",(w,h));px=im.load()
    for y,row in enumerate(rows):
        for x,idx in enumerate(row):
            px[x,y]=pal[idx] if idx<len(pal) else (255,0,255,255)
    return im

def safe(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s)

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def scan_cp932_lines(data):
    out=[];pos=0
    for line in data.splitlines(keepends=True):
        body=line.rstrip(b"\r\n")
        try:s=body.decode("cp932","strict")
        except Exception:
            pos+=len(line);continue
        if s.startswith(";"):
            pos+=len(line);continue
        jp=sum(1 for ch in s if JP_RE.fullmatch(ch))
        vis=sum(1 for ch in s if not ch.isspace())
        if jp>=2 and vis and jp/vis>=0.15:
            out.append((pos,s))
        pos+=len(line)
    return out

def contact_sheet(items,path,title):
    if not items:return
    font=ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf",14) if Path(r"C:\Windows\Fonts\malgun.ttf").exists() else ImageFont.load_default()
    cellw,cellh=320,220;cols=3;rows=math.ceil(len(items)/cols)
    sheet=Image.new("RGB",(cellw*cols,cellh*rows+35),"white")
    d=ImageDraw.Draw(sheet);d.text((8,8),title,font=font,fill="black")
    yoff=35
    for i,(label,im) in enumerate(items):
        x=(i%cols)*cellw;y=yoff+(i//cols)*cellh
        bg=Image.new("RGBA",im.size,(35,35,35,255));bg.alpha_composite(im)
        bg=bg.convert("RGB");bg.thumbnail((300,175))
        sheet.paste(bg,(x+(cellw-bg.width)//2,y+5))
        d.text((x+5,y+185),label[:46],font=font,fill="black")
    sheet.save(path,quality=90)

def decode_primary(dat,tab,name,m):
    r=next((x for x in tab["primary"] if x["name"]==name),None)
    if not r:return None
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    try:return m.decode_stored(stored,r["size"],r["zsize"])
    except:return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=str(ROOT_DEFAULT))
    a=ap.parse_args()
    root=Path(a.root);source=root/SOURCE_NAME;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)

    print("=== SUB52F FINAL STATIC RESIDUAL SWEEP ===",flush=True)
    if not source.exists():raise RuntimeError("SUB52E ISO missing: "+str(source))
    h=sha256_file(source);print("SHA256="+h,flush=True)
    if h!=SOURCE_SHA:raise RuntimeError("SUB52E source SHA mismatch")

    p14=mod("sub52f_p14",root/r"analysis\stage14\naruto_patcher.py")
    work=out/"_work"
    if work.exists():shutil.rmtree(work)
    work.mkdir()
    dat=work/"naruto.dat"
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    tab=p14.parse_pidx(p14.read_embedded_index(dat),"sub52f")

    print("[1/5] Static residual text scan",flush=True)
    textrows=[]
    with dat.open("rb") as f:
        for i,r in enumerate(tab["primary"]):
            n=r["name"]
            if not n.lower().endswith(".tbl") or EXCLUDE_TEXT_RE.match(n):continue
            f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
            try:dec=p14.decode_stored(stored,r["size"],r["zsize"])
            except:continue
            for off,s in scan_cp932_lines(dec):
                textrows.append(dict(entry_index=i,entry=n,offset=off,text=s))
    write_tsv(out/"residual_japanese_text.tsv",textrows,["entry_index","entry","offset","text"])
    print("  residual text rows:",len(textrows),flush=True)

    print("[2/5] Build texture candidate set from SUB52C + name heuristics",flush=True)
    # The prior SUB52C target set is the highest-value set. Also add text-like texture names
    # from every CCS so we do not rely only on previously selected targets.
    previous_assets=root/r"analysis\sub\sub52c_static_patch_sources\target_assets"
    previous_pairs=set()
    if previous_assets.exists():
        for p in previous_assets.glob("*.png"):
            parts=p.name.split("__")
            if len(parts)>=6:previous_pairs.add((parts[1],parts[3]))

    patched_manifest=root/"sub52e_assets"/"asset_manifest.json"
    patched_pairs=set()
    if patched_manifest.exists():
        for fn in json.loads(patched_manifest.read_text(encoding="utf-8")):
            parts=fn.split("__")
            if len(parts)>=6:patched_pairs.add((parts[1],parts[3]))

    candidates=[]
    for i,r in enumerate(tab["primary"]):
        if not r["name"].lower().endswith(".ccs"):continue
        dec=decode_primary(dat,tab,r["name"],p14)
        if not dec:continue
        try:tl=ccs_textures(dec)
        except:continue
        for t in tl:
            pair=(r["name"],t["name"])
            prior=pair in previous_pairs
            patched=pair in patched_pairs
            heuristic=bool(TEXTLIKE_RE.search(t["name"]))
            if not prior and not heuristic:continue
            candidates.append((i,r["name"],t,dec,prior,patched))

    print("  image candidates:",len(candidates),flush=True)

    print("[3/5] Extract final candidate textures",flush=True)
    imgdir=out/"residual_texture_candidates";imgdir.mkdir(exist_ok=True)
    residual_items=[];patched_items=[];inv=[]
    for i,res,t,dec,prior,patched in candidates:
        try:
            pal=palette(dec,t["palette"]);rows=tex_indices(dec,t);im=to_image(rows,pal)
        except Exception as e:
            inv.append(dict(entry_index=i,resource=res,texture=t["name"],prior=int(prior),patched=int(patched),
                            width=t["width"],height=t["height"],png="",error=str(e)))
            continue
        fn=f"{i:04d}__{safe(res)}__{safe(t['name'])}__{t['width']}x{t['height']}.png"
        im.save(imgdir/fn)
        inv.append(dict(entry_index=i,resource=res,texture=t["name"],prior=int(prior),patched=int(patched),
                        width=t["width"],height=t["height"],png=str((imgdir/fn).relative_to(out)),error=""))
        item=(f"{res}/{t['name']}",im)
        if patched:patched_items.append(item)
        else:residual_items.append(item)
    write_tsv(out/"residual_texture_inventory.tsv",inv,
              ["entry_index","resource","texture","prior","patched","width","height","png","error"])

    print("[4/5] Create contact sheets",flush=True)
    # Split sheets to keep image sizes reasonable.
    def sheets(items,prefix):
        paths=[]
        for n in range(0,len(items),30):
            p=out/f"{prefix}_{n//30+1:02d}.jpg"
            contact_sheet(items[n:n+30],p,f"{prefix} {n+1}-{min(n+30,len(items))} / {len(items)}")
            paths.append(str(p))
        return paths
    residual_sheets=sheets(residual_items,"residual_unpatched_contact")
    patched_sheets=sheets(patched_items,"patched_review_contact")

    print("[5/5] Package",flush=True)
    summary=dict(
        stage="SUB52F_FINAL_STATIC_RESIDUAL_SWEEP",
        source_iso=str(source),
        source_sha256=h,
        residual_japanese_text_rows=len(textrows),
        texture_candidates=len(candidates),
        residual_unpatched_texture_candidates=len(residual_items),
        patched_review_texture_candidates=len(patched_items),
        residual_contact_sheets=len(residual_sheets),
        patched_contact_sheets=len(patched_sheets),
        gameplay_used=False,ppsspp_used=False
    )
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"SUMMARY.txt").write_text("\n".join(f"{k}={v}" for k,v in summary.items()),encoding="utf-8-sig")

    z=root/"logs"/"naruto_sub52f_final_static_residual_sweep_upload.zip"
    z.parent.mkdir(parents=True,exist_ok=True)
    if z.exists():z.unlink()
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in out.rglob("*"):
            if p.is_file() and "_work" not in p.parts:
                zz.write(p,p.relative_to(out))
    shutil.rmtree(work,ignore_errors=True)
    print("UPLOAD_ZIP="+str(z),flush=True)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
