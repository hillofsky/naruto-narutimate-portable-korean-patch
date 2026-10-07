#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse, binascii, csv, hashlib, importlib.util, json, shutil, struct, sys, traceback, zlib

SECTOR=2048
SOURCE_REL=Path(r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso")
SOURCE_SHA="8a4ddc795e6f5287f6ed54018bd48c3c881a4e7343fb7ca31d60e0e8afa32081"
OUT_REL=Path(r"analysis\sub\sub51p_fix2_modesel_title_fix\build")
FINAL_NAME="Naruto_KR_MOV06E_SUB51P_FIX2_ModeSelTitleFix.iso"

TARGETS={
    "gauge.ccs":{
        "TEX_red":{"asset":"p__gauge__TEX_red_KO.png","rects":[(0,94,168,129)]},
        "TEX_white":{"asset":"p__gauge__TEX_white_KO.png","rects":[(23,0,61,16),(84,0,159,16)]},
        "TEX_xpanel":{"asset":"p__gauge__TEX_xpanel_KO.png","rects":None},
    },
    "title.ccs":{
        "TEX_panel":{"asset":"p__title__TEX_panel_fix2.png","rects":[(23,107,217,130)]},
        "TEX_panel2":{"asset":"p__title__TEX_panel2_fix2.png","rects":[(11,102,231,130)]},
        "TEX_panel3":{"asset":"p__title__TEX_panel3_fix2.png","rects":[(11,102,231,130)]},
    },
}

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("Bad ISO")
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

def segsha(iso,ipath):
    e=findiso(iso,ipath); h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=f.read(min(rem,1024*1024))
            if not b: raise RuntimeError("EOF")
            h.update(b); rem-=len(b)
    return e["size"],h.hexdigest()

def walk_pmfs(iso,path="PSP_GAME/USRDIR"):
    out=[]
    def walk(p):
        d=findiso(iso,p)
        for e in dirents(iso,d["lba"],d["size"]):
            if e["name"] in (".",".."): continue
            q=p+"/"+e["name"]
            if e["is_dir"]: walk(q)
            elif e["name"].lower().endswith(".pmf"): out.append(q)
    walk(path); return sorted(out)

# --- Standard-library PNG decoder (8-bit non-interlaced) ---
def paeth(a,b,c):
    p=a+b-c; pa=abs(p-a); pb=abs(p-b); pc=abs(p-c)
    if pa<=pb and pa<=pc: return a
    if pb<=pc: return b
    return c

def read_png_rgba(path):
    b=Path(path).read_bytes()
    if b[:8]!=b"\x89PNG\r\n\x1a\n": raise RuntimeError("Not PNG: "+str(path))
    pos=8; idat=bytearray(); plte=None; trns=None; ihdr=None
    while pos+12<=len(b):
        n=struct.unpack(">I",b[pos:pos+4])[0]; typ=b[pos+4:pos+8]; data=b[pos+8:pos+8+n]; pos+=12+n
        if typ==b"IHDR": ihdr=struct.unpack(">IIBBBBB",data)
        elif typ==b"PLTE": plte=[tuple(data[i:i+3]) for i in range(0,len(data),3)]
        elif typ==b"tRNS": trns=bytes(data)
        elif typ==b"IDAT": idat.extend(data)
        elif typ==b"IEND": break
    if not ihdr: raise RuntimeError("PNG missing IHDR")
    w,h,depth,ctype,comp,filt,interlace=ihdr
    if depth!=8 or interlace!=0: raise RuntimeError(f"Unsupported PNG depth/interlace: {depth}/{interlace}")
    channels={0:1,2:3,3:1,4:2,6:4}.get(ctype)
    if not channels: raise RuntimeError("Unsupported PNG color type "+str(ctype))
    raw=zlib.decompress(bytes(idat)); stride=w*channels
    rows=[]; off=0; prev=bytearray(stride)
    for y in range(h):
        ft=raw[off]; off+=1
        cur=bytearray(raw[off:off+stride]); off+=stride
        bpp=channels
        for x in range(stride):
            a=cur[x-bpp] if x>=bpp else 0
            bb=prev[x]
            c=prev[x-bpp] if x>=bpp else 0
            if ft==1: cur[x]=(cur[x]+a)&255
            elif ft==2: cur[x]=(cur[x]+bb)&255
            elif ft==3: cur[x]=(cur[x]+((a+bb)//2))&255
            elif ft==4: cur[x]=(cur[x]+paeth(a,bb,c))&255
            elif ft!=0: raise RuntimeError("Unsupported PNG filter "+str(ft))
        rows.append(cur); prev=cur
    rgba=[]
    for row in rows:
        rr=[]
        if ctype==6:
            for x in range(w): rr.append(tuple(row[x*4:x*4+4]))
        elif ctype==2:
            for x in range(w):
                r,g,bv=row[x*3:x*3+3]; rr.append((r,g,bv,255))
        elif ctype==0:
            for x in range(w): rr.append((row[x],row[x],row[x],255))
        elif ctype==4:
            for x in range(w):
                g,a=row[x*2:x*2+2]; rr.append((g,g,g,a))
        elif ctype==3:
            if plte is None: raise RuntimeError("Indexed PNG without PLTE")
            for x in range(w):
                i=row[x]; r,g,bv=plte[i]; a=trns[i] if trns and i<len(trns) else 255
                rr.append((r,g,bv,a))
        rgba.append(rr)
    return w,h,rgba

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
        pal=[]
        for i in range(n):
            bo,go,ro,ao=struct.unpack_from("BBBB",b,o+28+i*4)
            pal.append((ro,go,bo,min(ao*2,255)))
        return pal
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
    raw=b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    w,h=t["width"],t["height"]; vals=[]
    if t["type"]==0x13: vals=list(raw)
    else:
        for v in raw: vals.extend((v&15,(v>>4)&15))
    if len(vals)!=w*h: raise RuntimeError("Index payload size mismatch")
    rows=[vals[y*w:(y+1)*w] for y in range(h)]
    rows.reverse(); return rows

def encode_indices(rows,t):
    rows=list(reversed(rows)); flat=[x for r in rows for x in r]
    if t["type"]==0x13: raw=bytes(flat)
    else:
        if len(flat)%2: raise RuntimeError("4bpp odd pixel count")
        raw=bytes((flat[i]&15)|((flat[i+1]&15)<<4) for i in range(0,len(flat),2))
    if len(raw)!=t["data_len"]: raise RuntimeError("Encoded length mismatch")
    return raw

def nearest_index(c,pal,cache):
    if c in cache: return cache[c]
    best=0; bestd=None
    for i,p in enumerate(pal):
        dr=c[0]-p[0]; dg=c[1]-p[1]; db=c[2]-p[2]; da=c[3]-p[3]
        d=dr*dr+dg*dg+db*db+5*da*da
        if bestd is None or d<bestd: bestd=d; best=i
    cache[c]=best; return best

def patch_texture(ccs,name,png,rects):
    b=bytearray(ccs); t=find_texture(b,name); pal=find_palette(b,t["palette"])
    w,h,rgba=read_png_rgba(png)
    if (w,h)!=(t["width"],t["height"]): raise RuntimeError(f"{name}: PNG size {(w,h)} != {(t['width'],t['height'])}")
    old=decode_indices(b,t); new=[r[:] for r in old]
    cache={}
    if rects is None: rects=[(0,0,w,h)]
    changed=0
    for x0,y0,x1,y1 in rects:
        for y in range(y0,y1):
            for x in range(x0,x1):
                idx=nearest_index(rgba[y][x],pal,cache)
                if new[y][x]!=idx: changed+=1
                new[y][x]=idx
    raw=encode_indices(new,t); start=t["offset"]+36; b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=w,height=h,changed_indexed_pixels=changed,
                         unique_png_colors=len(cache),new_payload_sha256=hashlib.sha256(raw).hexdigest())

def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r: raise RuntimeError("Primary missing "+name)
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]); stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=r"D:\narutimate portable")
    ap.add_argument("--assets",required=True)
    a=ap.parse_args()
    root=Path(a.root); assets=Path(a.assets); source=root/SOURCE_REL; out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    diag=out/"SUB51O_diagnostic.txt"
    if diag.exists(): diag.unlink()
    def note(s):
        print(s,flush=True)
        with diag.open("a",encoding="utf-8") as f: f.write(str(s)+"\n")

    note("SUB51P FIX4 ModeSelTitleFix build starting")
    note("Python="+sys.version.replace("\n"," "))
    if not source.exists(): raise RuntimeError("SUB51N source ISO missing: "+str(source))
    ssha=sha256_file(source); note("SourceSHA256="+ssha)
    if ssha!=SOURCE_SHA: raise RuntimeError("SUB51N source SHA mismatch")

    p14=mod("sub51o_p14",root/r"analysis\stage14\naruto_patcher.py")
    p15=mod("sub51o_p15",root/r"analysis\stage15\stage15_iso_patcher.py")

    work=out/"_work"
    if work.exists(): shutil.rmtree(work)
    work.mkdir()
    dat=work/"naruto.dat"; idx=work/"naruto.idx"; boot=work/"BOOT.bin"

    note("[1/7] Extract SUB51N DAT/IDX/BOOT")
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)

    note("[2/7] Preflight exact four texture targets")
    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    rows=[]; replacements={}
    for resource,spec in TARGETS.items():
        old=decode_primary(dat,table,resource,p14); new=old
        for tex,ts in spec.items():
            p=assets/ts["asset"]
            if not p.exists(): raise RuntimeError("Missing asset "+str(p))
            new,row=patch_texture(new,tex,p,ts["rects"])
            row.update(resource=resource,asset=p.name,asset_sha256=sha256_file(p))
            rows.append(row)
            note(f"  {resource}/{tex}: changed={row['changed_indexed_pixels']}")
        if new==old: raise RuntimeError(resource+" unchanged")
        replacements[resource]=dict(new_decoded=new, original_sha256=hashlib.sha256(old).hexdigest())
    write_tsv(out/"sub51o_texture_patch.tsv",rows,
              ["resource","texture","width","height","changed_indexed_pixels","unique_png_colors",
               "new_payload_sha256","asset","asset_sha256"])

    note("[3/7] Replace primary resources")
    eb=bytearray(p14.read_embedded_index(dat)); xb=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(eb,"emb"); xi=p14.parse_pidx(xb,"ext")
    with dat.open("ab") as f:
        for name,repl in replacements.items():
            encoded=p14.encode_3_0(repl["new_decoded"])
            if p14.decode_3x(encoded)!=repl["new_decoded"]: raise RuntimeError("Encode check "+name)
            off=p14.align_up(f.tell())
            if off>f.tell(): f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,tab in ((eb,ei),(xb,xi)):
                r=next(r for r in tab["primary"] if r["name"]==name)
                struct.pack_into("<III",blob,r["record_off"]+12,off,len(repl["new_decoded"]),len(encoded))

    note("[4/7] Rebuild FSTS duplicates")
    fsts=[]
    with dat.open("r+b") as f:
        for r in ei["offset2_rows"]:
            f.seek(r["file_off"]); bundle=f.read(r["file_size"])
            rebuilt,changes=p14.rebuild_fsts(bundle,r["name"],replacements)
            if not changes: continue
            f.seek(0,2); off=p14.align_up(f.tell())
            if off>f.tell(): f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,tab in ((eb,ei),(xb,xi)):
                q=next(q for q in tab["offset2_rows"] if q["index"]==r["index"])
                struct.pack_into("<II",blob,q["record_abs"]+8,off,len(rebuilt))
            fsts.append(dict(bundle=r["name"],changes=str(changes)))
        f.seek(0); f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/"sub51o_fsts_rebuild.tsv",fsts,["bundle","changes"])

    note("[5/7] Build SUB51O by copying exact SUB51N and appending changed core files")
    final=out/FINAL_NAME
    if final.exists(): final.unlink()
    shutil.copyfile(source,final)
    with final.open("r+b") as f:
        vds=p15.read_volume_descriptors(f)
        for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx)):
            recs=[p15.find_path(f,vd,ip.split("/")) for vd in vds if vd["type"] in (1,2)]
            ext=p15.append_file_sector_aligned(f,host,host.name)
            for q in recs:
                if q: p15.patch_directory_record(f,q["record_offset"],ext["lba"],ext["size"])
        f.seek(0,2); p15.update_volume_space(f,vds,(f.tell()+2047)//2048)

    note("[6/7] Verify DAT/IDX and preserve every PMF")
    core=[]
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx)):
        sz,hs=segsha(final,ip); ok=hs==sha256_file(host)
        core.append(dict(iso_path=ip,size=sz,sha256=hs,match="YES" if ok else "NO"))
        if not ok: raise RuntimeError("Core verify failed "+ip)
    write_tsv(out/"sub51o_core_verification.tsv",core,["iso_path","size","sha256","match"])
    movies=[]
    for ip in walk_pmfs(source):
        _,a=segsha(source,ip); _,b=segsha(final,ip); ok=a==b
        movies.append(dict(iso_path=ip,source_sha256=a,final_sha256=b,match="YES" if ok else "NO"))
        if not ok: raise RuntimeError("PMF changed "+ip)
    write_tsv(out/"sub51o_movie_preservation.tsv",movies,["iso_path","source_sha256","final_sha256","match"])

    note("[7/7] Final report")
    report={
        "stage":"SUB51P_FIX4_MODESEL_TITLE_FIX",
        "source_sub51n_sha256":SOURCE_SHA,
        "final_iso":str(final),
        "final_iso_size":final.stat().st_size,
        "final_iso_sha256":sha256_file(final),
        "resources_changed":sorted(replacements),
        "textures_changed":len(rows),
        "textures":["gauge.ccs/TEX_red","gauge.ccs/TEX_white","gauge.ccs/TEX_xpanel","title.ccs/TEX_panel","title.ccs/TEX_panel2","title.ccs/TEX_panel3"],
        "pmf_movies_preserved":len(movies),
        "static_qa":"PASS",
        "runtime_qa":"PENDING",
        "external_python_packages_required":False,
    }
    (out/"SUB51O_static_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51P FIX4 - ModeSelTitleFix\n\n"
        f"SourceSUB51N_SHA256={SOURCE_SHA}\nFinalISO={final}\nFinalSHA256={report['final_iso_sha256']}\n"
        "Changed=gauge TEX_red/TEX_white/TEX_xpanel + title continue-selected row shift on TEX_panel/TEX_panel2/TEX_panel3\n"
        "Purpose=Use screenshot-based Game Mode Select header image; keep bottom controls; shift Continue-selected title row left to reduce white gap\n"
        f"PMFsPreserved={len(movies)}\nStaticQA=PASS\nRuntimeQA=PENDING\n"
        "ExternalPythonPackagesRequired=NO\n",
        encoding="utf-8-sig")
    shutil.rmtree(work,ignore_errors=True)
    note("SUCCESS "+str(final))

if __name__=="__main__":
    try: main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
