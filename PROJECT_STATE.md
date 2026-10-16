# PROJECT_STATE

초기 점검일: 2026-10-15. 당시에는 공개 기록만 점검했다. 최신 개발 도구 검증은 아래 2026-10-16 항목을 따른다.

## 보존할 기준점

| 용도 | 기준 | 권위 명세 | 검증 범위 |
|---|---|---|---|
| 기존 배포 | v0.1.0 / SUB51P FIX13 | patch/manifest.json | 기존 정적·패치 roundtrip 기록, 런타임 PENDING |
| 후속 개발 | v0.2.0-preview / SUB52U HUDRemaining | patch/sub52/manifest.json | 기존 정적 PASS 및 roundtrip 기록, 런타임 PENDING |

원본 ULKS46086 한국판 634,257,408 bytes. 해시와 결과 크기는 위 manifest를 기준으로 한다. 두 패치는 모두 원본에 적용하는 누적 패치다. SUB52U는 4,292,155,392 bytes로 4GiB까지 2,811,904 bytes 남는다.

## 현재 판단

- SUB52V charsel discovery와 SUB52W structural은 조사이며 새 빌드가 아니다. 로컬 sub52v_cleanup과 혼동하지 않는다.
- 캐릭터 선택 이름 겹침 NOT_FIXED. 전체 플레이/PSP 실기 검증 NOT_RECORDED.
- SUB52W 구조 검사 PASS는 ISO 해시 재검증이나 화면 수정 성공을 뜻하지 않는다.
- 근거: docs/SUB52_PROGRESS.md, docs/verification/sub52/, docs/KNOWN_ISSUES.md.
- 전체 개발 재빌드는 외부 중간 ISO·이미지·도구 없이는 재현할 수 없다. 공개 work/는 역사적 경로와 imports가 있어 사전 조정이 필요하다.

## 다음 완료 조건

소유한 원본과 preview 패치를 검증해 별도 출력에 적용한 뒤 normal boot에서 HUD와 캐릭터 선택 화면을 확인한다. 실제 charsel1.ccs/TEX_sel 추출 경로와 이름 UV 사각형을 확인하기 전 아틀라스를 수정하지 않는다. 실행 환경·재현 절차·화면 근거를 기록한 뒤에만 QA 상태를 변경한다.

## 개발 자료 복구 — 2026-10-16

[다른 환경에서 개발](docs/DEVELOPMENT.md)과 [이번 검증](docs/PORTABILITY_VALIDATION.md)을 추가했다. 기준 ISO 기반의 조사/제한된 수정/후보 재빌드는 공개 코드로 가능하다. 원본에서 시작하는 과거 전체 개발 체인의 재현은 아직 완료되지 않았다. 게임 화면 QA는 기존 PENDING 상태다.

## 작업 이력 대조 추가 — 2026-10-16

[이력 탐색](docs/HISTORY_INDEX.md), [지식·실패 기록](docs/KNOWLEDGE_LEDGER.md), [전체 대조 목록](docs/HISTORY_INVENTORY.json)을 추가했다. 공개 가능한 코드/결과를 경로 치환 사본으로 보존하고 중복·제외·기존 파일 연결을 기록했다. 원본/공개본 해시를 구분한다. 과거 코드를 실행하지 않았으며 최신 배포 기준과 QA 상태는 유지한다. 모든 로컬 파일/대화의 보존 완료를 뜻하지 않는다. 다음 작업 전 해당 근거를 먼저 읽어 중복 분석을 줄인다.
