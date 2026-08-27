#!/bin/sh
set -eu

ollama serve &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' INT TERM EXIT

until OLLAMA_HOST=http://127.0.0.1:11434 ollama list >/dev/null 2>&1; do
  sleep 1
done

OLLAMA_HOST=http://127.0.0.1:11434 ollama pull "${OLLAMA_EMBEDDING_MODEL}"
wait "$server_pid"
