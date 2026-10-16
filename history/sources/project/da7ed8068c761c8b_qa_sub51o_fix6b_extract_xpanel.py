from pathlib import Path
import struct, hashlib, importlib.util, json, zipfile, traceback, zlib, binascii

ROOT=Path(r"PROJECT_ROOT")
SOURCE=ROOT/r"analysis\sub\sub51d_full_text_apply\Naruto_KR_MOV06E_SUB51D_FullText.iso"
OUT=ROOT/r"analysis\sub\sub51o_fix6b_xpanel_extract"
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
    return int.from_bytes(r[2:6],"little"), int.from_bytes(r[10:14],"little")

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
        out.append({
            "name":name,
            "lba":int.from_bytes(r[2:6],"little"),
            "size":int.from_bytes(r[10:14],"little"),
            "is_dir":bool(r[25]&2),
        })
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso)
    cur={"lba":lba,"size":size,"is_dir":True}
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=next((e for e in dirents(iso,cur["lba"],cur["size"]) if e["name"].casefold()==part.casefold()),None)
        if not hit: raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath)
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b: raise RuntimeError("EOF")
            fo.write(b); rem-=len(b)

def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44)
    no=0x4C+32*pc
    if pc>10000 or nc>20000 or no+32*nc>len(b):
        raise RuntimeError(f"Bad CCS header pc={pc} nc={nc}")
    return [
        b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace")
        for i in range(nc)
    ]

def find_palette(b,palid):
    magic=bytes.fromhex("0004cccc")
    for o in range(0,len(b)-28,4):
        if b[o:o+4]!=magic: continue
        if struct.unpack_from("<I",b,o+8)[0]!=palid: continue
        n=struct.unpack_from("<I",b,o+24)[0]
        if n not in (16,256) or o+28+n*4>len(b): continue
        pal=[]
        for i in range(n):
            bo,go,ro,ao=struct.unpack_from("BBBB",b,o+28+i*4)
            pal.append((ro,go,bo,min(ao*2,255)))
        return pal
    raise RuntimeError(f"Palette missing id={palid}")

def find_texture(b,name):
    names=ccs_names(b)
    if name not in names: raise RuntimeError("Texture missing "+name)
    wanted=names.index(name); magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic: continue
        if struct.unpack_from("<I",b,o+8)[0]!=wanted: continue
        palid=struct.unpack_from("<I",b,o+12)[0]
        typ=b[o+21]; we,he=b[o+24:o+26]
        if typ not in (0x13,0x14) or we>12 or he>12: continue
        w,h=1<<we,1<<he
        dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            return {"offset":o,"palette":palid,"type":typ,"width":w,"height":h,"data_len":dl}
    raise RuntimeError("Texture record missing "+name)

def decode_indices(b,t):
    raw=b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    w,h=t["width"],t["height"]
    vals=[]
    if t["type"]==0x13:
        vals=list(raw)
        if len(vals)!=w*h: raise RuntimeError("Unexpected 8bpp data length")
    else:
        for v in raw:
            vals.append(v & 0x0F)
            vals.append((v >> 4) & 0x0F)
        if len(vals)!=w*h: raise RuntimeError("Unexpected 4bpp data length")
    rows=[vals[y*w:(y+1)*w] for y in range(h)]
    rows.reverse()
    return rows

def png_chunk(kind,data):
    crc=binascii.crc32(kind)
    crc=binascii.crc32(data,crc)&0xffffffff
    return struct.pack(">I",len(data))+kind+data+struct.pack(">I",crc)

def write_rgba_png(path,w,h,rgba_bytes):
    if len(rgba_bytes)!=w*h*4:
        raise RuntimeError("RGBA byte length mismatch")
    raw=bytearray()
    stride=w*4
    for y in range(h):
        raw.append(0)  # filter type 0
        raw.extend(rgba_bytes[y*stride:(y+1)*stride])
    sig=b"\x89PNG\r\n\x1a\n"
    ihdr=struct.pack(">IIBBBBB",w,h,8,6,0,0,0)
    data=sig+png_chunk(b"IHDR",ihdr)+png_chunk(b"IDAT",zlib.compress(bytes(raw),9))+png_chunk(b"IEND",b"")
    Path(path).write_bytes(data)

def rows_to_rgba(rows,pal):
    out=bytearray()
    for row in rows:
        for idx in row:
            if idx>=len(pal): raise RuntimeError(f"Palette index {idx} out of range")
            out.extend(bytes(pal[idx]))
    return bytes(out)

def palette_preview_rgba(pal):
    cols=16; cell=16
    rows=(len(pal)+cols-1)//cols
    w=cols*cell; h=rows*cell
    out=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            idx=(y//cell)*cols+(x//cell)
            c=pal[idx] if idx<len(pal) else (0,0,0,0)
            off=(y*w+x)*4
            out[off:off+4]=bytes(c)
    return w,h,bytes(out)

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    print("=== SUB51O FIX6B EXACT TEX_xpanel EXTRACT ===",flush=True)
    print("Standard library only: no NumPy, no Pillow.",flush=True)
    if not SOURCE.exists(): raise RuntimeError("Preserved SUB51D source ISO missing: "+str(SOURCE))

    p14path=ROOT/r"analysis\stage14\naruto_patcher.py"
    if not p14path.exists(): raise RuntimeError("stage14 naruto_patcher.py missing: "+str(p14path))
    p14=mod("sub51o_fix6b_p14",p14path)

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

    print("[3/4] Decode TEX_xpanel and write PNG directly",flush=True)
    t=find_texture(ccs,"TEX_xpanel")
    pal=find_palette(ccs,t["palette"])
    rows=decode_indices(ccs,t)
    rgba=rows_to_rgba(rows,pal)
    png=OUT/"gauge.ccs_TEX_xpanel.png"
    write_rgba_png(png,t["width"],t["height"],rgba)

    pw,ph,prgba=palette_preview_rgba(pal)
    write_rgba_png(OUT/"gauge.ccs_TEX_xpanel_palette.png",pw,ph,prgba)

    info={
        "resource":"gauge.ccs","texture":"TEX_xpanel",
        "width":t["width"],"height":t["height"],
        "type":hex(t["type"]),"palette_id":t["palette"],
        "palette_entries":len(pal),"data_len":t["data_len"],
        "png_sha256":hashlib.sha256(png.read_bytes()).hexdigest(),
        "source_iso":str(SOURCE),
        "external_python_packages_required":False
    }
    (OUT/"xpanel_info.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")

    print("[4/4] Package result",flush=True)
    z=LOGS/"naruto_sub51o_fix6b_xpanel_extract_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.iterdir():
            if p.is_file(): zz.write(p,p.name)
    print("SIZE",t["width"],"x",t["height"],"TYPE",hex(t["type"]),"PALETTE",t["palette"],flush=True)
    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try: main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        err=traceback.format_exc()
        (OUT/"FAILURE.txt").write_text(err,encoding="utf-8")
        z=LOGS/"fail_naruto_sub51o_fix6b_xpanel_extract_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
        print(err,flush=True)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
