#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52T: patch positively identified gauge.ccs TEX_vs and TEX_xgauge5.

Compact ISO rebuild: never append a second 470-MB DAT behind the input ISO.
Stops if any source checks / targeted pixel bounds / safe layout checks fail.
"""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,os,shutil,struct,sys,traceback
from pathlib import Path

HERE=Path(__file__).resolve().parent
SRC_REL=Path(r'analysis\sub\sub52n_reward_safe_fix1\Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso')
SRC_SHA='00bd998359e64e5d3f2af28c4f0d5b0dac7db8b11a35b773ea8a4ee290d58663'
OUT_REL=Path(r'analysis\sub\sub52t_gauge_hud_compact')
NAME='Naruto_KR_MOV06E_SUB52T_GaugeHUD_Compact.iso'
DAT='PSP_GAME/USRDIR/naruto.dat'
IDX='PSP_GAME/USRDIR/naruto.idx'
BOOT='PSP_GAME/SYSDIR/BOOT.BIN'
EBOOT='PSP_GAME/SYSDIR/EBOOT.BIN'
SECTOR=2048
LIMIT=1<<32
TEXTURES={
 'TEX_xgauge5':{
    'raw_sha256':'214eb0cffa31271849bab2944af30b41984f1c4eb1fde08cd054579902442d90',
    'assets':'gauge__TEX_xgauge5__KO.png',
    'rects':[(147,55,191,71),(98,91,157,107)],
    'translations':['ヒナタ → 히나타','シカマル → 시카마루'],
 },
 'TEX_vs':{
    'raw_sha256':'12766b638c0e4e2ead4f5bb2b22effcab6bae75fbc655441df9047720ad198f3',
    'assets':'gauge__TEX_vs__KO.png',
    'rects':[(0,100,64,132)],
    'translations':['勝者 → 승자'],
 }
}

def mod(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if not spec or not spec.loader:raise RuntimeError('Cannot import '+str(path))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj


def select_source(root,explicit):
    p=Path(explicit) if explicit else root/SRC_REL
    if not p.is_file():raise RuntimeError('Missing input ISO: '+str(p))
    got=k.iso.sha256_file(p)
    if got!=SRC_SHA:raise RuntimeError('Source SHA256 mismatch; refusing to alter unknown source: '+got)
    return p


def texture_patch_rects(original,name,cfg,asset_path):
    b=bytearray(original)
    info=k.ccs.find_texture(b,name)
    o=info['offset']+36
    raw_old=bytes(b[o:o+info['data_len']])
    old_sha=hashlib.sha256(raw_old).hexdigest()
    if old_sha!=cfg['raw_sha256']:
        raise RuntimeError(f'{name}: source indexed texture differs from verified baseline: {old_sha}')
    w,h,rgba=k.ccs.read_png_rgba(asset_path)
    if (w,h)!=(info['width'],info['height']):raise RuntimeError(name+': image dimensions mismatch')
    pal=k.ccs.find_palette(b,info['palette'])
    rows=k.ccs.decode_indices(b,info)
    rebuilt=[r[:] for r in rows]
    used={};changed=0
    for x0,y0,x1,y1 in cfg['rects']:
        if min(x0,y0)<0 or x1>w or y1>h or x0>=x1 or y0>=y1:
            raise RuntimeError(name+': invalid rect')
        for y in range(y0,y1):
            for x in range(x0,x1):
                idx=k.ccs.nearest_index(rgba[y][x],pal,used)
                if idx!=rebuilt[y][x]:
                    changed+=1
                    rebuilt[y][x]=idx
    if changed<10:raise RuntimeError(name+': no meaningful pixel change')
    new_raw=k.ccs.encode_indices(rebuilt,info)
    b[o:o+len(new_raw)]=new_raw
    # Check all other pixel indices and all non-texture bytes remain byte-identical.
    chk=k.ccs.decode_indices(b,info)
    for y in range(h):
        for x in range(w):
            allow=any(x0<=x<x1 and y0<=y<y1 for x0,y0,x1,y1 in cfg['rects'])
            if not allow and chk[y][x]!=rows[y][x]:
                raise RuntimeError(f'Forbidden atlas pixel change: {name} ({x},{y})')
    byte_only=bytearray(original)
    byte_only[o:o+len(new_raw)]=new_raw
    if bytes(byte_only)!=bytes(b):raise RuntimeError(name+': unrelated CCS data changed')
    return bytes(b),dict(texture=name,rects=str(cfg['rects']),changed_pixels=changed,
                         translations='; '.join(cfg['translations']),
                         src_payload_sha256=old_sha,new_payload_sha256=hashlib.sha256(new_raw).hexdigest())


def build_dat(root,source,out,work):
    dat=work/'naruto.dat';idx=work/'naruto.idx'
    print('[2/8] Extract DAT/IDX from verified current ISO',flush=True)
    k.ccs.extract(source,DAT,dat);k.ccs.extract(source,IDX,idx)
    p14=mod('sub52t_p14',root/r'analysis\stage14\naruto_patcher.py')
    old_idx=p14.parse_pidx(p14.read_embedded_index(dat),'before')
    old=k.ccs.decode_primary(dat,old_idx,'gauge.ccs',p14)
    new=old;rows=[]
    print('[3/8] Patch two confirmed gauge CCS atlases; verify changed pixels only in selected rectangles',flush=True)
    for name,cfg in TEXTURES.items():
        new,row=texture_patch_rects(new,name,cfg,HERE/'assets'/cfg['assets'])
        rows.append(row)
        print('   ',name,row['changed_pixels'],'changed pixels',flush=True)
    k.ccs.write_tsv(out/'sub52t_texture_report.tsv',rows,
       ['texture','rects','translations','changed_pixels','src_payload_sha256','new_payload_sha256'])
    if new==old:raise RuntimeError('gauge.ccs decoded bytes unchanged')

    replacement={'gauge.ccs':dict(new_decoded=new,original_sha256=hashlib.sha256(old).hexdigest())}
    embedded=bytearray(p14.read_embedded_index(dat));external=bytearray(idx.read_bytes())
    ei=p14.parse_pidx(embedded,'embedded');xi=p14.parse_pidx(external,'external')
    print('[4/8] Rebuild gauge.ccs primary + FSTS copies with strict round-trip check',flush=True)
    encoded=p14.encode_3_0(new)
    if p14.decode_3x(encoded)!=new:raise RuntimeError('Compressed gauge CCS roundtrip mismatch')
    with dat.open('ab') as f:
        off=p14.align_up(f.tell())
        if off>f.tell():f.write(bytes(off-f.tell()))
        f.write(encoded)
    for index_blob,parsed in ((embedded,ei),(external,xi)):
        item=next(q for q in parsed['primary'] if q['name']=='gauge.ccs')
        struct.pack_into('<III',index_blob,item['record_off']+12,off,len(new),len(encoded))
    fsts=[]
    with dat.open('r+b') as f:
        for r in ei['offset2_rows']:
            f.seek(r['file_off']);bundle=f.read(r['file_size'])
            rebuilt,changes=p14.rebuild_fsts(bundle,r['name'],replacement)
            if not changes:continue
            f.seek(0,os.SEEK_END)
            loc=p14.align_up(f.tell())
            if loc>f.tell():f.write(bytes(loc-f.tell()))
            f.write(rebuilt)
            for index_blob,parsed in ((embedded,ei),(external,xi)):
                t=next(q for q in parsed['offset2_rows'] if q['index']==r['index'])
                struct.pack_into('<II',index_blob,t['record_abs']+8,loc,len(rebuilt))
            fsts.append((r['name'],str(changes)))
        f.seek(0);f.write(embedded)
    idx.write_bytes(external)
    final_idx=p14.parse_pidx(p14.read_embedded_index(dat),'after')
    decoded=k.ccs.decode_primary(dat,final_idx,'gauge.ccs',p14)
    if decoded!=new:raise RuntimeError('gauge CCS resource verification mismatch')
    k.ccs.write_tsv(out/'sub52t_fsts_report.tsv',
       [dict(bundle=b,changes=c) for b,c in fsts],['bundle','changes'])
    return dat,idx,rows,fsts


def build_compact(root,source,dat,idx,out):
    p15=mod('sub52t_p15',root/r'analysis\stage15\stage15_iso_patcher.py')
    helper=k.iso
    with source.open('rb') as f:
        vds=p15.read_volume_descriptors(f)
        drec,dat_extent=helper.get_extent(f,p15,vds,DAT)
        irec,idx_extent=helper.get_extent(f,p15,vds,IDX)
    cut=dat_extent[0]*SECTOR
    protected_files,protected_dirs=helper.scan_live_extents(source,cut)
    if idx_extent[0]*SECTOR<cut or cut+dat_extent[1]>idx_extent[0]*SECTOR:
        raise RuntimeError('Input DAT/IDX placement is not compactable')
    idxstart=((cut+dat.stat().st_size+SECTOR-1)//SECTOR)*SECTOR
    predicted=((idxstart+idx.stat().st_size+SECTOR-1)//SECTOR)*SECTOR
    print('[5/8] Predict compact output / check disk space',flush=True)
    print('  input DAT offset',cut,'input DAT size',dat_extent[1],flush=True)
    print('  compact bytes',predicted,'under 4GiB by',LIMIT-predicted,flush=True)
    if predicted>=LIMIT:raise RuntimeError('Result exceeds 4GiB; do not boot this ISO')
    space=shutil.disk_usage(out).free
    # source input and temporary DAT remain safely on disk; do not delete normal baselines
    if space<predicted+128*1024*1024:
        raise RuntimeError(f'Insufficient free disk: {space} available, {predicted+128*1024*1024} required')
    part=out/(NAME+'.partial')
    if part.exists():part.unlink()  # only stale partial from this exact stage
    print('[6/8] Write compact ISO prefix + rebuilt DAT/IDX',flush=True)
    with source.open('rb') as sf,dat.open('rb') as df,idx.open('rb') as xf,part.open('wb+') as pf:
        helper.stream_region(sf,0,cut,pf)
        new_dat_lba=pf.tell()//SECTOR
        dat_hash=helper.stream_region(df,0,dat.stat().st_size,pf)
        helper.align_stream(pf)
        new_idx_lba=pf.tell()//SECTOR
        idx_hash=helper.stream_region(xf,0,idx.stat().st_size,pf)
        helper.align_stream(pf)
        if pf.tell()!=predicted:raise RuntimeError('Compact size prediction mismatch')
        vds=p15.read_volume_descriptors(pf)
        for path,lba,size in ((DAT,new_dat_lba,dat.stat().st_size),(IDX,new_idx_lba,idx.stat().st_size)):
            records,extent=helper.get_extent(pf,p15,vds,path)
            if extent!=((dat_extent if path==DAT else idx_extent)):
                raise RuntimeError('Unexpected current ISO directory entry')
            for record in records:p15.patch_directory_record(pf,record['record_offset'],lba,size)
        p15.update_volume_space(pf,vds,predicted//SECTOR)
        pf.flush()

    print('[7/8] Verify DAT/IDX hashes, PVD/Joliet, BOOT/EBOOT and movie extents',flush=True)
    with part.open('rb') as f:
        vds=p15.read_volume_descriptors(f)
        _,new_dat=helper.get_extent(f,p15,vds,DAT)
        _,new_idx=helper.get_extent(f,p15,vds,IDX)
    if new_dat!=(new_dat_lba,dat.stat().st_size) or new_idx!=(new_idx_lba,idx.stat().st_size):
        raise RuntimeError('Updated ISO extents mismatch')
    if helper.hash_iso_segment(part,*new_dat)!=dat_hash or helper.hash_iso_segment(part,*new_idx)!=idx_hash:
        raise RuntimeError('DAT/IDX hash mismatch')
    for path in (BOOT,EBOOT):
        with source.open('rb') as f:
            vv=p15.read_volume_descriptors(f);_,old_e=helper.get_extent(f,p15,vv,path)
        with part.open('rb') as f:
            vv=p15.read_volume_descriptors(f);_,new_e=helper.get_extent(f,p15,vv,path)
        if old_e!=new_e or helper.hash_iso_segment(source,*old_e)!=helper.hash_iso_segment(part,*new_e):
            raise RuntimeError(path+' changed unexpectedly')
    # Every non-DAT/IDX live file is inside the copied source prefix (checked above),
    # only directory metadata and volume size changed.
    os.replace(part,out/NAME)
    return dict(final_iso=str(out/NAME),final_size=predicted,
                final_sha256=helper.sha256_file(out/NAME),under_4gib_margin=LIMIT-predicted,
                dat_hash=dat_hash,idx_hash=idx_hash,
                protected_files=len(protected_files),protected_dirs=len(protected_dirs))


def main():
    a=argparse.ArgumentParser();a.add_argument('--root',default=r'PROJECT_ROOT');a.add_argument('--source',default='')
    args=a.parse_args();root=Path(args.root)
    out=root/OUT_REL;out.mkdir(parents=True,exist_ok=True)
    work=out/'_work';work.mkdir(exist_ok=True)
    source=select_source(root,args.source)
    print('=== SUB52T VERIFIED GAUGE HUD PATCH ===',flush=True)
    print('[1/8] Source exact SHA256 PASS:',k.iso.sha256_file(source),flush=True)
    print('  source',source,flush=True)
    try:
        dat,idx,rows,fsts=build_dat(root,source,out,work)
        info=build_compact(root,source,dat,idx,out)
        report=dict(stage='SUB52T_GAUGE_HUD_COMPACT',source_iso=str(source),
                    source_sha256=SRC_SHA,resources_changed=1,textures_changed=len(rows),
                    only_verified_atlas_rectangles=True, fsts_rebuilt=len(fsts),
                    previously_verified_gameplay='UNCHANGED_UNTIL_RUNTIME_QA',
                    runtime_qa='PENDING',static_qa='PASS',**info)
        (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (out/'SUMMARY.txt').write_text('SUB52T gauge HUD patch\n'+'\n'.join(f'{t}={v}' for t,v in report.items())+'\n',encoding='utf-8-sig')
        print('[8/8] PASS',json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        # Large intermediate archives are regenerable; free their space even after failure.
        shutil.rmtree(work,ignore_errors=True)
        part=out/(NAME+'.partial')
        if part.exists():part.unlink()

if __name__=='__main__':
    try:
        k=type('K',(),{})()
        k.iso=mod('sub52t_isohelpers',HERE/'sub52k_fix2_iso_helpers.py')
        k.ccs=mod('sub52t_ccshelpers',HERE/'sub52g_patch_helpers.py')
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
