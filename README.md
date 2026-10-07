# 나루토 나루티밋 포터블 — 무환성의 권 한국어화 (PSP)

한국판 『나루토 나루티밋 포터블 — 무환성의 권』(ULKS46086)을 기준으로 미번역 대사·영상 자막·메뉴를 보완한 비공식 팬 번역 프로젝트입니다.

**상태: 1차 작업 완료 · v0.1.0 (2026-10-07)**  
배포 기준: `MOV06E + SUB51P FIX13 FullAtlas`. 전체 플레이 검증은 아직 기록되지 않았으며, 최신 빌드 보고서의 런타임 QA는 PENDING입니다. 사용자 완료 선언과 빌드 검증 기록을 구분해 제공합니다.

## 다운로드와 적용

[Releases에서 v0.1.0 패치 다운로드](https://github.com/hillofsky/naruto-narutimate-portable-korean-patch/releases/tag/v0.1.0)

원본은 **한국판 ISO**입니다. 일본판·북미판 ISO나 이전에 패치한 ISO에 적용하지 마세요.

| 항목 | 값 |
|---|---|
| 원본 크기 | 634,257,408 bytes |
| 원본 SHA-256 | `6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7` |
| 결과 크기 | 1,621,979,136 bytes |
| 결과 SHA-256 | `1029c34956e23d4eee229a40e995f502fa8a2f249487f16de7fb72869d210cdb` |

[xdelta3](https://github.com/jmacd/xdelta)로 적용합니다. 패치 파일과 `manifest.json`을 저장소의 `patch/` 폴더에 두면 아래 도구가 원본과 결과 해시를 자동 확인합니다.

```powershell
python work/apply_patch.py --source "원본 한국판.iso" --output "Naruto_Korean_v0.1.0.iso" --xdelta "xdelta3.exe"
```

직접 적용할 경우:

```powershell
xdelta3 -d -s "원본 한국판.iso" "naruto-korean-v0.1.0.xdelta" "Naruto_Korean_v0.1.0.iso"
```

PPSSPP에서 결과 ISO를 새로 실행하고 일반 저장 데이터를 불러오세요. 세이브스테이트는 이전 메모리·텍스처를 복원하므로 최신 패치 확인 기준으로 사용할 수 없습니다.

## 포함된 작업

- 스토리 대사 1,976행: 의미 검수 및 23글자×2줄 레이아웃 보완.
- 영상 자막: MOV06E 기준 번역 영상 15개 반영. 전체 PMF 24개는 이후 텍스트·UI 빌드에서 보존.
- 대화창 화자명 36개, 무환성 안내문 44개와 메뉴 문구 보완.
- 추가 번역 후보 1,140개 적용: BOOT 문자열 1,223곳, TBL 32곳/18개 리소스.
- 한글 폰트 매핑 817자 구성.
- 모드 선택, 설정, 자택, 지도, 스킬, 무환성 메뉴와 타이틀 UI 보완.
- 마지막 FIX13에서 공용 `gauge/TEX_red` 전체 한글 아틀라스 및 O/X 안내 반영.

각 수치는 단계별 작업 단위이며 서로 합산한 전체 고유 문자열 수가 아닙니다. 모든 화면과 분기에서 미번역이 없음을 보장하는 수치도 아닙니다.

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `patch/manifest.json` | 원본·결과·패치 해시와 크기 |
| Releases | 용량이 큰 xdelta 배포 파일 |
| `data/` | 대사·메뉴 번역, 적용 목록, 폰트 매핑 |
| `work/` | 해시 검증 적용 도구 및 역사적 빌드 스크립트 |
| `docs/WORK_LOG.md` | 주요 작업 단계와 결과 |
| `docs/AI_HANDOFF.md` | 바이너리 형식, 의존성, 후속 작업 |
| `docs/KNOWN_ISSUES.md` | 검증 범위 및 제보 방법 |

원본·결과 ISO, 추출 게임 바이너리, 영상, 세이브스테이트와 에뮬레이터는 포함하지 않습니다. 공개 작업 스크립트는 외부 원본과 중간 결과·이미지 자산을 요구하는 기록용 도구도 포함합니다. 저장소만 받아 전체 개발 빌드가 재현되는 상태는 아닙니다. 최종 배포물 재현은 검증된 원본에 xdelta 패치를 적용하는 방식입니다.

## 참여 및 크레딧

[한국어 기여 안내](docs/CONTRIBUTING_ko.md)를 참고해 번역·화면 제보를 보내주세요. 번역과 수정은 hillofsky의 프로젝트 작업 및 ChatGPT/Codex 지원으로 진행했습니다. 게임·공식 이미지·음원 등의 권리는 각 권리자에게 있습니다. 공식 배포나 공식 번역판이 아닙니다.

문서 구성은 [무쌍 오로치 2 Special 한국어화 저장소](https://github.com/hillofsky/musou-orochi-2-special-korean-patch)를 참고했습니다.
