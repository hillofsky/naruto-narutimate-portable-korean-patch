#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import argparse,binascii,csv,hashlib,importlib.util,json,shutil,struct,sys,traceback,zlib,re

SECTOR=2048
SOURCE_CANDIDATES=[
    Path(r"Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso"),
    Path(r"Naruto_KR_MOV06E_SUB52G_FinalResidual.iso"),
    Path(r"patched_iso\Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso"),
    Path(r"patched_iso\Naruto_KR_MOV06E_SUB52G_FinalResidual.iso"),
    Path(r"Naruto_KR_MOV06E_SUB52E_StaticImages.iso"),
]
OUT_REL=Path(r"analysis\sub\sub52j_safe_atlas")
FINAL_NAME="Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso"


def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:
        raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":
        raise RuntimeError("Bad ISO")
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
        if not hit:
            raise RuntimeError("ISO missing "+path)
        cur=hit
    return cur


def extract(iso,ipath,out):
    e=findiso(iso,ipath);Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b: raise RuntimeError("ISO EOF")
            fo.write(b); rem-=len(b)


def segsha(iso,ipath):
    e=findiso(iso,ipath);h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR);rem=e["size"]
        while rem:
            b=f.read(min(rem,1024*1024))
            if not b: raise RuntimeError("ISO EOF")
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
    walk(path)
    return sorted(out)

# PNG decoder helpers

def paeth(a,b,c):
    p=a+b-c;pa=abs(p-a);pb=abs(p-b);pc=abs(p-c)
    if pa<=pb and pa<=pc:return a
    if pb<=pc:return b
    return c


def read_png_rgba(path):
    b=Path(path).read_bytes()
    if b[:8]!=b"\x89PNG\r\n\x1a\n": raise RuntimeError("Not PNG: "+str(path))
    pos=8;idat=bytearray();plte=None;trns=None;ihdr=None
    while pos+12<=len(b):
        n=struct.unpack(">I",b[pos:pos+4])[0];typ=b[pos+4:pos+8];data=b[pos+8:pos+8+n];pos+=12+n
        if typ==b"IHDR": ihdr=struct.unpack(">IIBBBBB",data)
        elif typ==b"PLTE": plte=[tuple(data[i:i+3]) for i in range(0,len(data),3)]
        elif typ==b"tRNS": trns=bytes(data)
        elif typ==b"IDAT": idat.extend(data)
        elif typ==b"IEND": break
    if not ihdr: raise RuntimeError("PNG missing IHDR")
    w,h,depth,ctype,comp,filt,interlace=ihdr
    if depth!=8 or interlace!=0: raise RuntimeError("Unsupported PNG")
    channels={0:1,2:3,3:1,4:2,6:4}.get(ctype)
    if not channels: raise RuntimeError("Unsupported PNG type")
    raw=zlib.decompress(bytes(idat));stride=w*channels
    rows=[];off=0;prev=bytearray(stride)
    for _ in range(h):
        ft=raw[off];off+=1
        cur=bytearray(raw[off:off+stride]);off+=stride
        for x in range(stride):
            a=cur[x-channels] if x>=channels else 0
            bb=prev[x];c=prev[x-channels] if x>=channels else 0
            if ft==1: cur[x]=(cur[x]+a)&255
            elif ft==2: cur[x]=(cur[x]+bb)&255
            elif ft==3: cur[x]=(cur[x]+((a+bb)//2))&255
            elif ft==4: cur[x]=(cur[x]+paeth(a,bb,c))&255
            elif ft!=0: raise RuntimeError("PNG filter")
        rows.append(cur);prev=cur
    rgba=[]
    for row in rows:
        rr=[]
        if ctype==6:
            for x in range(w): rr.append(tuple(row[x*4:x*4+4]))
        elif ctype==2:
            for x in range(w):
                r,g,bv=row[x*3:x*3+3];rr.append((r,g,bv,255))
        elif ctype==0:
            for x in range(w): rr.append((row[x],row[x],row[x],255))
        elif ctype==4:
            for x in range(w):
                g,a=row[x*2:x*2+2];rr.append((g,g,g,a))
        else:
            if plte is None: raise RuntimeError("Indexed PNG without PLTE")
            for x in range(w):
                i=row[x];r,g,bv=plte[i];a=trns[i] if trns and i<len(trns) else 255
                rr.append((r,g,bv,a))
        rgba.append(rr)
    return w,h,rgba


def ccs_names(b):
    pc,nc=struct.unpack_from("<II",b,0x44);no=0x4C+32*pc
    if pc>10000 or nc>50000 or no+32*nc>len(b): raise RuntimeError("Bad CCS")
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
    wanted=names.index(name);magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic or struct.unpack_from("<I",b,o+8)[0]!=wanted: continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if typ not in (0x13,0x14) or we>12 or he>12: continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b): return dict(offset=o,palette=palid,type=typ,width=w,height=h,data_len=dl)
    raise RuntimeError("Texture record missing "+name)


def decode_indices(b,t):
    raw=b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    vals=[]
    if t["type"]==0x13: vals=list(raw)
    else:
        for v in raw: vals.extend((v&15,(v>>4)&15))
    rows=[vals[y*t["width"]:(y+1)*t["width"]] for y in range(t["height"])]
    rows.reverse(); return rows


def encode_indices(rows,t):
    rows=list(reversed(rows));flat=[x for r in rows for x in r]
    if t["type"]==0x13: raw=bytes(flat)
    else: raw=bytes((flat[i]&15)|((flat[i+1]&15)<<4) for i in range(0,len(flat),2))
    if len(raw)!=t["data_len"]: raise RuntimeError("Encoded length mismatch")
    return raw


def nearest_index(c,pal,cache):
    if c in cache: return cache[c]
    best=0;bestd=None
    for i,p in enumerate(pal):
        dr=c[0]-p[0];dg=c[1]-p[1];db=c[2]-p[2];da=c[3]-p[3]
        d=dr*dr+dg*dg+db*db+5*da*da
        if bestd is None or d<bestd: bestd=d;best=i
    cache[c]=best
    return best


def patch_texture(ccs,name,png):
    b=bytearray(ccs);t=find_texture(b,name);pal=find_palette(b,t["palette"])
    w,h,rgba=read_png_rgba(png)
    if (w,h)!=(t["width"],t["height"]): raise RuntimeError(f"{name}: PNG size mismatch")
    old=decode_indices(b,t);new=[r[:] for r in old];cache={};changed=0
    for y in range(h):
        for x in range(w):
            idx=nearest_index(rgba[y][x],pal,cache)
            if new[y][x]!=idx: changed+=1
            new[y][x]=idx
    raw=encode_indices(new,t);start=t["offset"]+36;b[start:start+len(raw)]=raw
    return bytes(b),dict(texture=name,width=w,height=h,changed_indexed_pixels=changed,
                         png_colors=len(cache),payload_sha256=hashlib.sha256(raw).hexdigest())


def decode_primary(dat,table,name,m):
    r=next((x for x in table["primary"] if x["name"]==name),None)
    if not r: raise RuntimeError("Primary missing "+name)
    with Path(dat).open("rb") as f:
        f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
    return m.decode_stored(stored,r["size"],r["zsize"])


def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def load_mapping(path):
    rows=[]
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f,delimiter="\t"))
    cmap={}
    for r in rows:
        ch=r["hangul"]
        code=r["donor_sjis_hex"].replace(" ","").upper()
        if ch in cmap and cmap[ch]!=code:
            raise RuntimeError("mapping conflict for "+ch)
        cmap[ch]=code
    return cmap


def encode_text(s,cmap):
    out=bytearray()
    for ch in s:
        if ch in cmap:
            out.extend(bytes.fromhex(cmap[ch]))
        elif ch=="·":
            out.extend(b"/")
        else:
            try:
                out.extend(ch.encode("cp932"))
            except UnicodeEncodeError:
                raise RuntimeError(f"Cannot encode {ch!r} U+{ord(ch):04X} in {s!r}")
    return bytes(out)


def patch_boot_bytes(boot_bytes, patches, cmap):
    """
    Patch exact NUL-terminated C strings by content, not historical offsets.
    This survives BOOT layout changes and avoids substring corruption.
    """
    data=bytearray(boot_bytes)
    rows=[]
    prepared=[]
    for p in patches:
        old=encode_text(p['source'],cmap)
        new=encode_text(p['korean'],cmap)
        prepared.append((len(old),p,old,new))
    prepared.sort(key=lambda x:x[0], reverse=True)

    for _,p,old,new in prepared:
        if len(new)>len(old):
            raise RuntimeError(f"BOOT replacement longer than source: {p['id']}")

        old_sig=old+b'\\x00'
        new_sig=new+b'\\x00'
        blob=bytes(data)

        old_hits=[]
        pos=0
        while True:
            at=blob.find(old_sig,pos)
            if at<0: break
            old_hits.append(at)
            pos=at+1

        already=[]
        pos=0
        while True:
            at=blob.find(new_sig,pos)
            if at<0: break
            already.append(at)
            pos=at+1

        if old_hits:
            fill=new+b'\\x00'+bytes(len(old)-len(new))
            for at in reversed(old_hits):
                data[at:at+len(old)+1]=fill
            status='PATCHED'
        elif already:
            status='ALREADY_TRANSLATED'
        else:
            status='NOT_FOUND'

        rows.append(dict(
            id=p['id'],
            historical_offset=p.get('offset_hex',''),
            source=p['source'],
            korean=p['korean'],
            source_cstring_hits=len(old_hits),
            already_korean_hits=len(already),
            old_bytes=len(old),
            new_bytes=len(new),
            status=status,
        ))
    return bytes(data),rows


def patch_exact_lines(decoded, replacements, cmap, resource_name):
    data=decoded
    rows=[]
    for p in replacements:
        old=encode_text(p['source'],cmap)
        new=encode_text(p['korean'],cmap)
        source_count=data.count(old)
        korean_count=data.count(new)

        if source_count>0:
            data=data.replace(old,new)
            status='PATCHED'
        elif korean_count>0:
            status='ALREADY_TRANSLATED'
        else:
            status='NOT_FOUND'

        rows.append(dict(
            resource=resource_name,
            source=p['source'],
            korean=p['korean'],
            occurrences=source_count,
            already_korean_occurrences=korean_count,
            old_bytes=len(old),
            new_bytes=len(new),
            status=status
        ))
    return data,rows


def choose_source(root, explicit=None):
    if explicit:
        p=Path(explicit)
        if not p.is_absolute():
            p=root/p
        if not p.exists(): raise RuntimeError("Explicit source ISO missing: "+str(p))
        return p
    for rel in SOURCE_CANDIDATES:
        p=root/rel
        if p.exists(): return p
    raise RuntimeError("No source ISO found. Tried: " + ", ".join(str(root/r) for r in SOURCE_CANDIDATES))


def load_tsv_dict(path):
    with Path(path).open('r',encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f, delimiter='\t'))




# SUB52J: source SHA-pinned, UV-safe atlas fix for the two screenshot problems.
CURRENT_SHA='e67cbaca44abe4145a2ba97d52c6eebe32690373394b4925eced0cb486a380b9'
DONOR_SHA='46a2e934a4f6fc44585fac31b68735f04e182d4392251db76c89050c0b9de5d0'
SOURCE_CANDIDATES=[
    Path(r'analysis\sub\sub52i_p0_rollback_fix1\Naruto_KR_MOV06E_SUB52I_P0_Rollback_FIX1.iso'),
    Path('Naruto_KR_MOV06E_SUB52I_P0_Rollback_FIX1.iso'),
]
DONOR_CANDIDATES=[
    Path('Naruto_KR_MOV06E_SUB52D2_FIX2_StaticText.iso'),
    Path(r'analysis\sub\sub52d2_fix2_static_text_apply\Naruto_KR_MOV06E_SUB52D2_FIX2_StaticText.iso'),
    Path(r'analysis\sub\sub52d2_static_text_apply\Naruto_KR_MOV06E_SUB52D2_FIX2_StaticText.iso'),
]
MUGEN_RECTS=[(0,0,82,20)]
MGSELECT_RECTS=[
    (0,0,60,38),(62,0,128,38),(132,0,168,38),(169,0,203,38),
    (204,0,240,38),(241,0,275,38),(276,0,312,38),(313,0,348,38),(349,0,385,38),
    (0,94,60,134),(62,94,128,134),(132,94,168,134),(169,94,203,134),
    (204,94,240,134),(241,94,275,134),(276,94,312,134),(313,94,348,134),(349,94,385,134),
    (55,170,138,203),(88,205,127,235),
]

def verified_iso(root, candidates, expected, name):
    attempts=[]
    for c in candidates:
        p=root/c
        if not p.is_file():continue
        sha=sha256_file(p)
        attempts.append((str(p),sha))
        if sha==expected:return p
    raise RuntimeError(name+' verified ISO not found: '+json.dumps(attempts,ensure_ascii=False))


def texture_payload(data, desc):
    at=desc['offset']+36
    return bytes(data[at:at+desc['data_len']])


def transplant_exact(current,donor,texture,resource):
    a=find_texture(current,texture);b=find_texture(donor,texture)
    for k in ('type','width','height','data_len'):
        if a[k]!=b[k]:raise RuntimeError(resource+' donor format conflict: '+k)
    pa=find_palette(current,a['palette']);pb=find_palette(donor,b['palette'])
    if pa!=pb:raise RuntimeError(resource+' palette mismatch between donor and source')
    dat=bytearray(current)
    at=a['offset']+36
    dat[at:at+a['data_len']]=texture_payload(donor,b)
    if texture_payload(dat,a)!=texture_payload(donor,b):raise RuntimeError('donor texture transplant mismatch')
    return bytes(dat)


def in_any(x,y,rects):
    return any(x0<=x<x1 and y0<=y<y1 for x0,y0,x1,y1 in rects)


def patch_rects(data,texture,png,rects,resource):
    """Only write pixels under authorized atlas sprite cell coordinates."""
    t=find_texture(data,texture);pal=find_palette(data,t['palette'])
    w,h,rgba=read_png_rgba(png)
    if (w,h)!=(t['width'],t['height']):raise RuntimeError('Dimension mismatch '+resource+'/'+texture)
    for x0,y0,x1,y1 in rects:
        if x0<0 or y0<0 or x1>w or y1>h or x0>=x1 or y0>=y1:
            raise RuntimeError('Invalid sprite rect '+str((x0,y0,x1,y1)))
    original=decode_indices(data,t)
    modified=[r[:] for r in original]
    cache={}
    count=0
    for y in range(h):
        for x in range(w):
            if not in_any(x,y,rects):continue
            c=rgba[y][x]
            idx=nearest_index(c,pal,cache)
            if idx!=modified[y][x]:
                count+=1
            modified[y][x]=idx
    offrect=sum((modified[y][x]!=original[y][x]) for y in range(h) for x in range(w)
                if not in_any(x,y,rects))
    if offrect!=0:raise RuntimeError('Off-rect modified pixels: '+str(offrect))
    if count==0:raise RuntimeError('No indexed pixels changed: '+resource+'/'+texture)
    newraw=encode_indices(modified,t)
    output=bytearray(data);at=t['offset']+36
    output[at:at+t['data_len']]=newraw
    checked=decode_indices(output,t)
    if checked!=modified:raise RuntimeError('Indexed encode roundtrip failed')
    return bytes(output),dict(resource=resource,texture=texture,png=str(png),
                              rect_count=len(rects),changed_pixels=count,
                              offrect_changed_pixels=offrect,
                              payload_sha256=hashlib.sha256(newraw).hexdigest())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=r'D:\narutimate portable')
    parser.add_argument('--assets',required=True)
    args=parser.parse_args()
    root=Path(args.root);assets=Path(args.assets);out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    print('=== SUB52J SAFE ATLAS FIX ===',flush=True)
    print('Two textures only; preserve mugen.tbl UV / BOOT / EBOOT / movies.',flush=True)
    source=verified_iso(root,SOURCE_CANDIDATES,CURRENT_SHA,'SUB52I FIX1')
    donor=verified_iso(root,DONOR_CANDIDATES,DONOR_SHA,'SUB52D2 FIX2 (pre-image atlas)')
    print('Source:',source,'SHA256',CURRENT_SHA,flush=True)
    print('Donor:',donor,'SHA256',DONOR_SHA,flush=True)
    m=mod('sub52j_p14',root/r'analysis\stage14\naruto_patcher.py')
    p15=mod('sub52j_p15',root/r'analysis\stage15\stage15_iso_patcher.py')
    work=out/'_work'
    if work.exists():shutil.rmtree(work)
    work.mkdir()
    dat=work/'naruto.dat';idx=work/'naruto.idx';donor_dat=work/'donor_naruto.dat'
    print('[1/7] Extract precise ISO core sources',flush=True)
    extract(source,'PSP_GAME/USRDIR/naruto.dat',dat)
    extract(source,'PSP_GAME/USRDIR/naruto.idx',idx)
    extract(donor,'PSP_GAME/USRDIR/naruto.dat',donor_dat)
    tab=m.parse_pidx(m.read_embedded_index(dat),'source')
    dt=m.parse_pidx(m.read_embedded_index(donor_dat),'donor')
    replacement={};report=[]

    print('[2/7] Exact donor restoration + fixed-cell sprite edits',flush=True)
    # The original Japanese atlas has correct separate digit/unit glyph cell geometry.
    # Restore it byte-for-byte first; then Koreanize only original fixed-size cells.
    mg=decode_primary(dat,tab,'mgselect.ccs',m)
    original=decode_primary(donor_dat,dt,'mgselect.ccs',m)
    restored=transplant_exact(mg,original,'TEX_mgselect3','mgselect.ccs')
    fixed,row=patch_rects(restored,'TEX_mgselect3',assets/'mgselect__TEX_mgselect3__SUB52J.png',
                          MGSELECT_RECTS,'mgselect.ccs')
    replacement['mgselect.ccs']={'new_decoded':fixed,'original_sha256':hashlib.sha256(mg).hexdigest()}
    report.append(row)
    # Keep short 20px UV cells. Do not expand #061/#066 or affect the duplicated keys.
    mug=decode_primary(dat,tab,'mugen.ccs',m)
    safe,row=patch_rects(mug,'TEX_hanyou',assets/'mugen__TEX_hanyou__SUB52J.png',
                        MUGEN_RECTS,'mugen.ccs')
    replacement['mugen.ccs']={'new_decoded':safe,'original_sha256':hashlib.sha256(mug).hexdigest()}
    report.append(row)
    write_tsv(out/'pixel_patch_validation.tsv',report,
              ['resource','texture','png','rect_count','changed_pixels','offrect_changed_pixels','payload_sha256'])

    print('[3/7] Assert current mugen.tbl UVs are unchanged',flush=True)
    uv=decode_primary(dat,tab,'mugen.tbl',m)
    for anchor,expect in ((b'#060\t=TEX_hanyou',b'#061\t=0,0,20,20'),
                          (b'#065\t=TEX_hanyou',b'#066\t=20,0,40,20')):
        patt=re.escape(anchor)+rb'\r?\n'+re.escape(expect)
        if len(re.findall(patt,uv))!=1:
            raise RuntimeError('Safe UV/title anchor not found: '+repr(anchor))
    original_mugen_tbl_hash=hashlib.sha256(uv).hexdigest()

    approx=source.stat().st_size+dat.stat().st_size//2+300*1024*1024
    free=shutil.disk_usage(str(root)).free
    print('DISK_FREE',free,'MIN_ESTIMATE',approx,flush=True)
    if free<approx:raise RuntimeError('Insufficient disk free space for safe copy')

    print('[4/7] Rebuild primary + FSTS duplicates',flush=True)
    eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,'emb');xi=m.parse_pidx(xb,'ext')
    rows=[]
    with dat.open('ab') as f:
        for name,repl in replacement.items():
            new=repl['new_decoded'];enc=m.encode_3_0(new)
            if m.decode_3x(enc)!=new:raise RuntimeError('Compression roundtrip failed '+name)
            off=m.align_up(f.tell());f.write(bytes(off-f.tell()));f.write(enc)
            for blob,table in ((eb,ei),(xb,xi)):
                r=next(r for r in table['primary'] if r['name']==name)
                struct.pack_into('<III',blob,r['record_off']+12,off,len(new),len(enc))
            rows.append(dict(resource=name,decoded_size=len(new),stored_size=len(enc),offset=off))
    with dat.open('r+b') as f:
        for r in ei['offset2_rows']:
            f.seek(r['file_off']);bundle=f.read(r['file_size'])
            rebuilt,changes=m.rebuild_fsts(bundle,r['name'],replacement)
            if not changes:continue
            f.seek(0,2);off=m.align_up(f.tell());f.write(bytes(off-f.tell()));f.write(rebuilt)
            for blob,table in ((eb,ei),(xb,xi)):
                q=next(v for v in table['offset2_rows'] if v['index']==r['index'])
                struct.pack_into('<II',blob,q['record_abs']+8,off,len(rebuilt))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/'resource_rebuild.tsv',rows,['resource','decoded_size','stored_size','offset'])
    fin=m.parse_pidx(m.read_embedded_index(dat),'rebuilt')
    for name,repl in replacement.items():
        if decode_primary(dat,fin,name,m)!=repl['new_decoded']:
            raise RuntimeError('Rebuilt CCS mismatch '+name)
    if hashlib.sha256(decode_primary(dat,fin,'mugen.tbl',m)).hexdigest()!=original_mugen_tbl_hash:
        raise RuntimeError('UV config changed unexpectedly')

    print('[5/7] Build new ISO preserving all unrelated sectors',flush=True)
    result=out/FINAL_NAME
    if result.exists():result.unlink()
    shutil.copyfile(source,result)
    with result.open('r+b') as f:
        vds=p15.read_volume_descriptors(f)
        for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx)):
            recs=[p15.find_path(f,vd,ip.split('/')) for vd in vds if vd['type'] in (1,2)]
            ext=p15.append_file_sector_aligned(f,host,host.name)
            for rr in recs:
                if rr:p15.patch_directory_record(f,rr['record_offset'],ext['lba'],ext['size'])
        f.seek(0,2);p15.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print('[6/7] Static QA core/unchanged text/BOOT/PMFs',flush=True)
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx)):
        if segsha(result,ip)[1]!=sha256_file(host):raise RuntimeError('Core mismatch '+ip)
    for ip in ('PSP_GAME/SYSDIR/BOOT.BIN','PSP_GAME/SYSDIR/EBOOT.BIN'):
        if segsha(source,ip)[1]!=segsha(result,ip)[1]:raise RuntimeError('BOOT/EBOOT changed '+ip)
    pmfs=walk_pmfs(source)
    for ip in pmfs:
        if segsha(source,ip)[1]!=segsha(result,ip)[1]:raise RuntimeError('PMF changed '+ip)
    final_dat=work/'verify_final.dat'
    extract(result,'PSP_GAME/USRDIR/naruto.dat',final_dat)
    final_tab=m.parse_pidx(m.read_embedded_index(final_dat),'final ISO')
    for name,repl in replacement.items():
        if decode_primary(final_dat,final_tab,name,m)!=repl['new_decoded']:
            raise RuntimeError('Final ISO CCS mismatch '+name)
    if hashlib.sha256(decode_primary(final_dat,final_tab,'mugen.tbl',m)).hexdigest()!=original_mugen_tbl_hash:
        raise RuntimeError('Final mugen.tbl changed: abort')
    print('[7/7] Save report',flush=True)
    summary=dict(stage='SUB52J_UV_SAFE_ATLAS',source_iso=str(source),source_sha256=CURRENT_SHA,
       donor_iso=str(donor),donor_sha256=DONOR_SHA,output_iso=str(result),
       output_sha256=sha256_file(result),texture_resources_changed=2,
       atlas_cell_changes=report,mugen_tbl_uv_preserved=True,pmfs_preserved=len(pmfs),
       boot_eboot_preserved=True,static_qa='PASS',runtime_qa='PENDING',
       scope='scroll title clipped and tree-climb stray counter unit; other issues remain pending')
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in summary.items()),encoding='utf-8-sig')
    print('OUTPUT_ISO='+str(result),flush=True)
    print('STATIC_QA=PASS',flush=True)
    shutil.rmtree(work,ignore_errors=True)

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
