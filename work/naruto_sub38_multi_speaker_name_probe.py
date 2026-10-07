#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,csv,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path

SECTOR=2048
SUB36_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"
SUB16_BOOT_SHA="2fbbf997e679082d97bb5990c78719c3a1ba8993fb568dfb4434af9ad8a7b376"
FONT_SHA="fb95c0a7388ac75107d3ff46cf7e8324bdc4948085ff3c193520e0cd3ea2d2a5"

NAMES=[
 ("NRT","ナルト","나루토"),("SSK","サスケ","사스케"),("ROC","リー","리"),
 ("GAR","我愛羅","가아라"),("SIK","シカマル","시카마루"),("NEJ","ネジ","네지"),
 ("SKR","サクラ","사쿠라"),("KKS","カカシ","카카시"),("ORC","大蛇丸","오로치마루"),
 ("HNT","ヒナタ","히나타"),("TEN","テンテン","텐텐"),("TYO","チョウジ","쵸지"),
 ("INO","いの","이노"),("KIB","キバ","키바"),("SIN","シノ","시노"),
 ("GUY","ガイ","가이"),("JRY","自来也","지라이야"),("HKG","三代目","3대 호카게"),
 ("ITC","イタチ","이타치"),("KSM","鬼鮫","키사메"),("TND","綱手","츠나데"),
 ("SZN","シズネ","시즈네"),("KBT","カブト","카부토"),
]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()

def rt(p):
 with Path(p).open("r",encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f,delimiter="\t"))

def wt(p,rows,fields):
 Path(p).parent.mkdir(parents=True,exist_ok=True)
 with Path(p).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore");w.writeheader()
  for r in rows:w.writerow(r)

def iso_root(iso):
 with Path(iso).open("rb") as f:f.seek(16*SECTOR);p=f.read(SECTOR)
 if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b"CD001":raise RuntimeError("Bad ISO")
 r=p[156:190];return int.from_bytes(r[2:6],"little"),int.from_bytes(r[10:14],"little")

def dirents(iso,lba,size):
 with Path(iso).open("rb") as f:f.seek(lba*SECTOR);data=f.read(size)
 out=[];pos=0
 while pos<len(data):
  ln=data[pos]
  if ln==0:pos=((pos//SECTOR)+1)*SECTOR;continue
  r=data[pos:pos+ln]
  if len(r)<34:break
  nb=r[33:33+r[32]]
  name="." if nb==b"\0" else (".." if nb==b"\1" else nb.decode("ascii","replace").split(";",1)[0])
  out.append({"name":name,"lba":int.from_bytes(r[2:6],"little"),"size":int.from_bytes(r[10:14],"little"),"dir":bool(r[25]&2)})
  pos+=ln
 return out

def findiso(iso,path):
 lba,size=iso_root(iso);cur={"lba":lba,"size":size,"dir":True}
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
   b=fi.read(min(rem,1048576))
   if not b:raise RuntimeError("EOF")
   fo.write(b);rem-=len(b)

def segsha(iso,ipath):
 e=findiso(iso,ipath);h=hashlib.sha256()
 with Path(iso).open("rb") as f:
  f.seek(e["lba"]*SECTOR);rem=e["size"]
  while rem:
   b=f.read(min(rem,1048576));h.update(b);rem-=len(b)
 return e["size"],h.hexdigest()

def loadmap(path):
 m={}
 for r in rt(path):
  if r.get("hangul") and r.get("donor_sjis_hex"):m[r["hangul"]]=bytes.fromhex(r["donor_sjis_hex"])
 if len(m)!=694:raise RuntimeError("font map count")
 return m

def enc(s,m):
 out=bytearray()
 for c in s:
  if c in m:out+=m[c]
  else:out+=c.encode("cp932")
 return bytes(out)

def zero_capacity(data,start,jplen):
 # Exact string must be NUL-terminated. Capacity includes JP bytes plus NUL/padding
 # up to the next non-zero byte, capped at 32 bytes to avoid swallowing large blank areas.
 end=start+jplen
 if end>=len(data) or data[end]!=0:return 0
 p=end
 while p<len(data) and data[p]==0 and p-start<32:p+=1
 return p-start

def standalone(data,start,jplen):
 if start>0 and data[start-1]!=0:return False
 end=start+jplen
 return end<len(data) and data[end]==0

def patch_standalone(data,mapping):
 b=bytearray(data);rows=[]
 for code,jp,ko in NAMES:
  needle=jp.encode("cp932");new=enc(ko,mapping)
  pos=0
  while True:
   i=data.find(needle,pos)
   if i<0:break
   pos=i+1
   if not standalone(data,i,len(needle)):continue
   cap=zero_capacity(data,i,len(needle))
   can=(len(new)+1)<=cap
   rows.append({
    "speaker_code":code,"japanese":jp,"korean":ko,"offset_hex":"0x%X"%i,
    "jp_bytes":len(needle),"ko_bytes":len(new),"slot_capacity":cap,
    "patched":"YES" if can else "NO","reason":"" if can else "KOREAN_DOES_NOT_FIT_SLOT"
   })
   if can:
    b[i:i+cap]=new+b"\0"*(cap-len(new))
 return bytes(b),rows

def runlive(cmd,log):
 env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONIOENCODING"]="utf-8"
 print("[RUN] "+" ".join(str(x) for x in cmd),flush=True)
 with Path(log).open("w",encoding="utf-8") as lg:
  p=subprocess.Popen([str(x) for x in cmd],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1,env=env)
  for line in p.stdout:print(line,end="",flush=True);lg.write(line);lg.flush()
  rc=p.wait()
 if rc:raise RuntimeError("command failed rc=%d"%rc)

def parse_macro_paths(root):
 p=Path(root)/"generated_macros"/"naruto.bat";rows=[]
 if not p.exists():return rows
 txt=p.read_text(encoding="utf-8-sig",errors="ignore")
 for m in re.finditer(r'(?i)([A-Z]:\\[^"\r\n]*?\.exe)',txt):
  q=Path(m.group(1))
  rows.append({"kind":"EXE_FROM_MACRO","path":str(q),"exists":"YES" if q.exists() else "NO"})
 for m in re.finditer(r'(?i)([A-Z]:\\[^"\r\n]*?ppsspp[^"\r\n]*)',txt):
  q=Path(m.group(1).strip())
  rows.append({"kind":"PPSSPP_PATH_FROM_MACRO","path":str(q),"exists":"YES" if q.exists() else "NO"})
 return rows

def candidate_roots(root,macro_rows):
 home=Path.home();env=os.environ;rs=[]
 rs += [Path(root),home/"Documents"/"PPSSPP",home/"Documents"/"PPSSPP"/"PSP",
        home/"AppData"/"Roaming"/"PPSSPP",home/"AppData"/"Local"/"PPSSPP",
        home/"Downloads"]
 for r in macro_rows:
  p=Path(r["path"])
  if p.suffix.lower()==".exe":rs += [p.parent,p.parent/"memstick",p.parent/"PSP"]
 uniq=[];seen=set()
 for r in rs:
  try:k=str(r.resolve()).lower()
  except:k=str(r).lower()
  if k not in seen and r.exists():seen.add(k);uniq.append(r)
 return uniq

def bounded_files(root,maxdepth=6):
 base=len(Path(root).parts);seen=set()
 skip={"analysis","logs","old","failed","node_modules",".git","appdata\\local\\temp"}
 for d,dirs,files in os.walk(str(root),topdown=True,followlinks=False):
  rp=Path(d)
  try:key=str(rp.resolve()).lower()
  except:key=str(rp).lower()
  if key in seen:dirs[:]=[];continue
  seen.add(key)
  depth=len(rp.parts)-base
  if depth>=maxdepth:dirs[:]=[]
  dirs[:]=[x for x in dirs if x.lower() not in ("analysis","logs","old","failed","node_modules",".git")]
  for f in files:yield rp/f

def discover_ppsspp(root,macro_rows,out):
 states=[];inis=[];textures=[];seen=set()
 for rr in candidate_roots(root,macro_rows):
  for p in bounded_files(rr,6):
   try:st=p.stat()
   except:continue
   k=str(p).lower()
   if k in seen:continue
   low=p.name.lower()
   if low=="ppsspp.ini":
    inis.append({"path":str(p),"size":st.st_size,"mtime":st.st_mtime});seen.add(k)
   elif p.suffix.lower()==".ppst" or "ppsspp_state" in k:
    states.append({"path":str(p),"filename":p.name,"size":st.st_size,"mtime":st.st_mtime,
                   "slot1_hint":"YES" if re.search(r"(?:^|[_\-.])1(?:[_\-.]|$)",p.stem) else "NO"});seen.add(k)
   elif "textures" in k and p.suffix.lower() in (".png",".jpg",".jpeg",".dds",".ini"):
    textures.append({"path":str(p),"filename":p.name,"size":st.st_size,"mtime":st.st_mtime,
                     "new_dump":"YES" if "\\new\\" in k.replace("/","\\") else "NO"});seen.add(k)
 states.sort(key=lambda x:x["mtime"],reverse=True);inis.sort(key=lambda x:x["mtime"],reverse=True);textures.sort(key=lambda x:x["mtime"],reverse=True)
 # Copy best slot1 candidate into upload evidence.
 copied=""
 cands=[x for x in states if x["slot1_hint"]=="YES"] or states
 if cands:
  src=Path(cands[0]["path"]);dst=Path(out)/"slot1_state"/src.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);copied=str(dst)
 return states,inis,textures,copied

def movie_names(iso):
 d=findiso(iso,"PSP_GAME/USRDIR/movie")
 return sorted(x["name"] for x in dirents(iso,d["lba"],d["size"]) if not x["dir"] and x["name"].lower().endswith(".pmf"))

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--out",required=True)
 a=ap.parse_args();root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 src=root/"analysis"/"integrated"/"sub36_semantic_qa"/"output"/"Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"
 if not src.exists() or sha(src)!=SUB36_SHA:raise RuntimeError("SUB36 authority ISO missing/SHA mismatch")
 font=root/"analysis"/"shared"/"event_font_hangul_mapping.tsv"
 if sha(font)!=FONT_SHA:raise RuntimeError("font map mismatch")
 mapping=loadmap(font)
 ext=out/"extract";ext.mkdir(exist_ok=True)
 boot=ext/"BOOT.BIN";dat=ext/"naruto.dat";idx=ext/"naruto.idx"
 extract(src,"PSP_GAME/SYSDIR/BOOT.BIN",boot);extract(src,"PSP_GAME/USRDIR/naruto.dat",dat);extract(src,"PSP_GAME/USRDIR/naruto.idx",idx)
 if sha(boot)!=SUB16_BOOT_SHA:raise RuntimeError("BOOT authority mismatch")

 print("[1/5] Patch every standalone common character-name string that safely fits its slot",flush=True)
 patched,rows=patch_standalone(boot.read_bytes(),mapping)
 outboot=out/"BOOT_sub38_multiname_probe.bin";outboot.write_bytes(patched)
 wt(out/"speaker_multitable_probe.tsv",rows,["speaker_code","japanese","korean","offset_hex","jp_bytes","ko_bytes","slot_capacity","patched","reason"])
 print("  standalone candidates=%d patched=%d"%(len(rows),sum(r["patched"]=="YES" for r in rows)),flush=True)

 print("[2/5] Locate PPSSPP macro/install/save-state/texture paths",flush=True)
 macros=parse_macro_paths(root)
 states,inis,textures,copied=discover_ppsspp(root,macros,out)
 wt(out/"macro_ppsspp_paths.tsv",macros,["kind","path","exists"])
 wt(out/"ppsspp_savestate_inventory.tsv",states,["path","filename","size","mtime","slot1_hint"])
 wt(out/"ppsspp_ini_inventory.tsv",inis,["path","size","mtime"])
 wt(out/"ppsspp_texture_inventory.tsv",textures,["path","filename","size","mtime","new_dump"])

 print("[3/5] Build multi-name probe ISO",flush=True)
 stage24=root/"analysis"/"stage24"/"stage24_iso_multi_patch.py"
 probe=out/"Naruto_KR_SUB38_MultiSpeakerNamesProbe.iso";rep=out/"stage24_report"
 runlive([sys.executable,str(stage24),"--source-iso",str(src),"--dat",str(dat),"--idx",str(idx),
          "--boot",str(outboot),"--output-iso",str(probe),"--report-dir",str(rep)],out/"stage24_console.log")
 if not probe.exists():raise RuntimeError("probe ISO missing")

 print("[4/5] Verify core data and all movies preserved",flush=True)
 checks=[]
 for ip,hp in [("PSP_GAME/USRDIR/naruto.dat",dat),("PSP_GAME/USRDIR/naruto.idx",idx),
               ("PSP_GAME/SYSDIR/BOOT.BIN",outboot),("PSP_GAME/SYSDIR/EBOOT.BIN",outboot)]:
  sz,h=segsha(probe,ip);ok=h==sha(hp);checks.append({"iso_path":ip,"sha256":h,"match":"YES" if ok else "NO"})
  if not ok:raise RuntimeError("core verify fail "+ip)
 wt(out/"iso_core_verification.tsv",checks,["iso_path","sha256","match"])
 sm=movie_names(src);pm=movie_names(probe); 
 if sm!=pm:raise RuntimeError("movie names changed")
 mov=[]
 for n in sm:
  _,a1=segsha(src,"PSP_GAME/USRDIR/movie/"+n);_,a2=segsha(probe,"PSP_GAME/USRDIR/movie/"+n)
  mov.append({"filename":n,"match":"YES" if a1==a2 else "NO"})
  if a1!=a2:raise RuntimeError("movie changed "+n)
 wt(out/"movie_preservation.tsv",mov,["filename","match"])

 print("[5/5] Summary",flush=True)
 report={"stage":"SUB38_MULTI_SPEAKER_NAME_PROBE","source_iso_sha256":SUB36_SHA,
         "probe_iso":str(probe),"probe_iso_sha256":sha(probe),
         "standalone_name_candidates":len(rows),"standalone_name_patched":sum(r["patched"]=="YES" for r in rows),
         "standalone_name_skipped":sum(r["patched"]=="NO" for r in rows),
         "savestates_found":len(states),"slot1_hints":sum(r["slot1_hint"]=="YES" for r in states),
         "slot1_state_copied":copied,"ppsspp_ini_found":len(inis),
         "texture_assets_found":len(textures),"new_texture_dumps":sum(r["new_dump"]=="YES" for r in textures),
         "movie_pmfs_preserved":len(mov),"runtime_probe_required":True}
 (out/"sub38_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 lines=["Naruto PSP SUB38 - Multi Speaker Name Probe","",
        f"StandaloneNameCandidates={len(rows)}",f"StandaloneNamePatched={report['standalone_name_patched']}",
        f"StandaloneNameSkipped={report['standalone_name_skipped']}",f"SaveStatesFound={len(states)}",
        f"Slot1Hints={report['slot1_hints']}",f"Slot1StateCopied={'YES' if copied else 'NO'}",
        f"PPSSPPIniFound={len(inis)}",f"TextureAssetsFound={len(textures)}",
        f"NewTextureDumps={report['new_texture_dumps']}",f"MoviePMFsPreserved={len(mov)}",
        "StaticBuildQA=PASS","RuntimeSpeakerNameVisualCheck=REQUIRED"]
 (out/"SUMMARY.txt").write_text("\n".join(lines)+"\n",encoding="utf-8-sig");print("\n".join(lines),flush=True)

if __name__=="__main__":
 try:main()
 except Exception:
  import traceback;traceback.print_exc();sys.exit(1)
