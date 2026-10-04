#!/bin/sh
# 컨테이너 진입점: 검색 스키마 적용 → PCM Inspect(:2025) → Agent Server(:2024)
set -eu

alembic upgrade heads

uvicorn clio_agent_graph.context.pcm.inspect_api:app \
	--host 0.0.0.0 --port "${CLIO_PCM_INSPECT_PORT:-2025}" &

exec langgraph dev --host 0.0.0.0 --port 2024 --no-browser --no-reload
