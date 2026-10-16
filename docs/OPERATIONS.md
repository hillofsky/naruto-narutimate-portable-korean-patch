# 운영 절차

## 새 세션 점검 (게임 자료 불필요)

저장소 루트에서 Python 3.9+로 실행한다. 현재 작업 디렉터리에 의존하지 않고 스크립트 위치를 기준으로 점검한다.

```powershell
python tools/check_resume.py
git status --short
git diff --check
```

점검은 문서 존재와 docs/resume_baseline.json에 고정한 파일의 SHA-256만 확인한다. 실패하면 원인을 확인하고 기준 문서를 검토한다. 통과시키기 위해 해시만 자동 재생성하지 않는다. 고정 해시는 이번에 읽은 저장소 파일의 기준이며 게임 출력 검증 결과가 아니다.

## 로컬 자료

원본 ISO·중간 결과·추출 자료·개인 세이브는 저장소 밖 또는 무시되는 local/에 둔다. 원본은 읽기 전용으로 취급하며 기존 결과를 덮어쓰지 않는다. Python과 xdelta3가 필요하고, PPSSPP는 별도로 준비한다. 이 저장소에는 게임 자료나 xdelta 실행 파일이 없다. 릴리즈 링크와 입력/출력 해시는 README 및 해당 manifest를 따른다.

## 배포 패치 재현

v0.1.0은 patch/, SUB52U preview는 patch/sub52/에 해당 릴리즈 xdelta와 manifest를 받는다. 다음은 preview 적용 예시다. SOURCE.iso/OUTPUT.iso는 사용자가 정한 저장소 밖 경로로 대체한다.

```powershell
python work/apply_patch.py --manifest patch/sub52/manifest.json --source "SOURCE.iso" --output "OUTPUT.iso" --xdelta "xdelta3.exe"
```

도구는 원본/패치/출력 크기와 해시를 검사한다. 기존 패치 ISO에 누적 패치를 다시 적용하지 않는다. 전체 개발 재빌드 의존성과 보존 규칙은 docs/AI_HANDOFF.md를 따른다. work/sub52/sub52u_safe_cleanup/run.ps1은 삭제 기능이 있어 재개 점검에 포함하지 않는다.

## 실행 후 검증과 종료

결과 해시 일치 → PPSSPP normal boot → 알려진 화면 재현 → 일반 저장/불러오기 및 추가 플레이 순서로 범위를 늘린다. 이전 세이브스테이트는 신규 빌드 QA 근거로 사용하지 않는다. 각 항목의 날짜·환경·결과·근거와 미검증 범위를 별도로 남긴다.

공개 전 git diff --stat, git diff --check, git status --short로 변경과 신규 파일을 검토한다. ISO·원본 자산·비밀정보를 stage하지 않는다. 사용자가 commit/push를 명시적으로 승인한 뒤 연결과 대상 원격/브랜치를 확인하고 문서·스크립트만 명시적으로 stage한다. 이번 인계 구조는 사용자 승인 후 main에 커밋/푸시했다.

개발 재개 도구와 지원 범위는 [개발 안내](DEVELOPMENT.md)를 참고하세요.
