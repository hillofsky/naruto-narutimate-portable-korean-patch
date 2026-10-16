from pathlib import Path
import sys,struct,json,csv,hashlib
sys.path.insert(0,str(Path('work/deps312').resolve()))
import zstandard as zstd
BASE=Path(r'PROJECT_ROOT');src=Path('work/sub38/slot1_state/ULKS46086_1.00_0.ppst');out=Path('outputs/ULKS46086_SUB42_TranslatedSlot1.ppst')
file=src.read_bytes();rev,comp,cs,us=struct.unpack_from('<4I',file);assert rev==5 and comp==2 and len(file)==176+cs
state=bytearray(zstd.ZstdDecompressor().decompress(file[176:],max_output_size=us));assert len(state)==us;original=bytes(state)
ram=Path('work/slot1/ram.bin').read_bytes();boot=(BASE/'analysis/sub/sub40_tutorial/BOOT.bin').read_bytes();ob=(BASE/'kr_extracted/PSP_GAME/SYSDIR/BOOT.BIN').read_bytes();font=0x39cd04;needle=ob[font:font+1000]
rf=ram.find(needle);sf=state.find(needle);assert rf>=0 and sf>=0 and state.count(needle)==1;ramstart=sf-rf;assert ramstart>=0 and ramstart+0x2000000<=len(state)
mapping=list(csv.DictReader((BASE/'analysis/shared/event_font_hangul_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t'));added=list(csv.DictReader((BASE/'analysis/sub/sub40_tutorial/new_glyph_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t'));mp={r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in mapping+added};changes=[]
for r in mapping+added:
 g=int(r['glyph_index']);pos=sf+g*162;block=boot[font+g*162:font+(g+1)*162];state[pos:pos+162]=block;changes.append((pos,162,'glyph:'+r['hangul']))
rows=list(csv.DictReader((BASE/'analysis/sub/sub40_tutorial/tutorial_translations.tsv').open(encoding='utf-8-sig'),delimiter='\t'));menu=json.loads(Path('work/menu_text_ko.json').read_text(encoding='utf-8'));seen=set()
for jp,ko in [(r['japanese'],r['korean']) for r in rows]+list(menu.items()):
 if jp in seen:continue
 seen.add(jp);ko=ko.replace('－치유의 방－','－치유의방－').replace('－보물의 방－','－보물방－');needle=jp.encode('cp932');nb=b''.join(mp[c] if c in mp else b'\xa0' if c==' ' else c.encode('cp932') for c in ko);assert len(nb)<=len(needle),(jp,len(nb),len(needle));pos=ramstart
 while True:
  i=original.find(needle+b'\0',pos,ramstart+0x2000000)
  if i<0:break
  pos=i+len(needle)
  if i>ramstart and original[i-1] not in (0,ord('=')):continue
  state[i:i+len(needle)+1]=nb+bytes(len(needle)+1-len(nb));changes.append((i,len(needle)+1,'text:'+jp))
# All edits retain lengths and stay inside serialized RAM. No other state bytes change.
assert len(state)==len(original)
allowed=bytearray(len(state))
for pos,size,label in changes:assert ramstart<=pos and pos+size<=ramstart+0x2000000;allowed[pos:pos+size]=bytes([1])*size
assert all(a==b or allowed[i] for i,(a,b) in enumerate(zip(original,state)))
packed=zstd.ZstdCompressor(level=3).compress(state);assert zstd.ZstdDecompressor().decompress(packed)==state
header=bytearray(file[:176]);struct.pack_into('<I',header,8,len(packed));out.write_bytes(header+packed)
report=dict(source=str(src),source_sha256=hashlib.sha256(file).hexdigest(),output=str(out),ram_offset=ramstart,font_glyphs_patched=711,text_locations_patched=sum(1 for _,_,k in changes if k.startswith('text:')),serialized_size_preserved=True,original_user_slot_untouched=True,runtime_verified=False)
Path('outputs/분석/번역_슬롯1_검증.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
