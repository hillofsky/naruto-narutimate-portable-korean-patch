"""Portable SUB52U archive extraction and CCS candidate rebuild (stdlib only)."""
import argparse,hashlib,importlib.util,json,os,shutil,struct,sys,tempfile
from pathlib import Path
from dev import ccs,compact
ROOT=Path(__file__).resolve().parents[1]
DAT='PSP_GAME/USRDIR/naruto.dat';IDX='PSP_GAME/USRDIR/naruto.idx'

def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
p14=load('portable_p14',ROOT/'work/analysis/stage14/naruto_patcher.py')
p15=load('portable_p15',ROOT/'work/analysis/stage15/stage15_iso_patcher.py')

def prepare(source,resource,work):
 dat=work/'naruto.dat';idx=work/'naruto.idx'
 ccs.extract(source,DAT,dat);ccs.extract(source,IDX,idx)
 table=p14.parse_pidx(p14.read_embedded_index(dat),'baseline')
 old=ccs.decode_primary(dat,table,resource,p14)
 return dat,idx,table,old

def rebuild(source,dat,idx,target):
 with source.open('rb') as f:
  vds=p15.read_volume_descriptors(f)
  _,de=compact.get_extent(f,p15,vds,DAT);_,xe=compact.get_extent(f,p15,vds,IDX)
 cut=de[0]*2048;compact.scan_live_extents(source,cut)
 if xe[0]*2048<cut+de[1]:raise ValueError('Unsafe DAT/IDX layout')
 idxstart=(cut+dat.stat().st_size+2047)//2048*2048
 predicted=(idxstart+idx.stat().st_size+2047)//2048*2048
 if predicted>=1<<32:raise ValueError('Candidate exceeds 4GiB ISO limit')
 with source.open('rb') as src,dat.open('rb') as df,idx.open('rb') as xf,target.open('xb+') as out:
  compact.stream_region(src,0,cut,out)
  dl=out.tell()//2048;dh=compact.stream_region(df,0,dat.stat().st_size,out);compact.align_stream(out)
  xl=out.tell()//2048;xh=compact.stream_region(xf,0,idx.stat().st_size,out);compact.align_stream(out)
  if out.tell()!=predicted:raise ValueError('Predicted size mismatch')
  vds=p15.read_volume_descriptors(out)
  for name,lba,size in [(DAT,dl,dat.stat().st_size),(IDX,xl,idx.stat().st_size)]:
   records,_=compact.get_extent(out,p15,vds,name)
   for r in records:p15.patch_directory_record(out,r['record_offset'],lba,size)
  p15.update_volume_space(out,vds,predicted//2048)
 if compact.hash_iso_segment(target,dl,dat.stat().st_size)!=dh or compact.hash_iso_segment(target,xl,idx.stat().st_size)!=xh:raise ValueError('Archive ISO readback mismatch')
 # Check every other live file, including BOOT, EBOOT and all movies.
 for name,begin,end in compact.scan_live_extents(source,cut)[0]:
  if name.casefold() in {DAT.casefold(),IDX.casefold()}:continue
  with target.open('rb') as f:_,loc=compact.get_extent(f,p15,p15.read_volume_descriptors(f),name)
  if loc!=(begin//2048,end-begin) or compact.hash_iso_segment(source,begin//2048,end-begin)!=compact.hash_iso_segment(target,*loc):raise ValueError('Unrelated live file changed: '+name)

def main():
 a=argparse.ArgumentParser(description=__doc__)
 a.add_argument('command',choices=['inspect','extract','build'])
 a.add_argument('--source',type=Path,required=True);a.add_argument('--resource',default='gauge.ccs')
 a.add_argument('--replacement',type=Path);a.add_argument('--output',type=Path)
 args=a.parse_args();m=json.loads((ROOT/'patch/sub52/manifest.json').read_text())
 if ccs.sha256_file(args.source)!=m['target_sha256']:raise ValueError('Requires exact SUB52U preview ISO; candidate chaining not supported')
 if not args.resource.lower().endswith('.ccs') or '/' in args.resource or chr(92) in args.resource:raise ValueError('Expected CCS member name')
 if args.command!='inspect' and (not args.output or args.output.exists() or args.output.resolve()==args.source.resolve()):raise ValueError('Choose a new output path')
 if args.command=='build' and not args.replacement:raise ValueError('--replacement is required')
 parent=args.output.parent if args.output else Path(tempfile.gettempdir());parent.mkdir(parents=True,exist_ok=True)
 with args.source.open('rb') as f:
  _,extent=compact.get_extent(f,p15,p15.read_volume_descriptors(f),DAT)
 reserve=extent[1]+(args.source.stat().st_size+128*1024*1024 if args.command=='build' else 16*1024*1024)
 if shutil.disk_usage(parent).free<reserve:raise ValueError('Insufficient free disk for private archive and candidate')
 with tempfile.TemporaryDirectory(prefix='naruto_dev_',dir=parent) as td:
  dat,idx,table,old=prepare(args.source,args.resource,Path(td))
  if args.command=='inspect':
   print(json.dumps({'resource':args.resource,'decoded_bytes':len(old),'sha256':hashlib.sha256(old).hexdigest(),'primary_members':len(table['primary'])}));return
  if args.command=='extract':
   with args.output.open('xb') as f:f.write(old)
   print('Extracted locally; do not commit extracted CCS.');return
  new=args.replacement.read_bytes()
  # Byte layout/texture dimensions must be preserved. Broader structural changes need separate review.
  if len(new)!=len(old):raise ValueError('Conservative CCS replacement requires unchanged decoded length')
  embedded=bytearray(p14.read_embedded_index(dat));external=bytearray(idx.read_bytes())
  ei=p14.parse_pidx(embedded,'embedded');xi=p14.parse_pidx(external,'external')
  live=[(r['offset'],r['offset']+r['zsize'],('primary',r['entry'])) for r in ei['primary'] if not r['is_folder'] and r['zsize']]
  live += [(r['file_off'],r['file_off']+r['file_size'],('fsts',r['index'])) for r in ei['offset2_rows'] if r['file_size']]
  def put(payload,start,capacity,tag):
   safe=len(payload)<=capacity and start>=len(embedded) and not any(t!=tag and start<b and a<start+capacity for a,b,t in live)
   with dat.open('r+b') as f:
    if safe:f.seek(start);f.write(payload);return start
    f.seek(0,os.SEEK_END);off=p14.align_up(f.tell());f.write(bytes(off-f.tell()));f.write(payload);return off
  changed_bundles=set()
  if new!=old:
   encoded=p14.encode_3_0(new)
   if p14.decode_3x(encoded)!=new:raise ValueError('CCS compression roundtrip failed')
   item=next(r for r in ei['primary'] if r['name']==args.resource)
   off=put(encoded,item['offset'],item['zsize'],('primary',item['entry']))
   for blob,t in [(embedded,ei),(external,xi)]:
    item=next(r for r in t['primary'] if r['name']==args.resource)
    struct.pack_into('<III',blob,item['record_off']+12,off,len(new),len(encoded))
   replacements={args.resource:{'new_decoded':new,'original_sha256':hashlib.sha256(old).hexdigest()}}
   with dat.open('r+b') as f:
    for r in ei['offset2_rows']:
     f.seek(r['file_off']);bundle=f.read(r['file_size']);rebuilt,changes=p14.rebuild_fsts(bundle,r['name'],replacements)
     if not changes:continue
     loc=put(rebuilt,r['file_off'],r['file_size'],('fsts',r['index']));changed_bundles.add(r['index'])
     for blob,t in [(embedded,ei),(external,xi)]:
      row=next(x for x in t['offset2_rows'] if x['index']==r['index'])
      struct.pack_into('<II',blob,row['record_abs']+8,loc,len(rebuilt))
    f.seek(0);f.write(embedded)
   idx.write_bytes(external)
  updated=p14.parse_pidx(p14.read_embedded_index(dat),'candidate')
  if ccs.decode_primary(dat,updated,args.resource,p14)!=new:raise ValueError('Primary readback mismatch')
  with args.source.open('rb') as sf:
   _,source_extent=compact.get_extent(sf,p15,p15.read_volume_descriptors(sf),DAT)
   with dat.open('rb') as df:
    for start,size in [(r['offset'],r['zsize']) for r in ei['primary'] if not r['is_folder'] and r['name']!=args.resource and r['zsize']] + [(r['file_off'],r['file_size']) for r in ei['offset2_rows'] if r['index'] not in changed_bundles]:
     sf.seek(source_extent[0]*2048+start);df.seek(start)
     remaining=size
     while remaining:
      count=min(remaining,8*1024*1024)
      if sf.read(count)!=df.read(count):raise ValueError('Unrelated archive member changed')
      remaining-=count
  # TemporaryDirectory owns its private output. Publishing never overwrites a target.
  candidate=Path(td)/'candidate.iso';rebuild(args.source,dat,idx,candidate)
  os.link(candidate,args.output)
  print(json.dumps({'output_sha256':ccs.sha256_file(args.output),'static_readback':'PASS','runtime_qa':'PENDING','resource_changed':new!=old,'non_target_live_files':'PRESERVED'}))

if __name__=='__main__':
 try:main()
 except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
