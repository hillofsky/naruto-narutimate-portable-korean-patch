# 나루토 PSP 한글화 프로젝트 인계 README

## 0. 목적

이 문서는 다른 AI가 현재 작업을 그대로 이어받기 위한 인계 문서다.

게임은 **PSP `Naruto: Narutimate Portable` 계열**이고, 작업 루트는 다음과 같다.

```text
PROJECT_ROOT
```

현재 목표는 단순히 일본어 위에 한글을 덮는 것이 아니라,

- 기존 번역/영상/폰트 작업을 절대 회귀시키지 않고
- 원본 UI의 질감, 외곽선, 색감, 붓글씨 느낌을 최대한 유지하면서
- 남아 있는 일본어 이미지 UI까지 자연스럽게 한글화하고
- 마지막에 PPSSPP normal boot 기준으로 일괄 런타임 검수

하는 것이다.

---

## 1. 가장 중요한 현재 기준점

### 1-1. 텍스트/폰트 기준 ISO

```text
PROJECT_ROOT\analysis\sub\sub51d_full_text_apply\Naruto_KR_MOV06E_SUB51D_FullText.iso
```

SHA256:

```text
7138f8c35bacaaf85ff50c12daf0620030cb9b44e7b7bf242168c20c91e845
```

SUB51D에서:

- ChatGPT가 직접 번역한 후보 1,140개 적용
- BOOT 문자열 1,223곳 패치
- TBL 32곳 / 18개 리소스 패치
- 한글 매핑 711자 → 817자
- PMF 24개 보존
- BC250 / Gemma / Qwen / llama.cpp 번역 사용 안 함

**사용자는 앞으로도 번역을 BC250/로컬 LLM에 맡기지 말고 AI가 직접 번역하길 원한다.**

---

### 1-2. 현재 최신 통합 UI ISO

```text
PROJECT_ROOT\analysis\sub\sub51l_fix2_consolidated_ui\Naruto_KR_MOV06E_SUB51L_FIX2_ConsolidatedUI.iso
```

SHA256:

```text
d3556573931e102eafda7b2dafcaa5adce230004af0ca825e7b6b7c2aa8f0cf8
```

SUB51L FIX2 정적 검증 결과:

```text
ResourcesChanged=11
TexturesChanged=59
NonTargetPrimaryPreserved=633
FSTSBundlesRebuilt=7
PMFsPreserved=24
IntermediateISODependency=NO
StaticQA=PASS
RuntimeQA=DEFERRED
```

변경된 primary resource:

```text
cmnselect.ccs
gauge.ccs
home.ccs
mapsel1.ccs
mgn_skill.ccs
mgselect.ccs
modesel1.ccs
mugen.ccs
option.ccs
rpggauge.ccs
title.ccs
```

SUB51G/H/I/J 같은 중간 ISO가 없어도 된다.  
SUB51L FIX2는 **보존 중인 SUB51D에서 모든 검증된 UI 자산을 다시 한 번에 적용**하도록 만들어졌다.

---

## 2. 반드시 보존할 기준 파일

### SUB36 compact baseline

```text
PROJECT_ROOT\analysis\integrated\sub36_semantic_qa\output\Naruto_KR_MOV06E_SUB36_SemanticQA_Final.iso
```

SHA256:

```text
789984d99ee7003e2ddfebaaf1e80236d64459065ef27e29ca9c78e0cd24aa3f
```

### 현재 영화 번역 상태

최종 PMF는 24개이며 이후 SUB 단계에서도 모두 byte-preserve 검증 중이다.

특히 번역된 PMF:

```text
dm001~dm010
da101
da201
dk101
dk102
dk202
```

이 영상 작업을 절대 회귀시키지 말 것.

---

## 3. 폰트/문자열 관련 핵심

기존 이벤트 폰트 매핑:

```text
PROJECT_ROOT\analysis\shared\event_font_hangul_mapping.tsv
```

SUB40 추가 글리프:

```text
PROJECT_ROOT\analysis\sub\sub40_tutorial\new_glyph_mapping.tsv
```

SUB51D에서 최종적으로 필요한 추가 글리프를 더 넣어 총 817자 범위로 확장했다.

기존 매핑을 임의로 재배치하거나 덮어쓰지 말 것.

### 대사 렌더링 확정 경로

```text
0x088D752C  메인 이벤트 표시 루프
0x088D675C  제어 태그 파서
0x088D5640  Shift-JIS 1/2바이트 판별
0x088D56EC  2바이트 → 글리프
0x088D64E0  1바이트 렌더러
0x088D65CC  2바이트 렌더러
0x088D6180  비트맵 렌더
```

이벤트 폰트:

```text
18x18
4bpp
162 bytes/glyph
BOOT.BIN offset 0x39CD04
```

---

## 4. 현재 UI 한글화 방식

### 절대 피해야 할 방식

이전 일부 단계에서 다음 방식이 문제를 만들었다.

- 공유 atlas에 눈대중으로 사각형을 잡고 한글을 덮어씀
- atlas 전체를 다시 양자화
- UV를 모르는 상태에서 `TEX_red / TEX_white`를 넓게 수정
- 원본 배경 위에 진한 박스를 깔고 한글을 얹음

이 때문에 SUB48에서는 다른 화면에 무관한 한글 조각이 나타났다.

따라서 현재 원칙은:

> **정확한 texture / 정확한 region만 수정하고, region 바깥 indexed pixel이 1개라도 바뀌면 실패시킨다.**

공유 atlas는 반드시 실제 사용 영역을 확인한 뒤 수정한다.

---

## 5. 이미지 스타일 방향

사용자가 원하는 방향:

> "그냥 한글로 덮어씌우지 말고 원본 느낌을 그대로 살린 한글화"

권장 방식:

1. 원본 일본어 UI 텍스처를 기준으로 함
2. 일본어 글자 영역만 제거/복원
3. 한글 글자는 AI가 직접 그리게 맡기기보다 정확한 한글 폰트로 렌더
4. 원본의
   - 색상
   - 기울기
   - 붓글씨 느낌
   - 외곽선
   - 그림자
   - 광택
   을 최대한 복제
5. 원래 indexed palette/4bpp/8bpp 구조로 다시 삽입
6. primary + FSTS preload duplicate까지 같이 반영

이미지 생성 AI는 **배경 복원/스타일 레퍼런스 용도**로는 쓸 수 있지만,
최종 한글 글자는 오타 방지를 위해 결정론적으로 합성하는 편이 좋다.

---

## 6. 공식 한국판 ISO 조사 결과

공식 한국판 ISO:

```text
PROJECT_ROOT\kr\Naruto - Narutimate Portable - Muhwanseongui Gwon (Korea).iso
```

SHA256:

```text
6510ad253aed3e4a20c87e36844ce5db8794e4daeca0c2e6ba38081dd26745a7
```

조사 결과, 확인한 UI 이미지들은 일본판과 **pixel/byte 기준 동일**했다.

즉 공식 한국판도 해당 UI 이미지를 한글화하지 않았으므로,
공식 한국판을 한글 그래픽 donor로 사용할 수 없다.

---

## 7. 지금까지 적용된 UI 작업

### 7-1. `modesel1.ccs`

메인 모드 7개:

```text
無幻城       → 무환성
強敵との決闘 → 강적과의 결투
ナルPロード  → 나루P 로드
ナルトの自宅 → 나루토의 집
設定の変更   → 설정 변경
通信対戦     → 통신 대전
裏・無幻城   → 이면 무환성
```

원본 스타일 기반 재렌더를 시도했다.

---

### 7-2. `option.ccs / TEX_option01`

적용:

```text
난이도 설정
조작 설정
음량 설정
종료

쉬움
보통
어려움
매우 어려움
```

일반/선택 상태를 포함해 정확한 12개 text region만 수정했다.

---

### 7-3. `rpggauge.ccs`

`TEX_rpgmenu01`:

```text
소지품
커스텀
임무
자택
이야기 회상
저장
메뉴
현재 맵
임무 중
전체 맵
맵 표시
임무 확인
START 중단
닫기
```

`TEX_rpgmenu02`:

장소명 약 21개 번역.

예:

```text
라멘 일락
역대 호카게 얼굴 바위
중닌 선발 시험장
제44연습장 죽음의 숲
나루토 대교
나뭇잎 온천
나뭇잎 마을 문
다른 나라로 가기
...
```

---

### 7-4. `home.ccs`

`TEX_mhvid01` 비디오테이프의 `ナルト` 라벨을 `나루토`로 변경.

단, 아래 "현재 발견된 문제" 참조.

---

### 7-5. `mugen.ccs`

안전하게 번역한 항목:

```text
능력치
대장
대원
대기
체력
차크라
사용
확인
돌아가기
메뉴
전투
대장 능력
능력
사용 장소
스킬 효과
사용 횟수
중요
정답
이루카의 수수께끼
에비스의 분신 훈련
```

특히 `TEX_white / TEX_red`는 SUB50에서 깨끗한 SUB36 payload로 복구해 둔 이력이 있으므로,
넓은 범위 수정 금지.

SUB50 당시 알려진 clean payload:

```text
TEX_red
5a300c6a26f573f91751441c68db5eaaff99a5886b3162e50415de14d7867791

TEX_white
e5cc2c4e4a683652feaf4821e44f5d29cbc1e762643b02d8a360f631c1848a4f
```

---

### 7-6. `mgn_skill.ccs`

실제 texture 이름은:

```text
TEX_skl_tx00 ~ TEX_skl_tx22
```

주의:

```text
TEX_skl_t00
```

가 아니다.

FIX1이 이 오타 때문에 실패했고 FIX2에서 수정 완료했다.

번역된 스킬명 예:

```text
나선환
치도리
의료인술
백안
사륜안
츠쿠요미
풍둔 대돌파
그림자 흉내술
육탄전차
심전신술
통아
...
```

---

### 7-7. `mgselect.ccs`

독립 결과 이미지 일부:

```text
게임 클리어
성공
목표 달성
실패
시간 초과
게임 오버
신기록 달성
대성공
스트레이트 승리
노 미스 클리어
승자
```

아래는 아직 의도적으로 미완료:

```text
TEX_mgselect
TEX_mgselect3
```

작은 설명/지시문 atlas라 별도 정밀 작업 필요.

---

### 7-8. `gauge.ccs`

독립 texture 일부는 번역했다.

예:

```text
전투 시작
시간 초과
신기록 달성
대성공
게임 종료
START 버튼 안내
임무 실패
비전서 획득
무승부
승자
```

그러나 아래 공유 atlas는 여전히 위험 영역:

```text
TEX_red
TEX_white
```

**UV/사용 영역을 확정하기 전까지 넓은 패치 금지.**

---

## 8. SUB51M 런타임 QA 상태

SUB51M은 SUB51L FIX2 ISO로 PPSSPP normal boot 런타임 캡처를 실행했다.

기준 ISO SHA256:

```text
d3556573931e102eafda7b2dafcaa5adce230004af0ca825e7b6b7c2aa8f0cf8
```

결과:

```text
MacroExitCode=0
UniqueScreenshots=16
NormalBoot=YES
OldSaveStateVisualQA=NO
BC250Used=NO
LocalLLMUsed=NO
```

중요:

> 이 자동 매크로의 16장은 대부분 스토리 대화 화면이었다.

따라서 **메뉴 UI 전체의 시각 검수를 완료했다고 보면 안 된다.**

저장상태 기반 시각 QA는 예전 texture가 남을 수 있으므로 사용하지 말 것.  
UI 검수는 normal boot로 해야 한다.

PPSSPP:

```text
PROJECT_ROOT\tools\ppsspp-stage33-2314\PPSSPPWindows64.exe
```

자동 실행 매크로:

```text
PROJECT_ROOT\generated_macros\naruto.bat
```

---

## 9. 지금 사용자가 직접 확인한 문제 — 최우선 수정 대상

### 9-1. 타이틀 화면 `새로 시작 / 이어서 시작`

사용자가 직접 올린 런타임 화면에서:

- `새로 시작`
- `이어서 시작`

의 **시인성이 좋지 않다.**

현재 한글이 어둡고 배경과 대비가 약해서,
원본 일본어 메뉴보다 읽기 어렵다.

또 선택/비선택 상태가 자연스럽지 않다.

### 수정 방향

- 원본 일본어 텍스처의 흰색/검정 외곽선과 명암을 참고
- 글자 중심부와 outline 대비 강화
- scroll/panel 배경을 건드리지 말고 text layer만 재제작
- 선택 항목은 훨씬 명확한 밝기/색상 차이를 줄 것
- 한글 자간과 장평을 원본 UI 폭에 맞게 다시 조정

**현재 버전을 최종 디자인으로 취급하지 말 것.**

---

### 9-2. `나루토의 자택` 화면 O/X 도움말 미번역

사용자가 직접 올린 화면에서 오른쪽 아래:

```text
○ 決定
× 終了
```

가 여전히 일본어다.

반드시:

```text
○ 결정
× 종료
```

또는 프로젝트 용어 규칙에 맞춰 자연스럽게 한글화해야 한다.

현재 메뉴 본문:

```text
이미지
음악
영상
사진
```

은 한글로 나온다.

하단도:

```text
이미지 확인
```

은 한글이다.

---

### 9-3. `나루토의 자택` 화면의 추가 일본어

같은 사용자 스크린샷에서:

화면 좌상단 제목:

```text
ナルトの自宅
```

가 일본어로 남아 있다.

가능하면 원본 붉은 붓글씨 스타일을 유지해서:

```text
나루토의 자택
```

으로 제작할 것.

하단 카운터도:

```text
0 / 63個
```

의 `個`가 일본어로 남아 있다.

자연스러운 한국어 표기는 예:

```text
0 / 63개
```

단, 이 값이 문자열인지 이미지인지 먼저 확인할 것.

---

## 10. 이미지 생성 시안 관련 주의

사용자 문제 제기 후 `나루토의 자택` 화면을 참고로 이미지 생성 시안도 만들어 봤다.

하지만 그것은 **게임에 삽입된 자산이 아니라 디자인 참고용 mockup**이다.

즉:

- generated image를 그대로 게임 texture로 넣지 말 것
- 원본 게임 texture의 정확한 pixel/alpha/palette/UV 구조를 기준으로 다시 만들어야 함
- 생성형 AI가 나루토 캐릭터/배경 자체를 다시 그리게 해서는 안 됨
- 실제 수정 대상은 가능한 한 글자 layer/해당 region만

---

## 11. 다음 AI가 바로 해야 할 일

우선순위:

### A. 타이틀 메뉴 가독성 수정

대상 후보:

```text
title.ccs
TEX_panel
TEX_panel2
TEX_panel3
```

실제 runtime 화면과 atlas의 대응을 확인하고:

```text
새로 시작
이어서 시작
```

의 normal/selected 상태를 다시 제작.

---

### B. 자택 화면의 남은 일본어 찾기

반드시 런타임 화면과 texture를 매칭하여:

```text
ナルトの自宅
○ 決定
× 終了
個
```

의 실제 source를 찾을 것.

이전처럼 “아마 이 atlas일 것”이라고 추측해서 공유 atlas를 넓게 수정하면 안 된다.

권장 절차:

1. 관련 CCS texture dump
2. 텍스처 이름/UV 확인
3. 런타임 screenshot과 실제 sprite 영역 대조
4. exact rect 확정
5. 해당 rect만 한글화
6. indexed pixel off-region diff = 0 검증
7. primary + FSTS duplicate 반영
8. normal boot 런타임 확인

---

### C. 아직 의도적으로 미룬 잔여 UI

```text
gauge.ccs / TEX_red
gauge.ccs / TEX_white

mgselect.ccs / TEX_mgselect
mgselect.ccs / TEX_mgselect3
```

공유/복잡 atlas이므로 실제 UV가 확정된 부분만 패치할 것.

---

## 12. 자동 빌드/검증 규칙

모든 빌드는:

- 성공/실패 모두 로그 ZIP 생성
- 실패 ZIP은 `fail_` 접두사
- 실행한 PS1/Python 포함
- SUMMARY
- diagnostic
- 부분 결과 포함
- 모든 PMF 24개 SHA 보존 검증
- 비대상 primary byte-preserve 검증
- FSTS preload duplicate 반영

을 유지한다.

사용자는 다운로드 링크를 **PowerShell 실행 명령 바로 위에 배치**하는 형식을 선호한다.

ZIP 해제는 PowerShell 5.1 `Expand-Archive` 대신 Python 사용:

```powershell
& python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" `
    $ZipPath "PROJECT_ROOT"
```

비ASCII ZIP entry 이름은 피한다.

---

## 13. 데이터 용량 관련

사용자가 여러 번 디스크 부족을 겪었다.

따라서:

- 중간 ISO를 단계마다 계속 남기지 말 것
- 기준점 + 최신 성공 ISO만 유지
- 재생성 가능한 DAT/IDX는 가능한 한 작업 후 삭제
- contact sheet는 크기 제한
- 큰 수집 ZIP은 사용이 끝나면 정리

현재 구조처럼:

```text
SUB51D 기준 ISO
+ 최신 통합 ISO
```

를 중심으로 작업하는 것이 좋다.

---

## 14. 작업 철학

1. 런타임 증거가 과거 문서보다 우선이다.
2. “패치했다고 기록되어 있음”보다 실제 화면이 우선이다.
3. 공유 atlas는 추측 금지.
4. UI가 깨지면 넓게 재수정하지 말고 원본 clean payload로 복귀 후 exact region만 다시 작업.
5. 한글 번역은 로컬 LLM이 아니라 AI가 직접 수행.
6. 최종 UI는 “번역 패치 느낌”이 아니라 “원래 한국어판처럼 보이는 느낌”을 목표로 한다.
7. 최종 PPSSPP 검수 전에는 완료라고 선언하지 않는다.

---

## 15. 바로 다음 목표

현재 가장 합리적인 다음 단계 이름 예:

```text
SUB51N_TitleHomePolish
```

목표:

```text
1. 타이틀 새로 시작/이어서 시작 가독성 개선
2. 나루토의 자택 좌상단 타이틀 한글화
3. ○ 決定 / × 終了 한글화
4. 63個 → 63개 처리 가능 여부 확인
5. 관련 texture/UV 정확성 검증
6. SUB51L FIX2의 모든 기존 작업 및 PMF24 유지
7. normal boot PPSSPP에서 해당 두 화면 직접 캡처
```

이 작업이 끝난 뒤에야 공유 `gauge`/`mgselect`의 잔여 소형 일본어를 처리하고 최종 전체 검수로 가는 것이 안전하다.

---

## 16. 핵심 체크리스트

새 AI는 작업 시작 전에 반드시 확인:

```text
[ ] SUB51D SHA 일치
[ ] 최신 SUB51L FIX2 SHA 일치
[ ] PMF 24개 보존
[ ] 기존 817자 폰트 매핑 유지
[ ] BC250/local LLM 번역 미사용
[ ] 공유 atlas 임의 패치 없음
[ ] primary + FSTS duplicate 동시 반영
[ ] title menu 시인성 개선
[ ] 자택 ○決定 / ×終了 수정
[ ] ナルトの自宅 수정
[ ] 63個 잔여 확인
[ ] PPSSPP normal boot 검수
```

---

## 17. 한 줄 요약

> **현재 번역/영상/폰트 기반은 안정적이고 SUB51L FIX2 정적 QA도 통과했지만, UI 디자인 완성도와 잔여 일본어가 아직 남아 있다. 다음 작업은 타이틀 메뉴 가독성과 ‘나루토의 자택’ 화면의 `ナルトの自宅 / ○決定 / ×終了 / 個`를 정확한 texture/UV 기준으로 다듬는 것이다.**

---

## 18. SUB51N_TitleHomePolish 결과 (2026-10-07)

최종 ISO:

```text
PROJECT_ROOT\analysis\sub\sub51n_titlehomepolish\build\Naruto_KR_MOV06E_SUB51N_TitleHomePolish.iso
```

SHA256:

```text
c2cfefd79860706995aa71e17dae6b64e47b91f56e55b19b1ee0f666983e2865
```

정적 검증:

```text
ResourcesChanged=11
TexturesChanged=60
NonTargetPrimaryPreserved=633
FSTSBundlesRebuilt=7
PMFsPreserved=24
StaticQA=PASS
BC250Used=NO
LocalLLMUsed=NO
```

off-region indexed pixel 변경 60개 texture 전부 0.

### 18-1. 타이틀 (title.ccs TEX_panel/panel2/panel3)

원인 확정:

- 기존 한글 에셋이 얇은 외곽선 렌더라 명암 대비 부족
- 기존 rect `(0,0,240,172)`가 일본어 4번째 줄(y152~194)을 잘라내 잔상 잔류
- TEX_panel2(파랑 실루엣)/TEX_panel3(검정 실루엣)은 alpha 마스크층이라 얇은 글자가 backing을 잃음

수정 (`build_sub51n_titlehomepolish.py`, `gen_n4.py` 계열로 결정론적 렌더):

- 맑은고딕 Bold 통채움: 일반 검정 / 선택 파랑, panel2 전체 파랑, panel3 전체 검정
  → FIX1: Noto Sans KR Black(900)으로 변경해 원본 굵은 고딕 느낌에 맞춤.
  글자 폭 187→158px 축소 + 좌측 이동으로 두루마리 우측 잘림 해결.
  (`macro_screenshots/sub51n_title_20261007_105813_719875/`에서 `이어서 시작` 완전 표시 확인)
- 눌림 상태: 원본 일본어 ISO로 동일 프레임을 캡처해 대조한 결과,
  눌렀을 때 두루마리 전체가 빨갛게 물들고 좌측 흰 프레임이 생기는 것은
  원본 엔진 연출(빨간 실루엣 레이어 오버레이)과 동일. 우리 패치 회귀 아님.
  (두루마리 픽셀은 패치 rect 밖이라 1px도 안 건드림, off-region 0 검증)
  원본 눌림 글자(빨강+흰외곽선)에 맞춰 TEX_panel 글자에 흰 외곽선 2px 추가.
  (`macro_screenshots/sub51n_pressframe_20261007_110953_555721/`)
- rect를 `(0,0,240,196)`로 확장해 4번째 줄 전체 커버 (저작권 y208~ 보존, 두루마리 x240~ 보존)
- 글자 폭을 양피지 영역(200px) 안에収めて 우측 잘림 해결 (40/35pt)
- PPSSPP normal boot 런타임 캡처에서 `새로 시작`/`이어서 시작` 완전 표시 확인
  (`macro_screenshots/sub51n_title_20261007_105318_492109/`)

### 18-2. 카운터 (cmnselect.ccs TEX_nunber)

- 하단 `0/10個`의 `個`는 BOOT 문자열이 아니라 `TEX_nunber` 아틀라스 좌하단 글리프
  (x2~23, y52~70)임을 확정
- 같은 붓글씨 파랑 계열로 `개` 렌더, rect `(0,52,48,104)` exact-region 패치
- ISO 라운드트립 디코딩으로 `개` 삽입 확인. 자택 화면 런타임 확인은 DEFERRED
  (자택 진입에 게임플레이 내비게이션 필요, 저위험 정적 PASS 상태)

### 18-3. 메인 로고 (title.ccs TEX_rogo, FULL 교체)

- 사용자가 제공한 정식 한글판 로고 누끼
  (`나루토 나루티밋 포터블 로고.png` → `analysis/sub/sub51n_titlehomepolish/user_logo_nuki.png`,
  1881x836 RGBA)를 512x256에 그대로 스케일해 통째로 삽입. 생성형 AI 사용 안 함.
- `나루티밋 포터블` 대형 로고 + NARUTO + 치비 나루토 + `무환성의 권` 현판 포함.
  NARUTO 소형 로고(영문)는 사용자 요청대로 그대로 유지.
- 팔레트 실측 결과 TEX_rogo 256색 팔레트에 흰색은 alpha128 항목만 있어
  흰 렌더가 크림색으로 매핑되길래, 공식 아트 원본색 그대로 넣어 nearest 매핑.
- 중요 발견: TEX_rogo 팔레트는 raw RGBA 순서라 디코더 표시(BGR 가정)와 R/B가 뒤집혀 보인다
  (덤프 파랑 NARUTO = 게임 주황, 덤프 청록 현판 = 게임 황금).
  그래서 공식 누끼는 R/B 스왑 후 삽입해야 게임에서 원본색(빨간 현판·주황 NARUTO·흰 글자)대로 나온다.
  다른 텍스처(자택 메뉴 파랑 등)는 게임 내 색이 덤프와 일치하므로 rogo만 해당.
  최종 런타임에서 빨간 현판·흰 글자·주황 NARUTO 확인.
- `macro_screenshots/sub51n_title_20261007_122214_015071/`에서 확인.

### 18-4. 다음 AI 유의점

- `나루토의 집` 상단 타이틀과 `○확인 ×종료`는 SUB48 캡처 기준 이미 한글.
  사용자 제보 화면과 다르면 ISO 버전(SUB51L FIX2 이전) 차이일 수 있으니
  런타임 증거를 먼저 대조할 것.
- 타이틀 미선택 항목(어두운 두루마리 위 검정)은 원본 UX 그대로 둔 것.
  밝게 바꾸려면 원본 스타일 훼손이므로 사용자 확인 후 진행할 것.
