#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub50_mugen_atlas_surgical_restore"
ISO=OUT/"Naruto_KR_MOV06E_SUB50_MugenAtlasRestore.iso"
REP=OUT/"SUB50_static_verification.json"
sys.path.insert(0,str(ROOT/"tools"))
import macro_runtime as mr

TARGETS=[
 ("status","무환성 상태 상세: SUB49의 큰 한글 조각/잔상이 사라졌는지 확인"),
 ("item","무환성 아이템 화면: 회복/성장/중요 주변의 한글 오염과 우측 잔상이 사라졌는지 확인"),
 ("mugen_map","무환성 맵/방 선택: SUB45의 '격투의 방' 등 번역이 그대로인지 확인"),
 ("narup_help","나루P 로드 안내: 기존 한글 본문 회귀 확인"),
 ("speaker","가능하면 대화 장면의 화자명 한글 유지 확인. 접근이 번거로우면 s"),
 ("extra","추가 깨짐이 보이면 캡처, 없으면 s"),
]

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    rep=json.loads(REP.read_text(encoding="utf-8"));got=sha(ISO)
    if got!=rep["final_iso_sha256"]:raise RuntimeError("SUB50 ISO SHA mismatch")
    shots=OUT/"runtime_screenshots"
    if shots.exists():shutil.rmtree(shots)
    shots.mkdir()

    port=mr.choose_port();exe=Path(mr.PPSSPP)
    print("="*72);print("Naruto SUB50 Mugen Atlas Restore QA");print("="*72)
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

    qa=dict(stage="SUB50_RUNTIME_QA",iso_sha256=got,targets=manifest,
            captured=sum(x["status"]=="CAPTURED" for x in manifest))
    (OUT/"runtime_qa_report.json").write_text(
        json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();OUT.mkdir(parents=True,exist_ok=True)
        (OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        sys.exit(1)
