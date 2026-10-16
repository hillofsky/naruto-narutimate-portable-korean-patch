#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub45_menu_followup"
ISO=OUT/"Naruto_KR_MOV06E_SUB45_MenuFollowup.iso"
REPORT=OUT/"SUB45_static_verification.json"
TOOLS=ROOT/"tools"
sys.path.insert(0,str(TOOLS))
import macro_runtime as mr

TARGETS=[
 ("mugen_map","무환성 맵 화면: 왼쪽 방 미리보기 제목과 하단 조작 안내가 한국어인지 확인"),
 ("wireless","통신 대전 화면: 대기실 입장/종료와 하단 설명이 한국어인지 확인"),
 ("exit_prompt","모드 종료 확인창: 질문/예/아니요/하단 설명이 한국어인지 확인"),
 ("option","설정 화면: 난이도 선택 글자가 잘리거나 깨지는 현재 문제를 다시 기록"),
 ("extra","남은 일본어 이미지나 깨짐이 보이면 그 화면"),
]

def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()

def main():
 if not ISO.exists() or not REPORT.exists():raise RuntimeError("SUB45 build outputs missing")
 rep=json.loads(REPORT.read_text(encoding="utf-8"))
 exp=rep["final_iso_sha256"];got=sha(ISO)
 if got!=exp:raise RuntimeError(f"SUB45 SHA mismatch expected={exp} got={got}")
 shots=OUT/"runtime_screenshots"
 if shots.exists():
  import shutil;shutil.rmtree(shots)
 shots.mkdir(parents=True)
 port=mr.choose_port();exe=Path(mr.PPSSPP)
 print("="*72);print("Naruto SUB45 Runtime QA");print("="*72)
 print("ISO:",ISO);print("SHA:",got)
 print("각 화면으로 이동 후 이 창으로 돌아와 Enter. s=건너뛰기, q=종료.")
 p=subprocess.Popen([str(exe),"-i",f"--debugger={port}",str(ISO)],cwd=str(exe.parent))
 ws=mr.load_websocket_class()("127.0.0.1",port);manifest=[]
 try:
  ws.connect(timeout=30);c=mr.DebuggerConnection(ws)
  try:c.send_oneway("cpu.resume")
  except:pass
  time.sleep(3)
  idx=1
  for key,desc in TARGETS:
   print("\n"+"-"*72);print(f"[{idx}/{len(TARGETS)}] {key}");print(desc)
   ans=input("준비 후 Enter / s / q : ").strip().lower()
   if ans=="q":manifest.append(dict(target=key,status="USER_END",file=""));break
   if ans=="s":manifest.append(dict(target=key,status="SKIPPED",file=""));idx+=1;continue
   if p.poll() is not None:raise RuntimeError("PPSSPP exited")
   before=set(shots.glob("*.png"));mr.save_screenshot(c,shots,idx);time.sleep(.25)
   new=sorted(set(shots.glob("*.png"))-before,key=lambda x:x.stat().st_mtime)
   src=new[-1] if new else sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime)[-1]
   dst=shots/f"{idx:02d}_{key}.png"
   if src.resolve()!=dst.resolve():src.rename(dst)
   print("saved",dst);manifest.append(dict(target=key,status="CAPTURED",file=dst.name));idx+=1
 finally:
  try:ws.close()
  except:pass
  if p.poll() is None:print("PPSSPP remains open.")
 qa=dict(stage="SUB45_RUNTIME_QA",iso_sha256=got,targets=manifest,captured=sum(x["status"]=="CAPTURED" for x in manifest))
 (OUT/"runtime_qa_report.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print("Capture complete:",qa["captured"])

if __name__=="__main__":
 try:main()
 except Exception:
  traceback.print_exc()
  OUT.mkdir(parents=True,exist_ok=True)
  (OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
  sys.exit(1)
