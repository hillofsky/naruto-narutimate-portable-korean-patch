#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Naruto SUB52K read-only ISO/CCS binary comparison. Never launches PPSSPP."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, json, struct, sys, traceback
from pathlib import Path
from collections import defaultdict

SECTOR = 2048
BASE_REL = r"analysis\sub\sub52j_safe_atlas\Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso"
TEST_REL = r"analysis\sub\sub52k_face_names\Naruto_KR_MOV06E_SUB52K_FaceNames.iso"
BASE_EXPECTED = "2e6cb2e577ddeebe07453ec56f07f72422a6b3b20001987c253a5468658f5a05"
CORE_PATHS = (
    "PSP_GAME/USRDIR/naruto.dat", "PSP_GAME/USRDIR/naruto.idx",
    "PSP_GAME/SYSDIR/BOOT.BIN", "PSP_GAME/SYSDIR/EBOOT.BIN",
)

def sha_path(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

def vd_root(p):
    with p.open('rb') as f:
        f.seek(16*SECTOR);vd=f.read(SECTOR)
    if len(vd)!=SECTOR or vd[0]!=1 or vd[1:6]!=b'CD001':
        raise RuntimeError('Primary ISO9660 descriptor invalid: '+str(p))
    root=vd[156:190]
    return {
        'volume_sectors':int.from_bytes(vd[80:84],'little'),
        'root_lba':int.from_bytes(root[2:6],'little'),
        'root_size':int.from_bytes(root[10:14],'little'),
    }

def list_dir(p,lba,size):
    with p.open('rb') as f:
        f.seek(lba*SECTOR);buf=f.read(size)
    pos=0;out=[]
    while pos<len(buf):
        reclen=buf[pos]
        if not reclen:
            pos=(pos//SECTOR+1)*SECTOR
            continue
        rec=buf[pos:pos+reclen]
        if len(rec)<34:raise RuntimeError('Truncated ISO dir record')
        bn=rec[33:33+rec[32]]
        name='.' if bn==b'\0' else ('..' if bn==b'\x01' else bn.decode('ascii','replace').split(';')[0])
        out.append({'name':name,'lba':int.from_bytes(rec[2:6],'little'),
                    'size':int.from_bytes(rec[10:14],'little'),'dir':bool(rec[25]&2)})
        pos+=reclen
    return out

def iso_entry(p,pathname):
    vd=vd_root(p);cur={'lba':vd['root_lba'],'size':vd['root_size'],'dir':True}
    for name in pathname.replace('\\','/').split('/'):
        if not name:continue
        found=next((r for r in list_dir(p,cur['lba'],cur['size']) if r['name'].lower()==name.lower()),None)
        if not found:raise RuntimeError(f'ISO path missing: {pathname} in {p.name}')
        cur=found
    if cur['lba']*SECTOR+cur['size']>p.stat().st_size:
        raise RuntimeError('ISO extent outside physical file: '+pathname)
    return cur

def file_hash_region(p,offset,size):
    h=hashlib.sha256()
    with p.open('rb') as f:
        f.seek(offset)
        left=size
        while left:
            buf=f.read(min(left,4*1024*1024))
            if not buf:raise RuntimeError('EOF while hashing region')
            h.update(buf);left-=len(buf)
    return h.hexdigest()

def read_iso_file(p,pathname,max_size=16*1024*1024):
    e=iso_entry(p,pathname)
    if e['size']>max_size:
        raise RuntimeError('File too large for in-memory read: '+pathname)
    with p.open('rb') as f:
        f.seek(e['lba']*SECTOR)
        return f.read(e['size'])

def read_iso_pid_index(p,dat_entry,patcher):
    abs_start=dat_entry['lba']*SECTOR
    with p.open('rb') as f:
        f.seek(abs_start);head=f.read(0x50)
        if head[:5]!=b'PIDX0':raise RuntimeError('naruto.dat lacks PIDX0')
        names_off,names_size=struct.unpack_from('<2I',head,0x20)
        total=names_off+names_size
        if total<0x50 or total>min(dat_entry['size'],32*1024*1024):
            raise RuntimeError('Bad embedded PIDX span: '+str(total))
        f.seek(abs_start);blob=f.read(total)
    if len(blob)!=total:raise RuntimeError('Short embedded PIDX')
    return patcher.parse_pidx(blob,p.name)

def load_module(path):
    sp=importlib.util.spec_from_file_location('sub52k_static_diag_patcher',path)
    if not sp or not sp.loader:raise RuntimeError('Unable to load existing naruto_patcher.py')
    mod=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod

def read_decoded_primary(iso,datfile,row,patcher):
    length=row['zsize'] or row['size']
    offset=datfile['lba']*SECTOR+row['offset']
    if row['offset']+length>datfile['size']:
        raise RuntimeError(f"PIDX primary extent exceeds DAT: {row['name']}")
    with iso.open('rb') as f:
        f.seek(offset);stored=f.read(length)
    if len(stored)!=length:raise RuntimeError('Short stored resource')
    out=patcher.decode_stored(stored,row['size'],row['zsize'])
    if len(out)!=row['size']:raise RuntimeError(f"Wrong decode size {row['name']}")
    return out

def ccs_names(b):
    pc,nc=struct.unpack_from('<II',b,0x44)
    name_off=0x4C+32*pc
    if pc>10000 or nc>50000 or name_off+32*nc>len(b):raise RuntimeError('Bad CCS header')
    return [b[name_off+32*i:name_off+32*i+30].split(b'\0',1)[0].decode('cp932','replace') for i in range(nc)]

def texture_spans(b):
    names=ccs_names(b);spans={};magic=bytes.fromhex('0003cccc')
    for off in range(0,len(b)-36,4):
        if b[off:off+4]!=magic:continue
        name_idx=struct.unpack_from('<I',b,off+8)[0]
        typ=b[off+21];we,he=b[off+24:off+26]
        if name_idx>=len(names) or typ not in (0x13,0x14) or we>12 or he>12:continue
        w,h=1<<we,1<<he
        length=w*h if typ==0x13 else (w*h)//2
        if off+36+length>len(b):continue
        spans[names[name_idx]]={'start':off+36,'end':off+36+length,'type':typ,'width':w,'height':h}
    return spans

def report(root,out):
    source=root/BASE_REL;test=root/TEST_REL
    if not source.is_file():raise RuntimeError('Known-good SUB52J ISO missing: '+str(source))
    if not test.is_file():raise RuntimeError('SUB52K ISO missing: '+str(test))
    out.mkdir(parents=True,exist_ok=True)
    patcher=load_module(root/r'analysis\stage14\naruto_patcher.py')
    result={'source':str(source),'test':str(test),'read_only':True,'checks':{},'warnings':[]}
    print('[1/6] Compute source/test ISO hashes',flush=True)
    for kind,p in (('source',source),('test',test)):
        result[kind+'_sha256']=sha_path(p);result[kind+'_bytes']=p.stat().st_size
    result['checks']['source_matches_known_good_hash']=(result['source_sha256']==BASE_EXPECTED)
    print('SOURCE_SHA256='+result['source_sha256'],flush=True)
    print('TEST_SHA256='+result['test_sha256'],flush=True)
    if not result['checks']['source_matches_known_good_hash']:
        result['warnings'].append('Known-good SUB52J hash mismatch')
    print('[2/6] Check ISO9660 and core files',flush=True)
    source_vd=vd_root(source);test_vd=vd_root(test)
    result['volume']={'source':source_vd,'test':test_vd}
    for kind,p,vd in (('source',source,source_vd),('test',test,test_vd)):
        result['checks'][f'{kind}_volume_size_valid']=vd['volume_sectors']*SECTOR<=p.stat().st_size
    core={};dat={}
    for name in CORE_PATHS:
        s=iso_entry(source,name);t=iso_entry(test,name)
        hs=file_hash_region(source,s['lba']*SECTOR,s['size'])
        ht=file_hash_region(test,t['lba']*SECTOR,t['size'])
        core[name]={'source':s,'test':t,'source_sha256':hs,'test_sha256':ht,'same':hs==ht}
        if name.endswith('naruto.dat'):dat={'source':s,'test':t}
    result['core']=core
    for name in ('PSP_GAME/SYSDIR/BOOT.BIN','PSP_GAME/SYSDIR/EBOOT.BIN'):
        result['checks'][name+'_preserved']=core[name]['same']
    print('[3/6] Compare DAT internal/external indices',flush=True)
    a=read_iso_pid_index(source,dat['source'],patcher)
    b=read_iso_pid_index(test,dat['test'],patcher)
    ext_a=patcher.parse_pidx(read_iso_file(source,'PSP_GAME/USRDIR/naruto.idx'), 'source_external')
    ext_b=patcher.parse_pidx(read_iso_file(test,'PSP_GAME/USRDIR/naruto.idx'), 'test_external')
    result['counts']={'source_primary':len(a['primary']),'test_primary':len(b['primary']),
                      'source_offset2':len(a['offset2_rows']),'test_offset2':len(b['offset2_rows'])}
    result['checks']['primary_counts_match']=len(a['primary'])==len(b['primary'])==len(ext_b['primary'])
    result['checks']['offset2_counts_match']=len(a['offset2_rows'])==len(b['offset2_rows'])==len(ext_b['offset2_rows'])
    changes=[];mismatches=[]
    source_rows={r['name']:r for r in a['primary']}
    test_rows={r['name']:r for r in b['primary']}
    for name,br in test_rows.items():
        ar=source_rows.get(name)
        if ar is None:
            mismatches.append('Primary name missing in source: '+name);continue
        x=next((q for q in ext_b['primary'] if q['name']==name),None)
        if x is None:
            mismatches.append('External index missing '+name);continue
        if any(x[k]!=br[k] for k in ('offset','size','zsize')):
            mismatches.append('External PIDX mismatch for '+name)
        fields=('offset','size','zsize')
        if any(ar[k]!=br[k] for k in fields):
            changes.append({'name':name,'old_offset':ar['offset'],'new_offset':br['offset'],
                            'old_size':ar['size'],'new_size':br['size'],
                            'old_zsize':ar['zsize'],'new_zsize':br['zsize'],
                            'expected_face':name.lower().startswith('face_') and name.lower().endswith('.ccs')})
    result['primary_changes']=changes
    result['checks']['only_face_primary_changed']=all(r['expected_face'] for r in changes)
    result['checks']['exactly_23_face_primary_changed']=sum(r['expected_face'] for r in changes)==23
    for i,br in enumerate(b['offset2_rows']):
        x=ext_b['offset2_rows'][i]
        if any(x[k]!=br[k] for k in ('file_off','file_size')):
            mismatches.append('External OFFSET2 mismatch '+str(i))
    offs_changes=[]
    for ar,br in zip(a['offset2_rows'],b['offset2_rows']):
        if (ar['file_off'],ar['file_size'])!=(br['file_off'],br['file_size']):
            offs_changes.append({'bundle':br['name'],'old_size':ar['file_size'],'new_size':br['file_size']})
    result['offset2_changes']=offs_changes
    result['index_mismatches']=mismatches
    result['checks']['embedded_external_idx_match']=not mismatches
    print('[4/6] Decode 23 face CCS and isolate changed byte spans',flush=True)
    resource_checks=[]
    for change in changes:
        name=change['name']
        if not change['expected_face']:continue
        old=read_decoded_primary(source,dat['source'],source_rows[name],patcher)
        new=read_decoded_primary(test,dat['test'],test_rows[name],patcher)
        item={'resource':name,'old_decoded_size':len(old),'new_decoded_size':len(new),
              'decoded_size_preserved':len(old)==len(new)}
        if len(old)!=len(new):
            item['status']='DECODED_SIZE_CHANGED';resource_checks.append(item);continue
        at=texture_spans(old);bt=texture_spans(new)
        tex_names=[t for t in at if t.startswith('TEX_n_')]
        allowed=[(t,at[t]['start'],at[t]['end']) for t in tex_names if t in bt]
        item['allowed_texture_names']=tex_names
        item['texture_spans_identical']=(at==bt)
        allowed_mask=bytearray(len(old))
        for _,start,end in allowed:
            allowed_mask[start:end]=b'\x01'*(end-start)
        changed=outside=0
        for i,(x,y) in enumerate(zip(old,new)):
            if x!=y:
                changed+=1
                if not allowed_mask[i]:outside+=1
        item['bytes_changed']=changed
        item['unexpected_bytes_changed']=outside
        item['status']='PASS' if item['decoded_size_preserved'] and item['texture_spans_identical'] and outside==0 else 'FAIL'
        resource_checks.append(item)
    result['face_resource_checks']=resource_checks
    result['checks']['face_ccs_changed_bytes_only_in_name_textures']=bool(resource_checks) and all(r['status']=='PASS' for r in resource_checks)
    print('[5/6] Inspect ISO file ranges and structural anomalies',flush=True)
    for kind in ('source','test'):
        d=dat[kind];iso=source if kind=='source' else test
        res=a if kind=='source' else b
        bad=[]
        for row in res['primary']:
            length=row['zsize'] or row['size']
            if row['offset']+length>d['size']:
                bad.append(f"{row['name']} extent {row['offset']}+{length}>{d['size']}")
        for row in res['offset2_rows']:
            if row['file_off']+row['file_size']>d['size']:
                bad.append(f"OFFSET2 {row['name']} outside DAT")
        result['checks'][kind+'_pidx_extents_valid']=not bad
        result[kind+'_pidx_bad_extents']=bad[:50]
    print('[6/6] Save reports',flush=True)
    result['suspected_diagnosis']='The ISO is not proven runtime-safe by static tests; compare SUB52J boot and inspect PPSSPP process/logs.'
    summary=[]
    summary.append('Naruto SUB52K read-only black-screen diagnosis')
    for k,v in result['checks'].items():summary.append(f'{k}: {"PASS" if v else "FAIL"}')
    summary.append(f"Changed primary resources: {len(changes)}; FSTS bundles: {len(offs_changes)}")
    summary.append(f"Face checks: {len(resource_checks)}; non-texture changed bytes: {sum(r.get('unexpected_bytes_changed',0) for r in resource_checks)}")
    summary.append('No ISO / emulator modification was performed.')
    (out/'SUMMARY.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8-sig')
    (out/'diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'face_resource_validation.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['resource','old_decoded_size','new_decoded_size','decoded_size_preserved','texture_spans_identical',
              'bytes_changed','unexpected_bytes_changed','status']
        writer=csv.DictWriter(f,fieldnames=cols,delimiter='\t',extrasaction='ignore')
        writer.writeheader();writer.writerows(resource_checks)
    print('\n'.join(summary),flush=True)
    return result

if __name__=='__main__':
    try:
        ap=argparse.ArgumentParser()
        ap.add_argument('--root',default=r'D:\narutimate portable')
        ap.add_argument('--out',required=True)
        args=ap.parse_args()
        report(Path(args.root),Path(args.out))
    except Exception:
        traceback.print_exc();sys.exit(1)
