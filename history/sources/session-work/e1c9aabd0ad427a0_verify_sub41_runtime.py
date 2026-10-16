from pathlib import Path
import sys,os,time,json
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as mr,play_controller_macro as player
mr.MEMSTICK=Path('work/slot1/memstick').resolve();os.startfile=lambda p:None
opened={};orig=player.launch_game
def launch(iso):
 p,ws,c,iso=orig(iso);opened.update(pid=p.pid,port=ws.port);return p,ws,c,iso
player.launch_game=launch
sys.argv=['sub41',r'PROJECT_ROOT\analysis\sub\sub41_names_guides_menu\Naruto_KR_MOV06E_SUB41_Names_Guides_Menu.iso',r'PROJECT_ROOT\generated_macros\naruto.json'];player.main()
out=Path('work/sub41_runtime');out.mkdir(exist_ok=True);(out/'connection.json').write_text(json.dumps(opened),encoding='utf-8')
ws=mr.load_websocket_class()('127.0.0.1',opened['port']);ws.connect(timeout=15);c=mr.DebuggerConnection(ws)
try:
 for i in range(40):
  c.request('input.buttons.press',button='circle',duration=2);time.sleep(1)
  if i%4==0:mr.save_screenshot(c,out,i+1)
 mr.save_screenshot(c,out,41)
finally:ws.close()
