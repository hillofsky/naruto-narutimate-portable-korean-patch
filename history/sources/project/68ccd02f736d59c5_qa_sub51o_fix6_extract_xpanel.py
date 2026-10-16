from pathlib import Path
import struct, hashlib, importlib.util, json, zipfile, traceback
import numpy as np
from PIL import Image

ROOT=Path(r"PROJECT_ROOT")
SOURCE=ROOT/r"analysis\sub\sub51d_full_text_apply\Naruto_KR_MOV06E_SUB51D_FullText.iso"
OUT=ROOT/r"analysis\sub\sub51o_fix6_xpanel_extract"
LOGS=ROOT/"logs"
SECTOR=2048

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":
        raise RuntimeError("Bad ISO")
    r=p[156:190]
    return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR); data=f.read(size)
    out=[]; pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//SECTOR)+1)*SECTOR; continue
        r=data[pos:pos+ln]
        if len(r)<34: break
        nb=r[33:33+r[32]]
        name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
        out.append(dict(name=name,lba=int.from_bytes(r[2:6],"little"),
                        size=int.from_bytes(r[10:14],"little"),is_dir=bool(r[25]&2)))
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso); cur=dict(lba=lba,size=size,is_dir=True)
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"]) if e["name"].casefold()==part.casefold()),None)
        if not hit: raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath); Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b: raise RuntimeError("EOF")
            fo.write(b); rem-=len(b)

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44); no=0x4C+32*pc
    if pc>10000 or nc>20000 or no+32*nc>len(b): raise RuntimeError("Bad CCS")
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def find_palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=palid: continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b): continue
        raw=np.frombuffer(b[o+28:o+28+n*4],dtype=np.uint8).reshape(-1,4).copy()
        rgba=raw[:,[2,1,0,3]]
        rgba[:,3]=np.minimum(rgba[:,3].astype(np.int16)*2,255).astype(np.uint8)
        return rgba
    raise RuntimeError("Palette missing")

def find_texture(b,name):
    names=ccs_names(b)
    if name not in names: raise RuntimeError("Texture missing "+name)
    wanted=names.index(name); magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted: continue
        palid=struct.unpack_from("<I",b,o+12)[0]; typ=b[o+21]; we,he=b[o+24:o+26]
        if typ not in (0x13,0x14) or we>12 or he>12: continue
        w,h=1<<we,1<<he; dl=w*h if typ==0x13 else w*h//2
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

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    print("=== SUB51O FIX6 EXACT TEX_xpanel EXTRACT ===",flush=True)
    print("Source:",SOURCE,flush=True)
    if not SOURCE.exists(): raise RuntimeError("Preserved SUB51D source ISO missing")

    p14path=ROOT/r"analysis\stage14\naruto_patcher.py"
    if not p14path.exists(): raise RuntimeError("stage14 naruto_patcher.py missing")
    p14=mod("sub51o_fix6_p14",p14path)

    work=OUT/"_work"; work.mkdir(exist_ok=True)
    dat=work/"naruto.dat"
    print("[1/4] Extract naruto.dat from source ISO",flush=True)
    extract(SOURCE,"PSP_GAME/USRDIR/naruto.dat",dat)

    print("[2/4] Decode gauge.ccs primary resource",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    r=next((x for x in table["primary"] if x["name"]=="gauge.ccs"),None)
    if not r: raise RuntimeError("gauge.ccs primary missing")
    with dat.open("rb") as f:
        f.seek(r["offset"]); stored=f.read(r["zsize"] or r["size"])
    ccs=p14.decode_stored(stored,r["size"],r["zsize"])
    (OUT/"gauge.ccs.decoded.bin").write_bytes(ccs)

    print("[3/4] Decode TEX_xpanel to RGBA PNG",flush=True)
    t=find_texture(ccs,"TEX_xpanel")
    pal=find_palette(ccs,t["palette"])
    ix=decode_indices(ccs,t)
    rgba=pal[ix]
    im=Image.fromarray(rgba.astype(np.uint8),"RGBA")
    png=OUT/"gauge.ccs_TEX_xpanel.png"
    im.save(png)

    # save palette preview and raw metadata
    palim=Image.new("RGBA",(16*16,16*16),(0,0,0,0))
    pix=palim.load()
    for i,c in enumerate(pal):
        x0=(i%16)*16; y0=(i//16)*16
        for y in range(y0,y0+16):
            for x in range(x0,x0+16):
                pix[x,y]=tuple(int(v) for v in c)
    palim.save(OUT/"gauge.ccs_TEX_xpanel_palette.png")

    info={
        "resource":"gauge.ccs","texture":"TEX_xpanel",
        "width":t["width"],"height":t["height"],"type":hex(t["type"]),
        "palette_id":t["palette"],"data_len":t["data_len"],
        "png_sha256":hashlib.sha256(png.read_bytes()).hexdigest(),
        "source_iso":str(SOURCE)
    }
    (OUT/"xpanel_info.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")

    print("[4/4] Package result",flush=True)
    z=LOGS/"naruto_sub51o_fix6_xpanel_extract_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file(): zz.write(p,p.name)
    print("SIZE",im.size,"TYPE",hex(t["type"]),"PALETTE",t["palette"],flush=True)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try: main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix6_xpanel_extract_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
