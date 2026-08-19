PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
LANGGRAPH ?= .venv/bin/langgraph
LANGGRAPH_DEV_ARGS ?= --no-reload

.PHONY: dev inspect infra help

dev: ## 로컬 Agent Server와 PCM inspect 서버를 함께 실행
	./scripts/dev.sh $(LANGGRAPH_DEV_ARGS)

inspect: ## PCM inspect 서버만 실행
	$(UVICORN) --env-file .env clio_agent_graph.context.pcm.inspect_api:app --port 2025

infra: ## Ollama embedding 서버를 Docker로 실행
	docker compose -f compose.pcm.yaml up -d --wait

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile \
		| sed -E 's/^([a-zA-Z_-]+):.*##[[:space:]]*(.*)/\1: \2/'
