# 최종 기준 복원 확인 — 2026-10-16

공개 GitHub 저장소를 새로 clone하고 Releases의 manifest와 xdelta를 새로 다운로드했다. 사용자가 보유한 원본 ISO에 적용해 최종 기준 ISO를 복원했다. 기존 로컬 최종 ISO, 중간 ISO, 개인 빌드 폴더의 자산은 복원 입력으로 사용하지 않았다. 표준 xdelta3 실행 파일은 별도로 준비했다.

- 검사한 Git 커밋: `d6c170d29f64dde12a24b240f8fd4dfedfb8f2ca`
- 릴리즈: [공개 패치](https://github.com/hillofsky/naruto-narutimate-portable-korean-patch/releases/tag/v0.2.0-preview)
- 다운로드 manifest와 저장소 manifest 일치: PASS
- 원본 및 다운로드 패치 크기/SHA-256 검사: PASS
- 복원 ISO 크기: 4,292,155,392 bytes
- 복원 ISO SHA-256: `3192c66bf22f2a21b03346e6549f3c6d01f1d7ac69ec91c645ff7ed6fb503e5f` — 기존 배포 기준과 일치
- 새 clone의 check_resume.py / check_history.py: PASS
- 복원 ISO의 tools/develop.py inspect: PASS
- 게임 실행/전체 플레이: NOT_RUN. 기존 게임 QA 상태를 변경하지 않는다.

세부 값은 [검증 JSON](RESTORE_VERIFICATION.json)을 따른다. 검사에 사용한 새 다운로드 패치와 새 출력 ISO만 검사 후 정리했다. 기존 사용자 파일은 삭제하지 않았다.

## 로컬 정리 시 보관

현재 최종 기준에서 후속 수정하는 목적이라면 저장소 + 공개 릴리즈 패치 + 보유한 미패치 원본으로 재개할 수 있다. 과거 중간 ISO 전체는 필수가 아니다. 원본 ISO는 GitHub에 없으므로 삭제 대상 폴더 밖에 보관한다. 별도의 미공개 번역/매핑/자막/실험 자료와 개인 저장 데이터를 보존하려면 개인 백업도 따로 둔다.

이번 사용자의 추가 대조에서는 공개 이력에 없는 텍스트 자료와 저장 데이터를 개인 ZIP으로 보존하고 무결성을 검사했다. 그 ZIP은 공개 저장소에 포함하지 않는다. 모든 과거 파일/이미지/대화가 공개되거나 전체 개발 체인의 재현이 검증됐다는 뜻은 아니다. 개발 지원 범위는 [DEVELOPMENT.md](DEVELOPMENT.md)를 따른다.
