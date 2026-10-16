#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil

ROOT=Path(r"PROJECT_ROOT")
STAGE=ROOT/r"analysis\sub\sub44_ui_cleanup"
ISO=STAGE/"Naruto_KR_MOV06E_SUB44_UITextCleanup.iso"
REPORT=STAGE/"SUB44_static_verification.json"
TOOLS=ROOT/"tools"
sys.path.insert(0,str(TOOLS))
import macro_runtime as mr

TARGETS=[
 ("mode_select","모드 선택 화면: 아래 설명문이 한국어인지 확인"),
 ("option","설정 변경 화면: 난이도 4단계가 잘리지 않고, 아래 도움말이 한국어인지 확인"),
 ("wireless","통신 대전 화면: '대기실 입장/종료'와 아래 설명문이 한국어인지 확인"),
 ("exit_prompt","모드 종료 확인창: 질문/예/아니요/아래 설명문이 한국어인지 확인"),
 ("extra_problem","SUB44에서도 일본어 잔재나 글자 깨짐이 보이면 그 화면"),
]

def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()

def main():
 if not ISO.exists() or not REPORT.exists(): raise RuntimeError("SUB44 build output missing")
 rep=json.loads(REPORT.read_text(encoding="utf-8"))
 expected=rep["final_iso_sha256"]; got=sha(ISO)
 if got!=expected: raise RuntimeError(f"SUB44 ISO SHA mismatch: {got}")
 shots=STAGE/"runtime_screenshots"
 if shots.exists():shutil.rmtree(shots)
 shots.mkdir()
 port=mr.choose_port(); exe=Path(mr.PPSSPP)
 print("="*72);print("Naruto SUB44 Runtime QA");print("="*72)
 print("ISO:",ISO);print("SHA:",got)
 print("각 화면으로 이동 후 이 창으로 돌아와 Enter. s=건너뛰기, q=종료.")
 p=subprocess.Popen([str(exe),"-i",f"--debugger={port}",str(ISO)],cwd=str(exe.parent))
 ws=mr.load_websocket_class()("127.0.0.1",port)
 rows=[]
 try:
  ws.connect(timeout=30);c=mr.DebuggerConnection(ws)
  try:c.send_oneway("cpu.resume")
  except:pass
  time.sleep(3)
  i=1
  for key,desc in TARGETS:
   print("\n"+("-"*72));print(f"[{i}/{len(TARGETS)}] {key}");print(desc)
   ans=input("준비 후 Enter / s / q : ").strip().lower()
   if ans=="q":rows.append({"target":key,"status":"USER_END","file":""});break
   if ans=="s":rows.append({"target":key,"status":"SKIPPED","file":""});i+=1;continue
   if p.poll() is not None:raise RuntimeError("PPSSPP exited")
   before=set(shots.glob("*.png"))
   mr.save_screenshot(c,shots,i);time.sleep(.3)
   after=sorted(set(shots.glob("*.png"))-before,key=lambda x:x.stat().st_mtime)
   if not after:
    allp=sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime)
    new=allp[-1] if allp else None
   else:new=after[-1]
   if new:
    dst=shots/f"{i:02d}_{key}.png"
    if new.resolve()!=dst.resolve():
     if dst.exists():dst.unlink()
     new.rename(dst)
    rows.append({"target":key,"status":"CAPTURED","file":dst.name});print("saved",dst)
   else:rows.append({"target":key,"status":"CAPTURE_FAILED","file":""})
   i+=1
 finally:
  try:ws.close()
  except:pass
  if p.poll() is None:print("PPSSPP remains open.")
 out={"stage":"SUB44_RUNTIME_QA","iso_sha256":got,"targets":rows,"captured":sum(x["status"]=="CAPTURED" for x in rows)}
 (STAGE/"runtime_qa_report.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print("Capture complete:",out["captured"])

if __name__=="__main__":
 try:main()
 except Exception:
  traceback.print_exc()
  STAGE.mkdir(parents=True,exist_ok=True)
  (STAGE/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
  sys.exit(1)
