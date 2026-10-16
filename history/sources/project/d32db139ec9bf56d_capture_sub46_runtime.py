#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub46_ui_cleanup_discovery"
ISO=OUT/"Naruto_KR_MOV06E_SUB46_UICleanup.iso"
REPORT=OUT/"SUB46_static_verification.json"
TOOLS=ROOT/"tools"
sys.path.insert(0,str(TOOLS))
import macro_runtime as mr

TARGETS=[
 ("wireless","통신 대전 화면: 대기실 입장/종료가 바뀌었는지 확인"),
 ("exit_prompt","모드 종료 확인창: 선택된 예/아니요가 모두 한국어인지 확인"),
 ("home_help","나루토의 집 첫 안내문: 나루P 로드 안내가 한국어인지 확인"),
 ("option","설정 화면: 난이도 행의 현재 깨짐 상태 기록"),
 ("extra","추가 일본어 잔재나 깨짐이 보이면 그 화면"),
]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()

def main():
 if not ISO.exists() or not REPORT.exists():raise RuntimeError("SUB46 build outputs missing")
 rep=json.loads(REPORT.read_text(encoding="utf-8"));exp=rep["final_iso_sha256"];got=sha(ISO)
 if got!=exp:raise RuntimeError(f"SUB46 SHA mismatch expected={exp} got={got}")
 shots=OUT/"runtime_screenshots"
 if shots.exists():shutil.rmtree(shots)
 shots.mkdir(parents=True)
 port=mr.choose_port();exe=Path(mr.PPSSPP)
 print("="*72);print("Naruto SUB46 Runtime QA");print("="*72)
 print("ISO:",ISO);print("SHA:",got)
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
   allp=sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime)
   new=sorted(set(allp)-before,key=lambda x:x.stat().st_mtime);src=new[-1] if new else allp[-1]
   dst=shots/f"{idx:02d}_{key}.png"
   if src.resolve()!=dst.resolve():src.rename(dst)
   print("saved",dst);manifest.append(dict(target=key,status="CAPTURED",file=dst.name));idx+=1
 finally:
  try:ws.close()
  except:pass
  if p.poll() is None:print("PPSSPP remains open.")
 qa=dict(stage="SUB46_RUNTIME_QA",iso_sha256=got,targets=manifest,captured=sum(x["status"]=="CAPTURED" for x in manifest))
 (OUT/"runtime_qa_report.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print("Capture complete:",qa["captured"])

if __name__=="__main__":
 try:main()
 except Exception:
  traceback.print_exc()
  OUT.mkdir(parents=True,exist_ok=True)
  (OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
  sys.exit(1)
