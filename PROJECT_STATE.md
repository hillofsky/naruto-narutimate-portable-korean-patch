# PROJECT_STATE

기록일: 2026-10-15. 이번 세션은 공개 저장소와 기록을 점검했으며 ISO·릴리즈 패치·PPSSPP를 실행 검증하지 않았다.

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
