#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52N: exact fixed-offset/fixed-byte-length Naruto reward C-string patch.

Read-only source, no CCS/IDX/DAT/PMF modifications. Source is runtime-proven SUB52M.
Uses evidence extracted from that exact ISO in SUB52M diagnostics.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, shutil, sys, traceback
from pathlib import Path
import sub52m_iso_helpers as u

ROOT_DEFAULT=Path(r'D:\narutimate portable')
SOURCE_REL=Path(r'analysis\sub\sub52m_safe_boot_patch\Naruto_KR_MOV06E_SUB52M_SafeBoot.iso')
SOURCE_SHA='13a742002f89f9b19c5f6196079b3086b1c68a10c9cec537366e7fcffc9ecdbc'
OUT_REL=Path(r'analysis\sub\sub52n_reward_safe')
FINAL_NAME='Naruto_KR_MOV06E_SUB52N_RewardSafe.iso'

# SUB52M evidence, exact C-string offsets within each BOOT/EBOOT binary.
REWARDS=[
    dict(id='SINGLE_PLAYER',offset=0x3039D0,
         lines=[
           ('ナルＰポイントを<BLUE>%dＰ<BLACK>入手しました。',
            '나루P 포인트를<BLUE>%dP<BLACK> 획득했습니다.'),
           ('\u3000'*20+'<iconCIRCLE>', '\u3000'*20+'<iconCIRCLE>'),
         ]),
    dict(id='TWO_PLAYERS',offset=0x303A38,
         lines=[
           ('<RED>１Ｐ<BLACK>はナルＰポイントを<BLUE>%dＰ<BLACK>入手しました。',
            '<RED>1P<BLACK>는 나루P 포인트를<BLUE>%dP<BLACK> 획득했습니다.'),
           ('<BLUE>２Ｐ<BLACK>はナルＰポイントを<BLUE>%dＰ<BLACK>入手しました。',
            '<BLUE>2P<BLACK>는 나루P 포인트를<BLUE>%dP<BLACK> 획득했습니다.'),
         ]),
]


def prepare(mp):
    plans=[]
    for rr in REWARDS:
        before=[];after=[];linereport=[]
        for original,korean in rr['lines']:
            a=original.encode('cp932')
            b=u.encode_ko(korean,mp)
            if len(b)>len(a):
                raise RuntimeError(f"{rr['id']} translation overflows line: {len(b)} > {len(a)}")
            # Preserve the exact next-line positions by putting padding BEFORE <br>.
            fill=b+b' '*(len(a)-len(b))
            before.append(a);after.append(fill)
            linereport.append(dict(original=original,korean=korean,
                                   original_bytes=len(a),translated_bytes=len(b),
                                   padding_bytes=len(a)-len(b)))
        # Keep the control tags and both formatting placeholders in same order.
        original=b'<br>'.join(before)
        changed=b'<br>'.join(after)
        if len(original)!=len(changed):raise RuntimeError('unexpected byte-size change')
        if original==changed:raise RuntimeError('translation is a no-op')
        tokens=[b'<RED>',b'<BLUE>',b'<BLACK>',b'<br>',b'%d',b'<iconCIRCLE>']
        for t in tokens:
            if original.count(t)!=changed.count(t):
                raise RuntimeError(f"{rr['id']} control token count mismatch for {t!r}")
        for a,b in zip(before,after):
            for token in [b'<RED>',b'<BLUE>',b'<BLACK>',b'%d',b'<iconCIRCLE>']:
                if a.count(token)!=b.count(token):
                    raise RuntimeError('line token mismatch')
        plans.append(dict(id=rr['id'],offset=rr['offset'],source=original,replacement=changed,
                          lines=linereport))
    # Explicitly check non-overlapping C-string slots.
    ps=sorted(plans,key=lambda p:p['offset'])
    for a,b in zip(ps,ps[1:]):
        if a['offset']+len(a['source'])+1>b['offset']:
            raise RuntimeError('overlapping reward slots')
    return plans


def patch_iso_core(source,final,extents,plans):
    writes=[]
    # Strictly verify originals before copying the 4GB ISO.
    for name in ('BOOT.BIN','EBOOT.BIN'):
        e=extents[name]
        segment=u.read_iso_segment(source,e)
        for p in plans:
            off=p['offset'];old=p['source'];new=p['replacement']
            if off<0 or off+len(old)+1>len(segment):
                raise RuntimeError(f'{name}/{p["id"]}: outside BOOT/EBOOT extent')
            if segment[off:off+len(old)+1]!=old+b'\x00':
                actual=segment[off:off+min(len(old)+1,160)]
                raise RuntimeError(f'{name}/{p["id"]}: exact source bytes differ at 0x{off:X}: {actual!r}')
            if segment.count(old+b'\x00')!=1:
                raise RuntimeError(f'{name}/{p["id"]}: duplicate source C-string')
            writes.append(dict(binary=name,id=p['id'],relative_offset=off,
                               absolute_offset=e['lba']*u.SECTOR+off,
                               length=len(old),old_bytes=old,new_bytes=new))
    # source SHA verified by main; never modify source ISO.
    shutil.copyfile(source,final)
    with final.open('r+b') as f:
        for p in writes:
            f.seek(p['absolute_offset'])
            if f.read(p['length']+1)!=p['old_bytes']+b'\0':
                raise RuntimeError('copy differs immediately before write')
            f.seek(p['absolute_offset']);f.write(p['new_bytes'])
        f.flush()
    return writes


def verify_iso(source,final,extents,writes):
    if final.stat().st_size!=source.stat().st_size:
        raise RuntimeError('ISO size changed')
    for name in ('BOOT.BIN','EBOOT.BIN'):
        e=extents[name]
        e2=u.iso_entry(final,'PSP_GAME/SYSDIR/'+name)
        if e2!=e:raise RuntimeError('directory entry changed for '+name)
        orig=u.read_iso_segment(source,e)
        new=u.read_iso_segment(final,e2)
        patches=[x for x in writes if x['binary']==name]
        cursor=0
        for p in sorted(patches,key=lambda v:v['relative_offset']):
            at=p['relative_offset'];end=at+p['length']
            if new[cursor:at]!=orig[cursor:at]:
                raise RuntimeError('unintended earlier bytes changed for '+name)
            if new[at:end]!=p['new_bytes'] or new[end:end+1]!=b'\0':
                raise RuntimeError('target C-string bytes verification failed')
            cursor=end
        if new[cursor:]!=orig[cursor:]:
            raise RuntimeError('unintended trailing bytes changed for '+name)
    for name,path in [('naruto.dat','PSP_GAME/USRDIR/naruto.dat'),
                      ('naruto.idx','PSP_GAME/USRDIR/naruto.idx')]:
        aa=u.hash_iso_segment(source,extents[name]);bb=u.hash_iso_segment(final,u.iso_entry(final,path))
        if aa!=bb:raise RuntimeError('protected '+name+' SHA256 changed')
    return True


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=str(ROOT_DEFAULT))
    ap.add_argument('--bundle',required=True)
    ap.add_argument('--dry-run',action='store_true')
    a=ap.parse_args()
    root=Path(a.root);bundle=Path(a.bundle)
    source=root/SOURCE_REL;out=root/OUT_REL
    out.mkdir(parents=True,exist_ok=True)
    final=out/FINAL_NAME
    report=dict(stage='SUB52N_REWARD_SAFE',status='NOT_STARTED',source_iso=str(source),
                expected_source_sha256=SOURCE_SHA,final_iso=str(final))
    try:
        print('[1/6] Verify exact runtime-proven SUB52M source ISO',flush=True)
        if not source.is_file():raise RuntimeError('Source SUB52M missing: '+str(source))
        sha=u.hash_file(source)
        if sha!=SOURCE_SHA:raise RuntimeError('SUB52M source SHA256 mismatch: '+sha)
        if source.stat().st_size>=2**32:raise RuntimeError('Source at/above 4GiB')
        print('[2/6] Validate fixed-length Korean reward strings',flush=True)
        mp=u.mapping(bundle/'combined_hangul_mapping_sub52d2.tsv')
        plans=prepare(mp)
        report['rewards']=[dict(id=p['id'],offset_hex=hex(p['offset']),bytes=len(p['source']),
                                lines=p['lines']) for p in plans]
        ipaths={'BOOT.BIN':'PSP_GAME/SYSDIR/BOOT.BIN',
                'EBOOT.BIN':'PSP_GAME/SYSDIR/EBOOT.BIN',
                'naruto.dat':'PSP_GAME/USRDIR/naruto.dat',
                'naruto.idx':'PSP_GAME/USRDIR/naruto.idx'}
        extents={k:u.iso_entry(source,v) for k,v in ipaths.items()}
        for name in ('BOOT.BIN','EBOOT.BIN'):
            raw=u.read_iso_segment(source,extents[name])
            for p in plans:
                off=p['offset'];src=p['source']
                if raw[off:off+len(src)+1]!=src+b'\0':
                    raise RuntimeError(f'String evidence mismatch in {name}/{p["id"]}')
        u.write_tsv(out/'reward_translation_plan.tsv',[
            dict(reward=p['id'],offset_hex=hex(p['offset']),byte_length=len(p['source']),
                 source_cp932=p['source'].decode('cp932'),
                 translation_text=' | '.join(line['korean'] for line in p['lines']),
                 replacement_hex=p['replacement'].hex()) for p in plans],
             ['reward','offset_hex','byte_length','source_cp932','translation_text','replacement_hex'])
        if a.dry_run:
            report['status']='DRY_RUN_OK'
            (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('DRY_RUN_OK',flush=True);return
        print('[3/6] Copy SUB52M to new output without changing its size',flush=True)
        if final.exists():final.unlink()
        writes=patch_iso_core(source,final,extents,plans)
        print('[4/6] Verify BOOT/EBOOT exact changes only',flush=True)
        verify_iso(source,final,extents,writes)
        print('[5/6] Verify DAT/IDX preserved and ISO SHA256',flush=True)
        report.update(status='STATIC_PASS_RUNTIME_UNVERIFIED',
                      patch_count=len(writes),iso_size_bytes=final.stat().st_size,
                      new_iso_sha256=u.hash_file(final),
                      protected_resources=['naruto.dat','naruto.idx','all CCS in DAT','all PMF unchanged'])
        u.write_tsv(out/'exact_reward_patch_offsets.tsv',[
            dict(binary=p['binary'],reward=p['id'],relative_offset_hex=hex(p['relative_offset']),
                 absolute_iso_offset_hex=hex(p['absolute_offset']),length=p['length'],
                 old_sha256=hashlib.sha256(p['old_bytes']).hexdigest(),
                 new_sha256=hashlib.sha256(p['new_bytes']).hexdigest()) for p in writes],
            ['binary','reward','relative_offset_hex','absolute_iso_offset_hex','length','old_sha256','new_sha256'])
        print('[6/6] Write reports',flush=True)
        (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in report.items())+'\n',encoding='utf-8-sig')
        print('NEW_ISO='+str(final),flush=True)
        print('STATIC_PASS_RUNTIME_UNVERIFIED',flush=True)
    except Exception:
        report['status']='FAIL'
        report['exception']=traceback.format_exc()
        (out/'FAILURE.txt').write_text(report['exception'],encoding='utf-8')
        (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if final.exists():final.unlink()
        raise

if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
