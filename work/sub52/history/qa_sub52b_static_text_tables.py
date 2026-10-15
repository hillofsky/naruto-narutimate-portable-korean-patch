
from pathlib import Path
import struct, hashlib, importlib.util, json, zipfile, traceback, re, csv

ROOT = Path(r"D:\narutimate portable")
OUT = ROOT / r"analysis\sub\sub52b_static_text_tables"
LOGS = ROOT / "logs"
SECTOR = 2048

SOURCES = [
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX13_FullAtlas.iso",
    ROOT / "Naruto_KR_MOV06E_SUB51P_FIX12_StableUI.iso",
    ROOT / r"analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso",
]

EXACT_TARGETS = [
    "戦闘条件","進む","勝者",
    "うずまきナルト","ナルト","サクラ","シカマル",
    "ナルPポイント","ポイント","得ました","得ま",
    "ノルマ達成まであと","不正解"
]

JP_CHAR_RE = re.compile(r"[ぁ-んァ-ヶー一-龯々〆ヵヶ]")

def choose_source():
    for p in SOURCES:
        if p.exists():
            return p
    raise RuntimeError("No source ISO found")

def sha256_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader: raise RuntimeError("Cannot import "+str(path))
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

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

def is_sjis_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC

def is_sjis_trail(b):
    return 0x40 <= b <= 0x7E or 0x80 <= b <= 0xFC

def scan_cp932_runs(data):
    out=[]
    i=0
    n=len(data)
    while i<n:
        start=i
        buf=bytearray()
        while i<n:
            b=data[i]
            if 0x20 <= b <= 0x7E or 0xA1 <= b <= 0xDF:
                buf.append(b); i+=1; continue
            if is_sjis_lead(b) and i+1<n and is_sjis_trail(data[i+1]):
                buf.extend(data[i:i+2]); i+=2; continue
            break
        if len(buf)>=4:
            try:
                s=bytes(buf).decode("cp932","strict")
            except Exception:
                s=""
            if s:
                jp=sum(1 for ch in s if JP_CHAR_RE.fullmatch(ch))
                visible=sum(1 for ch in s if not ch.isspace())
                if jp>=2 and visible and jp/visible>=0.20 and len(s)<=240:
                    out.append((start,s))
        if i==start:
            i+=1
        else:
            i+=1
    return out

def write_tsv(path,rows,fields):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def main():
    OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
    src=choose_source()
    print("=== SUB52B STATIC TEXT TABLE SWEEP ===",flush=True)
    print("SOURCE:",src,flush=True)
    print("SHA256:",sha256_file(src),flush=True)
    print("No PPSSPP / no gameplay / no ISO modification.",flush=True)

    p14=mod("sub52b_p14",ROOT/r"analysis\stage14\naruto_patcher.py")
    work=OUT/"_work"; work.mkdir(exist_ok=True)
    dat=work/"naruto.dat"
    extract_iso_file(src,"PSP_GAME/USRDIR/naruto.dat",dat)

    table=p14.parse_pidx(p14.read_embedded_index(dat),"src")
    primary=table["primary"]

    rawdir=OUT/"decoded_tables"
    rawdir.mkdir(exist_ok=True)
    rows=[]
    exact_rows=[]

    candidates=[]
    for i,r in enumerate(primary):
        name=r["name"].lower()
        # Real text/script candidates only. Skip CCS/audio/model binary families.
        if name.endswith(".tbl"):
            candidates.append((i,r))
        elif not name.endswith((".ccs",".pbd",".phd",".png")) and r["size"] and r["size"] <= 512*1024:
            candidates.append((i,r))

    print("Candidates:",len(candidates),flush=True)

    with dat.open("rb") as f:
        for k,(i,r) in enumerate(candidates):
            if k%10==0: print(f"  {k}/{len(candidates)} {r['name']}",flush=True)
            f.seek(r["offset"])
            stored=f.read(r["zsize"] or r["size"])
            try:
                dec=p14.decode_stored(stored,r["size"],r["zsize"])
            except Exception:
                continue

            safe=re.sub(r'[^A-Za-z0-9._-]+','_',r["name"])
            (rawdir/f"{i:04d}__{safe}.bin").write_bytes(dec)

            for off,s in scan_cp932_runs(dec):
                rows.append({
                    "entry_index":i,"entry":r["name"],"offset":off,
                    "length_chars":len(s),"jp":s
                })

            for target in EXACT_TARGETS:
                try: needle=target.encode("cp932")
                except: continue
                pos=0
                while True:
                    at=dec.find(needle,pos)
                    if at<0: break
                    exact_rows.append({
                        "entry_index":i,"entry":r["name"],"offset":at,"target":target
                    })
                    pos=at+1

    write_tsv(OUT/"japanese_strings_filtered.tsv",rows,
              ["entry_index","entry","offset","length_chars","jp"])
    write_tsv(OUT/"exact_target_hits.tsv",exact_rows,
              ["entry_index","entry","offset","target"])

    summary={
        "stage":"SUB52B_STATIC_TEXT_TABLE_SWEEP",
        "source_iso":str(src),
        "source_sha256":sha256_file(src),
        "candidate_entries":len(candidates),
        "filtered_japanese_runs":len(rows),
        "exact_target_hits":len(exact_rows),
        "gameplay_used":False,
        "ppsspp_used":False,
    }
    (OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "Naruto SUB52B static text-table sweep\n\n"+
        "\n".join(f"{k}={v}" for k,v in summary.items())+
        "\n\nUnlike SUB52A, this scanner does not decode arbitrary CCS/model/audio bytes as text.\n",
        encoding="utf-8-sig"
    )

    z=LOGS/"naruto_sub52b_static_text_tables_upload.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
        for p in OUT.rglob("*"):
            if p.is_file() and "_work" not in p.parts:
                zz.write(p,p.relative_to(OUT))

    print("UPLOAD_ZIP="+str(z),flush=True)

if __name__=="__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True)
        err=traceback.format_exc()
        (OUT/"FAILURE.txt").write_text(err,encoding="utf-8")
        z=LOGS/"fail_naruto_sub52b_static_text_tables_upload.zip"
        with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zz:
            for p in OUT.rglob("*"):
                if p.is_file() and "_work" not in p.parts:
                    zz.write(p,p.relative_to(OUT))
        print(err,flush=True)
        print("UPLOAD_ZIP="+str(z),flush=True)
        raise
