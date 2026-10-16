#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52O read-only current-ISO audit. No direct game/PPSSPP modification."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, struct, sys, traceback
from pathlib import Path
import sub52l_core as core

DEFAULT_SOURCE = Path(r'analysis\sub\sub52n_reward_safe_fix1\Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso')
SOURCE_SHA = '00bd998359e64e5d3f2af28c4f0d5b0dac7db8b11a35b773ea8a4ee290d58663'
JP_TERMS = (
    '勝者', '勝利', '敗者', '勝敗', 'シカマル', '奈良シカマル', 'ヒナタ', '日向ヒナタ',
    'サクラ', 'ナルト', '選択', 'キャラクター選択', 'ナルＰポイント',
    'ボタンでゲーム', '試合終了', '対戦', '決定', 'タイトルに戻る',
)
FOCUS_FILES = (
    'charsel1.ccs', 'gauge.ccs', 'eff3eye.ccs', 'mgselect.ccs',
    'face_sik.ccs', 'face_hnt.ccs', '1sskbod1.ccs', '1hntbod1.ccs',
    'mugen.ccs', 'mgn_skill.ccs',
)
RELEVANT_TEX = re.compile(r'n_[a-z0-9]+_[ls]$|winner|name|hud|char|sel|mode|result|title|hanyou|white|red|text|txt|sik|hnt|mg_', re.I)
ALWAYS_TEX = ('TEX_xwinner','TEX_n_sik_s','TEX_n_hnt_s','TEX_n_sik_l','TEX_n_hnt_l','TEX_sel')


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as fp:
        for chunk in iter(lambda:fp.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def wtsv(path,rows,fields):
    with path.open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        w.writeheader();w.writerows(rows)


def exact_hits(b, name, group, cap=200):
    rows=[]
    for term in JP_TERMS:
        for enc in ('cp932','utf-16le','utf-16be'):
            try:needle=term.encode(enc)
            except UnicodeError:continue
            pos=0;found=0
            while found<12 and len(rows)<cap:
                at=b.find(needle,pos)
                if at<0:break
                chunk=b[max(0,at-28):at+len(needle)+56]
                rows.append(dict(source=name,kind=group,term=term,encoding=enc,
                                 offset=hex(at),source_bytes=len(b),context_hex=chunk.hex(),
                                 context_cp932=chunk.decode('cp932','replace').replace('\r','\\r').replace('\n','\\n'),
                                 caution='May be custom encoded Korean' if re.match(r'event\d+\.tbl',name,re.I) else 'Unverified resource context'))
                found+=1;pos=at+len(needle)
    return rows


def quick_tex_spans(data):
    """Equivalent structural CCS texture enumeration using fast bytes.find instead of millions of Python iterations."""
    names=core.names_ccs(data)
    magic=b'\x00\x03\xcc\xcc'
    rows=[];pos=0
    while True:
        at=data.find(magic,pos)
        if at<0: break
        pos=at+4
        if at%4 or at+36>len(data):continue
        idx=struct.unpack_from('<I',data,at+8)[0]
        typ=data[at+21];ew,eh=data[at+24:at+26]
        if idx>=len(names) or typ not in (0x13,0x14) or ew>12 or eh>12:continue
        w,h=1<<ew,1<<eh
        dl=w*h if typ==0x13 else w*h//2
        if at+36+dl>len(data):continue
        rows.append(dict(name=names[idx],offset=at,width=w,height=h,typ=typ,
                         palette=struct.unpack_from('<I',data,at+12)[0],size=dl))
    return rows


def select_priority(name,t):
    s=t['name'];w,h=t['width'],t['height']
    if name.startswith('face_') and (s.endswith('_s') or s.endswith('_l')):return 0
    if name in FOCUS_FILES and (s in ALWAYS_TEX or re.search(r'winner|name|txt|text|hanyou|sel',s,re.I)):return 0
    if name in FOCUS_FILES and RELEVANT_TEX.search(s) and w*h<=256*256:return 1
    if RELEVANT_TEX.search(s) and w*h<=256*256:return 2
    return 3


def audit(source,root,out,max_tex,max_resource_mb):
    out.mkdir(parents=True,exist_ok=True)
    print('== SUB52O COMPLETE STATIC SOURCE AUDIT ==',flush=True)
    print('ISO: '+str(source),flush=True)
    print('READ ONLY. No ISO copied or changed.',flush=True)
    if not source.is_file():raise RuntimeError('Source ISO missing: '+str(source))
    h=sha(source)
    if h.lower()!=SOURCE_SHA:
        raise RuntimeError('Source ISO SHA256 does not match verified SUB52N FIX2: '+h)
    if source.stat().st_size>=2**32:raise RuntimeError('Source ISO unexpectedly >=4GiB')
    patcher=core.loadpatcher(root)
    dat=core.isoentry(source,'PSP_GAME/USRDIR/naruto.dat')
    idx,_=core.read_index(source,dat,patcher)
    core.isoentry(source,'PSP_GAME/USRDIR/naruto.idx')
    print('Primary resources:',len(idx['primary']),flush=True)
    hits=[];inventory=[];candidates=[];warnings=[];resource_totals={}
    tex_by_priority={0:[],1:[],2:[]}
    maxsz=max_resource_mb*1024*1024
    # Open source once for streaming resource extraction through the ISO extent.
    for i,r in enumerate(idx['primary']):
        name=r['name'];size=r['size'];zsize=r['zsize']
        if size>maxsz:
            warnings.append('SKIPPED_LARGE: '+name+' '+str(size))
            continue
        if not (name.lower().endswith(('.tbl','.ccs','.bin','.txt','.dat','.msg'))):continue
        try:
            data, rr=core.primary_resource(source,dat,idx,name,patcher)
        except Exception as e:
            warnings.append('DECODE_FAIL: '+name+' '+repr(e))
            continue
        resource_totals[name]=len(data)
        if name.lower().endswith('.tbl') or re.search(r'option|result|battle|win|ui|menu|message|select|\bface',name,re.I):
            hits.extend(exact_hits(data,name,'PRIMARY'))
        if not name.lower().endswith('.ccs'):continue
        try:tts=quick_tex_spans(data)
        except Exception as e:
            warnings.append('CCS_TEX_PARSE_FAIL: '+name+' '+repr(e))
            continue
        decoded_sha=hashlib.sha256(data).hexdigest()
        for t in tts:
            p=select_priority(name,t)
            row=dict(resource_index=i,resource=name,texture=t['name'],width=t['width'],height=t['height'],type=hex(t['typ']),
                     palette=t['palette'],texture_offset=hex(t['offset']),priority=p,decoded_resource_sha256=decoded_sha)
            inventory.append(row)
            if p<=2:tex_by_priority[p].append((name,t,row))
        if i%100==0:print(f'  resources processed: {i}/{len(idx["primary"])}',flush=True)
    for name in ('BOOT.BIN','EBOOT.BIN'):
        e=core.isoentry(source,'PSP_GAME/SYSDIR/'+name)
        if e['size']>40*1024*1024:raise RuntimeError('Unexpected huge BOOT file')
        with source.open('rb') as fp:
            fp.seek(e['lba']*core.SECTOR)
            b=fp.read(e['size'])
        hits.extend(exact_hits(b,name,'BOOT'))
    wtsv(out/'primary_resource_inventory.tsv',[dict(resource=k,decoded_bytes=v) for k,v in resource_totals.items()],['resource','decoded_bytes'])
    wtsv(out/'exact_japanese_hits.tsv',hits,['source','kind','term','encoding','offset','source_bytes','context_hex','context_cp932','caution'])
    wtsv(out/'texture_inventory.tsv',inventory,['resource_index','resource','texture','width','height','type','palette','texture_offset','priority','decoded_resource_sha256'])
    print('Texture inventory:',len(inventory),'Japanese exact candidates:',len(hits),flush=True)
    selected=[];used=set()
    # Avoid 200 redundant copies of the same text; prefer priority targets.
    for p in (0,1,2):
        for name,t,row in tex_by_priority[p]:
            if len(selected)>=max_tex:break
            key=(name,t['name'])
            if key in used or t['width']*t['height']>512*256:continue
            used.add(key)
            selected.append((name,t,row))
    previews=out/'focus_textures';previews.mkdir(exist_ok=True)
    for old in previews.glob('*.png'):old.unlink()
    texrows=[]
    last_name=None;cached_decoded=None
    for ix,(name,t,row) in enumerate(selected):
        try:
            if name!=last_name:
                cached_decoded,_=core.primary_resource(source,dat,idx,name,patcher)
                last_name=name
            rgba,payload=core.decode_tex(cached_decoded,t)
            fn=f'{ix:03d}__{re.sub(r"[^A-Za-z0-9._-]","_",name)}__{re.sub(r"[^A-Za-z0-9._-]","_",t["name"])}.png'
            core.save_png(previews/fn,t['width'],t['height'],rgba)
            texrows.append(dict(resource=name,texture=t['name'],width=t['width'],height=t['height'],file='focus_textures/'+fn,
                                indexed_sha256=hashlib.sha256(payload).hexdigest(),rgba_sha256=hashlib.sha256(rgba).hexdigest()))
        except Exception as e:
            warnings.append('TEXTURE_DECODE_FAIL: '+name+'/'+t['name']+' '+repr(e))
    wtsv(out/'focus_texture_inventory.tsv',texrows,['resource','texture','width','height','file','indexed_sha256','rgba_sha256'])
    (out/'warnings.txt').write_text('\n'.join(warnings),encoding='utf-8-sig')
    report=dict(stage='SUB52O_UNIFIED_AUDIT',source_iso=str(source),source_sha256=h,
                iso_size_bytes=source.stat().st_size,resource_total=len(idx['primary']),resource_scanned=len(resource_totals),
                texture_total=len(inventory),extracted_focus_textures=len(texrows),
                japanese_exact_hits=len(hits),scan_warnings=len(warnings),
                runtime_symptoms={
                   'winner_label':'Japanese in runtime, known TEX_xwinner is already Korean',
                   'battle_hud_names':'Japanese in runtime, known face_* small textures already Korean',
                   'character_select':'name text overlaps character on screen',
                   'reward_message':'SUB52N passed user visual QA',
                },
                interpretation='Static candidates only: live rendering source not yet confirmed',
                iso_modified=False,ppsspp_controlled=False)
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in report.items()),encoding='utf-8-sig')
    print(json.dumps(report,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default=r'PROJECT_ROOT')
    p.add_argument('--source',default='')
    p.add_argument('--out',default='')
    p.add_argument('--max-textures',type=int,default=165)
    p.add_argument('--max-resource-mb',type=int,default=80)
    a=p.parse_args()
    root=Path(a.root)
    source=Path(a.source) if a.source else root/DEFAULT_SOURCE
    out=Path(a.out) if a.out else root/r'analysis\sub\sub52o_unified_audit'
    audit(source,root,out,max_tex=a.max_textures,max_resource_mb=a.max_resource_mb)

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
