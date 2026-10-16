#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,subprocess,json,hashlib,traceback,shutil

ROOT=Path(r"PROJECT_ROOT")
OUT=ROOT/r"analysis\sub\sub48_menu_atlas_cleanup"
ISO=OUT/"Naruto_KR_MOV06E_SUB48_MenuAtlasCleanup.iso"
REP=OUT/"SUB48_static_verification.json"
sys.path.insert(0,str(ROOT/"tools"))
import macro_runtime as mr

TARGETS=[
 ("option","설정 변경: 난이도 행에서 '료' 잔재가 사라지고 난이도/보통/종료가 정상인지 확인"),
 ("narup_help","나루P 로드: 상단 제목이 한글인지, 안내 마지막 줄까지 한국어인지 확인"),
 ("home_menu","나루토의 집: 이미지/음악/영상/사진 선택 후 하단 설명이 한국어인지 확인"),
 ("gauge_extra","맵/캐릭터 선택 또는 결과 화면 등 gauge 메뉴에서 일본어 잔재가 보이면 캡처"),
 ("rpg_menu","소지품/임무/자택 등이 있는 RPG 메뉴에 접근 가능하면 캡처, 불가능하면 s"),
 ("extra","추가 일본어 잔재나 깨짐이 보이면 캡처"),
]

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def main():
    rep=json.loads(REP.read_text(encoding="utf-8"));got=sha(ISO)
    if got!=rep["final_iso_sha256"]:raise RuntimeError("SUB48 ISO SHA mismatch")
    shots=OUT/"runtime_screenshots"
    if shots.exists():shutil.rmtree(shots)
    shots.mkdir()
    port=mr.choose_port();exe=Path(mr.PPSSPP)
    print("="*72);print("Naruto SUB48 Runtime QA");print("="*72)
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
    qa=dict(stage="SUB48_RUNTIME_QA",iso_sha256=got,targets=manifest,
            captured=sum(x["status"]=="CAPTURED" for x in manifest))
    (OUT/"runtime_qa_report.json").write_text(
        json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    try:main()
    except Exception:
        traceback.print_exc();OUT.mkdir(parents=True,exist_ok=True)
        (OUT/"RUNTIME_FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        sys.exit(1)
