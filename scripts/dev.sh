#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
	echo "error: .env 파일이 없습니다. cp .env.example .env 후 실행하세요." >&2
	exit 1
fi

set -a
source .env
set +a

INSPECT_PORT="${CLIO_PCM_INSPECT_PORT:-2025}"
INSPECT_LOG="${TMPDIR:-/tmp}/clio-pcm-inspect.log"

.venv/bin/uvicorn \
	--env-file .env \
	clio_agent_graph.context.pcm.inspect_api:app \
	--port "$INSPECT_PORT" >"$INSPECT_LOG" 2>&1 &
INSPECT_PID=$!

cleanup() {
	kill "$INSPECT_PID" 2>/dev/null || true
	wait "$INSPECT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
	if curl -fsS "http://127.0.0.1:${INSPECT_PORT}/docs" >/dev/null 2>&1; then
		break
	fi
	sleep 0.5
done

.venv/bin/langgraph dev
