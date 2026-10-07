from pathlib import Path
import importlib.util,struct,shutil,json,csv,re
BASE=Path(r'D:\narutimate portable');OUT=BASE/'analysis/sub/sub42_menu_text';OUT.mkdir(parents=True,exist_ok=True)
def mod(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=mod('p14',BASE/'analysis/stage14/naruto_patcher.py');s15=mod('p15',BASE/'analysis/stage15/stage15_iso_patcher.py');h=mod('h38',BASE/'naruto_sub38_multi_speaker_name_probe.py')
src=BASE/'analysis/sub/sub41_names_guides_menu/Naruto_KR_MOV06E_SUB41_Names_Guides_Menu.iso'
for ip,n in [('PSP_GAME/USRDIR/naruto.dat','naruto.dat'),('PSP_GAME/USRDIR/naruto.idx','naruto.idx')]:h.extract(src,ip,OUT/n)
dat=OUT/'naruto.dat';idx=OUT/'naruto.idx';eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes());ei=m.parse_pidx(eb,'embedded');xi=m.parse_pidx(xb,'external');e=next(e for e in ei['primary'] if e['name']=='mugen.tbl')
with dat.open('rb') as f:f.seek(e['offset']);old=m.decode_stored(f.read(e['zsize'] or e['size']),e['size'],e['zsize'])
mp={r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((BASE/'analysis/shared/event_font_hangul_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')};mp.update({r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((BASE/'analysis/sub/sub40_tutorial/new_glyph_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')})
ko=json.loads(Path('work/menu_text_ko.json').read_text(encoding='utf-8'));assert not ({c for s in ko.values() for c in s if '가'<=c<='힣'}-mp.keys())
def enc(s):return b''.join(mp[c] if c in mp else b'\xa0' if c==' ' else c.encode('cp932') for c in s)
lookup={jp.encode('cp932'):(jp,kr) for jp,kr in ko.items()};out=[];rows=[]
for line in old.splitlines(keepends=True):
 hit=re.match(rb'([^=\r\n]*=)(.*?)(\r*\n)?$',line)
 if hit and hit[2] in lookup:
  jp,kr=lookup[hit[2]];out.append(hit[1]+enc(kr)+(hit[3] or b''));rows.append(dict(japanese=jp,korean=kr,bytes_before=len(hit[2]),bytes_after=len(enc(kr))))
 else:out.append(line)
assert len(rows)==12
new=b''.join(out);(OUT/'mugen_ko.tbl').write_bytes(new);encoded=m.encode_3_0(new);assert m.decode_3x(encoded)==new;off=m.align_up(dat.stat().st_size)
with dat.open('ab') as f:f.write(bytes(off-f.tell()));f.write(encoded)
for blob,table in [(eb,ei),(xb,xi)]:
 q=next(q for q in table['primary'] if q['name']=='mugen.tbl');struct.pack_into('<III',blob,q['record_off']+12,off,len(new),len(encoded))
bundles=[]
with dat.open('r+b') as f:
 for r in ei['offset2_rows']:
  f.seek(r['file_off']);bundle=f.read(r['file_size']);rebuilt,changes=m.rebuild_fsts(bundle,r['name'],{'mugen.tbl':dict(original_sha256=m.sha256(old),new_decoded=new)})
  if not changes:continue
  f.seek(0,2);o=m.align_up(f.tell());f.write(bytes(o-f.tell()));f.write(rebuilt)
  for blob,table in [(eb,ei),(xb,xi)]:
   q=next(q for q in table['offset2_rows'] if q['index']==r['index']);struct.pack_into('<II',blob,q['record_abs']+8,o,len(rebuilt))
  bundles.append(r['name'])
 f.seek(0);f.write(eb)
idx.write_bytes(xb);target=OUT/'Naruto_KR_MOV06E_SUB42_Names_Guides_Menu.iso';shutil.copyfile(BASE/'analysis/integrated/sub36_semantic_qa/output/Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso',target)
with target.open('r+b') as f:
 vds=s15.read_volume_descriptors(f)
 for ip,p in [('PSP_GAME/USRDIR/naruto.dat',dat),('PSP_GAME/USRDIR/naruto.idx',idx),('PSP_GAME/SYSDIR/BOOT.BIN',BASE/'analysis/sub/sub40_tutorial/BOOT.bin'),('PSP_GAME/SYSDIR/EBOOT.BIN',BASE/'analysis/sub/sub40_tutorial/BOOT.bin')]:
  rs=[s15.find_path(f,vd,ip.split('/')) for vd in vds if vd['type'] in (1,2)];ext=s15.append_file_sector_aligned(f,p,p.name)
  for r in rs:
   if r:s15.patch_directory_record(f,r['record_offset'],ext['lba'],ext['size'])
 s15.update_volume_space(f,vds,(f.seek(0,2)+2047)//2048)
with (OUT/'menu_text_translations.tsv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');w.writeheader();w.writerows(rows)
print(json.dumps(dict(iso=str(target),menu_text_rows=len(rows),bundles=bundles),ensure_ascii=False))
