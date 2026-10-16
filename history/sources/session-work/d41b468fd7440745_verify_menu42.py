from pathlib import Path
import sys,json,csv,base64,time
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as m
info=json.loads(Path('work/sub41_runtime/connection.json').read_text());w=m.load_websocket_class()('127.0.0.1',info['port']);w.connect();c=m.DebuggerConnection(w)
try:
 c.send_oneway('cpu.stepping');time.sleep(.5);ram=bytearray()
 for addr in range(0x08000000,0x0a000000,0x100000):ram+=base64.b64decode(c.request('memory.read',address=addr,size=0x100000)['base64'])
 mp={r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((m.BASE/'analysis/shared/event_font_hangul_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')};mp.update({r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((m.BASE/'analysis/sub/sub40_tutorial/new_glyph_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')})
 count=0
 for jp,ko in json.loads(Path('work/menu_text_ko.json').read_text(encoding='utf-8')).items():
  needle=jp.encode('cp932');nb=b''.join(mp[ch] if ch in mp else b'\xa0' if ch==' ' else ch.encode('cp932') for ch in ko);assert len(nb)<=len(needle)
  pos=0
  while True:
   i=ram.find(needle+b'\0',pos)
   if i<0:break
   pos=i+len(needle)
   if i>0 and ram[i-1] not in (0,ord('=')):continue
   c.request('memory.write',address=0x08000000+i,base64=base64.b64encode(nb+bytes(len(needle)+1-len(nb))).decode());count+=1
 c.send_oneway('cpu.resume');time.sleep(1);m.save_screenshot(c,Path('work/sub42_runtime'),1);c.request('input.buttons.press',button='circle',duration=2);time.sleep(1);m.save_screenshot(c,Path('work/sub42_runtime'),2);print('runtime replacements',count)
finally:c.send_oneway('cpu.resume');w.close()
