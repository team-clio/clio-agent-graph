# 테스트와 운영 컨벤션

## 개발 환경과 기본 검증

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
cp .env.example .env
```

변경 후 기본 검증 순서는 다음과 같다.

```bash
ruff format .
ruff check .
pytest
```

format 변경을 원하지 않는 검증 환경에서는 `ruff format --check .`을 사용한다. 로컬 Agent
Server는 `langgraph dev`로 실행한다.

## 테스트 배치

| 대상 | 위치 |
|---|---|
| root routing과 cross-graph 동작 | `tests/test_graph.py` |
| orchestration node | `tests/nodes/` |
| normalization | `tests/normalization/` |
| matching | `tests/matching/` 및 `tests/test_report_matching_graph.py` |
| issue analysis | `tests/analysis/` |
| retrieval | `tests/retrieval/` |
| PCM | `tests/pcm/` |
| Agent Tool | `tests/tools/` |
| runtime·architecture | `tests/test_*.py` |

테스트 함수 이름은 `test_<behavior>()` 형식으로 짓는다. 구현 메서드명이 아니라 관찰 가능한
조건과 결과가 이름에서 드러나게 한다.

## 테스트 원칙

- 모든 동작 변경에는 가장 가까운 service/node 단위 회귀 테스트를 추가한다.
- routing이나 공개 결과가 달라지면 실제 graph input을 `invoke()` 또는 `ainvoke()`해 결과,
  terminal status, 실행·미실행 node를 함께 검증한다.
- live LLM에 의존하지 않는다. port fake나 `monkeypatch`로 deterministic output을 주입한다.
- DB·embedding·provider adapter는 계약 테스트를 유지하고, graph factory에 fake를 주입해
  orchestration을 분리 검증한다.
- async service/node에는 `@pytest.mark.asyncio`를 사용한다.
- 패키지 의존성 규칙은 `tests/test_architecture.py`의 AST import 검사로 보호한다.
- 오류 경로, 경계값, idempotent replay, snapshot/citation mismatch를 정상 경로와 함께 테스트한다.

## PostgreSQL 통합 테스트

일반 `pytest`는 외부 DB 없이 실행 가능해야 한다. 실제 PostgreSQL·pgvector가 필요한 테스트는
`postgres` marker를 사용한다.

```bash
docker compose -f compose.pcm.yaml up -d --wait
CLIO_TEST_POSTGRES_URL="$CLIO_PCM_DATABASE_URL" pytest -m postgres
```

통합 테스트는 migration, SQL/pgvector 동작, 영속성처럼 fake로 충분히 보장할 수 없는 경계에
한정한다.

## 설정 규칙

- `.env.example`을 설정의 기준 목록으로 유지하고 secret 값은 비워 둔다.
- API key, LangSmith token, provider credential은 commit하지 않는다.
- 애플리케이션 설정은 `CLIO_` prefix를 사용한다. Ollama 컨테이너와 애플리케이션이 함께 읽는
  모델명은 Ollama 표준에 맞춰 `OLLAMA_EMBEDDING_MODEL`을 사용한다. 읽는 코드와
  `.env.example` 및 관련 테스트를 함께 갱신한다.
- 설정 누락 시 개발용 fallback이 명시된 경우만 fallback한다. 운영 필수 설정은 구체적인 오류로 실패한다.
- 일반 테스트는 환경 변수에 암묵적으로 의존하지 않도록 `monkeypatch.setenv/delenv`로 격리한다.

주요 설정 그룹은 다음과 같다.

| 그룹 | 환경 변수 |
|---|---|
| 전역 LLM | `CLIO_MODEL`, `CLIO_MODEL_BASE_URL`, `CLIO_MODEL_API_KEY_ENV`, `CLIO_MODEL_EXTRA_BODY` |
| Codex 탐색 | `CLIO_CODEX_COMMAND`, `CLIO_CODEX_MODEL`, `CLIO_CODEX_TIMEOUT_SECONDS`, `CLIO_CODE_EXPLORER`, `CLIO_CODEBASE_PATH` |
| report/matching | `CLIO_MAX_RAW_PAYLOAD_BYTES`, `CLIO_RM_*` |
| PCM | `CLIO_PCM_DATABASE_URL`, `CLIO_PCM_DATA_ROOT`, `OLLAMA_EMBEDDING_MODEL`, `CLIO_OLLAMA_*` |
| retrieval | `CLIO_DATABASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `CLIO_OLLAMA_*` |

## 변경 완료 체크리스트

1. 공개 graph 계약과 `langgraph.json` entrypoint 호환성을 확인한다.
2. read Tool/write Node 경계와 snapshot provenance가 유지되는지 확인한다.
3. 새 설정과 migration의 upgrade 경로를 문서화한다.
4. 관련 단위·graph·선택적 통합 테스트를 실행한다.
5. `ruff check .`과 `ruff format --check .`을 통과시킨다.
6. PR에 변경된 graph/API 동작, 실행한 검증, 필요한 sample request/response를 적는다.
