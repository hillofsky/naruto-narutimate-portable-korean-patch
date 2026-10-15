# 작업 지침
원본/결과 ISO와 추출 게임 바이너리는 커밋하지 않는다. 배포는 Releases의 xdelta로 한다. patch/manifest.json 해시로 입력과 출력을 검증한다. 번역 제어 토큰, 기존 폰트 매핑, 비대상 리소스와 PMF를 보존한다. primary/FSTS 중복을 함께 반영한다. 전체 재빌드의 외부 의존성 및 런타임 미검증 범위를 숨기지 않는다. 공개 문서에 개인 인증정보나 세이브를 넣지 않는다.

## 세션 재개 규칙

- 변경 전 PROJECT_STATE.md, HANDOFF.md, docs/OPERATIONS.md를 읽는다. Naruto는 docs/AI_HANDOFF.md와 docs/SUB52_PROGRESS.md, BIA는 docs/QA_STATUS.md를 추가 확인한다.
- 배포 manifest와 기준 출력 해시를 후보 빌드의 값으로 바꾸지 않는다. 새 후보는 별도 명세/출력으로 기록한다.
- 역사적 PASS, 사용자 확인, 이번 실행 결과를 구분한다. 정적 PASS를 런타임 완료로 승격하지 않는다.
- ISO, 추출 게임 자산, 영상/음원, 세이브, 인증정보는 커밋하지 않는다. .gitignore는 이미 추적된 파일을 보호하지 못하므로 diff도 확인한다.
- 삭제/정리 스크립트는 자동 실행하지 않는다. 대상과 보존 기준을 검토한다.
- 종료 시 PROJECT_STATE.md와 HANDOFF.md를 실제 증거에 맞게 갱신한다. 보호 파일을 의도적으로 바꿀 때만 docs/resume_baseline.json의 해시와 이유를 검토해 함께 갱신한다.
- commit/push는 사용자의 명시적 승인과 연결 확인 후 수행한다.
