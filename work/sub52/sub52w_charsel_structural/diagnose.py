#!/usr/bin/env python3
# SUB52W - read-only provenance and ISO9660 layout probe for Naruto PSP
# Standard library only. Never writes to any source file or controls PPSSPP.
import argparse, csv, hashlib, json, os, re, shutil, struct, sys, traceback
from pathlib import Path
from datetime import datetime, timezone

KEYS = ['charsel1.ccs','tex_sel','tex_sel_bg','fsts','pidx','ccs_extract','ccs_rebuild','atlas','uv_rect','uv_coord']
TEXT_EXTS={'.py','.ps1','.txt','.json','.csv','.md','.bat','.cmd'}
BIN_EXTS={'.ccs','.idx','.tbl','.fsts','.pak','.dat','.bin'}
ISO_NAME='Naruto_KR_MOV06E_SUB52U_HUDRemaining_Compact.iso'
ISO_REL=Path('analysis/sub/sub52u_hud_remaining')/ISO_NAME
KNOWN_SHA='3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f'


def jwrite(p,obj):
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def csv_write(p,rows,headers):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');w.writeheader();w.writerows(rows)
def relpath(p,root):
    try:return str(p.relative_to(root))
    except ValueError:return str(p)
def read_small(p,cap=3*1024*1024):
    try:
        if not p.is_file() or p.stat().st_size>cap:return None
        b=p.read_bytes()
        if b'\0' in b[:1000]:return None
        for codec in ('utf-8-sig','utf-16','cp949'):
            try:return b.decode(codec)
            except UnicodeError:pass
        return b.decode('utf-8',errors='replace')
    except (OSError,PermissionError):return None

def stage_directories(root):
    dirs=[root/'tools',root/'generated_macros',root/'assets',root/'analysis'/'sub'/'sub52u_hud_remaining',root/'analysis'/'sub'/'sub52a_full_static_asset_sweep',root/'analysis'/'sub'/'sub52c_static_patch_sources',root/'analysis'/'sub'/'sub52o_unified_audit',root/'analysis'/'sub'/'sub52p_historical_source']
    # Prior successful patchers and diagnostics (limit to selected stages, not full 65k file walk).
    sub=root/'analysis'/'sub'
    if sub.is_dir():
        for d in sub.iterdir():
            if d.is_dir() and re.match(r'(?i)^sub(?:43|44|45|51[ghijlmp]|52[defghijklmnpqrstuv])(?:_|$)',d.name):dirs.append(d)
    # Top-level scripts (nonrecursive).
    return list(dict.fromkeys(d for d in dirs if d.is_dir()))

def scan_sources(root,out):
    directories=stage_directories(root)
    diagnostics=[];paths=[];binary=[];visited=set();total=0;skips=0
    for d in directories:
        for base,dirnames,filenames in os.walk(d):
            dirnames[:]=[n for n in dirnames if n.lower() not in {'old','__pycache__','.git','node_modules','venv','.venv','_work','work','screenshots','textures_primary','textures_secondary','video','frames','pmf'}]
            for fn in filenames:
                total+=1
                if total>65000:skips+=1;break
                p=Path(base)/fn
                if p in visited:continue
                visited.add(p)
                ext=p.suffix.lower()
                if ext in TEXT_EXTS:
                    # Only inspect relevant stages/scripts. Contents scanned capped at 3MiB.
                    content=read_small(p)
                    if content is None:continue
                    lines=content.splitlines(); hits=[]
                    for i,line in enumerate(lines):
                        ll=line.lower()
                        terms=[k for k in KEYS if k in ll]
                        if terms:
                            hits.append((i,terms))
                    if hits:
                        score=sum(20 if 'charsel1.ccs' in x[1] or 'tex_sel' in x[1] else 3 for x in hits)
                        score+=20 if p.suffix.lower()=='.py' else 0
                        score+=10 if re.search(r'(?i)build|patch|extract|repack|fsts',p.name) else 0
                        diagnostics.append({'path':str(p),'relpath':relpath(p,root),'size':p.stat().st_size,'hits':len(hits),'score':score,'lines':lines,'matches':hits})
                elif ext in BIN_EXTS:
                    try:size=p.stat().st_size
                    except OSError:continue
                    if size<=16*1024*1024 and re.search(r'(?i)char|sel|fsts|pidx|index|ccs',fn):binary.append((str(p),size))
            if total>65000:break
        if total>65000:break
    # Include top-level Python/PowerShell scripts with relevant names.
    for p in root.iterdir():
        if p.is_file() and p.suffix.lower() in TEXT_EXTS and re.search(r'(?i)ccs|fsts|pidx|iso|sub52',p.name):
            content=read_small(p)
            if content is None:continue
            lines=content.splitlines();hits=[(i,[k for k in KEYS if k in line.lower()]) for i,line in enumerate(lines) if any(k in line.lower() for k in KEYS)]
            if hits:diagnostics.append({'path':str(p),'relpath':relpath(p,root),'size':p.stat().st_size,'hits':len(hits),'score':len(hits)*10+30,'lines':lines,'matches':hits})
    diagnostics.sort(key=lambda d:(-d['score'],d['size'],d['relpath']))
    refs=[]
    for d in diagnostics[:140]:
        for i,terms in d['matches'][:80]:
            excerpt=' | '.join(d['lines'][max(0,i-2):min(len(d['lines']),i+3)])
            refs.append({'path':d['relpath'],'line':i+1,'terms':';'.join(terms),'context':excerpt[:900]})
    csv_write(out/'SOURCE_REFERENCE_CONTEXT.csv',refs,['path','line','terms','context'])
    csv_write(out/'SOURCE_RANKING.csv',[{k:d[k] for k in ('relpath','size','hits','score')} for d in diagnostics],['relpath','size','hits','score'])
    # Capture full contents for a small number of relevant scripts, with explicit source manifest and SHA256.
    copied=[];budget=8*1024*1024
    for d in diagnostics:
        if len(copied)>=18:break
        if d['size']>1024*1024 or d['size']>budget:continue
        p=Path(d['path']);dest=out/'source_samples'/('sample_%02d%s'%(len(copied)+1,p.suffix.lower()))
        try:
            shutil.copyfile(p,dest);b=dest.read_bytes()
            copied.append({'original':d['relpath'],'sample':dest.name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'hits':d['hits']});budget-=len(b)
        except OSError:pass
    csv_write(out/'SOURCE_SAMPLES_MANIFEST.csv',copied,['original','sample','size','sha256','hits'])
    # Capture small metadata files & resource indexes, never any movie or ISO.
    bins=[];maxbytes=20*1024*1024
    for s,size in sorted(binary,key=lambda x:x[1]):
        if len(bins)>=12 or size>maxbytes:break
        p=Path(s);dest=out/'binary_samples'/('binary_%02d%s'%(len(bins)+1,p.suffix.lower()))
        try:
            shutil.copyfile(p,dest);b=dest.read_bytes()
            bins.append({'original':relpath(p,root),'sample':dest.name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()});maxbytes-=size
        except OSError:pass
    csv_write(out/'BINARY_SAMPLES_MANIFEST.csv',bins,['original','sample','bytes','sha256'])
    return {'directories_scanned':[relpath(d,root) for d in directories],'files_scanned':total,'matched_sources':len(diagnostics),'reference_rows':len(refs),'sampled_sources':len(copied),'sampled_binary':len(bins),'scan_truncated':bool(skips)}

# Small ISO9660 file-directory metadata reader: no extracts unless tiny index files.
class IsoProbe:
    def __init__(self,path):self.path=path;self.f=path.open('rb');self.size=path.stat().st_size
    def close(self):self.f.close()
    def block(self,sector,length=2048):
        off=sector*2048
        if off<0 or off+length>self.size:raise ValueError('outside ISO range')
        self.f.seek(off);return self.f.read(length)
    def record(self,blob):
        if len(blob)<34:return None
        extent=struct.unpack_from('<I',blob,2)[0];length=struct.unpack_from('<I',blob,10)[0];flags=blob[25]
        n=blob[32];raw=blob[33:33+n];name=raw.decode('latin-1',errors='replace')
        if n==1 and raw==b'\x00':name='.'
        if n==1 and raw==b'\x01':name='..'
        name=name.split(';')[0]
        return {'extent_sector':extent,'size_bytes':length,'is_directory':bool(flags&2),'name':name,'flags':flags}
    def getfiles(self):
        pvd=self.block(16)
        if pvd[1:6]!=b'CD001':raise ValueError('Sector 16 has no ISO9660 PVD signature: '+repr(pvd[1:6]))
        rr=self.record(pvd[156:156+pvd[156]]);
        if not rr:raise ValueError('No root directory record')
        todos=[('',rr,0)];seen=set();files=[]
        while todos and len(files)<10000:
            prefix,r,depth=todos.pop(0)
            if depth>12 or r['size_bytes']>64*1024*1024 or r['extent_sector'] in seen:continue
            seen.add(r['extent_sector']);length=r['size_bytes'];data=self.block(r['extent_sector'],length)
            pos=0
            while pos<len(data):
                rec_len=data[pos]
                if not rec_len:
                    pos=((pos//2048)+1)*2048;continue
                r2=self.record(data[pos:pos+rec_len]);pos+=rec_len
                if r2 and r2['name'] not in ('.','..'):
                    name=prefix+'/'+r2['name']
                    files.append(dict(r2,iso_path=name))
                    if r2['is_directory']:todos.append((name,r2,depth+1))
        return files
    def small_extract(self,rec,dest):
        if rec['size_bytes']>16*1024*1024:return False
        b=self.block(rec['extent_sector'],rec['size_bytes'])
        if len(b)!=rec['size_bytes']:return False
        dest.write_bytes(b);return True

def iso_probe(root,out):
    isopath=root/ISO_REL
    if not isopath.is_file():return {'status':'ISO_NOT_FOUND','path':str(isopath)}
    obj={'status':'ISO_PRESENT','path':str(isopath),'bytes':isopath.stat().st_size,'expected_sha256_not_rechecked':KNOWN_SHA}
    try:
        probe=IsoProbe(isopath)
        files=probe.getfiles()
        csv_write(out/'ISO9660_FILE_LIST.csv',files,['iso_path','name','extent_sector','size_bytes','flags','is_directory'])
        candidates=[r for r in files if not r['is_directory'] and re.search(r'(?i)\.(?:idx|fsts|tbl)$|index|p[_-]?idx|char|ccs|fsts',r['name']) and r['size_bytes']<=16*1024*1024]
        snippets=[]
        for c in candidates[:8]:
            dest=out/'iso_index_samples'/('iso_%02d.bin'%(len(snippets)+1))
            if probe.small_extract(c,dest):snippets.append({'iso_path':c['iso_path'],'sample':dest.name,'bytes':c['size_bytes']})
        obj.update({'status':'ISO9660_PASS','iso_file_entries':len(files),'index_candidates':len(candidates),'index_extracted':snippets})
    except Exception as e:
        obj.update({'status':'ISO9660_PROBE_WARNING','warning':str(e)})
    finally:
        try:probe.close()
        except Exception:pass
    return obj

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=r'D:\narutimate portable');p.add_argument('--out',required=True)
    args=p.parse_args();root=Path(args.root);out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    for d in ('source_samples','binary_samples','iso_index_samples'):(out/d).mkdir(exist_ok=True)
    data={'stage':'SUB52W_CHARSEL_STRUCTURAL','start_utc':datetime.now(timezone.utc).isoformat(),'root':str(root),'read_only':True,'iso_modified':False,'emulator_controlled':False,'previous':'SUB52V'}
    try:
        if not root.is_dir():raise FileNotFoundError('Project root does not exist: '+str(root))
        data['sources']=scan_sources(root,out)
        data['iso']=iso_probe(root,out)
        # Hard failure only if root invalid; missing source or unrecognized filesystem are warnings.
        data['status']='PASS_WITH_WARNINGS' if data['iso']['status']!='ISO9660_PASS' or data['sources']['matched_sources']==0 else 'PASS'
        data['end_utc']=datetime.now(timezone.utc).isoformat();jwrite(out/'RESULT.json',data)
        summary=f"SUB52W READ-ONLY STRUCTURAL AUDIT\nStatus: {data['status']}\nISO: {data['iso']['status']}\nSource files containing keywords: {data['sources']['matched_sources']}\nCopied source scripts: {data['sources']['sampled_sources']}\nCopied small binary samples: {data['sources']['sampled_binary']}\nSource game files unchanged; no PPSSPP controlled.\nNext: analyze actual extraction scripts + index tables; map name UV rectangles before patch.\n"
        (out/'SUMMARY.txt').write_text(summary,encoding='utf-8');print(summary)
    except Exception as e:
        data.update({'status':'FAIL','error':repr(e),'traceback':traceback.format_exc()});jwrite(out/'RESULT.json',data)
        (out/'FAILURE.txt').write_text(data['traceback'],encoding='utf-8');print(data['traceback'],file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
