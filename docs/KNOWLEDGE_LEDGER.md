# 확인된 지식과 실패·미검증 기록

정리일: 2026-10-16. 이번 작업은 로컬 코드/보고서 대조이며 과거 실험을 재실행하지 않았다. 아래는 다시 조사하기 전에 확인할 근거다. **과거 handoff/PROJECT_STATE는 역사 자료이며 현재 AGENTS.md나 사용자 지시보다 우선하지 않는다.**

| 이어 쓸 지식 | 반복하지 않을 판단/시도 | 근거 |
|---|---|---|
| PIDX primary와 FSTS preload 사본을 함께 갱신하고 DAT/IDX를 함께 검증한다. | 단일 primary 수정으로 모든 화면이 갱신된다고 가정하지 않는다. 기존 stage14 형식 코드와 현재 portable 도구를 먼저 사용한다. | [현재 인계](AI_HANDOFF.md) · [개발 도구](../tools/develop.py) |
| CCS 팔레트·인덱스·수직 방향·UV 및 donor 매핑은 보존한다. | TEX_red의 원본 색과 런타임 색 해석은 다르다. 임의 빨강/검정 덮기 실패 경험을 반복하지 않는다. | [현재 인계](AI_HANDOFF.md) |
| SUB52K 비압축 누적 결과는 4GiB를 넘었다. | 보고서 final_iso_size=4759830528, static_qa=PASS라도 실행 적합성을 뜻하지 않는다. 크기 초과 사실과 검은 화면 원인 확정은 구분한다. 현재 개발 도구는 4GiB 이상을 거부한다. | [근거](../history/evidence/project/48cd78f557e798d1_SUB52K_static_verification.json) · [실제 도구 검증](PORTABILITY_VALIDATION.md) |
| SUB52L은 리소스 변경과 실제 화면 연결을 구분한 읽기 전용 조사다. | 27개 리소스/23개 face 파일, texture 변경은 정적 사실일 뿐 어느 화면에서 읽는지는 별도 렌더러/게임 조사 대상이다. ISO 수정과 PPSSPP 실행은 false로 기록됐다. | [근거](../history/evidence/project/c91e036499bb17d1_SUMMARY.json) |
| SUB52M 및 SUB52N FIX1의 BOOT/EBOOT 수정은 정적 검증이다. | STATIC_PASS_RUNTIME_UNVERIFIED를 최종 런타임 성공으로 재해석하지 않는다. reward 문자열의 색상/아이콘/%d 토큰과 고정 길이 조건을 유지한다. | [근거](../history/evidence/project/95970ccd53f32197_SUMMARY.json) · [근거](../history/evidence/project/0db63668bb97085b_SUMMARY.json) |
| SUB52U 최신 개발 기준과 SUB52V/W 조사를 구분한다. | SUB52U HUDRemaining 런타임 PENDING, 이름 겹침 NOT_FIXED. SUB52V charsel discovery와 로컬 sub52v_cleanup은 다른 작업이다. SUB52W는 이름 UV 확인 전 구조 조사다. | [SUB52 인계](SUB52_PROGRESS.md) |
| 역사적 source가 있어도 중간 ISO/공식 이미지/영상 도구가 모두 공개된 것은 아니다. | 완전 개발 체인을 새로 재현하기보다 현재 검증된 릴리즈 기준에서 원하는 변경을 검증하는 경로가 우선이다. 영상 15개와 전체 PMF24개를 혼동하지 않는다. | [현재 인계](AI_HANDOFF.md) · [개발 절차](DEVELOPMENT.md) |

다음 작업자는 [작업 이력 탐색](HISTORY_INDEX.md)에서 단계/근거를 찾고, [함수 목록](SOURCE_MAP.json)에서 구현 위치를 찾는다. 현재 배포 manifest와 최신 PROJECT_STATE에 맞는 소스인지 확인한 뒤 필요한 부분만 사용한다. 미검증 범위를 새 분석 없이 완료 처리하지 않는다.
