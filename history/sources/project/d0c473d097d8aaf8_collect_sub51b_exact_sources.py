#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,re,shutil,struct,sys,traceback

SECTOR=2048
SOURCE_SHA="5a750d02fc701c110106711dedfc3e19b34b32f1833ccbef811f3d55441f87b9"
SOURCE_REL=Path("analysis/sub/sub50_mugen_atlas_surgical_restore/Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso")
OUT_REL=Path("analysis/sub/sub51b_exact_source_collection")

UI_TERMS=(
    "mugen","gauge","rpggauge","option","setting","modesel","charsel","home",
    "network","menu","select","title","result","mission","load","save","status",
    "item","skill","mode","navi","map","room","common","cmn","battle","versus",
    "system","help","tutorial","stage","story","gallery","movie","music","photo"
)
JP_RE=re.compile(r"[ぁ-んァ-ヶ一-龯々〆ヵヶー]")
KANA_RE=re.compile(r"[ぁ-んァ-ヶー]")

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError(f"Cannot import {path}")
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR);p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("Bad ISO")
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

def load_reverse_maps(root):
    rev={}
    srcs=[]
    for p in (root/"analysis/shared/event_font_hangul_mapping.tsv",
              root/"analysis/sub/sub40_tutorial/new_glyph_mapping.tsv"):
        if not p.exists():raise RuntimeError("Mapping missing: "+str(p))
        srcs.append(p)
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                if r.get("hangul") and r.get("donor_sjis_hex"):
                    rev[bytes.fromhex(r["donor_sjis_hex"])]=r["hangul"]
    return rev,srcs

def donor_decode(raw,rev):
    out=[];i=0;mapped=0;pair_total=0
    while i<len(raw):
        if i+1<len(raw):
            pair=raw[i:i+2]
            # Count legal-looking two-byte positions only for density reporting.
            if (0x81<=raw[i]<=0x9F or 0xE0<=raw[i]<=0xFC):
                pair_total+=1
            if pair in rev:
                out.append(rev[pair]);mapped+=1;i+=2;continue
        try:
            ch=raw[i:i+1].decode("ascii")
            out.append(ch);i+=1;continue
        except:pass
        # Preserve an ordinary CP932 character when possible.
        ok=False
        for n in (2,1):
            try:
                out.append(raw[i:i+n].decode("cp932"));i+=n;ok=True;break
            except:pass
        if not ok:
            out.append("�");i+=1
    density=mapped/max(1,pair_total)
    return "".join(out),mapped,pair_total,density

def plausible_jp(s):
    if not JP_RE.search(s):return False
    if any(0xE000<=ord(ch)<=0xF8FF for ch in s):return False
    if any(0xFF61<=ord(ch)<=0xFF9F for ch in s):return False
    if any(ord(ch)<32 and ch not in "\t\r\n" for ch in s):return False
    jp=len(JP_RE.findall(s));kana=len(KANA_RE.findall(s))
    vis=sum(1 for ch in s if ch.isprintable() and not ch.isspace())
    if vis==0 or jp<2:return False
    # Genuine BOOT text has strong Japanese density. This rejects code/data coincidences.
    return (kana>=1 and jp/vis>=0.42) or ("<ruby" in s and jp>=2)

def scan_boot(raw,rev):
    rows=[];pos=0
    for chunk in raw.split(b"\0"):
        off=pos;pos+=len(chunk)+1
        if not 2<=len(chunk)<=600:continue
        try:s=chunk.decode("cp932")
        except:continue
        if not plausible_jp(s):continue
        decoded,mapped,pairs,density=donor_decode(chunk,rev)
        status="LIKELY_ALREADY_KO" if mapped>=2 and density>=0.55 else "RESIDUAL_JP"
        rows.append(dict(offset_hex=hex(off),bytes=len(chunk),status=status,
                         donor_mapped=mapped,donor_pair_total=pairs,
                         donor_density=f"{density:.3f}",cp932_text=s,
                         donor_decoded=decoded,raw_hex=chunk.hex()))
    return rows

def ccs_names(b):
    if len(b)<0x4c:return []
    try:pc,nc=struct.unpack_from("<II",b,0x44)
    except:return []
    no=0x4C+32*pc
    if pc>4096 or nc>8192 or no+32*nc>len(b):return []
    return [b[no+32*i:no+32*i+30].split(b"\0",1)[0].decode("cp932",errors="replace") for i in range(nc)]

def texture_records(b):
    names=ccs_names(b);magic=bytes.fromhex("0003cccc");out=[];seen=set()
    for o in range(0,len(b)-36,4):
        if b[o:o+4]!=magic:continue
        wi=struct.unpack_from("<I",b,o+8)[0]
        if wi>=len(names):continue
        palid=struct.unpack_from("<I",b,o+12)[0];typ=b[o+21];we,he=b[o+24:o+26]
        if we>12 or he>12 or typ not in (0x13,0x14):continue
        w,h=1<<we,1<<he;dl=w*h if typ==0x13 else w*h//2
        if o+36+dl>len(b):continue
        key=(names[wi],o)
        if key in seen:continue
        seen.add(key)
        out.append(dict(texture=names[wi],width=w,height=h,format=hex(typ),
                        palette=palid,offset_hex=hex(o),data_len=dl))
    return out

def write_tsv(path,rows,fields):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=r"PROJECT_ROOT")
    a=ap.parse_args();root=Path(a.root);source=root/SOURCE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    if not source.exists() or sha256_file(source)!=SOURCE_SHA:
        raise RuntimeError("SUB50 authority ISO missing/SHA mismatch")

    m=mod("sub51b_p14",root/"analysis/stage14/naruto_patcher.py")
    rev,map_sources=load_reverse_maps(root)

    print("[1/7] Extract exact SUB50 BOOT/DAT/IDX",flush=True)
    boot=out/"source_sub50_BOOT.bin";dat=out/"source_sub50_naruto.dat";idx=out/"source_sub50_naruto.idx"
    extract(source,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    extract(source,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(source,"PSP_GAME/USRDIR/naruto.idx",idx)

    print("[2/7] Copy exact Hangul mapping inputs",flush=True)
    mapsdir=out/"mappings";mapsdir.mkdir(exist_ok=True)
    for p in map_sources:shutil.copy2(p,mapsdir/p.name)

    print("[3/7] Filter BOOT residual Japanese with donor-map awareness",flush=True)
    bootrows=scan_boot(boot.read_bytes(),rev)
    write_tsv(out/"boot_filtered_strings.tsv",bootrows,
              ["offset_hex","bytes","status","donor_mapped","donor_pair_total",
               "donor_density","cp932_text","donor_decoded","raw_hex"])

    print("[4/7] Export ALL decoded TBL/text resources exactly",flush=True)
    ei=m.parse_pidx(m.read_embedded_index(dat),"sub50")
    tdir=out/"text_resources";tdir.mkdir(exist_ok=True)
    cdir=out/"ui_ccs";cdir.mkdir(exist_ok=True)
    textinv=[];ccsinv=[];texinv=[]
    with dat.open("rb") as f:
        for i,r in enumerate(ei["primary"]):
            if r.get("is_folder"):continue
            low=r["name"].lower()
            is_text=low.endswith((".tbl",".txt",".csv",".ini",".lst"))
            is_ui_ccs=low.endswith(".ccs") and any(t in low for t in UI_TERMS)
            if not (is_text or is_ui_ccs):continue
            f.seek(r["offset"]);stored=f.read(r["zsize"] or r["size"])
            try:dec=m.decode_stored(stored,r["size"],r["zsize"])
            except Exception as e:
                rec=dict(resource=r["name"],decoded_size="",sha256="",status="DECODE_FAIL:"+str(e)[:150])
                (textinv if is_text else ccsinv).append(rec);continue

            safe=re.sub(r'[^A-Za-z0-9_.-]+','_',r["name"])
            if is_text:
                fn=safe+".bin";(tdir/fn).write_bytes(dec)
                # Also produce donor-decoded line view for offline analysis.
                lines=[];off=0
                for raw in dec.splitlines(keepends=True):
                    body=raw.rstrip(b"\r\n")
                    if body:
                        try:cp=body.decode("cp932")
                        except:cp=""
                        dd,mapped,pairs,density=donor_decode(body,rev)
                        lines.append(dict(offset_hex=hex(off),raw_bytes=len(body),
                                          donor_mapped=mapped,donor_pair_total=pairs,
                                          donor_density=f"{density:.3f}",
                                          cp932_text=cp.replace("\t","\\t"),
                                          donor_decoded=dd.replace("\t","\\t"),
                                          raw_hex=body.hex()))
                    off+=len(raw)
                write_tsv(tdir/(safe+".lines.tsv"),lines,
                          ["offset_hex","raw_bytes","donor_mapped","donor_pair_total",
                           "donor_density","cp932_text","donor_decoded","raw_hex"])
                textinv.append(dict(resource=r["name"],decoded_size=len(dec),
                                    sha256=hashlib.sha256(dec).hexdigest(),status="EXPORTED"))
            if is_ui_ccs:
                fn=safe+".bin";(cdir/fn).write_bytes(dec)
                trs=texture_records(dec)
                ccsinv.append(dict(resource=r["name"],decoded_size=len(dec),
                                   sha256=hashlib.sha256(dec).hexdigest(),
                                   textures=len(trs),status="EXPORTED"))
                for t in trs:
                    q=dict(resource=r["name"]);q.update(t);texinv.append(q)
            if (i+1)%100==0:print(f"  processed {i+1}/{len(ei['primary'])}",flush=True)

    write_tsv(out/"text_resource_inventory.tsv",textinv,
              ["resource","decoded_size","sha256","status"])
    write_tsv(out/"ui_ccs_inventory.tsv",ccsinv,
              ["resource","decoded_size","sha256","textures","status"])
    write_tsv(out/"ui_texture_inventory.tsv",texinv,
              ["resource","texture","width","height","format","palette","offset_hex","data_len"])

    print("[5/7] Export exact primary/FSTS metadata",flush=True)
    primary=[]
    for r in ei["primary"]:
        primary.append(dict(index=r.get("index",""),name=r["name"],
                            is_folder="YES" if r.get("is_folder") else "NO",
                            offset=r.get("offset",""),size=r.get("size",""),
                            zsize=r.get("zsize","")))
    write_tsv(out/"primary_index.tsv",primary,
              ["index","name","is_folder","offset","size","zsize"])
    fsts=[]
    for r in ei["offset2_rows"]:
        fsts.append(dict(index=r["index"],name=r["name"],
                         file_off=r["file_off"],file_size=r["file_size"]))
    write_tsv(out/"fsts_index.tsv",fsts,["index","name","file_off","file_size"])

    print("[6/7] Create collection manifest",flush=True)
    report=dict(
        stage="SUB51B_EXACT_SOURCE_COLLECTION",
        source_iso=str(source),source_iso_sha256=SOURCE_SHA,
        boot_file=boot.name,boot_sha256=sha256_file(boot),
        dat_file=dat.name,dat_sha256=sha256_file(dat),
        idx_file=idx.name,idx_sha256=sha256_file(idx),
        mapping_files=[p.name for p in map_sources],
        boot_candidates=len(bootrows),
        boot_residual_jp=sum(r["status"]=="RESIDUAL_JP" for r in bootrows),
        boot_likely_already_ko=sum(r["status"]=="LIKELY_ALREADY_KO" for r in bootrows),
        text_resources_exported=sum(r["status"]=="EXPORTED" for r in textinv),
        ui_ccs_exported=sum(r["status"]=="EXPORTED" for r in ccsinv),
        ui_textures_inventoried=len(texinv),
        modifies_game_data=False,runtime_qa=False,
        note="Exact raw sources for offline full translation/UV analysis. No patching."
    )
    (out/"SUB51B_collection_summary.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    print("[7/7] Done",flush=True)
    (out/"SUMMARY.txt").write_text(
        "Naruto PSP SUB51B - Exact Source Collection\n\n"
        f"SourceSHA256={SOURCE_SHA}\n"
        f"BOOTResidualCandidates={report['boot_residual_jp']}\n"
        f"BOOTLikelyAlreadyKorean={report['boot_likely_already_ko']}\n"
        f"TextResourcesExported={report['text_resources_exported']}\n"
        f"UICCSExported={report['ui_ccs_exported']}\n"
        f"UITexturesInventoried={report['ui_textures_inventoried']}\n"
        "IncludesExactBOOT=YES\nIncludesExactDATIDX=YES\n"
        "IncludesHangulMappings=YES\n"
        "GameDataModified=NO\nRuntimeQA=NO\n",
        encoding="utf-8-sig")
    print((out/"SUMMARY.txt").read_text(encoding="utf-8-sig"),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
