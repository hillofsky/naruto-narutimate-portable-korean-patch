#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,csv,hashlib,json,os,re,shutil,struct,subprocess,sys
from pathlib import Path

SECTOR=2048
SUB36_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
SUB16_BOOT_SHA="2fbbf997e679082d97bb5990c78719c3a1ba8993fb568dfb4434af9ad8a7b376"
FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"
NAME_POOL_START=0x300C1C
NAME_POOL_END=0x300CE0
FILE_TO_RUNTIME=0x08803FAC
PRX_BASE=0x08804000

CODES=[
"NRT","SSK","ROC","GAR","SIK","NEJ","SKR","KKS","ORC","HNT","TEN","TYO",
"INO","KIB","SIN","GUY","JRY","HKG","ITC","KSM","TND","SZN","KBT"
]
JP=[
"ナルト","サスケ","リー","我愛羅","シカマル","ネジ","サクラ","カカシ","大蛇丸",
"ヒナタ","テンテン","チョウジ","いの","キバ","シノ","ガイ","自来也","三代目",
"イタチ","鬼鮫","綱手","シズネ","カブト"
]
KO=[
"나루토","사스케","리","가아라","시카마루","네지","사쿠라","카카시","오로치마루",
"히나타","텐텐","쵸지","이노","키바","시노","가이","지라이야","3대 호카게",
"이타치","키사메","츠나데","시즈네","카부토"
]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()

def rt(path):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def wt(path,rows,fields):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:w.writerow(r)

def align4(n): return (n+3)&~3

def iso_root(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001": raise RuntimeError("Bad ISO PVD")
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
        if len(r)<34:break
        nb=r[33:33+r[32]]
        if nb==b"\0":name="."
        elif nb==b"\1":name=".."
        else:name=nb.decode("ascii","replace").split(";",1)[0]
        out.append({"name":name,"lba":int.from_bytes(r[2:6],"little"),
                    "size":int.from_bytes(r[10:14],"little"),"dir":bool(r[25]&2)})
        pos+=ln
    return out

def findiso(iso,path):
    lba,size=iso_root(iso); cur={"lba":lba,"size":size,"dir":True}
    for part in [x for x in path.replace("\\","/").split("/") if x]:
        hit=None
        for e in dirents(iso,cur["lba"],cur["size"]):
            if e["name"].casefold()==part.casefold():hit=e;break
        if not hit:raise RuntimeError("ISO path missing "+path)
        cur=hit
    return cur

def extract(iso,ipath,out):
    e=findiso(iso,ipath)
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi,Path(out).open("wb") as fo:
        fi.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=fi.read(min(rem,1048576))
            if not b:raise RuntimeError("EOF "+ipath)
            fo.write(b); rem-=len(b)
    return e

def segsha(iso,ipath):
    e=findiso(iso,ipath); h=hashlib.sha256()
    with Path(iso).open("rb") as f:
        f.seek(e["lba"]*SECTOR); rem=e["size"]
        while rem:
            b=f.read(min(rem,1048576)); h.update(b); rem-=len(b)
    return e["size"],h.hexdigest()

def runlive(cmd,log):
    env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONIOENCODING"]="utf-8"
    print("[RUN] "+" ".join(str(x) for x in cmd),flush=True)
    with Path(log).open("w",encoding="utf-8") as lg:
        p=subprocess.Popen([str(x) for x in cmd],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           text=True,encoding="utf-8",errors="replace",bufsize=1,env=env)
        for line in p.stdout:
            print(line,end="",flush=True);lg.write(line);lg.flush()
        rc=p.wait()
    if rc:raise RuntimeError("command failed rc=%d"%rc)

def loadmap(path):
    m={}
    for r in rt(path):
        if r.get("hangul") and r.get("donor_sjis_hex"):
            m[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
    if len(m)!=694:raise RuntimeError("font map count "+str(len(m)))
    return m

def koenc(s,m):
    out=bytearray()
    for c in s:
        if c in m:out+=m[c]
        else:out+=c.encode("cp932")
    return bytes(out)

def parse_old_pool(data):
    pos=NAME_POOL_START; rows=[]
    for code,jp in zip(CODES,JP):
        raw=jp.encode("cp932")
        if data[pos:pos+len(raw)]!=raw:
            raise RuntimeError("speaker pool mismatch %s at 0x%X"%(code,pos))
        z=data.find(b"\0",pos)
        if z<0:raise RuntimeError("no NUL")
        slot=align4(z-pos+1)
        rows.append((code,jp,pos,slot))
        pos+=slot
    if pos!=NAME_POOL_END:
        raise RuntimeError("old pool end 0x%X expected 0x%X"%(pos,NAME_POOL_END))
    return rows

def build_new_pool(mapping):
    buf=bytearray(); rows=[]; pos=NAME_POOL_START
    for code,jp,ko in zip(CODES,JP,KO):
        b=koenc(ko,mapping)+b"\0"
        slot=align4(len(b))
        rows.append({"speaker_code":code,"japanese":jp,"korean":ko,
                     "new_offset_hex":"0x%X"%pos,"new_slot_bytes":slot,
                     "encoded_bytes":len(b)-1})
        buf+=b+b"\0"*(slot-len(b)); pos+=slot
    if pos!=NAME_POOL_END or len(buf)!=(NAME_POOL_END-NAME_POOL_START):
        raise RuntimeError("new Korean pool is not exact-size: %d"%len(buf))
    return bytes(buf),rows

def patch_xrefs(data,oldrows,newrows):
    b=bytearray(data); rows=[]
    new_by_code={r["speaker_code"]:int(r["new_offset_hex"],16) for r in newrows}
    for code,jp,old,slot in oldrows:
        new=new_by_code[code]
        if old==new:continue
        variants=[
            ("FILE_OFFSET",old,new),
            ("PRX_REL",old-0x54,new-0x54),
            ("RUNTIME",old+FILE_TO_RUNTIME,new+FILE_TO_RUNTIME),
        ]
        for typ,ov,nv in variants:
            needle=struct.pack("<I",ov); repl=struct.pack("<I",nv)
            start=0; cnt=0
            while True:
                i=b.find(needle,start)
                if i<0:break
                # Do not patch the actual name pool itself.
                if not (NAME_POOL_START<=i<NAME_POOL_END):
                    b[i:i+4]=repl;cnt+=1
                    rows.append({"speaker_code":code,"xref_type":typ,
                                 "xref_file_offset_hex":"0x%X"%i,
                                 "old_value_hex":"0x%X"%ov,"new_value_hex":"0x%X"%nv})
                start=i+4
    return bytes(b),rows

def elf_gp(data):
    if data[:4]!=b"\x7fELF":return None
    try:
        shoff=struct.unpack_from("<I",data,0x20)[0]
        shentsz=struct.unpack_from("<H",data,0x2E)[0]
        shnum=struct.unpack_from("<H",data,0x30)[0]
        for i in range(shnum):
            o=shoff+i*shentsz
            typ=struct.unpack_from("<I",data,o+4)[0]
            if typ==0x70000006:
                sec_off=struct.unpack_from("<I",data,o+16)[0]
                sec_sz=struct.unpack_from("<I",data,o+20)[0]
                if sec_sz>=24:
                    return struct.unpack_from("<I",data,sec_off+20)[0]
    except Exception:return None
    return None

def patch_gp_refs(data,oldrows,newrows):
    gp=elf_gp(data)
    if gp is None:return data,[],None
    b=bytearray(data); out=[]
    nb={r["speaker_code"]:int(r["new_offset_hex"],16) for r in newrows}
    for code,jp,old,slot in oldrows:
        new=nb[code]
        if old==new:continue
        ova=old+FILE_TO_RUNTIME; nva=new+FILE_TO_RUNTIME
        od=ova-gp; nd=nva-gp
        if not (-32768<=od<=32767 and -32768<=nd<=32767):continue
        oldimm=od&0xffff; newimm=nd&0xffff
        for i in range(0,len(b)-4,4):
            ins=struct.unpack_from("<I",b,i)[0]
            op=(ins>>26)&0x3f; rs=(ins>>21)&0x1f; imm=ins&0xffff
            # addiu/lw/lh/lhu/lb/lbu and similar gp-relative address/data accesses.
            if rs==28 and imm==oldimm and op in (0x09,0x20,0x21,0x23,0x24,0x25):
                ni=(ins&0xffff0000)|newimm
                struct.pack_into("<I",b,i,ni)
                out.append({"speaker_code":code,"xref_type":"GP_IMM",
                            "xref_file_offset_hex":"0x%X"%i,
                            "old_value_hex":"0x%04X"%oldimm,"new_value_hex":"0x%04X"%newimm})
    return bytes(b),out,gp

def special_pointer_report(data):
    out=[]
    for n,off in enumerate(range(0x300CE0,0x300D24,4)):
        v=struct.unpack_from("<I",data,off)[0]
        cands=[("RAW_FILE",v),("PRX_REL_PLUS54",v+0x54)]
        desc=[]
        for typ,fo in cands:
            if 0<=fo<len(data):
                raw=data[fo:min(len(data),fo+64)]
                txt=raw.decode("cp932","replace").replace("\0","·")
                desc.append("%s@0x%X:%s"%(typ,fo," ".join(txt.split())[:100]))
        out.append({"entry":n,"table_offset_hex":"0x%X"%off,
                    "raw_u32_hex":"0x%08X"%v,"candidate_context":" | ".join(desc)})
    return out

JP_RE=re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
def static_ui_strings(data):
    # This region contains game-mode descriptions, guide/help, gallery labels,
    # event speaker table and other front-end strings seen in SUB37 evidence.
    a=0x300300;b=min(len(data),0x303700);out=[];p=a
    while p<b:
        q=data.find(b"\0",p,b)
        if q<0:break
        raw=data[p:q]
        if raw:
            try:s=raw.decode("cp932")
            except:s=""
            if s and JP_RE.search(s):
                cat="OTHER"
                if "<RED>" in s or "<BLACK>" in s or "<br>" in s:cat="GUIDE_TEXT"
                elif "？" in s or "しますか" in s:cat="PROMPT"
                elif len(s)<=24:cat="LABEL_OR_MENU"
                out.append({"offset_hex":"0x%X"%p,"category":cat,
                            "japanese":s,"byte_length":len(raw)})
        p=q+1
    return out

def bounded_walk(start,maxdepth=5):
    start=Path(start)
    if not start.exists():return
    baseparts=len(start.parts); seen=set()
    for root,dirs,files in os.walk(str(start),topdown=True,followlinks=False):
        rp=Path(root)
        try:key=str(rp.resolve()).lower()
        except:key=str(rp).lower()
        if key in seen:
            dirs[:]=[];continue
        seen.add(key)
        depth=len(rp.parts)-baseparts
        if depth>=maxdepth:dirs[:]=[]
        # Avoid recursive junction-like project archives/huge analysis roots.
        dirs[:]=[d for d in dirs if d.lower() not in ("logs","old","failed","analysis")]
        yield rp,files

def ppsspp_inventory(root):
    home=Path.home()
    env=os.environ
    roots=[
        Path(root)/"memstick"/"PSP",
        Path(root)/"PSP",
        home/"Documents"/"PPSSPP"/"PSP",
        Path(env.get("APPDATA",""))/"PPSSPP"/"PSP" if env.get("APPDATA") else None,
        Path(env.get("LOCALAPPDATA",""))/"PPSSPP"/"PSP" if env.get("LOCALAPPDATA") else None,
    ]
    states=[];textures=[];seen=set()
    for rr in roots:
        if not rr or not rr.exists():continue
        for rp,files in bounded_walk(rr,5):
            for fn in files:
                p=rp/fn
                try:st=p.stat()
                except:continue
                k=str(p).lower()
                if k in seen:continue
                if p.suffix.lower()==".ppst" or "ppsspp_state" in k:
                    states.append({"path":str(p),"filename":p.name,"size":st.st_size,
                                   "slot1_hint":"YES" if re.search(r"(?:^|[_\-.])1(?:[_\-.]|$)",p.stem) else "NO",
                                   "mtime":st.st_mtime})
                    seen.add(k)
                if "textures" in k and p.suffix.lower() in (".png",".jpg",".jpeg",".dds",".ini"):
                    textures.append({"path":str(p),"filename":p.name,"size":st.st_size,
                                     "is_new_dump":"YES" if "\\new\\" in k.replace("/","\\") else "NO",
                                     "mtime":st.st_mtime})
                    seen.add(k)
    states.sort(key=lambda x:x["mtime"],reverse=True)
    textures.sort(key=lambda x:x["mtime"],reverse=True)
    return states,textures

def movie_names(iso):
    d=findiso(iso,"PSP_GAME/USRDIR/movie")
    return sorted(x["name"] for x in dirents(iso,d["lba"],d["size"]) if not x["dir"] and x["name"].lower().endswith(".pmf"))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--out",required=True)
    a=ap.parse_args();root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    srciso=root/"analysis"/"integrated"/"sub36_semantic_qa"/"output"/"Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"
    if not srciso.exists():raise RuntimeError("SUB36 ISO missing")
    if sha(srciso)!=SUB36_SHA:raise RuntimeError("SUB36 ISO SHA mismatch")
    font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
    if sha(font)!=FONT_SHA:raise RuntimeError("font map SHA mismatch")
    mapx=loadmap(font)

    ext=out/"extract";ext.mkdir(exist_ok=True)
    boot=ext/"BOOT.BIN";dat=ext/"naruto.dat";idx=ext/"naruto.idx"
    extract(srciso,"PSP_GAME/SYSDIR/BOOT.BIN",boot)
    extract(srciso,"PSP_GAME/USRDIR/naruto.dat",dat)
    extract(srciso,"PSP_GAME/USRDIR/naruto.idx",idx)
    if sha(boot)!=SUB16_BOOT_SHA:raise RuntimeError("SUB36 BOOT is not SUB16 authority")
    bd=boot.read_bytes()

    print("[1/6] Confirm and patch dialogue speaker-name pool",flush=True)
    oldrows=parse_old_pool(bd)
    pool,newrows=build_new_pool(mapx)
    for nr,orow in zip(newrows,oldrows):
        nr["old_offset_hex"]="0x%X"%orow[2];nr["old_slot_bytes"]=orow[3]
        nr["offset_changed"]="YES" if int(nr["new_offset_hex"],16)!=orow[2] else "NO"
    patched=bytearray(bd);patched[NAME_POOL_START:NAME_POOL_END]=pool

    # Patch common direct/pic references if present.
    p1,x1=patch_xrefs(bytes(patched),oldrows,newrows)
    p2,x2,gp=patch_gp_refs(p1,oldrows,newrows)
    patchedboot=out/"BOOT_sub37_speaker_ko_probe.bin";patchedboot.write_bytes(p2)
    wt(out/"speaker_name_pool_patch.tsv",newrows,
       ["speaker_code","japanese","korean","old_offset_hex","new_offset_hex",
        "old_slot_bytes","new_slot_bytes","encoded_bytes","offset_changed"])
    wt(out/"speaker_name_xref_patch.tsv",x1+x2,
       ["speaker_code","xref_type","xref_file_offset_hex","old_value_hex","new_value_hex"])
    wt(out/"speaker_special_pointer_report.tsv",special_pointer_report(bd),
       ["entry","table_offset_hex","raw_u32_hex","candidate_context"])

    print("[2/6] Extract static guide/menu Japanese strings",flush=True)
    ui=static_ui_strings(bd)
    wt(out/"ui_static_japanese_strings.tsv",ui,["offset_hex","category","japanese","byte_length"])

    print("[3/6] Inventory PPSSPP slot states / existing texture dumps",flush=True)
    states,textures=ppsspp_inventory(root)
    wt(out/"ppsspp_savestate_inventory.tsv",states,["path","filename","size","slot1_hint","mtime"])
    wt(out/"ppsspp_texture_inventory.tsv",textures,["path","filename","size","is_new_dump","mtime"])

    print("[4/6] Build name-probe ISO using SUB36 as exact base",flush=True)
    stage24=root/"analysis"/"stage24"/"stage24_iso_multi_patch.py"
    final=out/"Naruto_KR_SUB37_SpeakerNamesProbe.iso"
    rep=out/"stage24_report"
    cmd=[sys.executable,str(stage24),"--source-iso",str(srciso),
         "--dat",str(dat),"--idx",str(idx),"--boot",str(patchedboot),
         "--output-iso",str(final),"--report-dir",str(rep)]
    runlive(cmd,out/"stage24_console.log")
    if not final.exists():raise RuntimeError("probe ISO missing")

    print("[5/6] Verify DAT/IDX and movies unchanged",flush=True)
    checks=[]
    for ip,hp in [("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
                  ("PSP_GAME/SYSDIR/BOOT.BIN",patchedboot),("PSP_GAME/SYSDIR/EBOOT.BIN",patchedboot)]:
        sz,h=segsha(final,ip)
        checks.append({"iso_path":ip,"size":sz,"iso_sha256":h,"host_sha256":sha(hp),"match":"YES" if h==sha(hp) else "NO"})
        if h!=sha(hp):raise RuntimeError("ISO verify failed "+ip)
    wt(out/"iso_core_verification.tsv",checks,["iso_path","size","iso_sha256","host_sha256","match"])
    sm=movie_names(srciso);fm=movie_names(final)
    if sm!=fm:raise RuntimeError("movie file list changed")
    mov=[]
    for n in sm:
        ip="PSP_GAME/USRDIR/movie/"+n
        ss,sh=segsha(srciso,ip);fs,fh=segsha(final,ip)
        ok=ss==fs and sh==fh
        mov.append({"filename":n,"source_sha256":sh,"probe_sha256":fh,"match":"YES" if ok else "NO"})
        if not ok:raise RuntimeError("movie changed "+n)
    wt(out/"movie_preservation.tsv",mov,["filename","source_sha256","probe_sha256","match"])

    print("[6/6] Summary",flush=True)
    report={
      "stage":"SUB37_FIX1_SPEAKER_NAME_PROBE",
      "source_iso_sha256":SUB36_SHA,"probe_iso":str(final),"probe_iso_sha256":sha(final),
      "speaker_pool_offset":"0x300C1C-0x300CDF","speaker_names_patched":23,
      "speaker_pool_exact_size_bytes":len(pool),"xref_patches":len(x1)+len(x2),
      "elf_gp":None if gp is None else "0x%08X"%gp,
      "static_ui_japanese_strings":len(ui),"savestates_found":len(states),
      "slot1_hints":sum(x["slot1_hint"]=="YES" for x in states),
      "texture_assets_found":len(textures),"movie_pmfs_preserved":len(mov),
      "game_files_modified":True,"runtime_probe_required":True
    }
    (out/"sub37_fix1_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[
      "Naruto PSP SUB37 FIX1 - Speaker Name Probe",
      "",f"SpeakerNamesPatched={len(CODES)}",f"NamePoolBytes={len(pool)}",
      f"XrefPatches={len(x1)+len(x2)}",f"StaticUIJapaneseStrings={len(ui)}",
      f"SaveStatesFound={len(states)}",f"Slot1Hints={report['slot1_hints']}",
      f"TextureAssetsFound={len(textures)}",f"MoviePMFsPreserved={len(mov)}",
      "StaticBuildQA=PASS","RuntimeSpeakerNameVisualCheck=REQUIRED"
    ]
    (out/"SUMMARY.txt").write_text("\n".join(lines)+"\n",encoding="utf-8-sig")
    print("\n".join(lines),flush=True)

if __name__=="__main__":
    try:main()
    except Exception:
        import traceback;traceback.print_exc();sys.exit(1)
