from pathlib import Path
import sys,base64,json,time
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as mr
port=int(sys.argv[1]);out=Path('work/live');out.mkdir(exist_ok=True)
ws=mr.load_websocket_class()('127.0.0.1',port);ws.connect(timeout=15);c=mr.DebuggerConnection(ws)
try:
 print(c.request('version'),flush=True);c.send_oneway('cpu.stepping');time.sleep(0.5)
 for region,start,size in [('ram',0x08000000,0x2000000),('vram',0x04000000,0x200000)]:
  data=bytearray()
  for a in range(start,start+size,0x100000):
   r=c.request('memory.read',address=a,size=0x100000,timeout=30);data+=base64.b64decode(r['base64'])
  (out/(region+'.bin')).write_bytes(data)
 print('dump complete',flush=True)
finally:c.send_oneway('cpu.resume');ws.close()
