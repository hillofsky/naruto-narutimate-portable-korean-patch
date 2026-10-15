#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SUB52P: no modifications; find preserved legacy CCS bytes and FSTS routing."""
from pathlib import Path
import argparse, csv, hashlib, json, traceback, sys, time
import sub52l_core as core

SRC = Path(r'analysis\sub\sub52j_safe_atlas\Naruto_KR_MOV06E_SUB52J_SafeAtlas.iso')
CUR = Path(r'analysis\sub\sub52n_reward_safe_fix1\Naruto_KR_MOV06E_SUB52N_FIX1_RewardSafe.iso')
SRC_SHA = '2e6cb2e577ddeebe07453ec56f07f72422a6b3b20001987c253a5468658f5a05'
CUR_SHA = '00bd998359e64e5d3f2af28c4f0d5b0dac7db8b11a35b773ea8a4ee290d58663'
RESOURCES = [
  'face_sik.ccs','face_hnt.ccs','gauge.ccs','eff3eye.ccs',
  'mgselect.ccs','charsel1.ccs','1sikbod1.ccs','1hntbod1.ccs',
  '1sskbod1.ccs','mugen.ccs',
]
FOCUS = {
 'face_sik.ccs':['TEX_n_sik_l','TEX_n_sik_s'],
 'face_hnt.ccs':['TEX_n_hnt_l','TEX_n_hnt_s'],
 'gauge.ccs':['TEX_xwinner'],
 'eff3eye.ccs':['TEX_xwinner'],
 'mgselect.ccs':['TEX_xwinner'],
 'charsel1.ccs':['TEX_sel'],
 '1sikbod1.ccs':['TEX_name'],
 '1hntbod1.ccs':['TEX_name'],
 '1sskbod1.ccs':['TEX_name'],
 'mugen.ccs':['TEX_hanyou','TEX_name'],
}

def sha_file(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda: f.read(8*1024*1024), b''):h.update(b)
 return h.hexdigest()

def stored(iso,extent,r):
 n=r['zsize'] or r['size']
 if r['offset']<0 or n<0 or r['offset']+n>extent['size']:
  raise ValueError('Record out of DAT bounds: '+r['name'])
 with iso.open('rb') as f:
  f.seek(extent['lba']*core.SECTOR+r['offset'])
  b=f.read(n)
 if len(b)!=n:raise ValueError('short read: '+r['name'])
 return b

def old_location(iso,extent,r):
 n=r['zsize'] or r['size']
 if r['offset']<0 or n<0 or r['offset']+n>extent['size']:
  return None
 return stored(iso,extent,r)

def writer(path,rows,fields):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore')
  w.writeheader();w.writerows(rows)

def choose_tex(buf,tname):
 ts=[t for t in core.tex_spans(buf) if t['name']==tname]
 if len(ts)!=1:return None
 return ts[0]

def main():
 a=argparse.ArgumentParser()
 a.add_argument('--root',default=r'D:\narutimate portable')
 a.add_argument('--out',default='')
 args=a.parse_args()
 root=Path(args.root);out=Path(args.out) if args.out else root/r'analysis\sub\sub52p_historical_source'
 out.mkdir(parents=True,exist_ok=True)
 src=root/SRC;cur=root/CUR
 for path,hs in ((src,SRC_SHA),(cur,CUR_SHA)):
  if not path.is_file():raise RuntimeError('Required verified source ISO missing: '+str(path))
  sh=sha_file(path)
  if sh!=hs:raise RuntimeError('Unexpected ISO sha256 '+str(path)+' '+sh)
 print('SOURCE_SHA_AND_CURRENT_SHA=PASS',flush=True)
 patcher=core.loadpatcher(root)
 sd=core.isoentry(src,'PSP_GAME/USRDIR/naruto.dat')
 cd=core.isoentry(cur,'PSP_GAME/USRDIR/naruto.dat')
 si,_=core.read_index(src,sd,patcher)
 ci,_=core.read_index(cur,cd,patcher)
 rows=[];texrows=[];problems=[]
 texdir=out/'comparison_png';texdir.mkdir(exist_ok=True)
 for name in RESOURCES:
  print('CHECK',name,flush=True)
  sr=next((r for r in si['primary'] if r['name'].lower()==name.lower()),None)
  cr=next((r for r in ci['primary'] if r['name'].lower()==name.lower()),None)
  if sr is None or cr is None:
   problems.append('Resource missing: '+name)
   continue
  oldblob=stored(src,sd,sr)
  newblob=stored(cur,cd,cr)
  legacy=old_location(cur,cd,sr)
  preserved=legacy is not None and legacy==oldblob
  decoded_src=patcher.decode_stored(oldblob,sr['size'],sr['zsize'])
  decoded_cur=patcher.decode_stored(newblob,cr['size'],cr['zsize'])
  row=dict(
   resource=name,old_dat_offset=hex(sr['offset']),current_dat_offset=hex(cr['offset']),
   old_decoded_size=sr['size'],current_decoded_size=cr['size'],
   old_stored_size=len(oldblob),current_stored_size=len(newblob),
   old_stored_sha256=hashlib.sha256(oldblob).hexdigest(),
   old_stored_bytes_still_at_old_offset='YES' if preserved else 'NO',
   indexed_current_stored_sha256=hashlib.sha256(newblob).hexdigest(),
   indexed_resource_changed='YES' if decoded_src!=decoded_cur else 'NO',
   same_dat_relative_offset='YES' if sr['offset']==cr['offset'] else 'NO',
  )
  rows.append(row)
  for tn in FOCUS.get(name,[]):
   a=choose_tex(decoded_src,tn);b=choose_tex(decoded_cur,tn)
   if not a or not b:continue
   oldrgba,oldpayload=core.decode_tex(decoded_src,a)
   newrgba,newpayload=core.decode_tex(decoded_cur,b)
   base=name.replace('.ccs','')+'__'+tn
   for prefix,buf,t in [('OLD',oldrgba,a),('CURRENT',newrgba,b)]:
    core.save_png(texdir/(prefix+'__'+base+'.png'),t['width'],t['height'],buf)
   texrows.append(dict(resource=name,texture=tn,
     old_indexed_sha256=hashlib.sha256(oldpayload).hexdigest(),
     current_indexed_sha256=hashlib.sha256(newpayload).hexdigest(),
     changed='YES' if oldpayload!=newpayload else 'NO',
     original_still_present_at_legacy_blob='YES' if preserved else 'NO'))
 fields=['resource','old_dat_offset','current_dat_offset','old_decoded_size','current_decoded_size',
         'old_stored_size','current_stored_size','old_stored_sha256',
         'old_stored_bytes_still_at_old_offset','indexed_current_stored_sha256',
         'indexed_resource_changed','same_dat_relative_offset']
 writer(out/'legacy_ccs_offsets.tsv',rows,fields)
 writer(out/'legacy_texture_diff.tsv',texrows,
       ['resource','texture','old_indexed_sha256','current_indexed_sha256','changed',
        'original_still_present_at_legacy_blob'])
 # Scan only FSTS header map, not full archive dumps.
 try:
  dup,issues=core.scan_fsts_headers(cur,cd,ci,patcher,set(x.lower() for x in RESOURCES))
  writer(out/'fsts_duplicate_candidates.tsv',dup,
     ['bundle','member','base','decoded_sha256','stored_size','bundle_offset','member_offset'])
  problems.extend(issues)
 except Exception as e:
  dup=[];problems.append('FSTS scan exception: '+repr(e))
 summary={
  'stage':'SUB52P_HISTORICAL_CCS_PROBE',
  'source_iso_sha256':SRC_SHA,'current_iso_sha256':CUR_SHA,
  'ccs_checked':len(rows),
  'legacy_original_blob_still_present':sum(x['old_stored_bytes_still_at_old_offset']=='YES' for x in rows),
  'current_indexed_ccs_changed':sum(x['indexed_resource_changed']=='YES' for x in rows),
  'textures_compared':len(texrows),
  'changed_textures':sum(x['changed']=='YES' for x in texrows),
  'fsts_candidates':len(dup),
  'warnings':problems[:60],
  'iso_modified':False,
  'ppsspp_controlled':False,
  'interpretation':'Legacy blobs remaining on disk does NOT prove runtime reads them; PSP load provenance requires further verification.'
 }
 (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'SUMMARY.txt').write_text('\n'.join(f'{k}={v}' for k,v in summary.items()),encoding='utf-8-sig')
 print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();sys.exit(1)
