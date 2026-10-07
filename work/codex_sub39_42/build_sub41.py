from pathlib import Path
import importlib.util,struct,shutil,json,csv
import numpy as np
from PIL import Image,ImageDraw,ImageFont
BASE=Path(r'D:\narutimate portable');OUT=BASE/'analysis/sub/sub41_names_guides_menu';OUT.mkdir(parents=True,exist_ok=True)
def mod(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=mod('p14',BASE/'analysis/stage14/naruto_patcher.py');s15=mod('p15',BASE/'analysis/stage15/stage15_iso_patcher.py');h=mod('h38',BASE/'naruto_sub38_multi_speaker_name_probe.py')
src=BASE/'analysis/sub/sub40_tutorial/Naruto_KR_MOV06E_SUB40_Names_Tutorial.iso'
for ip,n in [('PSP_GAME/USRDIR/naruto.dat','naruto.dat'),('PSP_GAME/USRDIR/naruto.idx','naruto.idx')]:h.extract(src,ip,OUT/n)
dat=OUT/'naruto.dat';idx=OUT/'naruto.idx';eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes());ei=m.parse_pidx(eb,'embedded');xi=m.parse_pidx(xb,'external');e=next(e for e in ei['primary'] if e['name']=='mugen.ccs')
with dat.open('rb') as f:f.seek(e['offset']);old=m.decode_stored(f.read(e['zsize'] or e['size']),e['size'],e['zsize'])
b=bytearray(old);rows=[]
def regenerate(o,palid,w,h,rects,preview):
 po=next(i for i in range(0,len(b)-28,4) if b[i:i+4]==bytes.fromhex('0004cccc') and struct.unpack_from('<I',b,i+8)[0]==palid)
 n=struct.unpack_from('<I',b,po+24)[0];pal=np.frombuffer(b[po+28:po+28+n*4],np.uint8).reshape(-1,4).copy()[:,[2,1,0,3]];pal[:,3]=np.minimum(pal[:,3].astype(int)*2,255);effective=pal.astype(float);effective[:,:3]*=effective[:,3:4]/255
 raw=np.frombuffer(b[o+36:o+36+w*h//2],np.uint8);ix=np.stack((raw&15,raw>>4),axis=1).reshape(h,w)[::-1].copy()
 for x,y,rw,rh,jp,ko in rects:
  im=Image.new('RGBA',(rw*4,rh*4));d=ImageDraw.Draw(im);size=15*4
  while True:
   f=ImageFont.truetype(r'C:\Windows\Fonts\malgunbd.ttf',size)
   if d.textlength(ko,font=f)<=(rw-4)*4:break
   size-=1
  box=d.textbbox((0,0),ko,font=f);d.text(((rw*4-(box[2]-box[0]))/2-box[0],(rh*4-(box[3]-box[1]))/2-box[1]),ko,font=f,fill='white',stroke_width=3,stroke_fill='black')
  a=np.asarray(im.resize((rw,rh),Image.Resampling.LANCZOS)).astype(float);a[:,:,:3]*=a[:,:,3:4]/255;dist=((a[:,:,None,:]-effective[None,None,:,:])**2).sum(axis=3);ix[y:y+rh,x:x+rw]=dist.argmin(axis=2)
  rows.append(dict(texture=preview,japanese=jp,korean=ko,uv=f'{x},{y},{rw},{rh}',font_size=size/4))
 Image.fromarray(pal[ix]).save(OUT/(preview+'.png'));flat=ix[::-1].reshape(-1);b[o+36:o+36+w*h//2]=(flat[::2]|flat[1::2]<<4).tobytes()
rects=[(0,0,96,18,'メニュー','메뉴'),(0,18,96,18,'ステータス','상태'),(0,36,96,18,'アイテム','아이템'),(0,54,96,18,'スキル','스킬'),(0,72,96,18,'誰に使う？','누구에게 사용?'),(0,90,114,18,'どれに変更？','무엇으로 변경?'),(0,110,96,18,'隊長能力','대장 능력'),(96,0,78,18,'隊長','대장'),(96,18,78,18,'隊員','대원'),(96,36,78,18,'小隊','소대'),(96,54,78,18,'小隊編成','소대 편성'),(96,72,78,18,'行動選択','행동 선택')]
regenerate(0x1dba64,275,256,128,rects,'TEX_yellow_ko');regenerate(0xe3824,189,512,256,[(228,48,72,24,'自／綱','지라이야·츠나데')],'TEX_name_ko')
assert len(b)==len(old);(OUT/'mugen_ko.ccs').write_bytes(b);encoded=m.encode_3_0(b);assert m.decode_3x(encoded)==b
off=m.align_up(dat.stat().st_size)
with dat.open('ab') as f:f.write(bytes(off-f.tell()));f.write(encoded)
for blob,table in [(eb,ei),(xb,xi)]:
 rec=next(q for q in table['primary'] if q['name']=='mugen.ccs');struct.pack_into('<III',blob,rec['record_off']+12,off,len(b),len(encoded))
bundles=[]
with dat.open('r+b') as f:
 for r in ei['offset2_rows']:
  f.seek(r['file_off']);bundle=f.read(r['file_size']);rebuilt,changes=m.rebuild_fsts(bundle,r['name'],{'mugen.ccs':dict(original_sha256=m.sha256(old),new_decoded=bytes(b))})
  if not changes:continue
  f.seek(0,2);o=m.align_up(f.tell());f.write(bytes(o-f.tell()));f.write(rebuilt)
  for blob,table in [(eb,ei),(xb,xi)]:
   q=next(q for q in table['offset2_rows'] if q['index']==r['index']);struct.pack_into('<II',blob,q['record_abs']+8,o,len(rebuilt))
  bundles.append(r['name'])
 f.seek(0);f.write(eb)
idx.write_bytes(xb);target=OUT/'Naruto_KR_MOV06E_SUB41_Names_Guides_Menu.iso';shutil.copyfile(src,target)
with target.open('r+b') as f:
 vds=s15.read_volume_descriptors(f)
 for ip,p in [('PSP_GAME/USRDIR/naruto.dat',dat),('PSP_GAME/USRDIR/naruto.idx',idx)]:
  rs=[s15.find_path(f,vd,ip.split('/')) for vd in vds if vd['type'] in (1,2)];ext=s15.append_file_sector_aligned(f,p,p.name)
  for r in rs:
   if r:s15.patch_directory_record(f,r['record_offset'],ext['lba'],ext['size'])
 s15.update_volume_space(f,vds,(f.seek(0,2)+2047)//2048)
with (OUT/'menu_and_special_name_translations.tsv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');w.writeheader();w.writerows(rows)
print(json.dumps(dict(iso=str(target),speaker_names=36,tutorial_rows=44,menu_labels=12,bundles=bundles),ensure_ascii=False))
