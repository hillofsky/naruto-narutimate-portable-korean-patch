from pathlib import Path
import importlib.util,struct,json,hashlib,shutil,csv
import numpy as np
from PIL import Image,ImageDraw,ImageFont
BASE=Path(r'D:\narutimate portable');OUT=BASE/'analysis/sub/sub39_speaker_texture';OUT.mkdir(parents=True,exist_ok=True)
def mod(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=mod('p14',BASE/'analysis/stage14/naruto_patcher.py');iso=mod('p15',BASE/'analysis/stage15/stage15_iso_patcher.py')
helper=mod('sub38',BASE/'naruto_sub38_multi_speaker_name_probe.py')
src=BASE/'analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso'
assert helper.sha(src)==helper.SUB36_SHA
for ip,n in [('PSP_GAME/USRDIR/naruto.dat','naruto.dat'),('PSP_GAME/USRDIR/naruto.idx','naruto.idx')]:helper.extract(src,ip,OUT/n)
dat=OUT/'naruto.dat';idx=OUT/'naruto.idx';eb=m.read_embedded_index(dat);eidx=idx.read_bytes();ei=m.parse_pidx(eb,'embedded');xi=m.parse_pidx(eidx,'external');ent=next(e for e in ei['primary'] if e['name']=='mugen.ccs')
with dat.open('rb') as f:f.seek(ent['offset']);stored=f.read(ent['zsize'] or ent['size'])
b=bytearray(m.decode_3x(stored));o=0xe3824;assert b[o:o+4]==bytes.fromhex('0003cccc');assert struct.unpack_from('<II',b,o+8)==(190,189)
po=b.find(bytes.fromhex('0004cccc')+struct.pack('<II',21,189))
if po<0:
 po=next(i for i in range(0,len(b)-28,4) if b[i:i+4]==bytes.fromhex('0004cccc') and struct.unpack_from('<I',b,i+8)[0]==189)
n=struct.unpack_from('<I',b,po+24)[0];pal=np.frombuffer(b[po+28:po+28+n*4],np.uint8).reshape(-1,4).copy()[:,[2,1,0,3]];pal[:,3]=np.minimum(pal[:,3].astype(int)*2,255)
ko=[['환영','사쿠라','시카마루','시즈네','츠나데','히나타','키바','키리히메','카스미','시노'],['쵸지','이노','네지','리','가아라','카카시','가이','텐텐','이타치','키사메'],['지라이야','카부토','오로치마루','나루토','3대 호카게','이루카','에비스','병사장','시녀','여자아이'],['사념체','사념체들',None,'지라이야 일행','병사','일동']]
jp=[['幻影','サクラ','シカマル','シズネ','綱手','ヒナタ','キバ','霧姫','花澄','シノ'],['チョウジ','いの','ネジ','リー','我愛羅','カカシ','ガイ','テンテン','イタチ','鬼鮫'],['自来也','カブト','大蛇丸','ナルト','三代目','イルカ','エビス','兵士長','侍女','女の子'],['思念体','思念体達','自／綱','自来也達','兵士','一同']]
# Keep each original UV cell and palette. Render code-native text glyphs at 4x resolution.
raw=b[o+36:o+36+65536];a=np.frombuffer(raw,np.uint8);ix=np.stack((a&15,a>>4),axis=1).reshape(256,512)[::-1].copy();rows=[]
for col,ls in enumerate(ko):
 for row,text in enumerate(ls):
  if text is None:continue
  x=col*76;y=row*24;mask=Image.new('RGBA',(72*4,24*4));d=ImageDraw.Draw(mask);size=16*4
  while True:
   font=ImageFont.truetype(r'C:\Windows\Fonts\malgunbd.ttf',size)
   if d.textlength(text,font=font)<=70*4 or size<=32:break
   size-=1
  box=d.textbbox((0,0),text,font=font);tw=box[2]-box[0];th=box[3]-box[1];d.text(((72*4-tw)//2-box[0],(24*4-th)//2-box[1]),text,font=font,fill=(255,255,255,255),stroke_width=4,stroke_fill=(0,0,0,255))
  target_rgba=np.asarray(mask.resize((72,24),Image.Resampling.LANCZOS)).astype(float)
  target_rgba[:,:,:3]*=target_rgba[:,:,3:4]/255
  effective=pal.astype(float);effective[:,:3]*=effective[:,3:4]/255
  dist=((target_rgba[:,:,None,:]-effective[None,None,:,:])**2).sum(axis=3)
  inds=dist.argmin(axis=2).astype(np.uint8);ix[y:y+24,x:x+72]=inds
  rows.append(dict(column=col,row=row,japanese=jp[col][row],korean=text,font_size=size/4,status='PATCHED'))
img=Image.fromarray(pal[ix],'RGBA');img.save(OUT/'speaker_names_ko.png');flat=ix[::-1].reshape(-1);packed=(flat[::2]|(flat[1::2]<<4)).tobytes();assert len(packed)==65536
old=bytes(b);b[o+36:o+36+65536]=packed;assert old[:o+36]==b[:o+36] and old[o+36+65536:]==b[o+36+65536:]
(OUT/'mugen_ko.ccs').write_bytes(b);encoded=m.encode_3_0(b);assert m.decode_3x(encoded)==b
new_off=m.align_up(dat.stat().st_size)
with dat.open('ab') as f:f.write(bytes(new_off-f.tell()));f.write(encoded)
eb=bytearray(eb);xb=bytearray(eidx)
bundle_changes=[]
with dat.open('r+b') as f:
 for r in ei['offset2_rows']:
  f.seek(r['file_off']);bundle=f.read(r['file_size'])
  rebuilt,changes=m.rebuild_fsts(bundle,r['name'],{'mugen.ccs':{'original_sha256':m.sha256(old),'new_decoded':bytes(b)}})
  if not changes:continue
  f.seek(0,2);off=m.align_up(f.tell());f.write(bytes(off-f.tell()));f.write(rebuilt)
  for blob,table in [(eb,ei),(xb,xi)]:
   rec=next(q for q in table['offset2_rows'] if q['index']==r['index']);struct.pack_into('<II',blob,rec['record_abs']+8,off,len(rebuilt))
  bundle_changes.append({'bundle':r['name'],'offset':off,'size':len(rebuilt),'members':changes});print('FSTS',r['name'],flush=True)
for blob,table in [(eb,ei),(xb,xi)]:
 e=next(e for e in table['primary'] if e['name']=='mugen.ccs');struct.pack_into('<III',blob,e['record_off']+12,new_off,len(b),len(encoded))
with dat.open('r+b') as f:f.write(eb)
idx.write_bytes(xb)
target=OUT/'Naruto_KR_MOV06E_SUB39_SpeakerTexture.iso';shutil.copyfile(src,target)
with target.open('r+b') as f:
 vds=iso.read_volume_descriptors(f)
 for path,p in [('PSP_GAME/USRDIR/naruto.dat',dat),('PSP_GAME/USRDIR/naruto.idx',idx)]:
  recs=[iso.find_path(f,vd,path.split('/')) for vd in vds if vd['type'] in (1,2)];ext=iso.append_file_sector_aligned(f,p,p.name)
  for r in recs:
   if r:iso.patch_directory_record(f,r['record_offset'],ext['lba'],ext['size'])
 iso.update_volume_space(f,vds,(f.seek(0,2)+2047)//2048)
with (OUT/'speaker_translations.tsv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');w.writeheader();w.writerows(rows)
report=dict(stage='SUB39',source_iso_sha256=helper.sha(src),output_iso=str(target),patched_names=len(rows),unresolved_special_label='自／綱',changed_asset='mugen.ccs/TEX_name',changed_decoded_byte_range=[o+36,o+36+65536],fsts_bundles=bundle_changes,runtime_verified=False)
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
