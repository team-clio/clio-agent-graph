# clio-agent 실행 편의화 — 결정 기록

## D1. 도구 선택

- 결정: Makefile + `scripts/dev.sh`.
- 근거: 프로세스 시작·종료 정리를 코드로 재사용할 수 있고 Makefile이 진입점을
  단순하게 만든다.

## D2. `make dev` 동작

- 결정: inspect 서버를 background로 띄우고 `langgraph dev`를 foreground로 실행.
- 근거: 에이전트 로그는 화면에 유지하고, inspect 서버는 종료 시 trap으로 정리한다.

## D3. 문서 갱신

- 결정: README와 작업 문서 모두 갱신.
- 근거: README는 사용법, 작업 문서는 결정 근거를 각각 담당한다.
