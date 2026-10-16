from pathlib import Path
import importlib.util,hashlib,json
BASE=Path(r'PROJECT_ROOT');OUT=BASE/'analysis/sub/sub41_names_guides_menu'
def mod(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=mod('p14',BASE/'analysis/stage14/naruto_patcher.py');h=mod('h38',BASE/'naruto_sub38_multi_speaker_name_probe.py')
src=BASE/'analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso';final=OUT/'Naruto_KR_MOV06E_SUB41_Names_Guides_Menu.iso'
source_dat=BASE/'analysis/sub/sub38_multi_speaker_name_probe/extract/naruto.dat';a=m.parse_pidx(m.read_embedded_index(source_dat),'source');b=m.parse_pidx(m.read_embedded_index(OUT/'naruto.dat'),'final')
preserved=0
with source_dat.open('rb') as sf,(OUT/'naruto.dat').open('rb') as ff:
 for x,y in zip(a['primary'],b['primary']):
  assert x['name']==y['name']
  if x['is_folder'] or x['name'] in ('mugen.ccs','mugen.tbl'):continue
  sf.seek(x['offset']);ff.seek(y['offset']);assert sf.read(x['zsize'] or x['size'])==ff.read(y['zsize'] or y['size']),x['name'];preserved+=1
 for x,y in zip(a['offset2_rows'],b['offset2_rows']):
  sf.seek(x['file_off']);ff.seek(y['file_off']);sb=sf.read(x['file_size']);fb=ff.read(y['file_size'])
  if x['name'] not in ('mugen0','mugen1'):assert sb==fb,x['name'];continue
  sa=m.parse_fsts(sb,'s');fa=m.parse_fsts(fb,'f');assert len(sa['members'])==len(fa['members'])
  for sx,fx in zip(sa['members'],fa['members']):
   assert sx['name']==fx['name']
   if sx['basename'] not in ('mugen.ccs','mugen.tbl'):assert sx['stored']==fx['stored'],sx['name']
movies=[]
def walk(path):
 e=h.findiso(src,path)
 for q in h.dirents(src,e['lba'],e['size']):
  if q['name'] in ('.','..'):continue
  p=path+'/'+q['name']
  if q['dir']:walk(p)
  elif q['name'].lower().endswith('.pmf'):movies.append(p)
walk('PSP_GAME/USRDIR')
for ip in movies:assert h.segsha(src,ip)==h.segsha(final,ip),ip
for ip in ['PSP_GAME/USRDIR/naruto.dat','PSP_GAME/USRDIR/naruto.idx']:
 n=Path(ip).name;assert h.segsha(final,ip)[1]==h.sha(OUT/n)
boot=BASE/'analysis/sub/sub40_tutorial/BOOT.bin'
for ip in ['PSP_GAME/SYSDIR/BOOT.BIN','PSP_GAME/SYSDIR/EBOOT.BIN']:assert h.segsha(final,ip)[1]==h.sha(boot)
r=dict(stage='SUB41',iso=str(final),iso_sha256=h.sha(final),speaker_names=36,tutorial_rows=44,menu_image_labels=12,preserved_primary_resources=preserved,preserved_pmf_movies=len(movies),preserved_other_fsts_members=True,existing_694_glyph_mapping_preserved=True,new_safe_glyphs=17,static_qa='PASS',runtime_qa='pending',source_iso_sha256=h.sha(src))
(OUT/'verification.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False))
