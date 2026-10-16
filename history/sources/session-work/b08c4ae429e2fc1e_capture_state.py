from pathlib import Path
import sys,time,subprocess,json,base64,shutil,csv
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as mr
out=Path('work/slot1');out.mkdir(exist_ok=True)
ms=(out/'memstick').resolve();(ms/'PSP/SYSTEM').mkdir(parents=True,exist_ok=True)
ini=mr.MEMSTICK/'PSP/SYSTEM/ppsspp.ini'
t=ini.read_text(encoding='utf-8-sig');t=t.replace('SaveNewTextures = False','SaveNewTextures = True').replace('ReplaceTextures = False','ReplaceTextures = True')
(ms/'PSP/SYSTEM/ppsspp.ini').write_text(t,encoding='utf-8')
port=mr.choose_port();iso=Path(r'PROJECT_ROOT\analysis\integrated\sub36_semantic_qa\output\Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso')
state=Path('work/sub38/slot1_state/ULKS46086_1.00_0.ppst').resolve()
if '--statefile' in sys.argv:state=Path(sys.argv[sys.argv.index('--statefile')+1]).resolve()
if '--iso' in sys.argv:iso=Path(sys.argv[sys.argv.index('--iso')+1]).resolve()
p=subprocess.Popen([str(mr.PPSSPP),'-i',f'--debugger={port}',f'--memstick={ms}',f'--state={state}',str(iso)],cwd=str(mr.PPSSPP.parent))
ws=mr.load_websocket_class()('127.0.0.1',port)
try:
 ws.connect(timeout=30);c=mr.DebuggerConnection(ws);print(c.request('version'),flush=True);time.sleep(3)
 print(c.request('game.status'),flush=True);c.send_oneway('cpu.resume');time.sleep(10)
 mr.save_screenshot(c,out,1)
 c.send_oneway('cpu.stepping');time.sleep(1)
 ram=bytearray()
 for addr in range(0x08000000,0x0a000000,0x100000):
  r=c.request('memory.read',address=addr,size=0x100000,timeout=30);ram+=base64.b64decode(r['base64'])
 (out/'ram.bin').write_bytes(ram)
 if '--patch' in sys.argv:
  guide=mr.BASE/'analysis/sub/sub40_tutorial';boot=(guide/'BOOT.bin').read_bytes();original=(mr.BASE/'kr_extracted/PSP_GAME/SYSDIR/BOOT.BIN').read_bytes();off=0x39cd04;fb=ram.find(original[off:off+1000]);assert fb>=0 and ram.count(original[off:off+1000])==1
  c.request('memory.write',address=0x08000000+fb,base64=base64.b64encode(boot[off:off+3600*162]).decode(),timeout=30)
  mapping={r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((mr.BASE/'analysis/shared/event_font_hangul_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')}
  mapping.update({r['hangul']:bytes.fromhex(r['donor_sjis_hex']) for r in csv.DictReader((guide/'new_glyph_mapping.tsv').open(encoding='utf-8-sig'),delimiter='\t')})
  changed=[]
  for r in csv.DictReader((guide/'tutorial_translations.tsv').open(encoding='utf-8-sig'),delimiter='\t'):
   needle=r['japanese'].encode('cp932');nb=b''.join(mapping[ch] if ch in mapping else b'\xa0' if ch==' ' else ch.encode('cp932') for ch in r['korean'])
   if len(nb)>len(needle):continue
   pos=0
   while True:
    i=ram.find(needle+b'\0',pos)
    if i<0:break
    pos=i+len(needle);c.request('memory.write',address=0x08000000+i,base64=base64.b64encode(nb+bytes(len(needle)+1-len(nb))).decode());changed.append((r['id'],hex(0x08000000+i)))
  (out/'runtime_patch.json').write_text(json.dumps(changed,indent=2),encoding='utf-8');print('runtime text patches',len(changed),flush=True)
 c.send_oneway('cpu.resume');print('RAM',len(ram),flush=True)
 if '--patch' in sys.argv:
  time.sleep(1);mr.save_screenshot(c,out,2);c.request('input.buttons.press',button='circle',duration=2);time.sleep(1);mr.save_screenshot(c,out,3)
 if '--verify-menu' in sys.argv:
  c.request('input.buttons.press',button='circle',duration=2);time.sleep(1);mr.save_screenshot(c,out,2)
  c.request('input.buttons.press',button='circle',duration=2);time.sleep(1)
  c.request('input.buttons.press',button='triangle',duration=2);time.sleep(1);mr.save_screenshot(c,out,3)
finally:
 ws.close();p.terminate();p.wait(timeout=15)
