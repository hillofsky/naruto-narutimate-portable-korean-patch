from pathlib import Path
import struct,re,csv
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(r'PROJECT_ROOT\analysis\stage9\extracted\kr')
OUT=Path('work/ui');OUT.mkdir(exist_ok=True)
def u(b,o): return struct.unpack_from('<I',b,o)[0]
def decode(p):
 b=p.read_bytes(); pc,nc=struct.unpack_from('<II',b,0x44);no=0x4c+32*pc
 names=[b[no+32*i:no+32*i+30].split(b'\0')[0].decode('cp932','replace') for i in range(nc)]
 pal={};tex=[]
 for m in re.finditer(b'\x00\x04\xcc\xcc',b):
  o=m.start();i=u(b,o+8);n=u(b,o+24)
  if o%4 or i>=nc or n not in (16,256) or o+28+n*4>len(b):continue
  a=np.frombuffer(b[o+28:o+28+n*4],dtype=np.uint8).reshape(-1,4).copy()[:,[2,1,0,3]];a[:,3]=np.minimum(a[:,3].astype(int)*2,255);pal[i]=a
 for m in re.finditer(b'\x00\x03\xcc\xcc',b):
  o=m.start()
  if o%4 or o+36>len(b):continue
  i,c=u(b,o+8),u(b,o+12);typ=b[o+21];we,he=b[o+24:o+26]
  if i>=nc or typ not in (0,0x13,0x14) or we>11 or he>11:continue
  w,h=1<<we,1<<he;n=u(b,o+32)*4;raw=b[o+36:o+36+n]
  if len(raw)!=n or n!=w*h*{0:4,0x13:1,0x14:0.5}[typ]:continue
  if typ==0:a=np.frombuffer(raw,np.uint8).reshape(h,w,4).copy()
  else:
   if c not in pal:continue
   ix=np.frombuffer(raw,np.uint8)
   if typ==0x14: ix=np.stack((ix&15,ix>>4),axis=1).reshape(-1)
   a=pal[c][ix].reshape(h,w,4)
  im=Image.fromarray(a,'RGBA');fn=f'{p.stem}__{i:04d}__{names[i]}.png';fn=re.sub(r'[<>:"/\\|?*]','_',fn);im.save(OUT/fn)
  tex.append(dict(file=p.name,name=names[i],index=i,palette=c,offset=hex(o),width=w,height=h,format=hex(typ),png=fn))
 return tex
rows=[]
for p in ROOT.glob('*.ccs'):
 if re.search(r'__(mugen|strmcmn|charsel1|modesel1|home|setting|option|navi_nrt|rpggauge|gauge|1.*bod1)\.ccs$',p.name): rows+=decode(p)
with (OUT/'inventory.tsv').open('w',encoding='utf-8-sig',newline='') as f:
 wr=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');wr.writeheader();wr.writerows(rows)
print('textures',len(rows))
selected=[r for r in rows if 'name' in r['name'].lower() or r['file'].split('__')[1] in ('mugen.ccs','strmcmn.ccs','setting.ccs','rpggauge.ccs')]
sheet=Image.new('RGB',(1000,230*((len(selected)+3)//4)),(70,70,70));d=ImageDraw.Draw(sheet)
for j,r in enumerate(selected):
 im=Image.open(OUT/r['png']);im.thumbnail((244,195));x=(j%4)*250;y=(j//4)*230;sheet.paste(im,(x,y+30),im);d.text((x,y),r['file'].split('__')[1]+' '+r['name'],fill='white')
sheet.save(OUT/'contact.png');print('selected',len(selected))
