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
OUT_REL=Path(r"analysis\sub\sub52i_p0_rollback_fix1")
FINAL_NAME="Naruto_KR_MOV06E_SUB52I_P0_Rollback_FIX1.iso"


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



# SUB52I: conservative, evidence-checked rollback of the two verified regressions.
# The prior FIX3 attempted BOOT/EBOOT searches but actually changed zero strings.
FIX3_SHA="87e1d9ad950e8b2ed9674e3569a139c21a39f93db7cbbd66997ee03f3162f194"
FIX1_SHA="f595279862cd1fc0b208d40645b1629abd6af3c9ae4849d0edbc8c09c99516d1"
FIX3_CANDIDATES=[
    Path('Naruto_KR_MOV06E_SUB52H_FIX3.iso'),
    Path(r'analysis\sub\sub52h_residual_fix2\Naruto_KR_MOV06E_SUB52H_FIX3.iso'),
    Path(r'analysis\sub\sub52h_fix3\Naruto_KR_MOV06E_SUB52H_FIX3.iso'),
]
FIX1_CANDIDATES=[
    Path('Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso'),
    Path(r'patched_iso\Naruto_KR_MOV06E_SUB52G_FIX1_FinalResidual.iso'),
]
TEXTURE_ROLLBACK=[('mugen.ccs','TEX_hanyou'),('mgselect.ccs','TEX_mgselect3')]
UV_KEYS=[b'#061\t=',b'#066\t=']
EXPECTED_CURRENT={b'#061\t=':b'0,0,44,20',b'#066\t=':b'52,0,128,20'}
EXPECTED_PRE={b'#061\t=':b'0,0,20,20',b'#066\t=':b'20,0,40,20'}


def choose_sha_verified(root, candidates, expected_sha, kind):
    present=[]
    for rel in candidates:
        p=root/rel
        if not p.is_file(): continue
        actual=sha256_file(p)
        present.append((str(p),actual))
        if actual==expected_sha:
            return p
    raise RuntimeError(kind+' exact ISO not found. Existing candidates / SHA256='+json.dumps(present,ensure_ascii=False))


def texture_payload(blob,desc):
    o=desc['offset']+36
    return blob[o:o+desc['data_len']]


def transplant_payload(current, previous, texture, resource):
    ct=find_texture(current,texture)
    pt=find_texture(previous,texture)
    for key in ('width','height','type','data_len'):
        if ct[key]!=pt[key]:
            raise RuntimeError(f'{resource}/{texture} format mismatch: {key}')
    if find_palette(current,ct['palette'])!=find_palette(previous,pt['palette']):
        raise RuntimeError(f'{resource}/{texture} palette differs between FIX1 and FIX3')
    old=texture_payload(current,ct)
    baseline=texture_payload(previous,pt)
    if old==baseline:
        raise RuntimeError(f'{resource}/{texture} unexpectedly unchanged: refusing misleading rollback')
    result=bytearray(current)
    at=ct['offset']+36
    result[at:at+ct['data_len']]=baseline
    assert texture_payload(result,ct)==baseline
    # count changed INDEX values, not the source PNG pixels, so 4bpp is handled correctly
    idx1=decode_indices(current,ct)
    idx2=decode_indices(previous,pt)
    pixels=sum(a!=b for r1,r2 in zip(idx1,idx2) for a,b in zip(r1,r2))
    row=dict(resource=resource,texture=texture,pixels_restored=pixels,
             payload_bytes=len(old),before_sha256=hashlib.sha256(old).hexdigest(),
             restored_sha256=hashlib.sha256(baseline).hexdigest(),status='EXACT_INDEX_RESTORE')
    return bytes(result),row


def find_title_uv(blob, key, expected, title_anchor):
    """Find one UV setting *under its TEX_hanyou title reference*.

    mugen.tbl repeats #061 and #066 in unrelated sections. Require exact
    adjacent #060/#065 TEX_hanyou line to disambiguate instead of relying
    on a globally unique key.
    """
    pat=(rb'(?m)^'+re.escape(title_anchor)+rb'\r?\n'
         +rb'(?P<uv>'+re.escape(key)+rb'[^\r\n]*)')
    matches=list(re.finditer(pat,blob))
    if len(matches)!=1:
        raise RuntimeError(
            f'Expected exactly one TEX_hanyou title UV {key!r} after '
            f'{title_anchor!r}, observed {len(matches)}')
    m=matches[0]
    value=m.group('uv')
    if value != key+expected:
        raise RuntimeError(f'Unexpected title UV {key!r}: {value!r}, '
                           f'expected {key+expected!r}')
    return m.span('uv'),value


def list_key_lines(blob,key):
    pat=rb'(?m)^'+re.escape(key)+rb'[^\r\n]*'
    return [m.group(0) for m in re.finditer(pat,blob)]


def patch_uv_only(current,previous):
    # Exact title texture anchors. The unrelated #061 (skill index)
    # and #066 (character name) must remain byte-identical to FIX3.
    anchors={
        b'#061\t=':b'#060\t=TEX_hanyou',
        b'#066\t=':b'#065\t=TEX_hanyou',
    }
    result=current
    rows=[]
    for key in UV_KEYS:
        title_anchor=anchors[key]
        (cstart,cend),cr=find_title_uv(result,key,EXPECTED_CURRENT[key],title_anchor)
        _,pr=find_title_uv(previous,key,EXPECTED_PRE[key],title_anchor)
        before_lines=list_key_lines(result,key)
        if len(before_lines)<2:
            raise RuntimeError(f'Expected a duplicated {key!r} entry for safety check')
        result=result[:cstart]+pr+result[cend:]
        after_lines=list_key_lines(result,key)
        # Exactly one title UV may change; all other repeated key entries remain.
        expected_lines=list(before_lines)
        old_match_count=sum(1 for x in expected_lines if x==cr)
        if old_match_count!=1:
            raise RuntimeError(f'Title UV {key!r} occurs {old_match_count} times; unsafe to patch')
        expected_lines[expected_lines.index(cr)]=pr
        if after_lines!=expected_lines:
            raise RuntimeError(f'Unrelated {key!r} records were modified')
        rows.append(dict(
            key=key.decode('ascii'),
            anchor=title_anchor.decode('ascii'),
            total_duplicate_key_rows=len(before_lines),
            fix3_line=cr.decode('ascii'),
            restored_line=pr.decode('ascii'),
            status='TITLE_UV_ONLY_EXACT_RESTORE',
        ))
    for key in UV_KEYS:
        title_anchor=anchors[key]
        find_title_uv(result,key,EXPECTED_PRE[key],title_anchor)
    return result,rows


def png_chunk(kind,data):
    crc=binascii.crc32(kind)
    crc=binascii.crc32(data,crc)&0xffffffff
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',crc)


def write_tex_png(path,raw,name):
    # Standard-library RGBA PNG export, no Pillow dependency.
    t=find_texture(raw,name)
    pal=find_palette(raw,t['palette'])
    rows=decode_indices(raw,t)
    h=t['height'];w=t['width']
    pix=bytearray()
    for row in rows:
        pix.append(0)
        for idx in row:
            pix.extend(pal[idx] if idx<len(pal) else (255,0,255,255))
    ihdr=struct.pack('>IIBBBBB',w,h,8,6,0,0,0)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',ihdr)+png_chunk(b'IDAT',zlib.compress(bytes(pix),9))+png_chunk(b'IEND',b''))


def dump_static_evidence(cur_dat,cur_table,old_dat,old_table,mod14,out):
    p=out/'comparisons'
    p.mkdir(exist_ok=True)
    pairs=[('mugen.ccs','TEX_hanyou'),('mgselect.ccs','TEX_mgselect3'),
           ('mugen.ccs','TEX_name'),('mugen.ccs','TEX_st_sik')]
    rows=[]
    for resource,tex in pairs:
        try:
            a=decode_primary(cur_dat,cur_table,resource,mod14)
            b=decode_primary(old_dat,old_table,resource,mod14)
            ta=find_texture(a,tex);tb=find_texture(b,tex)
            ha=hashlib.sha256(texture_payload(a,ta)).hexdigest()
            hb=hashlib.sha256(texture_payload(b,tb)).hexdigest()
            write_tex_png(p/(resource.replace('.ccs','')+'__'+tex+'__FIX3.png'),a,tex)
            write_tex_png(p/(resource.replace('.ccs','')+'__'+tex+'__BEFORE_FIX3.png'),b,tex)
            rows.append(dict(resource=resource,texture=tex,fix3_payload_sha256=ha,
                             baseline_payload_sha256=hb,identical=ha==hb,status='EXPORTED'))
        except Exception as exc:
            rows.append(dict(resource=resource,texture=tex,status='ERROR',error=str(exc)))
    write_tsv(out/'target_texture_evidence.tsv',rows,
              ['resource','texture','fix3_payload_sha256','baseline_payload_sha256','identical','status','error'])
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default=r'D:\narutimate portable')
    parser.add_argument('--inspect-only',action='store_true')
    args=parser.parse_args()
    root=Path(args.root)
    out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    print('=== SUB52I P0 SAFE ROLLBACK FIX1 ===',flush=True)
    print('Do not touch BOOT/EBOOT or any other unrelated CCS/TBL resource.',flush=True)

    print('[1/8] Verify exact source ISOs',flush=True)
    current=choose_sha_verified(root,FIX3_CANDIDATES,FIX3_SHA,'FIX3')
    previous=choose_sha_verified(root,FIX1_CANDIDATES,FIX1_SHA,'Pre-FIX3 (SUB52G FIX1)')
    print('FIX3=',current,flush=True)
    print('BASE=',previous,flush=True)
    m=mod('sub52i_p14',root/r'analysis\stage14\naruto_patcher.py')
    p15=mod('sub52i_p15',root/r'analysis\stage15\stage15_iso_patcher.py')
    work=out/'_work'
    if work.exists():shutil.rmtree(work)
    work.mkdir()
    cur_dat=work/'current_naruto.dat'
    prev_dat=work/'previous_naruto.dat'
    idx=work/'naruto.idx'

    print('[2/8] Extract DAT and index from verified ISO sectors',flush=True)
    extract(current,'PSP_GAME/USRDIR/naruto.dat',cur_dat)
    extract(previous,'PSP_GAME/USRDIR/naruto.dat',prev_dat)
    extract(current,'PSP_GAME/USRDIR/naruto.idx',idx)
    cur_tab=m.parse_pidx(m.read_embedded_index(cur_dat),'fix3')
    prev_tab=m.parse_pidx(m.read_embedded_index(prev_dat),'base')
    
    print('[3/8] Export targeted before/after diagnostic PNGs',flush=True)
    evidence=dump_static_evidence(cur_dat,cur_tab,prev_dat,prev_tab,m,out)

    print('[4/8] Restore EXACT texture index payloads from SUB52G FIX1',flush=True)
    replacements={}
    texrows=[]
    for resource,tex in TEXTURE_ROLLBACK:
        c=decode_primary(cur_dat,cur_tab,resource,m)
        b=decode_primary(prev_dat,prev_tab,resource,m)
        patched,row=transplant_payload(c,b,tex,resource)
        replacements[resource]=dict(new_decoded=patched,original_sha256=hashlib.sha256(c).hexdigest())
        texrows.append(row)
        print('RESTORED',resource,tex,'indexed-pixels',row['pixels_restored'],flush=True)
    write_tsv(out/'texture_rollback.tsv',texrows,
              ['resource','texture','pixels_restored','payload_bytes','before_sha256','restored_sha256','status'])

    print('[5/8] Restore ONLY mugen.tbl #061/#066 UV values',flush=True)
    c=decode_primary(cur_dat,cur_tab,'mugen.tbl',m)
    b=decode_primary(prev_dat,prev_tab,'mugen.tbl',m)
    patched,uvrows=patch_uv_only(c,b)
    replacements['mugen.tbl']=dict(new_decoded=patched,original_sha256=hashlib.sha256(c).hexdigest())
    write_tsv(out/'uv_rollback.tsv',uvrows,['key','anchor','total_duplicate_key_rows','fix3_line','restored_line','status'])

    if args.inspect_only:
        print('INSPECT ONLY complete: no ISO changed or created.',flush=True)
        return

    # Require enough free disk space for safe, non-destructive ISO copy.
    approx=(current.stat().st_size + cur_dat.stat().st_size//2 + 300*1024*1024)
    free=shutil.disk_usage(str(root)).free
    print('DISK_FREE=',free,'EST_REQUIRED=',approx,flush=True)
    if free<approx:
        raise RuntimeError('Insufficient disk space for non-destructive ISO build: '
                           f'free={free}, minimum estimate={approx}. No source ISO modified.')

    print('[6/8] Rebuild DAT/IDX + FSTS duplicates',flush=True)
    eb=bytearray(m.read_embedded_index(cur_dat));xb=bytearray(idx.read_bytes())
    ei=m.parse_pidx(eb,'emb');xi=m.parse_pidx(xb,'ext')
    rebuildrows=[]
    with cur_dat.open('ab') as f:
        for name,repl in replacements.items():
            new=repl['new_decoded']
            encoded=m.encode_3_0(new)
            if m.decode_3x(encoded)!=new:
                raise RuntimeError('Compression roundtrip mismatch for '+name)
            off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(encoded)
            for blob,table in ((eb,ei),(xb,xi)):
                r=next(v for v in table['primary'] if v['name']==name)
                struct.pack_into('<III',blob,r['record_off']+12,off,len(new),len(encoded))
            rebuildrows.append(dict(resource=name,decoded_size=len(new),stored_size=len(encoded),new_offset=off))
    with cur_dat.open('r+b') as f:
        for r in ei['offset2_rows']:
            f.seek(r['file_off']);bundle=f.read(r['file_size'])
            rebuilt,changes=m.rebuild_fsts(bundle,r['name'],replacements)
            if not changes:continue
            f.seek(0,2);off=m.align_up(f.tell())
            if off>f.tell():f.write(bytes(off-f.tell()))
            f.write(rebuilt)
            for blob,tab in ((eb,ei),(xb,xi)):
                q=next(x for x in tab['offset2_rows'] if x['index']==r['index'])
                struct.pack_into('<II',blob,q['record_abs']+8,off,len(rebuilt))
        f.seek(0);f.write(eb)
    idx.write_bytes(xb)
    write_tsv(out/'resource_rebuild.tsv',rebuildrows,
              ['resource','decoded_size','stored_size','new_offset'])
    fin=m.parse_pidx(m.read_embedded_index(cur_dat),'final')
    for name,repl in replacements.items():
        if decode_primary(cur_dat,fin,name,m)!=repl['new_decoded']:
            raise RuntimeError('Rebuilt resource validation failure: '+name)

    print('[7/8] Build safe ISO copy and re-point only DAT/IDX',flush=True)
    final=out/FINAL_NAME
    if final.exists():final.unlink()
    shutil.copyfile(current,final)
    with final.open('r+b') as f:
        vds=p15.read_volume_descriptors(f)
        for ip,host in (("PSP_GAME/USRDIR/naruto.dat",cur_dat),
                        ("PSP_GAME/USRDIR/naruto.idx",idx)):
            recs=[p15.find_path(f,vd,ip.split('/')) for vd in vds if vd['type'] in (1,2)]
            ext=p15.append_file_sector_aligned(f,host,host.name)
            for rr in recs:
                if rr:p15.patch_directory_record(f,rr['record_offset'],ext['lba'],ext['size'])
        f.seek(0,2);p15.update_volume_space(f,vds,(f.tell()+2047)//2048)

    print('[8/8] Verify core, untouched BOOT/EBOOT and 24 PMFs',flush=True)
    core=[]
    for ip,host in (("PSP_GAME/USRDIR/naruto.dat",cur_dat),
                    ("PSP_GAME/USRDIR/naruto.idx",idx)):
        _,a=segsha(final,ip);b=sha256_file(host)
        if a!=b:raise RuntimeError('ISO core hash mismatch: '+ip)
        core.append(dict(iso_path=ip,status='MATCH_GENERATED',sha256=a))
    for ip in ('PSP_GAME/SYSDIR/BOOT.BIN','PSP_GAME/SYSDIR/EBOOT.BIN'):
        _,a=segsha(current,ip);_,b=segsha(final,ip)
        if a!=b:raise RuntimeError('Unexpected BOOT/EBOOT change: '+ip)
        core.append(dict(iso_path=ip,status='PRESERVED_FROM_FIX3',sha256=b))
    write_tsv(out/'core_verification.tsv',core,['iso_path','status','sha256'])
    movies=[]
    for ip in walk_pmfs(current):
        _,a=segsha(current,ip);_,b=segsha(final,ip)
        if a!=b:raise RuntimeError('PMF changed: '+ip)
        movies.append(dict(iso_path=ip,sha256=b,status='PRESERVED'))
    write_tsv(out/'movie_preservation.tsv',movies,['iso_path','sha256','status'])
    # check decoded payload, not approximate PNG palette projection
    datfin=work/'verify_final.dat'
    extract(final,'PSP_GAME/USRDIR/naruto.dat',datfin)
    tf=m.parse_pidx(m.read_embedded_index(datfin),'ISO-final')
    for name,repl in replacements.items():
        if decode_primary(datfin,tf,name,m)!=repl['new_decoded']:
            raise RuntimeError('Final ISO embedded resource does not match expected: '+name)

    summary=dict(stage='SUB52I_P0_SAFE_ROLLBACK_FIX1',
                 source_fix3_iso=str(current),source_fix3_sha256=FIX3_SHA,
                 baseline_iso=str(previous),baseline_sha256=FIX1_SHA,
                 final_iso=str(final),final_size=final.stat().st_size,
                 final_sha256=sha256_file(final),
                 texture_payloads_restored=len(texrows),
                 uv_rows_restored=len(uvrows),
                 text_resource_preserved_except_uv=True,
                 pmfs_preserved=len(movies),
                 boot_eboot_preserved=True,
                 static_qa='PASS',runtime_qa='NOT_TESTED',
                 remaining='Shikamaru character name duplication, tree-climb start prompt, counter unit glyph, winner reward strings; requires exact source identification')
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in summary.items())+'\n',encoding='utf-8-sig')
    shutil.rmtree(work,ignore_errors=True)
    print('OUTPUT_ISO='+str(final),flush=True)
    print('FINAL_SHA256='+summary['final_sha256'],flush=True)
    print('STATIC_QA=PASS',flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
