#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Naruto SUB52M, bounded BOOT/EBOOT C-string patch, compact ISO size preserved.

Never modifies the source. Only updates a previously verified single, fixed-length
C-string in BOOT/EBOOT; no index, CCS, FSTS or atlas modifications.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import shutil
import sys
import traceback
from pathlib import Path

SECTOR = 2048
ROOT_DEFAULT = Path(r'D:\narutimate portable')
SOURCE_REL = Path(r'analysis\sub\sub52k_fix2_compact\Naruto_KR_MOV06E_SUB52K_FIX2_Compact.iso')
SOURCE_SHA = 'a487c2e6deb3701ac2e529e84c4180a06980da32d14eadf91c1242a05df121af'
OUT_REL = Path(r'analysis\sub\sub52m_safe_boot_patch')
FINAL_NAME = 'Naruto_KR_MOV06E_SUB52M_SafeBoot.iso'
SOURCE_TEXT = '<iconCIRCLE>ボタンでゲーム開始！'
TARGET_TEXT = '<iconCIRCLE> 버튼으로 게임 시작!'
REWARD_TERMS = ['ナルＰポイント','ナルPポイント']


def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(4*1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def write_tsv(path,rows,fields):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def dir_entries(iso,lba,size):
    with Path(iso).open('rb') as f:
        f.seek(lba*SECTOR)
        data=f.read(size)
    if len(data)!=size: raise RuntimeError('Short ISO directory read')
    out=[]; pos=0
    while pos<len(data):
        n=data[pos]
        if n==0:
            pos=(pos//SECTOR+1)*SECTOR
            continue
        r=data[pos:pos+n]
        if len(r)<34: raise RuntimeError('Malformed ISO directory record')
        nb=r[33:33+r[32]]
        name='.' if nb==b'\0' else ('..' if nb==b'\1' else nb.decode('ascii','replace').split(';',1)[0])
        l_le=int.from_bytes(r[2:6],'little')
        l_be=int.from_bytes(r[6:10],'big')
        s_le=int.from_bytes(r[10:14],'little')
        s_be=int.from_bytes(r[14:18],'big')
        if l_le!=l_be or s_le!=s_be: raise RuntimeError('ISO extent endian mismatch: '+name)
        out.append(dict(name=name,lba=l_le,size=s_le,is_dir=bool(r[25]&2)))
        pos+=n
    return out


def iso_entry(iso, path):
    with Path(iso).open('rb') as f:
        f.seek(16*SECTOR); p=f.read(SECTOR)
    if len(p)!=SECTOR or p[0]!=1 or p[1:6]!=b'CD001':
        raise RuntimeError('ISO Primary Volume Descriptor invalid')
    root=p[156:190]
    cur=dict(lba=int.from_bytes(root[2:6],'little'),size=int.from_bytes(root[10:14],'little'),is_dir=True)
    for part in path.replace('\\','/').strip('/').split('/'):
        matches=[x for x in dir_entries(iso,cur['lba'],cur['size']) if x['name'].casefold()==part.casefold()]
        if len(matches)!=1: raise RuntimeError('Missing/ambiguous ISO path '+path)
        cur=matches[0]
    if cur['is_dir']: raise RuntimeError('Expected ISO file: '+path)
    if cur['lba']*SECTOR + cur['size']>Path(iso).stat().st_size:
        raise RuntimeError('ISO extent outside file: '+path)
    return cur


def hash_iso_segment(iso,e):
    h=hashlib.sha256()
    with Path(iso).open('rb') as f:
        f.seek(e['lba']*SECTOR)
        remaining=e['size']
        while remaining:
            chunk=f.read(min(4*1024*1024,remaining))
            if not chunk: raise RuntimeError('Unexpected ISO EOF')
            h.update(chunk);remaining-=len(chunk)
    return h.hexdigest()


def read_iso_segment(iso,e):
    with Path(iso).open('rb') as f:
        f.seek(e['lba']*SECTOR)
        buf=f.read(e['size'])
    if len(buf)!=e['size']: raise RuntimeError('Short ISO segment')
    return buf


def mapping(path):
    mp={}; used={}
    with Path(path).open('r',encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            ch=r['hangul']; code=bytes.fromhex(r['donor_sjis_hex'])
            if not ('가'<=ch<='힣') or len(code)!=2:
                raise RuntimeError('Invalid Hangul mapping row')
            if ch in mp and mp[ch]!=code:
                raise RuntimeError('Conflicting Hangul mapping for '+ch)
            mp[ch]=code
    return mp


def encode_ko(text,mp):
    b=bytearray()
    for ch in text:
        if ch in mp: b.extend(mp[ch])
        elif '가'<=ch<='힣': raise RuntimeError('Unmapped Hangul: '+ch)
        else: b.extend(ch.encode('cp932'))
    return bytes(b)


def inspect_cstring_windows(data,term):
    encoded=term.encode('cp932'); reports=[]; at=0
    while True:
        pos=data.find(encoded,at)
        if pos<0:break
        # Limited C-string context, never interpret other binary data as strings.
        lo=data.rfind(b'\0',max(0,pos-384),pos)
        hi=data.find(b'\0',pos,min(len(data),pos+384))
        lo=lo+1 if lo>=0 else max(0,pos-100)
        hi=hi if hi>=0 else min(len(data),pos+150)
        raw=data[lo:hi]
        reports.append(dict(target=term,offset_hex=f'0x{pos:X}',cstring_offset_hex=f'0x{lo:X}',
                            cstring_len=len(raw),text_cp932=raw.decode('cp932','replace'),raw_hex=raw.hex()))
        at=pos+len(encoded)
    return reports


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=str(ROOT_DEFAULT))
    ap.add_argument('--bundle',required=True)
    ap.add_argument('--only-dry-run',action='store_true')
    a=ap.parse_args()
    root=Path(a.root);bundle=Path(a.bundle)
    source=root/SOURCE_REL
    out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    final=out/FINAL_NAME
    report={"stage":"SUB52M_SAFE_BOOT_PATCH","status":"NOT_STARTED","source_iso":str(source),
            "target_iso":str(final),"source_sha256_expected":SOURCE_SHA,
            "modified_resources":["BOOT.BIN","EBOOT.BIN"],
            "untouched_resources":["naruto.dat","naruto.idx","all .ccs","all .pmf"],
            "translation":dict(source=SOURCE_TEXT,target=TARGET_TEXT)}
    try:
        print('[1/6] Verify SHA256 of known-good SUB52K FIX2 source...',flush=True)
        if not source.is_file():raise RuntimeError('Missing source ISO: '+str(source))
        digest=hash_file(source);report['source_sha256_actual']=digest
        if digest!=SOURCE_SHA:raise RuntimeError('Source ISO SHA256 mismatch; refusing to patch')
        if source.stat().st_size>=2**32:raise RuntimeError('Source ISO unexpectedly exceeds 4 GiB')

        print('[2/6] Resolve exact ISO9660 segments and encoding...',flush=True)
        mp=mapping(bundle/'combined_hangul_mapping_sub52d2.tsv')
        old=SOURCE_TEXT.encode('cp932')
        new=encode_ko(TARGET_TEXT,mp)
        if len(new)!=len(old):raise RuntimeError(f'Encoded length differs: old {len(old)}, new {len(new)}')
        if old==new:raise RuntimeError('No-op translation')
        ipaths={
            'BOOT.BIN':'PSP_GAME/SYSDIR/BOOT.BIN',
            'EBOOT.BIN':'PSP_GAME/SYSDIR/EBOOT.BIN',
            'naruto.dat':'PSP_GAME/USRDIR/naruto.dat',
            'naruto.idx':'PSP_GAME/USRDIR/naruto.idx',
        }
        extents={name:iso_entry(source,path) for name,path in ipaths.items()}
        patches=[]; rewards=[]
        for name in ('BOOT.BIN','EBOOT.BIN'):
            e=extents[name]; raw=read_iso_segment(source,e)
            needle=old+b'\0'; hits=[];at=0
            while True:
                pos=raw.find(needle,at)
                if pos<0:break
                hits.append(pos);at=pos+1
            if len(hits)!=1:raise RuntimeError(f'{name}: expected one exact Japanese C-string, found {len(hits)}')
            p=hits[0]; patches.append(dict(resource=name,relative_offset=p,absolute_offset=e['lba']*SECTOR+p,
                                            old_bytes=old,new_bytes=new,original_segment_sha=hashlib.sha256(raw).hexdigest()))
            for term in REWARD_TERMS:
                for rr in inspect_cstring_windows(raw,term):
                    rr['binary']=name;rewards.append(rr)
        if len({p['absolute_offset'] for p in patches})!=2:
            raise RuntimeError('BOOT/EBOOT point to the same file extent; manual review required')
        write_tsv(out/'reward_cstring_evidence.tsv',rewards,
                  ['binary','target','offset_hex','cstring_offset_hex','cstring_len','text_cp932','raw_hex'])
        write_tsv(out/'exact_boot_patch_plan.tsv',[
            {"binary":p['resource'],"relative_offset_hex":hex(p['relative_offset']),
             "absolute_offset_hex":hex(p['absolute_offset']),"old_bytes_hex":p['old_bytes'].hex(),
             "new_bytes_hex":p['new_bytes'].hex(),"same_encoded_size":True} for p in patches],
            ['binary','relative_offset_hex','absolute_offset_hex','old_bytes_hex','new_bytes_hex','same_encoded_size'])
        report['patch_count']=len(patches)
        report['reward_exact_occurrences']=len(rewards)
        report['encoded_length_bytes']=len(old)
        if a.only_dry_run:
            report['status']='DRY_RUN_VALIDATED'
            (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('DRY_RUN_VALIDATED',flush=True);return

        print('[3/6] Copy source to new ISO (never modify original)...',flush=True)
        if final.exists():final.unlink()
        shutil.copyfile(source,final)

        print('[4/6] Patch one verified, equal-byte-length C-string in BOOT and EBOOT...',flush=True)
        with final.open('r+b') as f:
            for p in patches:
                f.seek(p['absolute_offset'])
                if f.read(len(old)+1)!=old+b'\0':
                    raise RuntimeError('Patched ISO bytes mismatch before write: '+p['resource'])
                f.seek(p['absolute_offset']);f.write(new)
            f.flush()

        print('[5/6] Verify same ISO size, BOOT/EBOOT changes, DAT/IDX unchanged...',flush=True)
        if final.stat().st_size!=source.stat().st_size:
            raise RuntimeError('ISO size changed unexpectedly')
        for name in ('BOOT.BIN','EBOOT.BIN'):
            src_e=extents[name];final_e=iso_entry(final,ipaths[name])
            if src_e!=final_e:raise RuntimeError('ISO directory record changed: '+name)
            raw=read_iso_segment(final,final_e)
            p=next(p for p in patches if p['resource']==name)
            if raw[p['relative_offset']:p['relative_offset']+len(new)+1]!=new+b'\0':
                raise RuntimeError('Patched bytes not present in '+name)
            orig=read_iso_segment(source,src_e)
            if raw[:p['relative_offset']]!=orig[:p['relative_offset']] or raw[p['relative_offset']+len(new):]!=orig[p['relative_offset']+len(old):]:
                raise RuntimeError('Unexpected bytes changed in '+name)
            if raw.count(new+b'\0')<1:
                raise RuntimeError('Target C-string verification failed in '+name)
        preserved=[]
        for name in ('naruto.dat','naruto.idx'):
            orig_sha=hash_iso_segment(source,extents[name]);final_sha=hash_iso_segment(final,iso_entry(final,ipaths[name]))
            if orig_sha!=final_sha:raise RuntimeError(name+' changed unexpectedly')
            preserved.append(name)
        report['preserved_verified']=preserved
        report['final_iso_size_bytes']=final.stat().st_size
        report['final_iso_sha256']=hash_file(final)
        report['status']='STATIC_PASS_RUNTIME_UNVERIFIED'
        print('[6/6] Write reports...',flush=True)
        (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in report.items()),encoding='utf-8-sig')
        print('NEW_ISO='+str(final),flush=True)
        print('FINAL_SHA256='+report['final_iso_sha256'],flush=True)
        print('STATIC_PASS_RUNTIME_UNVERIFIED',flush=True)
    except Exception:
        report['status']='FAIL'
        report['failure']=traceback.format_exc()
        (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'FAILURE.txt').write_text(report['failure'],encoding='utf-8')
        # Never allow an incomplete output ISO to be mistaken for successful build.
        if final.exists():final.unlink()
        raise

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
