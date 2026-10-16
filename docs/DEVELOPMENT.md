# 다른 환경에서 개발 이어가기

기록일: 2026-10-16. Python 3.9+ 표준 라이브러리만 사용하는 개발 도구를 추가했다. 개인 경로·Windows API·에뮬레이터 연결 없이 파일로 동작한다. NTFS/ext4 등 하드링크를 지원하는 출력 파일시스템이 필요하다. 출력과 임시 자료를 위한 여유 공간을 확보한다.

## 시작점

1. 저장소를 clone하고 AGENTS.md와 PROJECT_STATE.md를 읽는다.
2. 사용자가 보유한 원본 ISO를 README의 해시와 대조한다.
3. README에 연결된 Releases에서 해당 누적 xdelta를 받아 기존 적용 도구로 기준 ISO를 만든다. 저장소 소스만으로 과거 모든 단계를 처음부터 다시 만드는 경로는 아직 제공하지 않는다.
4. 아래 개발 도구로 기준 ISO를 조사하고 별도 후보를 만든다. 기준 해시가 다르면 중단한다. 후보를 다시 입력하는 연속 적용은 아직 지원하지 않는다. 누적 변경은 기준 ISO에 적용할 하나의 편집 명세/리소스로 관리한다.

공개 Git 파일 + Releases 패치 + 소유한 원본 ISO로 아래 범위의 개발을 시작할 수 있다. 개인 작업 폴더 전체는 필요하지 않다. 편집한 게임 리소스와 ISO는 local/ 등 로컬에만 보관한다.

## Naruto: SUB52U CCS 조사와 재삽입

- tools/dev/ccs.py: 기존 SUB52G의 PNG/CCS/팔레트 처리 함수 복구.
- tools/dev/compact.py: 기존 SUB52K FIX2의 ISO 구조/스트리밍 검증 함수 복구.
- data/sub52/sub52u_hud_rectangles.json: 기존 HUD 번역과 사각형 좌표. 원본 텍스처 이미지는 포함하지 않는다.
- 기존 data/ 번역/폰트 매핑과 work/analysis/stage14, stage15 형식 코드를 함께 사용한다.

```powershell
python tools/develop.py inspect --source "SUB52U.iso" --resource gauge.ccs
python tools/develop.py extract --source "SUB52U.iso" --resource gauge.ccs --output "local/gauge.ccs"
python tools/develop.py build --source "SUB52U.iso" --resource gauge.ccs --replacement "local/gauge-edited.ccs" --output "local/candidate.iso"
```

추출한 CCS는 사용자 소유 게임에서 로컬로 만든 자료다. tools/dev/ccs.py의 find_texture/decode_indices/encode_indices 등으로 별도 작업 코드에서 텍스처를 편집할 수 있다. 이 도구가 번역 TSV를 자동으로 텍스처에 그려 주지는 않는다. 텍스처 크기·팔레트·UV·폰트 donor 매핑과 제어 토큰을 유지한다. 캐릭터 선택 이름 UV는 별도 확인해야 하며 이번에 겹침 문제를 수정하지 않았다.

보수적으로 압축 해제 CCS 길이를 유지하는 변경만 허용한다. 바이트 길이 일치는 구조·화면 정확성의 충분조건이 아니다. 편집자는 내부 구조를 검토해야 한다. primary와 FSTS 사본을 함께 갱신하고 압축 roundtrip을 검사한다. 기존 슬롯에 안전하게 들어가면 재사용하고, 다른 활성 리소스와 겹치거나 용량이 부족하면 뒤에 배치한다. 미대상 primary/FSTS 바이트와 모든 비대상 ISO 활성 파일을 대조한다. DAT/IDX를 재배치한 뒤 결과가 4GiB 이상이면 중단한다.

기존 SUB52U는 4GiB까지 2,811,904 bytes만 남는다. 큰 변경이 한계를 넘으면 오래된 아카이브 구간을 추가로 정리하는 재패킹 구현이 필요하다. 미사용 영역을 임의 삭제하지 않는다. 영상 재인코딩과 과거 전체 단계 재현은 이 도구 범위에 포함하지 않는다.

## 이번 검증과 남은 범위

실제 검증 결과는 docs/PORTABILITY_VALIDATION.md를 따른다. 새 후보의 정적 검증은 기존 릴리즈의 런타임 검증을 상속하지 않는다. PPSSPP normal boot, 해당 화면, 일반 저장/불러오기를 별도로 확인하고 기록한다. Linux/macOS 실환경 실행은 아직 확인하지 않았다.
