# 코드 검색 결과 순서 — Decisions

사용자가 plan 승인 시 "추천대로 진행"으로 D1~D6 결정을 위임했다. 각 항목은 plan의 추천안을 따른다.

## D2. 파일 분류 판정

### 결정: A — 확장자와 경로 규칙

- 대안 A: 확장자·경로 규칙으로 소스·테스트·설정·문서를 나눈다. ← 선택
- 대안 B: GitHub Linguist 같은 외부 분류기. 정확하지만 의존성과 이미지 크기가 늘어난다.
- 대안 C: 저장소 등록의 include/exclude만 쓴다. 설정하지 않으면 지금과 같다.

선택 이유: 의존성 없이 결정적으로 동작하고, 실제 문제(문서가 소스를 밀어냄)를 가르는 데 충분하다.

구현 규칙 (`classify_search_path`, 판정 순서대로):
1. 문서: `.md .mdx .rst .adoc .txt`. 테스트 디렉터리 안의 문서도 문서로 본다.
2. 테스트: 경로 조각 `test/ tests/ __tests__/ spec/` 또는 파일명 `test_*`, `*_test.*`, `*Test.*`, `*Tests.*`, `*.spec.*`, `*.test.*`.
3. 설정: `.json .yml .yaml .toml .xml .properties .gradle .ini .cfg .conf`.
4. 그 외는 소스다.
