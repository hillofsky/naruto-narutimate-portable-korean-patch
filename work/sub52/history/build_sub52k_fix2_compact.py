#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compact an ISO by preserving verified source prefix and reusing K's patched DAT/IDX.
Read-only inputs. No game automation. Standard-library Python.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,struct,sys,time,traceback

SECTOR=2048
LIMIT=1<<32
ROOT_DEFAULT=Path(r'D:\narutimate portable')
SRC_REL=Path(r'analysis\sub\sub52j_safe_atlas\Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso')
TEST_REL=Path(r'analysis\sub\sub52k_face_names\Naruto_KR_MOV06E_SUB52K_FaceNames.iso')
OUT_REL=Path(r'analysis\sub\sub52k_fix2_compact')
NAME='Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso'
KNOWN={
 'source_sha256':'2e6cb2e577ddeebe07453ec56f07f72422a6b3b20001987c253a5468658f5a05',
 'source_bytes':4282079232,
 'test_sha256':'e240529895e2abef3d239cdb9d70aa9d1c05a06a97e883921c9dde2a39e93fb3',
 'test_bytes':4759830528,
 'dat_test_sha256':'2e57c1640fb915c92d875acdbf74623252c0bb5b2ca65d22eba4750ce434f260',
 'idx_test_sha256':'995ae23d84c07f7d1c9ca32173fcb8834cddc1ba1677585dfecf6795d35a1dbb',
}
DAT='PSP_GAME/USRDIR/naruto.dat'
IDX='PSP_GAME/USRDIR/naruto.idx'

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):
            h.update(b)
    return h.hexdigest()

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if not s or not s.loader:
        raise RuntimeError('Cannot import '+str(path))
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def get_root_extent(iso):
    with Path(iso).open('rb') as f:
        f.seek(16*SECTOR)
        p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b'CD001':
        raise RuntimeError('Not ISO9660 primary descriptor')
    r=p[156:190]
    return int.from_bytes(r[2:6],'little'),int.from_bytes(r[10:14],'little')

def dirents(f,lba,size):
    f.seek(lba*SECTOR)
    data=f.read(size)
    entries=[];pos=0
    while pos<len(data):
        n=data[pos]
        if n==0:
            pos=(pos//SECTOR+1)*SECTOR
            continue
        r=data[pos:pos+n]
        if len(r)<34:
            raise RuntimeError('Short ISO9660 directory record')
        ident=r[33:33+r[32]]
        name='.' if ident==b'\x00' else ('..' if ident==b'\x01' else ident.decode('ascii','replace').split(';',1)[0])
        entries.append(dict(name=name,lba=int.from_bytes(r[2:6],'little'),
                            size=int.from_bytes(r[10:14],'little'),is_dir=bool(r[25]&2)))
        pos+=n
    return entries

def scan_live_extents(source, cut):
    root=get_root_extent(source)
    files=[];dirs=[];seen=set()
    with Path(source).open('rb') as f:
        def walk(path,lba,size,depth):
            if depth>15:raise RuntimeError('Excessive directory depth')
            key=(lba,size)
            if key in seen:return
            seen.add(key)
            dirs.append((path or '/',lba*SECTOR,lba*SECTOR+size))
            for e in dirents(f,lba,size):
                if e['name'] in ('.','..'):continue
                name=(path+'/'+e['name']).lstrip('/')
                a=e['lba']*SECTOR;b=a+e['size']
                if e['is_dir']:
                    walk(name,e['lba'],e['size'],depth+1)
                else:
                    files.append((name,a,b))
        walk('',*root,0)
    protected={DAT.casefold(),IDX.casefold()}
    beyond=[]
    for name,a,b in files:
        if b>cut and name.casefold() not in protected:
            beyond.append((name,a,b))
    for name,a,b in dirs:
        if b>cut:
            beyond.append((name,a,b))
    if beyond:
        raise RuntimeError('Unsafe compaction: live source file/dir after DAT start: '+repr(beyond[:12]))
    return files,dirs

def extent_from_record(f,rec):
    """Read authoritative ISO9660 directory-record fields from disk.

    Stage15 find_path() guarantees record_offset, but its returned dictionary
    does not expose 'lba' and 'size'. Both PVD and Joliet directory entries
    encode the file LBA and length at bytes +2/+10, respectively.
    """
    if not isinstance(rec,dict) or 'record_offset' not in rec:
        raise RuntimeError('stage15.find_path missing record_offset: '+repr(rec))
    offset=rec['record_offset']
    if not isinstance(offset,int) or offset<0:
        raise RuntimeError('Invalid ISO record offset: '+repr(offset))
    f.seek(offset)
    head=f.read(34)
    if len(head)<34 or head[0]<34:
        raise RuntimeError('ISO9660 directory record truncated at '+str(offset))
    le_lba=int.from_bytes(head[2:6],'little')
    be_lba=int.from_bytes(head[6:10],'big')
    le_size=int.from_bytes(head[10:14],'little')
    be_size=int.from_bytes(head[14:18],'big')
    if le_lba!=be_lba or le_size!=be_size:
        raise RuntimeError('ISO directory endian mismatch at '+str(offset))
    if le_size==0:
        raise RuntimeError('Zero-length ISO file record at '+str(offset))
    end=le_lba*SECTOR+le_size
    f.seek(0,os.SEEK_END)
    if end>f.tell():
        raise RuntimeError('File extent outside ISO: '+repr((le_lba,le_size,end)))
    return (le_lba,le_size)


def get_extent(f,mod15,vds,path):
    found=[]
    for vd in vds:
        if vd['type'] not in (1,2):
            continue
        d=mod15.find_path(f,vd,path.split('/'))
        if d is not None:
            found.append(d)
    if not found:
        raise RuntimeError('Missing file in ISO: '+path)
    loc={extent_from_record(f,x) for x in found}
    if len(loc)!=1:
        raise RuntimeError('Primary/Joliet extents disagree for '+path+': '+repr(loc))
    return found,next(iter(loc))


def stream_region(src,start,size,dst,chunk=8*1024*1024):
    h=hashlib.sha256()
    src.seek(start)
    rem=size
    while rem:
        b=src.read(min(rem,chunk))
        if not b:raise RuntimeError('Unexpected EOF streaming segment')
        dst.write(b);h.update(b);rem-=len(b)
    return h.hexdigest()

def align_stream(f):
    f.seek(0,os.SEEK_END)
    off=f.tell()
    rem=off%SECTOR
    if rem:f.write(bytes(SECTOR-rem))
    return f.tell()

def hash_iso_segment(path,lba,size):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        f.seek(lba*SECTOR);remain=size
        while remain:
            b=f.read(min(remain,8*1024*1024))
            if not b:raise RuntimeError('Truncated output')
            h.update(b);remain-=len(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=str(ROOT_DEFAULT))
    args=ap.parse_args()
    root=Path(args.root)
    source=root/SRC_REL;test=root/TEST_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    final=out/NAME
    part=out/(NAME+'.partial')
    print('=== SUB52K FIX2 COMPACT: READ INPUTS, REPACK OUTPUT ===',flush=True)
    print('Source:',source,flush=True)
    print('Failed test ISO:',test,flush=True)
    print('Output:',final,flush=True)
    if not source.is_file() or not test.is_file():
        raise RuntimeError('Source/test ISO missing; cannot safely proceed')
    for key,p in [('source',source),('test',test)]:
        got=p.stat().st_size
        if got!=KNOWN[key+'_bytes']:
            raise RuntimeError(f'{key} length mismatch: {got} != {KNOWN[key+"_bytes"]}')

    m15=mod('sub52k_fix1_stage15',root/r'analysis\stage15\stage15_iso_patcher.py')
    print('[1/7] Verify input SHA256 against previous diagnostic',flush=True)
    for key,p in [('source',source),('test',test)]:
        actual=sha256_file(p)
        if actual!=KNOWN[key+'_sha256']:
            raise RuntimeError(f'{key} SHA256 mismatch, refusing rebuild')
        print(f'  {key}: {actual}',flush=True)

    print('[2/7] Validate core extents and every live source file before truncation',flush=True)
    with source.open('rb') as f:
        vs=m15.read_volume_descriptors(f)
        sd,source_dat=get_extent(f,m15,vs,DAT)
        si,source_idx=get_extent(f,m15,vs,IDX)
    with test.open('rb') as f:
        vt=m15.read_volume_descriptors(f)
        td,test_dat=get_extent(f,m15,vt,DAT)
        ti,test_idx=get_extent(f,m15,vt,IDX)
    cut=source_dat[0]*SECTOR
    files,dirs=scan_live_extents(source,cut)
    if source_idx[0]*SECTOR<cut:
        raise RuntimeError('Source IDX before intended truncation; invalid layout')
    if source_dat[0]*SECTOR+source_dat[1]>source_idx[0]*SECTOR:
        raise RuntimeError('Source DAT overlaps source IDX; not compactable by this strategy')
    if test_dat[0]*SECTOR+test_dat[1]>test_idx[0]*SECTOR:
        raise RuntimeError('Test DAT overlaps test IDX')
    print('  protected live files:',len(files),'dirs:',len(dirs),flush=True)
    print('  source DAT: LBA',source_dat[0],'size',source_dat[1],flush=True)
    print('  test DAT: LBA',test_dat[0],'size',test_dat[1],flush=True)

    proposed_idx_lba=(cut+test_dat[1]+SECTOR-1)//SECTOR
    predicted=(proposed_idx_lba*SECTOR+test_idx[1]+SECTOR-1)//SECTOR*SECTOR
    if predicted>=LIMIT:
        raise RuntimeError(f'Compacted ISO still exceeds 4GiB: {predicted}')
    print('  predicted compact output bytes:',predicted,'under 4GiB by:',LIMIT-predicted,flush=True)
    space=shutil.disk_usage(out).free
    if space<predicted+256*1024*1024:
        raise RuntimeError(f'Insufficient free disk space: {space} available, need at least {predicted+256*1024*1024}')

    print('[3/7] Copy unmodified source prefix; stream translated DAT/IDX into compact tail',flush=True)
    if part.exists():part.unlink()
    try:
        with source.open('rb') as sf,test.open('rb') as tf,part.open('wb+') as pf:
            prefix_hash=stream_region(sf,0,cut,pf)
            pf.flush()
            if pf.tell()!=cut:raise RuntimeError('Prefix copy length mismatch')
            newdat_lba=pf.tell()//SECTOR
            dat_hash=stream_region(tf,test_dat[0]*SECTOR,test_dat[1],pf)
            if dat_hash!=KNOWN['dat_test_sha256']:
                raise RuntimeError('Translated DAT SHA mismatch; refusing output')
            align_stream(pf)
            newidx_lba=pf.tell()//SECTOR
            idx_hash=stream_region(tf,test_idx[0]*SECTOR,test_idx[1],pf)
            if idx_hash!=KNOWN['idx_test_sha256']:
                raise RuntimeError('Translated IDX SHA mismatch; refusing output')
            align_stream(pf)
            actualsize=pf.tell()
            if actualsize!=predicted or actualsize>=LIMIT:
                raise RuntimeError('Unexpected compact file size')

            print('[4/7] Update ISO9660 PVD/Joliet directory records + volume size',flush=True)
            vds=m15.read_volume_descriptors(pf)
            changes=((DAT,newdat_lba,test_dat[1]),(IDX,newidx_lba,test_idx[1]))
            for path,lba,size in changes:
                records,oldextent=get_extent(pf,m15,vds,path)
                if oldextent not in (source_dat,source_idx):
                    raise RuntimeError(f'Unexpected original extent for {path}: {oldextent}')
                for rec in records:
                    m15.patch_directory_record(pf,rec['record_offset'],lba,size)
            m15.update_volume_space(pf,vds,actualsize//SECTOR)
            pf.flush()
        print('[5/7] Verify compact ISO extents and core SHA256',flush=True)
        with part.open('rb') as f:
            vd=m15.read_volume_descriptors(f)
            _,verified_dat=get_extent(f,m15,vd,DAT)
            _,verified_idx=get_extent(f,m15,vd,IDX)
        if verified_dat!=(newdat_lba,test_dat[1]) or verified_idx!=(newidx_lba,test_idx[1]):
            raise RuntimeError('ISO directory verification failed')
        if hash_iso_segment(part,*verified_dat)!=KNOWN['dat_test_sha256']:
            raise RuntimeError('Output DAT SHA mismatch')
        if hash_iso_segment(part,*verified_idx)!=KNOWN['idx_test_sha256']:
            raise RuntimeError('Output IDX SHA mismatch')
        for p in ('PSP_GAME/SYSDIR/BOOT.BIN','PSP_GAME/SYSDIR/EBOOT.BIN'):
            with source.open('rb') as f:
                vv=m15.read_volume_descriptors(f)
                _,src_e=get_extent(f,m15,vv,p)
            with part.open('rb') as f:
                vv=m15.read_volume_descriptors(f)
                _,out_e=get_extent(f,m15,vv,p)
            if src_e!=out_e or hash_iso_segment(source,*src_e)!=hash_iso_segment(part,*out_e):
                raise RuntimeError(p+' not preserved')

        print('[6/7] Move verified output to final ISO',flush=True)
        os.replace(part,final)
        report={
            'stage':'SUB52K_FIX2_COMPACT',
            'source_sha256':KNOWN['source_sha256'],
            'translated_test_sha256':KNOWN['test_sha256'],
            'output_iso':str(final),
            'output_bytes':final.stat().st_size,
            'output_sha256':sha256_file(final),
            'under_4gib':final.stat().st_size<LIMIT,
            'under_4gib_margin_bytes':LIMIT-final.stat().st_size,
            'dat_sha256':dat_hash,
            'idx_sha256':idx_hash,
            'face_name_translation_resources':23,
            'face_name_translation_textures':46,
            'no_resource_changes_in_compaction':True,
            'boot_eboot_preserved':True,
            'source_prefix_bytes_copied':cut,
            'source_prefix_sha256_before_metadata_patch':prefix_hash,
            'source_live_entries_checked':len(files),
            'static_qa':'PASS',
            'runtime_qa':'PENDING',
        }
        (out/'SUB52K_FIX2_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'SUMMARY.txt').write_text('Naruto SUB52K FIX2 compact result\n\n'+'\n'.join(f'{k}={v}' for k,v in report.items())+'\n',encoding='utf-8-sig')
        print('[7/7] PASS: '+str(final),flush=True)
        print(json.dumps(report,ensure_ascii=False),flush=True)
    except Exception:
        # leave incomplete output only as a diagnostic, never as final ISO
        if part.exists():
            try:part.unlink()
            except OSError:pass
        raise

if __name__=='__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
