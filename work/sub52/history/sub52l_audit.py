#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only static investigation of remaining Naruto PSP HUD/result strings.

No changes to ISO, no PPSSPP launch, no dependency beyond stdlib.
This script does not equate a Japanese text match with proof of actual renderer use.
"""
from __future__ import annotations
import argparse
import binascii
import csv
import hashlib
import importlib.util
import json
import re
import struct
import sys
import traceback
import zlib
from collections import defaultdict
from pathlib import Path

SECTOR = 2048
SOURCE = Path(r'analysis\sub\sub52k_fix2_compact\Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso')
BASE = Path(r'analysis\sub\sub52j_safe_atlas\Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso')
OUT = Path(r'analysis\sub\sub52l_runtime_source_audit')
TARGETS = ('face_sik.ccs','face_hnt.ccs','eff3eye.ccs','gauge.ccs','mgselect.ccs','charsel1.ccs')
FOCUS_TEX = ('TEX_n_sik_s','TEX_n_sik_l','TEX_n_hnt_s','TEX_n_hnt_l','TEX_xwinner')
JP_TERMS = ('シカマル','ヒナタ','サクラ','勝者','ナルＰポイント','ナルPポイント','ボタンでゲーム','木登り')
CHUNK = 4 * 1024 * 1024


def sha256(b):return hashlib.sha256(b).hexdigest()


def hash_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(CHUNK),b''):
            h.update(b)
    return h.hexdigest()


def write_tsv(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def directory(iso,lba,size):
    with iso.open('rb') as f:
        f.seek(lba*SECTOR); buf=f.read(size)
    out=[];pos=0
    while pos<len(buf):
        n=buf[pos]
        if not n:pos=(pos//SECTOR+1)*SECTOR;continue
        rec=buf[pos:pos+n]
        if len(rec)<34:raise RuntimeError('ISO dir record too short')
        raw=rec[33:33+rec[32]]
        name='.' if raw==b'\0' else ('..' if raw==b'\x01' else raw.decode('ascii','replace').split(';')[0])
        lba_le=int.from_bytes(rec[2:6],'little'); lba_be=int.from_bytes(rec[6:10],'big')
        size_le=int.from_bytes(rec[10:14],'little');size_be=int.from_bytes(rec[14:18],'big')
        if lba_le!=lba_be or size_le!=size_be:
            raise RuntimeError('ISO endian extent mismatch: '+name)
        out.append(dict(name=name,lba=lba_le,size=size_le,is_dir=bool(rec[25]&2)))
        pos+=n
    return out


def isoentry(iso,path):
    with iso.open('rb') as f:
        f.seek(16*SECTOR); vd=f.read(SECTOR)
    if vd[:1]!=b'\1' or vd[1:6]!=b'CD001':raise RuntimeError('ISO PVD invalid')
    root=vd[156:190]
    cur=dict(lba=int.from_bytes(root[2:6],'little'),size=int.from_bytes(root[10:14],'little'),is_dir=True)
    for part in path.replace('\\','/').strip('/').split('/'):
        cur=next((x for x in directory(iso,cur['lba'],cur['size']) if x['name'].casefold()==part.casefold()),None)
        if cur is None:raise RuntimeError(f'Missing ISO file {path}')
    if cur['lba']*SECTOR+cur['size']>iso.stat().st_size:
        raise RuntimeError('ISO extent out of range: '+path)
    return cur


def loadpatcher(root):
    path=root / r'analysis\stage14\naruto_patcher.py'
    sp=importlib.util.spec_from_file_location('sub52l_existing_patcher',path)
    if not sp or not sp.loader:raise RuntimeError('Missing original stage14 naruto_patcher.py: '+str(path))
    module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
    return module


def read_index(iso,dat_extent,patcher):
    with iso.open('rb') as f:
        absstart=dat_extent['lba']*SECTOR
        f.seek(absstart);header=f.read(0x50)
        if header[:5]!=b'PIDX0':raise RuntimeError('Embedded DAT index missing PIDX0')
        names_off,names_size=struct.unpack_from('<II',header,0x20)
        length=names_off+names_size
        if length<0x50 or length>min(32*1024*1024,dat_extent['size']):
            raise RuntimeError(f'Embedded PIDX size unreasonable: {length}')
        f.seek(absstart);blob=f.read(length)
    return patcher.parse_pidx(blob,'sub52l'),blob


def primary_resource(iso,dat_extent,index,name,patcher):
    rows=[r for r in index['primary'] if r['name'].lower()==name.lower()]
    if len(rows)!=1:raise RuntimeError(f'Expected one primary {name}, got {len(rows)}')
    r=rows[0];n=r['zsize'] or r['size']
    if r['offset']+n>dat_extent['size']:raise RuntimeError('DAT primary out of range '+name)
    with iso.open('rb') as f:
        f.seek(dat_extent['lba']*SECTOR+r['offset']);stored=f.read(n)
    if len(stored)!=n:raise RuntimeError('Short primary '+name)
    data=patcher.decode_stored(stored,r['size'],r['zsize'])
    return data,r


def names_ccs(buf):
    if len(buf)<0x4c:raise RuntimeError('Small CCS')
    pc,nc=struct.unpack_from('<II',buf,0x44)
    base=0x4C+32*pc
    if pc>10000 or nc>50000 or base+32*nc>len(buf):raise RuntimeError('Invalid CCS names')
    return [buf[base+i*32:base+i*32+30].split(b'\0')[0].decode('cp932','replace') for i in range(nc)]


def tex_spans(buf):
    names=names_ccs(buf)
    out=[]
    magic=b'\x00\x03\xcc\xcc'
    for off in range(0,len(buf)-36,4):
        if buf[off:off+4]!=magic:continue
        idx=struct.unpack_from('<I',buf,off+8)[0]
        typ=buf[off+21];ew,eh=buf[off+24:off+26]
        if idx>=len(names) or typ not in (0x13,0x14) or ew>12 or eh>12:continue
        w,h=1<<ew,1<<eh
        size=w*h if typ==0x13 else w*h//2
        if off+36+size>len(buf):continue
        out.append(dict(name=names[idx],offset=off,width=w,height=h,typ=typ,
                        palette=struct.unpack_from('<I',buf,off+12)[0],size=size))
    return out


def palette(buf,palid):
    magic=b'\x00\x04\xcc\xcc'
    for pos in range(0,len(buf)-28,4):
        if buf[pos:pos+4]!=magic or struct.unpack_from('<I',buf,pos+8)[0]!=palid:continue
        n=struct.unpack_from('<I',buf,pos+24)[0]
        if n not in (16,256) or pos+28+4*n>len(buf):continue
        return [tuple((lambda bgra:(bgra[2],bgra[1],bgra[0],min(255,bgra[3]*2)))(buf[pos+28+i*4:pos+32+i*4])) for i in range(n)]
    raise RuntimeError(f'Palette {palid} not found')


def decode_tex(buf,span):
    raw=buf[span['offset']+36:span['offset']+36+span['size']]
    if span['typ']==0x13:inds=list(raw)
    else:
        inds=[]
        for c in raw:inds.extend((c&15,c>>4))
    w,h=span['width'],span['height'];pal=palette(buf,span['palette'])
    # PSP atlas is stored bottom-up as in prior decoder.
    rgba=bytearray(w*h*4)
    for y in range(h):
        for x in range(w):
            idx=inds[(h-1-y)*w+x]
            rgba[4*(y*w+x):4*(y*w+x)+4]=bytes(pal[idx])
    return bytes(rgba),bytes(raw)


def save_png(path,w,h,rgba):
    def piece(tag,data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',binascii.crc32(tag+data)&0xffffffff)
    scans=b''.join(b'\0'+rgba[y*w*4:(y+1)*w*4] for y in range(h))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+piece(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+
                     piece(b'IDAT',zlib.compress(scans,6))+piece(b'IEND',b''))


def capture_resources(iso,label,patcher,out,targets):
    print(f'[{label}] inspect primary resources',flush=True)
    dat=isoentry(iso,'PSP_GAME/USRDIR/naruto.dat')
    idx,idxblob=read_index(iso,dat,patcher)
    records=[]; data_by={}; tex_by={}; payload_by={}; record_by={}
    for name in targets:
        data,r=primary_resource(iso,dat,idx,name,patcher)
        data_by[name]=data;record_by[name]=r
        ts=tex_spans(data)
        tex_by[name]={x['name']:x for x in ts}
        for t in ts:
            if not (name.startswith('face_') or t['name']=='TEX_xwinner'):
                continue
            if name.startswith('face_') and not t['name'].startswith('TEX_n_'):
                continue
            rgba,raw=decode_tex(data,t)
            payload_by[name,t['name']]=dict(png_rgba_sha256=sha256(rgba),indexed_payload_sha256=sha256(raw),rgba=rgba)
            png=f'{name.replace(".ccs","")}__{t["name"]}.png'
            save_png(out/label/png,t['width'],t['height'],rgba)
            records.append(dict(stage=label,resource=name,texture=t['name'],width=t['width'],height=t['height'],
                                rgba_sha256=sha256(rgba),raw_sha256=sha256(raw),primary_offset=r['offset']))
        print(f'  {name}: {len(ts)} textures',flush=True)
    return dict(records=records,tex=tex_by,payload=payload_by,dat=dat,index=idx,idx_blob=idxblob,records_map=record_by, decoded_sha256={n:sha256(d) for n,d in data_by.items()})


def scan_fsts_headers(iso,dat,index,patcher,nameset):
    # Bounded, header-only scan of OFFSET2 archives. Do NOT read large FSTS bundles in memory.
    seen=[];errors=[]
    with iso.open('rb') as f:
        for r in index['offset2_rows']:
            pos=dat['lba']*SECTOR+r['file_off']; sz=r['file_size']
            if r['file_off']+sz>dat['size'] or sz<20:
                errors.append(f'offset2 extent malformed: {r["name"]}');continue
            f.seek(pos); head=f.read(20)
            if head[:4]!=b'FSTS':continue
            count,info_off,names_off,names_size=struct.unpack_from('<4I',head,4)
            if count>50000 or names_size>4*1024*1024 or info_off+count*16>sz or names_off+names_size>sz:
                errors.append(f'FSTS header invalid: {r["name"]}');continue
            f.seek(pos+names_off); names=f.read(names_size)
            f.seek(pos+info_off); records=f.read(count*16)
            for i in range(count):
                no,fo,size,zsize=struct.unpack_from('<4I',records,i*16)
                if no>=len(names):continue
                end=names.find(b'\0',no)
                if end==-1:continue
                full=names[no:end].decode('cp932','replace')
                base=full.replace('\\','/').split('/')[-1]
                if base.lower() not in nameset:continue
                n=zsize or size
                if fo+n>sz:
                    errors.append('FSTS member out of bounds '+full);continue
                f.seek(pos+fo);payload=f.read(n)
                try:
                    decoded=patcher.decode_stored(payload,size,zsize)
                    dh=sha256(decoded)
                except Exception as e:
                    dh='DECODE_ERROR:'+str(e)[:120]
                seen.append(dict(bundle=r['name'],member=full,base=base,decoded_sha256=dh,
                                 stored_size=n,bundle_offset=r['file_off'],member_offset=fo))
                f.seek(pos+info_off)
    return seen,errors


def scan_boot(iso,out,label):
    names=('BOOT.BIN','EBOOT.BIN')
    rows=[]
    for file in names:
        e=isoentry(iso,'PSP_GAME/SYSDIR/'+file)
        if e['size']>40*1024*1024:raise RuntimeError('Unexpected huge '+file)
        with iso.open('rb') as f:f.seek(e['lba']*SECTOR); data=f.read(e['size'])
        for term in JP_TERMS:
            for enc in ('cp932','utf-16le'):
                try:needle=term.encode(enc)
                except UnicodeError:continue
                pos=0;hits=0
                while hits<30:
                    at=data.find(needle,pos)
                    if at<0:break
                    rows.append(dict(file=file,text=term,encoding=enc,offset=hex(at),
                                     context_hex=data[max(0,at-12):at+len(needle)+12].hex()))
                    hits+=1;pos=at+1
    write_tsv(out/f'{label}_boot_target_hits.tsv',rows,['file','text','encoding','offset','context_hex'])
    return rows


def main(root,out,source,baseline):
    out.mkdir(parents=True,exist_ok=True)
    if not source.exists():raise RuntimeError('Current compact ISO not found: '+str(source))
    if not baseline.exists():raise RuntimeError('Known-good SUB52J ISO not found: '+str(baseline))
    print('=== SUB52L RUNTIME SOURCE STATIC AUDIT ===',flush=True)
    print('No ISO writes / no PPSSPP.',flush=True)
    print('Current ISO:',source,flush=True)
    print('Baseline ISO:',baseline,flush=True)
    patcher=loadpatcher(root)
    curdat=isoentry(source,'PSP_GAME/USRDIR/naruto.dat')
    source_index,_=read_index(source,curdat,patcher)
    allfaces=sorted({r['name'] for r in source_index['primary'] if re.fullmatch(r'face_[A-Za-z0-9_]+\.ccs',r['name'],re.I)})
    targets=tuple(allfaces)+('eff3eye.ccs','gauge.ccs','mgselect.ccs','charsel1.ccs')
    print(f'Found {len(allfaces)} face CCS resources; comparing {len(targets)} total CCS resources',flush=True)
    cur=capture_resources(source,'current_FIX2',patcher,out,targets)
    base=capture_resources(baseline,'baseline_SUB52J',patcher,out,targets)
    result=[]
    for rec in cur['records']:
        key=(rec['resource'],rec['texture'])
        bas=base['payload'].get(key)
        curp=cur['payload'][key]
        if bas is None:continue
        cb=curp['rgba']; bb=bas['rgba']
        changed=sum(cb[i:i+4]!=bb[i:i+4] for i in range(0,len(cb),4))
        result.append(dict(resource=key[0],texture=key[1],width=rec['width'],height=rec['height'],
                           source_rgba_sha256=bas['png_rgba_sha256'],current_rgba_sha256=curp['png_rgba_sha256'],
                           source_payload_sha256=bas['indexed_payload_sha256'],current_payload_sha256=curp['indexed_payload_sha256'],
                           is_changed=(bas['png_rgba_sha256']!=curp['png_rgba_sha256']),
                           min_changed_rgba_pixels=changed))
    write_tsv(out/'texture_before_after.tsv',result,
              ['resource','texture','width','height','source_rgba_sha256','current_rgba_sha256',
               'source_payload_sha256','current_payload_sha256','is_changed','min_changed_rgba_pixels'])
    print('[3/5] FSTS duplicate scan',flush=True)
    dup,errors=scan_fsts_headers(source,cur['dat'],cur['index'],patcher,{x.lower() for x in targets})
    for d in dup:
        d['same_as_primary']=(d['decoded_sha256']==cur['decoded_sha256'][d['base']])
    write_tsv(out/'duplicate_fsts_members.tsv',dup,
              ['bundle','member','base','decoded_sha256','stored_size','bundle_offset','member_offset','same_as_primary'])
    print('[4/5] Embedded BOOT exact Japanese target scan',flush=True)
    boot=scan_boot(source,out,'current')
    print('[5/5] Summary',flush=True)
    focus=[r for r in result if r['texture'] in FOCUS_TEX]
    summary={
        'stage':'SUB52L_RUNTIME_SOURCE_STATIC_AUDIT',
        'source_iso':str(source),'source_iso_sha256':hash_file(source),
        'baseline_iso':str(baseline),'baseline_iso_sha256':hash_file(baseline),
        'source_size_bytes':source.stat().st_size,
        'source_below_4gib':source.stat().st_size<2**32,
        'resource_count':len(targets),
        'face_resources':len(allfaces),
        'texture_records':len(result),
        'focus_texture_checks':focus,
        'fsts_duplicate_members':len(dup),
        'fsts_scan_warnings':errors[:60],
        'boot_target_hits':len(boot),
        'note':'Texture changes prove resource data changed, not which screen renders it. Gameplay or renderer tracing required for definitive display linkage.',
        'iso_modified':False,'ppsspp_launched':False,
    }
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARY.txt').write_text(
        'SUB52L Read-only runtime source audit\n'+
        '\n'.join(f'{k}={v}' for k,v in summary.items() if not isinstance(v,(list,dict)))+'\n\n'+
        'FOCUS RESOURCES:\n'+'\n'.join(f'{r["resource"]}/{r["texture"]}: changed={r["is_changed"]}' for r in focus)+'\n',
        encoding='utf-8-sig')
    print((out/'SUMMARY.txt').read_text(encoding='utf-8-sig'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',default=r'D:\narutimate portable')
    p.add_argument('--source',default='')
    p.add_argument('--baseline',default='')
    a=p.parse_args()
    root=Path(a.root)
    try:
        main(root,root/OUT,Path(a.source) if a.source else root/SOURCE,
             Path(a.baseline) if a.baseline else root/BASE)
    except Exception:
        traceback.print_exc();sys.exit(1)
