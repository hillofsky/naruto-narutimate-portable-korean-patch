#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, struct, sys
from pathlib import Path
from collections import Counter, defaultdict

SECTOR=2048
EXPECTED_ISO_SHA="789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f"

# Candidate display strings.  This list is intentionally broader than the
# four names seen in the first runtime screenshots so we can locate a table.
JP_NAMES = {
    "NRT": ["ナルト"],
    "JRY": ["自来也","ジライヤ"],
    "KSU": ["カスミ"],
    "KKS": ["カカシ"],
    "KRH": ["キリヒメ"],
    "TND": ["綱手","ツナデ"],
    "SKR": ["サクラ"],
    "ORC": ["大蛇丸","オロチマル"],
    "SIK": ["シカマル"],
    "KBT": ["カブト"],
    "SZN": ["シズネ"],
    "HNT": ["ヒナタ"],
    "HKG": ["三代目火影","3代目火影","猿飛"],
    "NEJ": ["ネジ"],
    "ROC": ["リー","ロック・リー"],
    "HST": ["兵士隊長","兵隊長"],
    "GUY": ["ガイ"],
    "GAR": ["ガアラ","我愛羅"],
    "ONK": ["女の子","少女"],
    "KIB": ["キバ"],
    "JJO": ["侍女","女中"],
    "SIN": ["シド","シドウ"],
    "TYO": ["チョウジ"],
    "INO": ["イノ"],
    "HIS": ["兵士"],
    "TEN": ["テンテン"],
    "KSM": ["キサメ","鬼鮫"],
    "ITD": ["イタチ"],
    "SNS": ["思念体"],
    "SN1": ["思念体","思念"],
    "JRS": ["一同"],
    "JT2": ["一同"],
}

KO_TARGETS = {
    "NRT":"나루토","JRY":"지라이야","KSU":"카스미","KKS":"카카시",
    "KRH":"키리히메","TND":"츠나데","SKR":"사쿠라","ORC":"오로치마루",
    "SIK":"시카마루","KBT":"카부토","SZN":"시즈네","HNT":"히나타",
    "HKG":"3대 호카게","NEJ":"네지","ROC":"리","HST":"병사대장",
    "GUY":"가이","GAR":"가아라","ONK":"여자아이","KIB":"키바",
    "JJO":"시녀","SIN":"시도","TYO":"쵸지","INO":"이노","HIS":"병사",
    "TEN":"텐텐","KSM":"키사메","ITD":"이타치","SNS":"사념체",
    "SN1":"사념체","JRS":"일동","JT2":"일동",
}

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def write_tsv(path, rows, fields):
    path=Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

def iso_root_record(iso):
    with Path(iso).open("rb") as f:
        f.seek(16*SECTOR)
        pvd=f.read(SECTOR)
    if len(pvd)!=SECTOR or pvd[0]!=1 or pvd[1:6]!=b"CD001":
        raise RuntimeError("ISO9660 PVD not found")
    rec=pvd[156:190]
    return int.from_bytes(rec[2:6],"little"),int.from_bytes(rec[10:14],"little")

def iso_dir_entries(iso,lba,size):
    with Path(iso).open("rb") as f:
        f.seek(lba*SECTOR); data=f.read(size)
    out=[]; pos=0
    while pos<len(data):
        ln=data[pos]
        if ln==0:
            pos=((pos//SECTOR)+1)*SECTOR
            continue
        rec=data[pos:pos+ln]
        if len(rec)<34: break
        extent=int.from_bytes(rec[2:6],"little")
        length=int.from_bytes(rec[10:14],"little")
        flags=rec[25]; nlen=rec[32]; nb=rec[33:33+nlen]
        if nb==b"\x00": name="."
        elif nb==b"\x01": name=".."
        else:
            name=nb.decode("ascii",errors="replace").split(";",1)[0]
        out.append({"name":name,"lba":extent,"size":length,"is_dir":bool(flags&2)})
        pos+=ln
    return out

def iso_find(iso,path):
    parts=[x for x in path.replace("\\","/").split("/") if x]
    lba,size=iso_root_record(iso)
    cur={"lba":lba,"size":size,"is_dir":True}
    for part in parts:
        hit=None
        for e in iso_dir_entries(iso,cur["lba"],cur["size"]):
            if e["name"].casefold()==part.casefold():
                hit=e; break
        if not hit: raise RuntimeError("ISO path not found: "+path)
        cur=hit
    return cur

def extract_iso_file(iso,ipath,out):
    e=iso_find(iso,ipath)
    if e["is_dir"]: raise RuntimeError("Expected file: "+ipath)
    out=Path(out); out.parent.mkdir(parents=True,exist_ok=True)
    with Path(iso).open("rb") as fi, out.open("wb") as fo:
        fi.seek(e["lba"]*SECTOR)
        remain=e["size"]
        while remain:
            b=fi.read(min(remain,1024*1024))
            if not b: raise RuntimeError("Unexpected EOF: "+ipath)
            fo.write(b); remain-=len(b)
    return e

def all_occurrences(data, needle):
    pos=0
    while True:
        i=data.find(needle,pos)
        if i<0: break
        yield i
        pos=i+1

def safe_cp932_context(data,off,needle_len,radius=96):
    a=max(0,off-radius); b=min(len(data),off+needle_len+radius)
    chunk=data[a:b]
    txt=chunk.decode("cp932",errors="replace")
    txt=txt.replace("\r"," ").replace("\n"," ")
    txt=" ".join(txt.split())
    return txt[:260]

def scan_blob(label,path,out_dir):
    p=Path(path)
    data=p.read_bytes()
    hits=[]
    for code,variants in JP_NAMES.items():
        for jp in variants:
            needle=jp.encode("cp932")
            for off in all_occurrences(data,needle):
                hits.append({
                    "source":label,
                    "path":str(p),
                    "speaker_code":code,
                    "jp_candidate":jp,
                    "ko_target":KO_TARGETS.get(code,""),
                    "offset_dec":off,
                    "offset_hex":f"0x{off:X}",
                    "byte_len":len(needle),
                    "context_cp932":safe_cp932_context(data,off,len(needle)),
                })
    # Speaker-code ASCII occurrences.
    code_hits=[]
    for code in JP_NAMES:
        needle=code.encode("ascii")
        for off in all_occurrences(data,needle):
            code_hits.append({
                "source":label,"path":str(p),"speaker_code":code,
                "offset_dec":off,"offset_hex":f"0x{off:X}",
                "context_cp932":safe_cp932_context(data,off,len(needle)),
            })

    # Cluster name hits. A true speaker table should normally contain several
    # different display names in a compact region.
    clusters=[]
    hs=sorted(hits,key=lambda r:int(r["offset_dec"]))
    if hs:
        cur=[hs[0]]
        for h in hs[1:]:
            if int(h["offset_dec"])-int(cur[-1]["offset_dec"])<=0x2000:
                cur.append(h)
            else:
                clusters.append(cur); cur=[h]
        clusters.append(cur)

    cluster_rows=[]
    slice_no=0
    for cl in clusters:
        codes=sorted(set(x["speaker_code"] for x in cl))
        jps=sorted(set(x["jp_candidate"] for x in cl))
        start=min(int(x["offset_dec"]) for x in cl)
        end=max(int(x["offset_dec"])+int(x["byte_len"]) for x in cl)
        row={
            "source":label,
            "start_hex":f"0x{start:X}",
            "end_hex":f"0x{end:X}",
            "span":end-start,
            "hit_count":len(cl),
            "distinct_codes":len(codes),
            "codes":",".join(codes),
            "jp_names":" | ".join(jps),
            "likely_table":"YES" if len(codes)>=4 and (end-start)<=0x10000 else "NO",
            "slice_file":"",
        }
        if row["likely_table"]=="YES":
            slice_no+=1
            a=max(0,start-0x1000); b=min(len(data),end+0x1000)
            sp=Path(out_dir)/"speaker_candidate_slices"/f"{label}_cluster{slice_no:02d}_{a:08X}_{b:08X}.bin"
            sp.parent.mkdir(parents=True,exist_ok=True)
            sp.write_bytes(data[a:b])
            row["slice_file"]=str(sp.name)
        cluster_rows.append(row)
    return hits,code_hits,cluster_rows

def find_existing_files(root):
    root=Path(root)
    candidates=[]
    patterns=[
        "analysis/sub/sub36_semantic_qa/sub36_patcher_ready_1976_semanticqa_23x2.tsv",
        "analysis/shared/event_font_hangul_mapping.tsv",
        "analysis/stage8/decoded_tbl/kr",
        "kr_extracted/PSP_GAME/SYSDIR/BOOT.BIN",
        "kr_extracted/PSP_GAME/SYSDIR/EBOOT.BIN",
        "kr_extracted/PSP_GAME/USRDIR/naruto.dat",
        "us_extracted/PSP_GAME/SYSDIR/BOOT.BIN",
        "us_extracted/PSP_GAME/SYSDIR/EBOOT.BIN",
    ]
    for rel in patterns:
        p=root/rel
        if p.exists():
            candidates.append(str(p))
    return candidates

def state_inventory(root):
    roots=[]
    home=Path.home()
    env=os.environ
    candidates=[
        Path(root),
        home/"Documents"/"PPSSPP",
        home/"Documents"/"PPSSPP"/"PSP",
        Path(env.get("APPDATA",""))/"PPSSPP" if env.get("APPDATA") else None,
        Path(env.get("LOCALAPPDATA",""))/"PPSSPP" if env.get("LOCALAPPDATA") else None,
        home/"Downloads",
    ]
    seen=set()
    rows=[]
    for r in candidates:
        if not r or not r.exists(): continue
        key=str(r.resolve()).lower()
        if key in seen: continue
        seen.add(key); roots.append(r)
        # Search only likely PPSSPP/state paths to keep the scan fast.
        for p in r.rglob("*"):
            try:
                if not p.is_file(): continue
            except OSError:
                continue
            low=p.name.lower()
            parent=str(p.parent).lower()
            if (
                low.endswith(".ppst") or
                "ppsspp_state" in parent or
                "savestate" in parent or
                ("state" in low and p.stat().st_size>1024)
            ):
                try:
                    st=p.stat()
                    rows.append({
                        "path":str(p),
                        "filename":p.name,
                        "size":st.st_size,
                        "mtime":st.st_mtime,
                        "slot1_name_hint":"YES" if re.search(r"(^|[_\-.])1([_\-.]|$)",p.stem) else "NO",
                        "sha256":sha256_file(p) if st.st_size<128*1024*1024 else "",
                    })
                except Exception:
                    pass
    rows.sort(key=lambda x:x["mtime"],reverse=True)
    return rows

def ppsspp_config_inventory(root):
    home=Path.home()
    env=os.environ
    roots=[
        Path(root),
        home/"Documents"/"PPSSPP",
        Path(env.get("APPDATA",""))/"PPSSPP" if env.get("APPDATA") else None,
        Path(env.get("LOCALAPPDATA",""))/"PPSSPP" if env.get("LOCALAPPDATA") else None,
    ]
    rows=[]
    seen=set()
    for r in roots:
        if not r or not r.exists(): continue
        for p in list(r.rglob("ppsspp.ini"))+list(r.rglob("PPSSPPWindows64.exe"))+list(r.rglob("PPSSPPWindows.exe")):
            try:
                rp=str(p.resolve()).lower()
                if rp in seen: continue
                seen.add(rp)
                row={"path":str(p),"type":"INI" if p.suffix.lower()==".ini" else "EXE","details":""}
                if p.suffix.lower()==".ini":
                    txt=p.read_text(encoding="utf-8-sig",errors="ignore")
                    vals=[]
                    for k in ["SaveNewTextures","ReplaceTextures","MemStickDirectory","CurrentDirectory"]:
                        m=re.search(rf"(?mi)^\s*{re.escape(k)}\s*=\s*(.*?)\s*$",txt)
                        if m: vals.append(f"{k}={m.group(1)}")
                    row["details"]="; ".join(vals)
                rows.append(row)
            except Exception:
                pass
    return rows

def texture_inventory(root):
    home=Path.home()
    roots=[]
    # Existing project texture folders and normal PPSSPP memstick locations.
    candidates=[
        Path(root)/"textures",
        Path(root)/"memstick"/"PSP"/"TEXTURES",
        home/"Documents"/"PPSSPP"/"PSP"/"TEXTURES",
        home/"PSP"/"TEXTURES",
    ]
    rows=[]
    seen=set()
    game_ids=("ULKS46086","ULJS00055","ULUS10349")
    for r in candidates:
        if not r.exists(): continue
        for gid in game_ids:
            g=r/gid
            if not g.exists(): continue
            for p in g.rglob("*"):
                if not p.is_file(): continue
                if p.suffix.lower() not in (".png",".jpg",".jpeg",".bmp",".tga",".dds",".ktx2",".ini"):
                    continue
                try:
                    st=p.stat()
                    k=str(p.resolve()).lower()
                    if k in seen: continue
                    seen.add(k)
                    rows.append({
                        "game_id":gid,
                        "path":str(p),
                        "relative":str(p.relative_to(g)),
                        "size":st.st_size,
                        "in_new_folder":"YES" if "new" in [x.lower() for x in p.parts] else "NO",
                        "sha256":sha256_file(p) if st.st_size<32*1024*1024 else "",
                    })
                except Exception:
                    pass
    return rows

def filesystem_name_scan(root):
    root=Path(root)
    scan_roots=[
        root/"analysis",
        root/"kr_extracted",
        root/"us_extracted",
    ]
    rows=[]
    exts={".bin",".prx",".tbl",".dat",".idx",".txt",".csv",".tsv",".ini",".json"}
    skip_parts={"logs","old","failed","macro_screenshots"}
    for sr in scan_roots:
        if not sr.exists(): continue
        for p in sr.rglob("*"):
            try:
                if not p.is_file(): continue
                if any(x.lower() in skip_parts for x in p.parts): continue
                if p.suffix.lower() not in exts: continue
                st=p.stat()
                if st.st_size>16*1024*1024: continue
                data=p.read_bytes()
            except Exception:
                continue
            found=[]
            for code,vs in JP_NAMES.items():
                for jp in vs:
                    b=jp.encode("cp932")
                    off=data.find(b)
                    if off>=0:
                        found.append((code,jp,off))
            if found:
                rows.append({
                    "path":str(p),
                    "size":len(data),
                    "hits":" | ".join(f"{c}:{j}@0x{o:X}" for c,j,o in found[:30]),
                    "hit_count":len(found),
                })
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    root=Path(args.root); out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)

    iso=root/"analysis"/"integrated"/"sub36_semantic_qa"/"output"/"Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso"
    if not iso.exists(): raise RuntimeError("SUB36 final ISO missing: "+str(iso))
    iso_sha=sha256_file(iso)
    if iso_sha!=EXPECTED_ISO_SHA:
        raise RuntimeError("SUB36 final ISO SHA mismatch: "+iso_sha)

    print("[1/6] Extract/search core ISO files",flush=True)
    ext=out/"iso_extract"
    ext.mkdir(exist_ok=True)
    core=[
        ("BOOT","PSP_GAME/SYSDIR/BOOT.BIN"),
        ("EBOOT","PSP_GAME/SYSDIR/EBOOT.BIN"),
        ("DAT","PSP_GAME/USRDIR/naruto.dat"),
        ("IDX","PSP_GAME/USRDIR/naruto.idx"),
    ]
    all_hits=[]; all_code_hits=[]; all_clusters=[]
    for label,ipath in core:
        p=ext/(label.lower()+Path(ipath).suffix.lower())
        info=extract_iso_file(iso,ipath,p)
        print(f"  {label}: {info['size']} bytes",flush=True)
        h,c,cl=scan_blob(label,p,out)
        all_hits.extend(h); all_code_hits.extend(c); all_clusters.extend(cl)

    write_tsv(out/"speaker_name_occurrences.tsv",all_hits,
              ["source","path","speaker_code","jp_candidate","ko_target","offset_dec","offset_hex","byte_len","context_cp932"])
    write_tsv(out/"speaker_code_occurrences.tsv",all_code_hits,
              ["source","path","speaker_code","offset_dec","offset_hex","context_cp932"])
    write_tsv(out/"speaker_name_clusters.tsv",all_clusters,
              ["source","start_hex","end_hex","span","hit_count","distinct_codes","codes","jp_names","likely_table","slice_file"])

    print("[2/6] Scan existing extracted/project files",flush=True)
    fsrows=filesystem_name_scan(root)
    write_tsv(out/"speaker_name_filesystem_hits.tsv",fsrows,["path","size","hits","hit_count"])

    print("[3/6] Inventory PPSSPP save states",flush=True)
    states=state_inventory(root)
    write_tsv(out/"ppsspp_savestate_inventory.tsv",states,
              ["path","filename","size","mtime","slot1_name_hint","sha256"])

    print("[4/6] Inventory PPSSPP executables/config",flush=True)
    configs=ppsspp_config_inventory(root)
    write_tsv(out/"ppsspp_environment.tsv",configs,["path","type","details"])

    print("[5/6] Inventory existing texture dumps",flush=True)
    textures=texture_inventory(root)
    write_tsv(out/"ppsspp_texture_inventory.tsv",textures,
              ["game_id","path","relative","size","in_new_folder","sha256"])

    print("[6/6] Summary",flush=True)
    likely=[r for r in all_clusters if r["likely_table"]=="YES"]
    slot1=[r for r in states if r["slot1_name_hint"]=="YES"]
    texnew=[r for r in textures if r["in_new_folder"]=="YES"]

    summary={
        "stage":"SUB37_SPEAKER_UI_DISCOVERY",
        "sub36_iso":str(iso),
        "sub36_iso_sha256":iso_sha,
        "speaker_name_occurrences":len(all_hits),
        "speaker_code_occurrences":len(all_code_hits),
        "likely_compact_name_clusters":len(likely),
        "filesystem_files_with_name_hits":len(fsrows),
        "savestates_found":len(states),
        "slot1_name_hint_states":len(slot1),
        "ppsspp_environment_entries":len(configs),
        "existing_texture_assets":len(textures),
        "existing_new_texture_dumps":len(texnew),
        "next_step":"PATCH_SPEAKER_NAMES_IF_TABLE_CONFIRMED_ELSE_TARGETED_RUNTIME_MEMORY_DUMP",
        "game_files_modified":False,
    }
    (out/"sub37_report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[
        "Naruto PSP SUB37 - Speaker Name / UI Discovery",
        "",
        "SUB36ISO=VERIFIED",
        f"SpeakerNameOccurrences={len(all_hits)}",
        f"LikelyCompactNameClusters={len(likely)}",
        f"FilesystemFilesWithNameHits={len(fsrows)}",
        f"SaveStatesFound={len(states)}",
        f"Slot1NameHintStates={len(slot1)}",
        f"ExistingTextureAssets={len(textures)}",
        f"ExistingNewTextureDumps={len(texnew)}",
        "",
        "GameFilesModified=NO",
        "Next=Speaker name patch if static table is confirmed; otherwise targeted runtime memory dump.",
    ]
    (out/"SUMMARY.txt").write_text("\n".join(lines)+"\n",encoding="utf-8-sig")
    print("\n".join(lines),flush=True)

if __name__=="__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)
