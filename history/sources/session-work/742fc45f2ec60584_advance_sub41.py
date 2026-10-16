from pathlib import Path
import sys,json,time
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as mr
info=json.loads(Path('work/sub41_runtime/connection.json').read_text());ws=mr.load_websocket_class()('127.0.0.1',info['port']);ws.connect();c=mr.DebuggerConnection(ws);out=Path('work/sub41_runtime/advance')
try:
 print(c.request('version'),flush=True)
 for i in range(100):
  c.request('input.buttons.press',button='circle',duration=2);time.sleep(.8)
  if i%10==0:mr.save_screenshot(c,out,i+1)
 mr.save_screenshot(c,out,101)
finally:ws.close()
