# clio-agent 실행 편의화

## 1. 작업 배경

clio-agent-graph는 `langgraph dev`와 standalone PCM inspect 서버(`:2025`)를 별도로
실행해야 한다. `uvicorn`은 `.env`를 자동으로 읽지 않아 `--env-file`을 기억해야 하고,
두 프로세스의 시작·종료가 번거롭다.

## 2. 개선 방향

- `make dev` 한 번으로 inspect 서버를 백그라운드로 띄우고 `langgraph dev`를 실행한다.
- 종료 시 inspect 서버를 정리해 포트 점유를 막는다.
- `make inspect`로 inspect 서버만 실행하고, `make infra`로 Ollama를 시작한다.
- README 로컬 실행 섹션에 사용법을 추가한다.

## 3. 범위

### 포함

- `Makefile`: `dev` · `inspect` · `infra` 타깃
- `scripts/dev.sh`: `.env` 로드 → inspect 서버 시작 → `langgraph dev` → 종료 정리
- README 실행 안내

### 제외

- 서버 프로세스 데몬화·systemd·Docker로 에이전트 전체 패키징
- clio-server DB 자동 시작(기존 compose 가이드 유지)

## 4. 완료 기준

- `make dev`에서 inspect 서버와 `langgraph dev`가 함께 뜬다.
- Ctrl+C 종료 시 inspect 서버가 함께 종료된다.
- `make inspect` 단독 실행이 가능하다.
