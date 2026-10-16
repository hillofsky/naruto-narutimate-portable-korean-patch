#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub49_safe_atlas_rollback"
ISO=OUT/"Naruto_KR_MOV06E_SUB49_SafeAtlasRollback.iso"
REP=OUT/"SUB49_static_verification.json"
sys.path.insert(0,str(ROOT/"tools"))
import macro_runtime as mr

TARGETS=[
 ("option","설정 화면: 일본어로 돌아가도 괜찮으니 글자 겹침/잔상이 사라졌는지 확인"),
 ("status","무환성 상태 상세: SUB48처럼 한글 조각이 겹치지 않고 원래 UI가 정상인지 확인"),
 ("narup_help","나루P 로드: SUB48에서 정상화한 본문 마지막 줄이 유지되는지 확인"),
 ("home_menu","나루토의 집: 하단 '사진 확인' 등 SUB48 문자열 개선이 유지되는지 확인"),
 ("wireless","통신 대전: SUB47의 대기실 입장/종료 한글 이미지가 유지되는지 확인"),
 ("extra","추가 깨짐이 있으면 캡처, 없으면 s"),
]

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    rep=json.loads(REP.read_text(encoding="utf-8"));got=sha(ISO)
    if got!=rep["final_iso_sha256"]:raise RuntimeError("SUB49 ISO SHA mismatch")
    shots=OUT/"runtime_screenshots"
    if shots.exists():shutil.rmtree(shots)
    shots.mkdir()

    port=mr.choose_port();exe=Path(mr.PPSSPP)
    print("="*72);print("Naruto SUB49 Safe Rollback Runtime QA");print("="*72)
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
            before=set(shots.glob("*.png"));mr.save_screenshot(c,shots,idx);time.sleep(.3)
            pp=sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime)
            new=sorted(set(pp)-before,key=lambda x:x.stat().st_mtime)
            if not pp:raise RuntimeError("Screenshot missing")
            src=new[-1] if new else pp[-1];dst=shots/f"{idx:02d}_{key}.png"
            if src.resolve()!=dst.resolve():src.rename(dst)
            manifest.append(dict(target=key,status="CAPTURED",file=dst.name));print("saved",dst);idx+=1
    finally:
        try:ws.close()
        except:pass
        if p.poll() is None:print("PPSSPP remains open.")

    qa=dict(stage="SUB49_RUNTIME_QA",iso_sha256=got,targets=manifest,
            captured=sum(x["status"]=="CAPTURED" for x in manifest))
    (OUT/"runtime_qa_report.json").write_text(
        json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc()
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        sys.exit(1)
