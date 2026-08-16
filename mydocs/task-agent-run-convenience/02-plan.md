# clio-agent 실행 편의화 — 구현 계획

## 1. 단계

1. overview 작성·확정·커밋
2. plan 작성·확정(이 문서)
3. 결정 기록 작성·커밋
4. Makefile + `scripts/dev.sh` 구현
5. README 안내 추가
6. 검증(쉘 문법, ruff, pytest)
7. result 작성·커밋

## 2. 결정 포인트

### D1. 도구 선택

- 선택지: README 명령만 / Makefile / Makefile + dev script
- 추천: Makefile + dev script. 프로세스 정리를 script에서 처리한다.

### D2. `make dev` 동작

- 선택지: 두 서버를 모두 foreground로 관리 / inspect를 background로 띄우고
  `langgraph dev`를 foreground로 실행
- 추천: 후자. `langgraph dev`의 인터랙티브 로그를 유지하고 inspect는 종료 시 정리한다.

### D3. 문서 갱신

- 선택지: README만 / README + 작업 문서
- 추천: README + 작업 문서 모두 갱신.

## 3. 구현 계획(결정 후)

```makefile
PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

.PHONY: dev inspect infra

dev:
	./scripts/dev.sh

inspect:
	$(UVICORN) --env-file .env clio_agent_graph.context.pcm.inspect_api:app --port 2025

infra:
	docker compose -f compose.pcm.yaml up -d --wait
```

`scripts/dev.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env 파일이 필요합니다. cp .env.example .env"; exit 1; }
set -a; source .env; set +a
INSPECT_PORT="${CLIO_PCM_INSPECT_PORT:-2025}"
.venv/bin/uvicorn --env-file .env clio_agent_graph.context.pcm.inspect_api:app \
  --port "$INSPECT_PORT" &
INSPECT_PID=$!
cleanup() {
  kill "$INSPECT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$INSPECT_PORT/docs" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
langgraph dev
```

## 4. 커밋 계획

- `docs: clio-agent 실행 편의화 overview` / `docs: ... 구현 계획` /
  `docs: ... 결정 기록`
- `chore: add agent dev convenience make targets`
- `docs: clio-agent 실행 편의화 result`
