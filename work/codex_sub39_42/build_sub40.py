from pathlib import Path
import importlib.util,struct,json,csv,re,shutil
from PIL import ImageFont
BASE=Path(r'D:\narutimate portable');OUT=BASE/'analysis/sub/sub40_tutorial';OUT.mkdir(parents=True,exist_ok=True)
def mod(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=mod('p14',BASE/'analysis/stage14/naruto_patcher.py');s15=mod('p15',BASE/'analysis/stage15/stage15_iso_patcher.py');fontmod=mod('font16',BASE/'naruto_sub16_collision_free_boot.py');helper=mod('h38',BASE/'naruto_sub38_multi_speaker_name_probe.py')
src=BASE/'analysis/sub/sub39_speaker_texture/Naruto_KR_MOV06E_SUB39_SpeakerTexture.iso'
for ip,n in [('PSP_GAME/USRDIR/naruto.dat','naruto.dat'),('PSP_GAME/USRDIR/naruto.idx','naruto.idx'),('PSP_GAME/SYSDIR/BOOT.BIN','BOOT.bin')]:helper.extract(src,ip,OUT/n)
def rt(p):return list(csv.DictReader(p.open(encoding='utf-8-sig'),delimiter='\t'))
mapping=rt(BASE/'analysis/shared/event_font_hangul_mapping.tsv');mp={r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in mapping};ko=json.loads(Path('work/tutorial_ko.json').read_text(encoding='utf-8'))
missing=sorted({c for s in ko.values() for c in s if '가'<=c<='힣'}-mp.keys());used={int(r['glyph_index']) for r in mapping}
slots=[r for r in rt(BASE/'analysis/sub/sub15_actual_runtime_mapping/sub15_runtime_slot_inventory.tsv') if r['strict_safe']=='1' and int(r['glyph']) not in used];slots.sort(key=lambda r:(0 if r['bitmap_empty']=='1' else 1,-int(r['glyph'])))
boot=bytearray((OUT/'BOOT.bin').read_bytes());oldboot=bytes(boot);added=[];font=ImageFont.truetype(str(fontmod.FONT_PATH),16)
for ch,s in zip(missing,slots):
 code=bytes.fromhex(s['runtime_sjis']);mp[ch]=code;g=int(s['glyph']);off=fontmod.FONT_FILE_OFFSET+g*162;block=fontmod.render_glyph(ch,font);boot[off:off+162]=block;added.append(dict(hangul=ch,glyph_index=g,donor_sjis_hex=code.hex().upper(),font_file_offset=hex(off)))
assert len(added)==len(missing)==17;fontmod.verify_only_target_ranges(oldboot,boot,[r['glyph_index'] for r in added]);(OUT/'BOOT.bin').write_bytes(boot)
def enc(s):return b''.join(mp[c] if c in mp else (b'\xa0' if c==' ' else c.encode('cp932')) for c in s)
dat=OUT/'naruto.dat';idx=OUT/'naruto.idx';eb=bytearray(m.read_embedded_index(dat));xb=bytearray(idx.read_bytes());ei=m.parse_pidx(eb,'embedded');xi=m.parse_pidx(xb,'external');e=next(e for e in ei['primary'] if e['name']=='mugen.tbl')
with dat.open('rb') as f:f.seek(e['offset']);raw=m.decode_stored(f.read(e['zsize'] or e['size']),e['size'],e['zsize'])
lines=raw.splitlines(keepends=True);in_section=False;outlines=[];rows=[]
for line in lines:
 if line.strip()==b'[TUTORIAL]':in_section=True
 elif line.startswith(b'['):in_section=False
 hit=re.match(rb'#(\d{3})\s*=(.*?)(\r*\n)?$',line)
 if in_section and hit and hit[1].decode() in ko:
  k=hit[1].decode();jp=hit[2].decode('cp932');kr=ko[k]
  assert re.findall(r'<[^>]+>',jp)==re.findall(r'<[^>]+>',kr),(k,'control tokens changed')
  assert all(len(re.sub(r'<[^>]+>','',p))<=23 for p in kr.split('<br>'))
  nb=enc(kr);prefix=line[:hit.start(2)];outlines.append(prefix+nb+(hit[3] or b''));rows.append(dict(id=k,japanese=jp,korean=kr,jp_bytes=len(hit[2]),ko_bytes=len(nb),runtime_in_place=len(nb)<=len(hit[2])))
 else:outlines.append(line)
assert len(rows)==44
newraw=b''.join(outlines);(OUT/'mugen_ko.tbl').write_bytes(newraw);encoded=m.encode_3_0(newraw);assert m.decode_3x(encoded)==newraw
off=m.align_up(dat.stat().st_size)
with dat.open('ab') as f:f.write(bytes(off-f.tell()));f.write(encoded)
for blob,table in [(eb,ei),(xb,xi)]:
 rec=next(q for q in table['primary'] if q['name']=='mugen.tbl');struct.pack_into('<III',blob,rec['record_off']+12,off,len(newraw),len(encoded))
bundles=[]
with dat.open('r+b') as f:
 for r in ei['offset2_rows']:
  f.seek(r['file_off']);bundle=f.read(r['file_size']);rebuilt,changes=m.rebuild_fsts(bundle,r['name'],{'mugen.tbl':dict(original_sha256=m.sha256(raw),new_decoded=newraw)})
  if not changes:continue
  f.seek(0,2);o=m.align_up(f.tell());f.write(bytes(o-f.tell()));f.write(rebuilt)
  for blob,table in [(eb,ei),(xb,xi)]:
   q=next(q for q in table['offset2_rows'] if q['index']==r['index']);struct.pack_into('<II',blob,q['record_abs']+8,o,len(rebuilt))
  bundles.append(r['name'])
 f.seek(0);f.write(eb)
idx.write_bytes(xb)
target=OUT/'Naruto_KR_MOV06E_SUB40_Names_Tutorial.iso';shutil.copyfile(src,target)
with target.open('r+b') as f:
 vds=s15.read_volume_descriptors(f)
 for ip,p in [('PSP_GAME/USRDIR/naruto.dat',dat),('PSP_GAME/USRDIR/naruto.idx',idx),('PSP_GAME/SYSDIR/BOOT.BIN',OUT/'BOOT.bin'),('PSP_GAME/SYSDIR/EBOOT.BIN',OUT/'BOOT.bin')]:
  rs=[s15.find_path(f,vd,ip.split('/')) for vd in vds if vd['type'] in (1,2)];ext=s15.append_file_sector_aligned(f,p,p.name)
  for r in rs:
   if r:s15.patch_directory_record(f,r['record_offset'],ext['lba'],ext['size'])
 s15.update_volume_space(f,vds,(f.seek(0,2)+2047)//2048)
for name,rs in [('tutorial_translations.tsv',rows),('new_glyph_mapping.tsv',added)]:
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rs[0]),delimiter='\t');w.writeheader();w.writerows(rs)
report=dict(stage='SUB40',iso=str(target),tutorial_rows=44,new_safe_glyphs=17,old_mapping_unchanged=True,fsts_bundles=bundles,control_tokens_preserved=True,max_visible_chars_per_line=23,runtime_verified=False)
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));print('longer RAM strings',[r['id'] for r in rows if not r['runtime_in_place']])
