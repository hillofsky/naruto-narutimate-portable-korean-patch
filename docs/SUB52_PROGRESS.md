# SUB52 후속 작업 — 나루토 번역 분석 계속2

기록 정리: 2026-10-15. 채팅 첨부의 실행 결과와 로컬 보고서를 대조했습니다. 채팅 응답 본문은 조회 결과에 콘텐츠 참조만 남아 있어, 그 본문의 설명을 복원했다고 주장하지 않습니다.

## 해당 채팅에서 확인한 작업

- **SUB52U safe cleanup**: 2026-10-13 실행. 오래된 중간 ISO/불완전 결과 21개, 41,378,519,040 bytes(약 38.537 GiB) 정리, 오류/경고 0. SUB52T/U와 보호 기준점, 원본/세이브/PMF/자산/코드/로그 보존 규칙을 사용했습니다. 이 정리 스크립트는 기본 읽기 전용이 아닌 삭제 기능이 있으므로 실행 전 run.ps1의 모드와 대상 판정을 직접 확인해야 합니다. 이번 Git 제출에서는 실행하지 않았습니다.
- **SUB52V charsel discovery**: 파일 65,292개 조사, 이미지 후보 203개와 소스 참조 49개 확인. 추출된 charsel CCS 후보는 0개. 보고서 PASS는 수집 작업 성공을 뜻하며 이름 겹침 해결을 뜻하지 않습니다. ISO와 PPSSPP를 수정/제어하지 않았습니다.
- **SUB52W charsel structural**: 소스 62,680개 조사, 키워드 일치 소스 125개, 참조 594행, 소스 샘플 18개 수집. SUB52U ISO의 ISO9660 구조 검사가 PASS였습니다. 게임 해시는 이 조사에서 다시 확인하지 않았습니다. ISO 수정/PPSSPP 제어 없음. 다음 단계는 실제 charsel1.ccs/TEX_sel 추출 경로와 이름 UV 사각형 확인입니다.

## 기준 빌드와 미해결 사항

로컬 SUB52T/U 보고서는 배경 자료로 따로 보존합니다. SUB52U HUDRemaining은 TEX_xgauge5의 검증된 영역에서 캐릭터 이름 21개를 변경하고 FSTS 묶음 1개를 재구축했습니다. 정적 QA PASS, 런타임 QA PENDING입니다. 캐릭터 선택 화면 이름 겹침은 NOT FIXED로 기록되어 있습니다.

보고서상 SUB52U ISO 크기: 4,292,155,392 bytes, SHA-256: `3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f`. 4GiB 한계까지 여유가 2,811,904 bytes뿐입니다. 이는 기존 보고서 값이며 이번 제출에서 ISO 재생성/재검증을 하지 않았습니다.

**단계 이름 충돌 주의:** 로컬 폴더 `sub52v_cleanup`은 별도의 디스크 정리 기록입니다. 이 채팅 첨부 `naruto_sub52v_charsel_discovery_upload.zip`의 SUB52V와 다릅니다. 파일/목적을 포함한 이름으로 구분합니다.

## 공개 파일과 재현 범위

- `work/sub52/sub52u_safe_cleanup/`: 채팅의 정리 스크립트.
- `work/sub52/sub52v_charsel_discovery/`: 캐릭터 선택 화면 조사 스크립트.
- `work/sub52/sub52w_charsel_structural/`: 읽기 전용 구조 조사 스크립트.
- `work/sub52/history/`: 로컬에 남아 있는 SUB52 이전 단계의 빌드/진단 소스. 일부 중간 ISO, 이미지 자산과 도구가 외부 의존성이며, 이 폴더만으로 전체 빌드를 재현할 수 없습니다.
- `data/sub52/`: 기존 SUB52 번역/폰트 매핑/적용 목록.
- `docs/verification/sub52/`: 경로를 PROJECT_ROOT로 치환한 실행 결과와 배경 보고서. provenance.json에 채팅 첨부 원본 ZIP의 해시를 기록했습니다.

게임 ISO, 추출 BIN/DAT/IDX/CCS, 텍스처 원본, 세이브, 원본 ZIP과 개인 실행 로그는 공개하지 않습니다. 구조 조사에서 수집된 charasel.at3는 음원이며 공개 파일에서 제외했습니다.

## 배포 상태

이 제출은 후속 개발 코드/데이터/조사 기록입니다. 기존 v0.1.0 릴리즈와 patch/manifest.json은 계속 SUB51P FIX13을 가리키며 변경하지 않았습니다. 2026-10-15 v0.2.0-preview로 SUB52U 누적 xdelta를 추가했습니다. 새 메타데이터는 patch/sub52/manifest.json입니다. 원본에서 재적용한 결과의 크기와 SHA-256이 SUB52U와 일치함을 검증했습니다. 기존 v0.1.0 패치는 변경하지 않았습니다.
