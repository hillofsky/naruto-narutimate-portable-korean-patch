#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil
ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub47_network_option_home"
ISO=OUT/"Naruto_KR_MOV06E_SUB47_Network_Option_Home.iso"
REP=OUT/"SUB47_static_verification.json"
sys.path.insert(0,str(ROOT/"tools"))
import macro_runtime as mr
TARGETS=[
 ("wireless","통신 대전: 대기실 입장/종료가 한국어로 표시되는 화면"),
 ("option","설정 변경: 난이도 설정과 쉬움/보통/어려움/매우 어려움 배치 확인"),
 ("narup_help","나루P 로드 첫 안내 페이지: 본문 번역 확인"),
 ("home_menu","나루토의 집: 이미지/음악/영상/사진 메뉴와 하단 설명 확인"),
 ("exit_prompt","종료 확인창: 예/아니요 회귀 확인"),
 ("extra","추가 일본어 잔재나 깨짐이 보이면 그 화면"),
]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
def main():
 rep=json.loads(REP.read_text(encoding="utf-8"));got=sha(ISO)
 if got!=rep["final_iso_sha256"]:raise RuntimeError("SUB47 ISO SHA mismatch")
 shots=OUT/"runtime_screenshots"
 if shots.exists():shutil.rmtree(shots)
 shots.mkdir()
 port=mr.choose_port();exe=Path(mr.PPSSPP)
 print("="*72);print("Naruto SUB47 Runtime QA");print("="*72);print("ISO:",ISO);print("SHA:",got)
 print("각 화면으로 이동 후 이 창으로 돌아와 Enter. s=건너뛰기, q=종료.")
 p=subprocess.Popen([str(exe),"-i",f"--debugger={port}",str(ISO)],cwd=str(exe.parent))
 ws=mr.load_websocket_class()("127.0.0.1",port);manifest=[]
 try:
  ws.connect(timeout=30);c=mr.DebuggerConnection(ws)
  try:c.send_oneway("cpu.resume")
  except:pass
  time.sleep(3);idx=1
  for key,desc in TARGETS:
   print("\n"+"-"*72);print(f"[{idx}/{len(TARGETS)}] {key}");print(desc)
   ans=input("준비 후 Enter / s / q : ").strip().lower()
   if ans=="q":manifest.append(dict(target=key,status="USER_END",file=""));break
   if ans=="s":manifest.append(dict(target=key,status="SKIPPED",file=""));idx+=1;continue
   if p.poll() is not None:raise RuntimeError("PPSSPP exited")
   before=set(shots.glob("*.png"));mr.save_screenshot(c,shots,idx);time.sleep(.25)
   pp=sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime);new=sorted(set(pp)-before,key=lambda x:x.stat().st_mtime)
   src=new[-1] if new else pp[-1];dst=shots/f"{idx:02d}_{key}.png"
   if src.resolve()!=dst.resolve():src.rename(dst)
   manifest.append(dict(target=key,status="CAPTURED",file=dst.name));print("saved",dst);idx+=1
 finally:
  try:ws.close()
  except:pass
  if p.poll() is None:print("PPSSPP remains open.")
 qa=dict(stage="SUB47_RUNTIME_QA",iso_sha256=got,targets=manifest,captured=sum(x["status"]=="CAPTURED" for x in manifest))
 (OUT/"runtime_qa_report.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":
 try:main()
 except Exception:
  traceback.print_exc();OUT.mkdir(parents=True,exist_ok=True);(OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8");sys.exit(1)
