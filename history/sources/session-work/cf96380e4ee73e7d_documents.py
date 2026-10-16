from pathlib import Path
import json,shutil,hashlib
root=Path(r'LOCAL_PATH');repo=root/'outputs/naruto-narutimate-portable-korean-patch';project=Path(r'PROJECT_ROOT')
def put(path,text):
 p=repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text.strip()+'\n',encoding='utf-8')
m=json.loads((repo/'patch/manifest.json').read_text(encoding='utf-8'))
put('README.md',f'''# 나루토 나루티밋 포터블 — 무환성의 권 한국어화 (PSP)

한국판 『나루토 나루티밋 포터블 — 무환성의 권』(ULKS46086)을 기준으로 미번역 대사·영상 자막·메뉴를 보완한 비공식 팬 번역 프로젝트입니다.

**상태: 1차 작업 완료 · v0.1.0 (2026-10-07)**  
배포 기준: `MOV06E + SUB51P FIX13 FullAtlas`. 전체 플레이 검증은 아직 기록되지 않았으며, 최신 빌드 보고서의 런타임 QA는 PENDING입니다. 사용자 완료 선언과 빌드 검증 기록을 구분해 제공합니다.

## 다운로드와 적용

[Releases에서 v0.1.0 패치 다운로드](httpLOCAL_PATH

원본은 **한국판 ISO**입니다. 일본판·북미판 ISO나 이전에 패치한 ISO에 적용하지 마세요.

| 항목 | 값 |
|---|---|
| 원본 크기 | {m['source_size']:,} bytes |
| 원본 SHA-256 | `{m['source_sha256']}` |
| 결과 크기 | {m['target_size']:,} bytes |
| 결과 SHA-256 | `{m['target_sha256']}` |

[xdelta3](httpLOCAL_PATH 적용합니다. 패치 파일과 `manifest.json`을 저장소의 `patch/` 폴더에 두면 아래 도구가 원본과 결과 해시를 자동 확인합니다.

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

문서 구성은 [무쌍 오로치 2 Special 한국어화 저장소](httpLOCAL_PATH 참고했습니다.
''')
put('docs/WORK_LOG.md','''# 1차 작업 기록

## MOV06E — 영상
번역 영상 15개를 통합하고 자막 시간·음성 구간·끝부분 길이를 조정했습니다. dm001~dm010, da101, da201, dk101, dk102, dk202가 번역 영상 목록입니다. 나머지를 포함한 PMF 24개는 이후 단계에서 바이트/해시 보존 검사를 수행했습니다.

## SUB36 — 대사
39개 이벤트 파일의 1,976행을 의미 검수하고 23글자×2줄 범위로 다듬었습니다. 최종 의미 수정 42개를 통합했습니다.

## SUB39~42 — 이름표·안내문
문자열 수정만으로 바뀌지 않던 이름표가 mugen.ccs/TEX_name 이미지임을 확인했습니다. 36개 화자명, 안내문 44개, 소대 메뉴 이미지 문구 12개 및 루트 메뉴 문자열 12개를 적용했습니다. primary 리소스와 mugen0/mugen1 FSTS 중복을 동시에 수정했습니다. 사용자 세이브 슬롯은 보존했고 별도 상태 파일은 공개 배포에서 제외했습니다.

## SUB43~50 — 메뉴 이미지
모드 선택·설정·자택·상태/스킬 등의 텍스처를 조사하고 번역했습니다. 공용 아틀라스의 넓은 수정에서 겹침 문제가 발생해 원본 복원과 영역별 교체를 반복했습니다.

## SUB51D — 추가 문자열
번역 후보 1,140개를 적용했습니다. BOOT 1,223곳, TBL 32곳/18개 리소스를 수정하고 폰트 매핑을 711자에서 817자로 확장했습니다. 수치 및 해시는 docs/verification의 정적 검증 보고서를 기준으로 합니다.

## SUB51L/N — UI 통합
SUB51D 기준으로 UI 자산을 통합했습니다. SUB51N 보고서는 11개 리소스, 61개 텍스처, FSTS 묶음 7개 변경과 PMF 24개 보존을 기록합니다. 타이틀 로고·문구, 자택 개수 글리프 등을 보완했습니다. 역사적 눌림 상태 진단은 전체 런타임 검증 완료 기록과 구분해야 합니다.

## SUB51P FIX13 — 배포 기준
SUB51N을 바탕으로 gauge.ccs의 TEX_red/TEX_white/TEX_xpanel 3개를 변경했습니다. TEX_red는 기존 전체 한글 아틀라스를 사용하고 게임 모드 선택 문구를 원본 계열 팔레트에 맞췄습니다. title.ccs는 이 단계에서 수정하지 않았습니다. 정적 QA PASS, 최신 단계 런타임 보고서 PENDING. 사용자가 2026-10-07 1차 작업 완료를 선언했습니다.
''')
put('docs/KNOWN_ISSUES.md','''# 검증 범위와 확인 필요 항목

1차 작업 완료는 현재 번역 작업의 마일스톤입니다. 전체 플레이와 모든 분기·메뉴의 검증 완료를 뜻하지 않습니다.

- 최신 SUB51P FIX13 정적 QA: PASS. 런타임 QA: 빌드 보고서에 PENDING으로 남아 있음.
- 타이틀의 이어서 시작 눌림 상태에서 과거 흰 블록/왼쪽 잘림/초록 롤 가림이 보고되었습니다. 과거 인계 문서는 수정 시도를 기록하지만 최종 FIX13 기준 해결 여부의 별도 증거가 필요합니다. 확정된 현재 결함으로 단정하지 않습니다.
- 게임 모드 선택 헤더·공용 TEX_red·O/X 안내는 마지막 수정 대상입니다. 모든 해당 화면의 최신 실행 검증은 별도 확인이 필요합니다.
- 모든 캐릭터/아이템/스킬·분기 대사·통신 기능·실기 PSP 전체 검증은 기록되지 않았습니다.
- 예전 세이브스테이트는 일본어 텍스트와 이전 이미지가 보일 수 있습니다. 일반 실행 후 일반 저장 데이터로 재현해 주세요.

제보할 때 패치 버전, 결과 ISO SHA-256, PPSSPP 버전/실기 종류, 화면 위치, 재현 순서와 스크린샷을 보내주세요. 원본 게임 파일이나 세이브스테이트를 공개 이슈에 첨부하지 마세요.
''')
put('docs/CONTRIBUTING_ko.md','''# 번역·기술 기여

GitHub Issues에 화면 위치, 기존 문구, 제안 문구, 재현 순서와 버전을 기록해 주세요. 번역 TSV를 수정하는 PR은 ID·제어 토큰·행 연결 정보를 유지해 주세요.

대사 레이아웃은 SUB36의 23글자×2줄 기준을 확인합니다. 색상/제어 토큰은 순서와 개수를 보존하고, 바이트 길이·글리프 존재 여부를 별도로 검증합니다.

게임 원본 ISO, 추출 바이너리, 영상, 세이브스테이트, 개인 인증정보는 커밋하지 않습니다. 결과물 공개는 검증한 차분 패치로 합니다. 코드 수정 시 원본 해시·비대상 리소스·PMF 보존, primary/FSTS 동시 반영을 확인해 주세요.
''')
put('docs/AI_HANDOFF.md','''# 후속 작업 인계

## 배포 기준
v0.1.0 = MOV06E + SUB51P FIX13 FullAtlas. 정확한 입력·출력 해시는 patch/manifest.json이 기준입니다. SUB51D 전체 텍스트와 SUB51N UI 통합 위에 FIX13이 gauge.ccs 3개 텍스처만 보완합니다. 이름이 final/SUCCESS라고 런타임 검증까지 완료된 것으로 해석하지 않습니다.

## 외부 작업 루트와 의존성
역사적 로컬 프로젝트는 PROJECT_ROOT, 배포 기준 ISO는 Naruto_KR_MOV06E_SUB51P_FIX13_FullAtlas.iso였습니다. 스크립트의 --root로 작업 루트를 지정하거나 하드코딩 경로를 변경해야 합니다. 공개 work/의 내용을 외부 작업 루트에 해당 상대 경로로 배치해야 역사적 imports가 맞습니다. data/는 검토용 재배치이므로 일부 원래 스크립트에는 입력 경로 조정도 필요합니다.

Python, 일부 단계의 Pillow, xdelta3, 영상 재빌드 단계의 ffmpeg/기존 mux 도구, 사용자가 보유한 한국판 원본과 북미판 참조 자료 등이 필요합니다. 공식 로고/공식 한국판 이미지, 중간 ISO/추출 자료는 저장소에서 제외했습니다. 따라서 역사적 스크립트의 완전 재빌드는 외부 프로젝트 자산 없이 실행할 수 없습니다. 배포 ISO 재현은 xdelta 적용 도구를 사용합니다.

## 리소스 형식
- PSP_GAME/USRDIR/naruto.dat 및 naruto.idx의 PIDX 테이블.
- 압축 태그 3;0 raw/XOR 0x72, 3;1 LZSS는 stage14 패처를 참고.
- CCS 텍스처 인덱스·팔레트·수직 방향 및 해당 UV를 보존.
- FSTS preload의 동일 리소스도 수정하고 DAT 내부 PIDX와 외부 IDX를 갱신.
- mugen TEX_name: 512×256, 4bpp, 화자 셀 76×24.
- gauge TEX_red는 공용 아틀라스이며 화면 스타일과 팔레트 해석을 먼저 확인. 원본 파란 계열과 실행 시 빨간 계열 표시 관계 때문에 임의 빨강/검정 이미지 덮기가 잘못된 출력으로 이어졌습니다.
- 폰트는 SJIS donor 코드 매핑과 18×18 4bpp 글리프를 사용. 기존 매핑을 덮지 않고 검증된 미사용 슬롯을 사용.

## 보존과 검증
PMF 전체 24개는 MOV06E 이후 바이트 보존. 번역 영상은 15개입니다. 비대상 primary 및 FSTS 멤버를 보존합니다. 정적 출력과 런타임 캡처를 분리해서 기록합니다. 게임 실행 검증은 이전 상태 파일이 아닌 normal boot를 우선합니다.

## 다음 작업
KNOWN_ISSUES.md의 최신 런타임 확인부터 수행하고, 전체 플레이/분기 검수와 미번역·넘침 목록을 수집합니다. 최신 빌드 보고서에 남아 있는 PENDING은 실제 검증 후 근거와 함께 업데이트합니다. 필요한 자산과 중간 단계가 없는 상황에서 전체 재빌드가 된다고 주장하지 않습니다.

## 출처
ChatGPT 대화: 나루토 번역 분석 계속 SUB, SUB2, 브랜치 · 나루토 번역 분석 계속 SUB2, 나루토 번역 분석 계속. Codex SUB39~42 작업과 로컬 SUB51D/N/P 검증 보고서를 대조했습니다. 공개 문서에 채팅 전체나 개인 세이브는 포함하지 않았습니다. 구형 OpenCode 인계 문서의 SUB51D 해시에는 오타가 있어 실제 JSON 보고서 값을 우선했습니다.
''')
put('AGENTS.md','''# 작업 지침
원본/결과 ISO와 추출 게임 바이너리는 커밋하지 않는다. 배포는 Releases의 xdelta로 한다. patch/manifest.json 해시로 입력과 출력을 검증한다. 번역 제어 토큰, 기존 폰트 매핑, 비대상 리소스와 PMF를 보존한다. primary/FSTS 중복을 함께 반영한다. 전체 재빌드의 외부 의존성 및 런타임 미검증 범위를 숨기지 않는다. 공개 문서에 개인 인증정보나 세이브를 넣지 않는다.
''')
with (repo/'.gitignore').open('a',encoding='utf-8') as f:f.write('*.xdelta\n')
for pattern in ['mov*core.py','naruto_mov*.py','run_naruto_mov*.ps1','invoke_naruto_mov*.ps1']:
 for p in project.glob(pattern):shutil.copy2(p,repo/'work'/p.name)
for folder in ['analysis/stage24']:
 for p in (project/folder).glob('*.py'):
  d=repo/'work'/p.relative_to(project);d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
for folder in ['analysis/shared']:
 for p in (project/folder).glob('*mapping*.tsv'):shutil.copy2(p,repo/'data/font'/p.name)
for p in (project/'analysis/mov').rglob('*'):
 if p.is_file() and p.suffix.lower() in ['.srt','.ass'] and p.stat().st_size<1024*1024:
  d=repo/'data/movies'/p.relative_to(project/'analysis/mov');d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,d)
p=project/'analysis/sub/sub51n_titlehomepolish/build/SUB51N_static_verification.json'
o=json.loads(p.read_text(encoding='utf-8-sig'));o.pop('final_iso',None)
put('docs/verification/SUB51N_static_verification.json',json.dumps(o,ensure_ascii=False,indent=2))
# Review inventory contains relative paths only.
put('PUBLISH_CONTENTS.txt','\n'.join(str(p.relative_to(repo)).replace('\\','/') for p in sorted(repo.rglob('*')) if p.is_file() and p.suffix!='.xdelta'))
print('DOCS_READY',len([p for p in repo.rglob('*') if p.is_file()]))
