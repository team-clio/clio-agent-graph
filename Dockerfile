FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra llm --extra dev

COPY . .
RUN uv sync --frozen --extra llm --extra dev && touch .env

ENV CLIO_PCM_DATA_ROOT=/data/pcm
VOLUME ["/data"]
EXPOSE 2024 2025
ENTRYPOINT ["/app/docker/entrypoint.sh"]
