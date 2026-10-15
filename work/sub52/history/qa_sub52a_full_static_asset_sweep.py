
from pathlib import Path
import struct, hashlib, importlib.util, json, zipfile, traceback, zlib, binascii, re, csv, os

ROOT = Path(r"D:\narutimate portable")
OUT = ROOT / r"analysis\sub\sub52a_full_static_asset_sweep"
LOGS = ROOT / "logs"
SECTOR = 2048

SOURCE_CANDIDATES = [
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX13_FullAtlas.iso",
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX12_StableUI.iso",
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX11_StableUI.iso",
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX10_StableUI.iso",
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX9_StableUI.iso",
    ROOT / r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso",
]

JP_RE = re.compile(r"[ぁ-んァ-ヶー一-龯々〆ヵヶ]{2,}")
ASCII_JP_HINTS = ("JP", "JPN", "japanese")

def choose_source():
    for p in SOURCE_CANDIDATES:
        if p.exists():
            return p
    raise RuntimeError("No source ISO found")

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:
        raise RuntimeError("Cannot import "+str(path))
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
        out.append({"name":name,"lba":int.from_bytes(r[2:6],"little"),
                    "size":int.from_bytes(r[10:14],"little"),"is_dir":bool(r[25]&2)})
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

def extract_iso_file(iso,ipath,out):
    e=findiso(iso,ipath)
    out.parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=fi.read(min(rem,1024*1024))
            if not b: raise RuntimeError("EOF")
            fo.write(b); rem-=len(b)

def ccs_names(b):
    if len(b)<0x4C: raise RuntimeError("CCS too small")
    pc,nc=struct.unpack_from("<II",b,0x44)
    no=0x4C+32*pc
    if pc>10000 or nc>50000 or no+32*nc>len(b):
        raise RuntimeError(f"Bad CCS header pc={pc} nc={nc}")
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def ccs_textures(b):
    names=ccs_names(b)
    out=[]; magic=bytes.fromhex("0003cccc")
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic: continue
        nid=struct.unpack_from("<I",b,o+8)[0]
        palid=struct.unpack_from("<I",b,o+12)[0]
        typ=b[o+21]; we,he=b[o+24:o+26]
        if nid>=len(names) or typ not in (0x13,0x14) or we>12 or he>12: continue
        w,h=1<<we,1<<he
        dl=w*h if typ==0x13 else w*h//2
        if o+36+dl<=len(b):
            out.append({"offset":o,"name":names[nid],"palette":palid,"type":typ,
                        "width":w,"height":h,"data_len":dl})
    return out

def ccs_palette(b,palid):
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

def decode_indices(b,t):
    raw=b[t["offset"]+36:t["offset"]+36+t["data_len"]]
    w,h=t["width"],t["height"]; vals=[]
    if t["type"]==0x13:
        vals=list(raw)
    else:
        for v in raw:
            vals.extend((v&15,(v>>4)&15))
    if len(vals)!=w*h: raise RuntimeError("index len mismatch")
    rows=[vals[y*w:(y+1)*w] for y in range(h)]
    rows.reverse()
    return rows

def png_chunk(kind,data):
    crc=binascii.crc32(kind)
    crc=binascii.crc32(data,crc)&0xffffffff
    return struct.pack(">I",len(data))+kind+data+struct.pack(">I",crc)

def write_png(path,w,h,rgba):
    raw=bytearray(); stride=w*4
    for y in range(h):
        raw.append(0)
        raw.extend(rgba[y*stride:(y+1)*stride])
    sig=b"\x89PNG\r\n\x1a\n"
    ihdr=struct.pack(">IIBBBBB",w,h,8,6,0,0,0)
    Path(path).write_bytes(sig+png_chunk(b"IHDR",ihdr)+png_chunk(b"IDAT",zlib.compress(bytes(raw),9))+png_chunk(b"IEND",b""))

def to_rgba(rows,pal):
    out=bytearray()
    for row in rows:
        for idx in row:
            if idx<len(pal): out.extend(bytes(pal[idx]))
            else: out.extend(b"\xff\x00\xff\xff")
    return bytes(out)

def sanitize(s):
    return re.sub(r'[^A-Za-z0-9._-]+','_',s)

def extract_jp_strings(data):
    results=[]
    seen=set()
    # CP932
    try:
        text=data.decode("cp932",errors="ignore")
        for m in JP_RE.finditer(text):
            s=m.group(0)
            if s in seen: continue
            seen.add(s)
            try:
                enc=s.encode("cp932")
                off=data.find(enc)
            except Exception:
                off=-1
            results.append(("cp932",s,off))
    except Exception:
        pass
    # UTF-16 LE
    try:
        text=data.decode("utf-16le",errors="ignore")
        for m in JP_RE.finditer(text):
            s=m.group(0)
            key=("utf16le",s)
            if key in seen: continue
            seen.add(key)
            try: off=data.find(s.encode("utf-16le"))
            except: off=-1
            results.append(("utf16le",s,off))
    except Exception:
        pass
    # UTF-16 BE
    try:
        text=data.decode("utf-16be",errors="ignore")
        for m in JP_RE.finditer(text):
            s=m.group(0)
            key=("utf16be",s)
            if key in seen: continue
            seen.add(key)
            try: off=data.find(s.encode("utf-16be"))
            except: off=-1
            results.append(("utf16be",s,off))
    except Exception:
        pass
    return results

def write_tsv(path, rows, fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def zip_chunks(files, prefix, max_bytes=80*1024*1024):
    parts=[]; cur=[]; total=0; part=1
    for p in files:
        sz=p.stat().st_size
        if cur and total+sz>max_bytes:
            z=LOGS/f"{prefix}_{part:02d}_upload.zip"
            with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
                for q in cur: zz.write(q,q.relative_to(OUT))
            parts.append(str(z)); part+=1; cur=[]; total=0
        cur.append(p); total+=sz
    if cur:
        z=LOGS/f"{prefix}_{part:02d}_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for q in cur: zz.write(q,q.relative_to(OUT))
        parts.append(str(z))
    return parts

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    src=choose_source()
    print("=== SUB52A FULL STATIC ASSET SWEEP ===",flush=True)
    print("SOURCE:",src,flush=True)
    print("SHA256:",sha256_file(src),flush=True)
    print("No PPSSPP. No gameplay. No ISO modification.",flush=True)

    p14=mod("sub52a_p14",ROOT/r"analysis\stage14\naruto_patcher.py")
    work=OUT/"_work"; work.mkdir(exist_ok=True)
    dat=work/"naruto.dat"

    print("[1/8] Extract naruto.dat",flush=True)
    extract_iso_file(src,"PSP_GAME/USRDIR/naruto.dat",dat)

    print("[2/8] Parse PIDX",flush=True)
    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    primary=table["primary"]
    offset2=table.get("offset2_rows",[])
    print("Primary:",len(primary),"FSTS rows:",len(offset2),flush=True)

    texroot=OUT/"textures_primary"
    texroot.mkdir(exist_ok=True)
    inv=[]
    jp=[]
    failed_ccs=[]

    print("[3/8] Decode every primary entry; extract every CCS texture",flush=True)
    with dat.open("rb") as f:
        for i,r in enumerate(primary):
            if i%100==0: print(f"  primary {i}/{len(primary)}",flush=True)
            f.seek(r["offset"])
            stored=f.read(r["zsize"] or r["size"])
            try:
                dec=p14.decode_stored(stored,r["size"],r["zsize"])
            except Exception as e:
                inv.append({"entry_index":i,"entry":r["name"],"decoded":"NO","size":r["size"],"zsize":r["zsize"] or 0,
                            "kind":"decode_fail","texture_count":0})
                continue

            # static JP string scan on all decoded primary entries
            for enc,s,off in extract_jp_strings(dec):
                if 2 <= len(s) <= 120:
                    jp.append({"scope":"primary","entry_index":i,"entry":r["name"],"encoding":enc,
                               "offset":off,"jp":s})

            tc=0
            if r["name"].lower().endswith(".ccs"):
                try:
                    tl=ccs_textures(dec)
                    tc=len(tl)
                    ed=texroot/f"{i:04d}__{sanitize(r['name'])}"
                    ed.mkdir(exist_ok=True)
                    for ti,t in enumerate(tl):
                        try:
                            pal=ccs_palette(dec,t["palette"])
                            rows=decode_indices(dec,t)
                            rgba=to_rgba(rows,pal)
                            outpng=ed/f"{ti:03d}__{sanitize(t['name'])}__{t['width']}x{t['height']}__0x{t['type']:02X}.png"
                            write_png(outpng,t["width"],t["height"],rgba)
                            inv.append({
                                "entry_index":i,"entry":r["name"],"decoded":"YES","size":r["size"],"zsize":r["zsize"] or 0,
                                "kind":"texture","texture_index":ti,"texture":t["name"],"width":t["width"],"height":t["height"],
                                "type":f"0x{t['type']:02X}","palette":t["palette"],"png":str(outpng.relative_to(OUT))
                            })
                        except Exception as e:
                            failed_ccs.append({"entry_index":i,"entry":r["name"],"texture":t["name"],"error":str(e)})
                except Exception as e:
                    failed_ccs.append({"entry_index":i,"entry":r["name"],"texture":"","error":str(e)})
            else:
                inv.append({"entry_index":i,"entry":r["name"],"decoded":"YES","size":r["size"],"zsize":r["zsize"] or 0,
                            "kind":"resource","texture_count":0})

    print("[4/8] Static Japanese scan of FSTS/offset2 bundles",flush=True)
    fsts_rows=[]
    with dat.open("rb") as f:
        for j,r in enumerate(offset2):
            if j%50==0: print(f"  fsts {j}/{len(offset2)}",flush=True)
            f.seek(r["file_off"]); b=f.read(r["file_size"])
            hits=extract_jp_strings(b)
            cnt=0
            for enc,s,off in hits:
                if 2 <= len(s) <= 120:
                    jp.append({"scope":"fsts_bundle","entry_index":r["index"],"entry":r["name"],
                               "encoding":enc,"offset":off,"jp":s})
                    cnt+=1
            fsts_rows.append({"row":j,"index":r["index"],"name":r["name"],"file_off":r["file_off"],
                              "file_size":r["file_size"],"jp_string_count":cnt})

    print("[5/8] Inventory existing Koreanized PNG candidates",flush=True)
    ko_rows=[]
    roots=[ROOT/r"analysis\sub", ROOT/"sub43_assets"]
    for rr in roots:
        if not rr.exists(): continue
        for p in rr.rglob("*.png"):
            n=p.name.lower()
            if "tex_" not in n and "texture" not in n: continue
            if not any(k in n for k in ["ko","kr","styled","upright","translated"]): continue
            try:
                rel=str(p.relative_to(ROOT))
            except:
                rel=str(p)
            ko_rows.append({"path":rel,"name":p.name,"size":p.stat().st_size})

    print("[6/8] Write inventories",flush=True)
    write_tsv(OUT/"primary_texture_inventory.tsv",inv,
              ["entry_index","entry","decoded","size","zsize","kind","texture_count","texture_index","texture",
               "width","height","type","palette","png"])
    write_tsv(OUT/"japanese_strings_static.tsv",jp,
              ["scope","entry_index","entry","encoding","offset","jp"])
    write_tsv(OUT/"fsts_bundle_inventory.tsv",fsts_rows,
              ["row","index","name","file_off","file_size","jp_string_count"])
    write_tsv(OUT/"existing_ko_asset_candidates.tsv",ko_rows,
              ["path","name","size"])
    write_tsv(OUT/"failed_texture_extracts.tsv",failed_ccs,
              ["entry_index","entry","texture","error"])

    summary={
        "stage":"SUB52A_FULL_STATIC_ASSET_SWEEP",
        "source_iso":str(src),
        "source_sha256":sha256_file(src),
        "primary_entries":len(primary),
        "fsts_rows":len(offset2),
        "extracted_texture_pngs":sum(1 for p in texroot.rglob("*.png")),
        "static_japanese_string_hits":len(jp),
        "existing_ko_candidate_pngs":len(ko_rows),
        "failed_texture_extracts":len(failed_ccs),
        "gameplay_used":False,
        "ppsspp_used":False,
    }
    (OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "Naruto SUB52A full static asset sweep\n\n"
        + "\n".join(f"{k}={v}" for k,v in summary.items())
        + "\n\nNo gameplay / no PPSSPP / no ISO modification.\n",
        encoding="utf-8-sig"
    )

    print("[7/8] Package metadata + texture parts",flush=True)
    meta_files=[
        OUT/"SUMMARY.json",OUT/"SUMMARY.txt",OUT/"primary_texture_inventory.tsv",
        OUT/"japanese_strings_static.tsv",OUT/"fsts_bundle_inventory.tsv",
        OUT/"existing_ko_asset_candidates.tsv",OUT/"failed_texture_extracts.tsv",
    ]
    meta_zip=LOGS/"naruto_sub52a_static_sweep_meta_upload.zip"
    with zipfile.ZipFile(meta_zip,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in meta_files:
            if p.exists(): zz.write(p,p.relative_to(OUT))

    tex_files=sorted(texroot.rglob("*.png"))
    parts=zip_chunks(tex_files,"naruto_sub52a_static_sweep_textures",80*1024*1024)

    manifest={"meta_zip":str(meta_zip),"texture_parts":parts,"summary":summary}
    (OUT/"UPLOAD_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    manifest_zip=LOGS/"naruto_sub52a_static_sweep_manifest_upload.zip"
    with zipfile.ZipFile(manifest_zip,"w",zipfile.ZIP_DEFLATED) as zz:
        zz.write(OUT/"UPLOAD_MANIFEST.json","UPLOAD_MANIFEST.json")
        zz.write(OUT/"SUMMARY.txt","SUMMARY.txt")

    print("META_ZIP="+str(meta_zip),flush=True)
    print("MANIFEST_ZIP="+str(manifest_zip),flush=True)
    for p in parts: print("TEXTURE_ZIP="+p,flush=True)

    print("[8/8] Done",flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        err=traceback.format_exc()
        (OUT/"FAILURE.txt").write_text(err,encoding="utf-8")
        z=LOGS/"fail_naruto_sub52a_full_static_asset_sweep_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.iterdir():
                if p.is_file(): zz.write(p,p.name)
        print(err,flush=True)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
