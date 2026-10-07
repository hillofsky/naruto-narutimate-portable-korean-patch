#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys, time, subprocess, json, hashlib, shutil, traceback

ROOT = Path(r"D:\narutimate portable")
ISO = ROOT / r"analysis\sub\sub43_menu_images\Naruto_KR_MOV06E_SUB43_MenuImages.iso"
EXPECTED_SHA = "9c565369ac5cf6ccf5fb2898577503a5cac43ab0aec297482ba76698eeba3433"
OUT = ROOT / r"analysis\sub\sub43_runtime_qa"
TOOLS = ROOT / "tools"

sys.path.insert(0, str(TOOLS))
import macro_runtime as mr

TARGETS = [
    ("mode_select", "모드 선택 화면: 무환성/강적과의 결투/나루P 로드/나루토의 집/설정 변경/통신 대전/이면 무환성 중 번역 패널이 보이는 화면"),
    ("option", "설정 변경 화면: 난이도 설정/조작 설정/음량 설정/종료와 난이도 항목이 보이는 화면"),
    ("char_select", "캐릭터 선택 화면: 한글 캐릭터 이름과 '전투 장소'가 보이는 화면"),
    ("mugen_status", "무환성 상태/상세 화면: 상태/대장/대원/체력/차크라/대장 능력/스킬 효과 등이 보이는 화면"),
    ("gauge_menu", "공통 메뉴 화면: 설정 변경/맵 선택/캐릭터 선택/규칙·모드 선택 또는 확인/뒤로/다음 등의 버튼 문구가 보이는 화면"),
    ("battle_setting", "대전 설정 화면: '대전' 또는 관련 설정 문구가 보이는 화면"),
    ("extra_problem", "추가 확인 화면: 일본어 잔재, 글자 잘림, 깨진 색/투명도 등이 보이면 그 화면"),
]

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def latest_png_before_after(folder: Path, before):
    after=set(folder.glob("*.png"))
    new=sorted(after-before, key=lambda p:p.stat().st_mtime)
    return new[-1] if new else None

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots=OUT/"screenshots"
    if shots.exists():
        shutil.rmtree(shots)
    shots.mkdir()

    if not ISO.exists():
        raise RuntimeError(f"SUB43 ISO not found: {ISO}")
    got=sha256(ISO)
    if got.lower()!=EXPECTED_SHA:
        raise RuntimeError(f"SUB43 ISO SHA mismatch\nExpected={EXPECTED_SHA}\nActual={got}")

    port=mr.choose_port()
    exe=Path(mr.PPSSPP)
    print("="*72)
    print("Naruto SUB43 Runtime Menu QA")
    print("="*72)
    print("ISO :",ISO)
    print("SHA :",got)
    print("PPSSPP:",exe)
    print()
    print("PPSSPP가 실행됩니다.")
    print("각 대상 화면으로 직접 이동한 뒤 PowerShell 창으로 Alt+Tab하여 Enter를 누르세요.")
    print("해당 화면에 갈 수 없으면 s + Enter, 검증을 끝내려면 q + Enter.")
    print()

    p=subprocess.Popen(
        [str(exe), "-i", f"--debugger={port}", str(ISO)],
        cwd=str(exe.parent)
    )
    ws=mr.load_websocket_class()("127.0.0.1", port)
    manifest=[]
    try:
        ws.connect(timeout=30)
        c=mr.DebuggerConnection(ws)
        try:
            print("Debugger:",c.request("version"),flush=True)
        except Exception:
            pass
        try:
            c.send_oneway("cpu.resume")
        except Exception:
            pass
        time.sleep(3)

        idx=1
        for key,desc in TARGETS:
            print("\n"+"-"*72)
            print(f"[{idx}/{len(TARGETS)}] {key}")
            print(desc)
            ans=input("화면 준비 후 Enter / 건너뛰기 s / 종료 q : ").strip().lower()
            if ans=="q":
                manifest.append({"target":key,"status":"USER_END","file":""})
                break
            if ans=="s":
                manifest.append({"target":key,"status":"SKIPPED","file":""})
                idx+=1
                continue
            if p.poll() is not None:
                raise RuntimeError("PPSSPP가 캡처 전에 종료되었습니다.")

            before=set(shots.glob("*.png"))
            mr.save_screenshot(c, shots, idx)
            time.sleep(.3)
            new=latest_png_before_after(shots,before)
            if new is None:
                # save_screenshot normally uses numeric name; fall back to newest.
                pp=sorted(shots.glob("*.png"),key=lambda x:x.stat().st_mtime)
                new=pp[-1] if pp else None
            if new:
                dst=shots/f"{idx:02d}_{key}.png"
                if new.resolve()!=dst.resolve():
                    if dst.exists(): dst.unlink()
                    new.rename(dst)
                print("저장:",dst)
                manifest.append({"target":key,"status":"CAPTURED","file":dst.name})
            else:
                manifest.append({"target":key,"status":"CAPTURE_FAILED","file":""})
            idx+=1

        print("\n캡처가 끝났습니다. PPSSPP는 닫아도 됩니다.")
    finally:
        try: ws.close()
        except Exception: pass
        # Do not kill PPSSPP abruptly if the user still wants to inspect it.
        try:
            if p.poll() is None:
                print("PPSSPP는 실행 상태로 남겨둡니다.")
        except Exception:
            pass

    report={
        "stage":"SUB43_RUNTIME_MENU_QA",
        "iso":str(ISO),
        "iso_sha256":got,
        "targets":manifest,
        "captured":sum(x["status"]=="CAPTURED" for x in manifest),
        "runtime_visual_review":"PENDING_CHATGPT_REVIEW",
        "game_files_modified":False,
    }
    (OUT/"runtime_qa_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"SUMMARY.txt").write_text(
        "Naruto SUB43 Runtime Menu QA\n\n"
        f"ISO_SHA256={got}\n"
        f"Captured={report['captured']}\n"
        "GameFilesModified=NO\n"
        "VisualReview=PENDING_CHATGPT_REVIEW\n",
        encoding="utf-8-sig"
    )
    print("\nRuntime QA capture complete.")
    print("Folder:",OUT)

if __name__=="__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/"FAILURE.txt").write_text(traceback.format_exc(),encoding="utf-8")
        sys.exit(1)
