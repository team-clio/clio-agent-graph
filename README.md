# Clio Agent Graph

Clio의 버그 분석 워크플로를 제공하는 Python LangGraph Agent Server입니다.

- Report Normalizer(NM)는 여러 형태의 BugReport를 원문에 근거한 표준 사실로 바꿉니다.
- Report Matcher(RM)는 RAG 하위 에이전트가 찾은 기존 Issue 후보를 비교해 연결 방향을 제안합니다.
- Issue Analyzer(IA)는 코드 탐색 결과를 Evidence·Finding·Hypothesis로 구분해 가능한 원인을 분석합니다.

## 구조

```text
src/clio_agent_graph/
├── graph.py           # Agent Server에 노출되는 compiled graph
├── state.py           # 공개 입출력과 내부 graph state
├── normalization/     # NM 계약·서비스·모델 adapter
├── matching/          # RM 계약·retrieval subgraph·비교 정책·모델 adapter
├── retrieval/         # Hybrid Bug 검색·색인·PostgreSQL adapter
└── analysis/          # IA 계약·Code Explorer·Judgment subagent·공통 오케스트레이터
```

현재 흐름:

```text
START
  → normalize_report
  → issue_retrieval_subgraph
  → 후보 있음?
      ├─ 없음 → apply_match_policy
      └─ 있음 → judge_issue_match → apply_match_policy
  → END
```

RM은 DB를 변경하지 않고 `AUTO_LINK`, `REVIEW`, `CREATE_NEW` 중 하나를 제안합니다. 실제 Issue 연결과
생성은 Clio Server 또는 상위 오케스트레이터의 책임입니다.

IA는 Supervisor가 호출 시점을 결정하는 별도 공개 그래프입니다.

```text
issue_analyzer   → Initial Judgment Subagent → 최초 IssueAnalysis
issue_reanalyzer → Revision Judgment Subagent → 새 전체 IssueAnalysis snapshot
```

두 그래프는 공통 IA 오케스트레이터를 사용해 Code Explorer를 최대 3회 호출하고, Evidence를 최대 20개로
중복 제거한 뒤 Finding과 root cause Hypothesis를 생성합니다.

## Issue Retrieval Agent

RM 앞의 Retrieval Agent는 기존 Bug를 세 채널로 검색한 뒤 연결된 Issue별로 집계합니다.

```text
NormalizedReport
  → exact error signal + pg_trgm + pgvector
  → weighted RRF Bug 순위
  → Issue별 집계
  → 대표 Bug 최대 3개 / Issue 최대 5개
  → RM
```

`bugs`, `issues`, `issue_bugs`, `bug_occurrences`는 읽기 전용이며 Python이
`bug_retrieval_documents`, `bug_embeddings`를 소유합니다. 모든 Issue 상태를 검색하고 현재 Bug 및 이미 연결된
Issue는 제외합니다. 대상 Bug의 compatible active index coverage가 100%가 아니면 불완전 검색을 후보 없음으로
숨기지 않고 실패합니다.

새 snapshot은 `bug_retrieval_indexer`, 기존 데이터는 cursor 방식 `bug_retrieval_backfill` graph로 색인합니다.
테스트에서는 repository와 embedding model 또는 기존 callback Fake를 주입할 수 있습니다.

## Codebase Exploration Agent

IA의 Code Explorer는 ChatGPT로 로그인된 Codex CLI를 읽기 전용으로 실행해 실제 repository에서 1~10줄짜리
Evidence 후보를 수집할 수 있습니다. 탐색기를 설정하지 않은 IA 그래프는
`CodeExplorerNotConfiguredError`로 실패해 정상적인 검색 결과 0건과 설정 실패를 구분합니다.

## 로컬 실행

Python 3.11 이상이 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,openai]"
cp .env.example .env
alembic upgrade head
langgraph dev
```

서버가 시작되면 다음 주소를 사용할 수 있습니다.

- API: `http://127.0.0.1:2024`
- API 문서: `http://127.0.0.1:2024/docs`
- 그래프 ID: `clio_agent`, `bug_retrieval_indexer`, `bug_retrieval_backfill`, `issue_analyzer`,
  `issue_reanalyzer`

기본 `langchain` backend에서 `CLIO_MODEL`은 NM·RM·IA가 공유하는 모델 식별자입니다. ChatGPT Plus·Pro
구독 로그인을 로컬 테스트에 사용하려면 먼저 Codex CLI 로그인을 확인한 뒤 backend를 바꿉니다.

```bash
codex login status
# 로그인이 안 돼 있으면: codex login
```

```text
CLIO_CHAT_BACKEND=codex
CLIO_CODEX_TIMEOUT_SECONDS=300
CLIO_CODE_EXPLORER=codex
CLIO_CODEBASE_PATH=/absolute/path/to/clio-server
```

이 경로는 `codex exec`를 일회성·읽기 전용으로 실행하며 저장된 ChatGPT OAuth 자격 증명을 사용합니다.
`OPENAI_API_KEY`는 Codex 자식 프로세스에 전달하지 않습니다. 일반 OpenAI API를 쓸 때는
`CLIO_CHAT_BACKEND=langchain`과 provider API key를 사용하면 됩니다.

Issue Retrieval Agent에는 PostgreSQL과 embedding 설정이 필요합니다. 로컬 기본 구성은
`clio-server/compose.yaml`의 Ollama에서 Qwen3 Embedding 0.6B를 실행합니다.

```text
CLIO_DATABASE_URL=postgresql+psycopg://clio:clio@localhost:5432/clio
CLIO_EMBEDDING_MODEL=ollama:qwen3-embedding:0.6b
CLIO_OLLAMA_BASE_URL=http://127.0.0.1:11434
CLIO_OLLAMA_TIMEOUT_SECONDS=120
```

`docker compose up -d ollama`을 처음 실행하면 image와 약 639MB 모델을 내려받으므로 시간이 걸릴 수 있습니다.
모델은 `clio-ollama` volume에 보존됩니다. Qwen3 query에는 동일 원인의 과거 Bug를 찾으라는 영문 instruction을
추가하고, 색인 document에는 instruction을 넣지 않습니다.

DB engine과 embedding provider는 최초 실제 호출 때만 생성됩니다. 설정이 없거나 Ollama가 준비되지 않으면
hash 모델로 조용히 대체하지 않고 retrieval run이 실패합니다. embedding 모델을 변경하면 기존 active 문서도
새 모델로 다시 색인해야 합니다.

외부 embedding API 없이 로컬 흐름만 smoke test할 때는 아래 값을 명시할 수 있습니다.

```text
CLIO_EMBEDDING_MODEL=local:hash-v1
```

이 deterministic hash embedding은 연결 확인용이며 의미 검색 품질을 평가하거나 운영에 사용할 모델은 아닙니다.

NM의 `raw_payload`는 민감 key를 가린 뒤 모델에 전달하며 기본 상한은 32 KiB입니다.
`CLIO_MAX_RAW_PAYLOAD_BYTES`로 상한을 변경할 수 있습니다.

RM 정책 기본값은 다음 환경변수로 변경할 수 있습니다.

```text
CLIO_RM_AUTO_LINK_THRESHOLD=0.95
CLIO_RM_REVIEW_THRESHOLD=0.70
CLIO_RM_CANDIDATE_MARGIN=0.10
```

## 그래프 입출력

입력:

```json
{
  "project_id": 3,
  "bug_id": 72,
  "bug_report": {
    "bug_report_id": 351,
    "title": "결제 실패",
    "description": "결제 버튼을 누르면 500 오류가 발생합니다.",
    "error_type": "PaymentException",
    "message": "Internal Server Error",
    "stack_trace": ["PaymentService.approve"],
    "raw_payload": {
      "appVersion": "3.14.1"
    }
  }
}
```

정상 출력:

```json
{
  "normalized_report": {
    "bug_report_id": 351,
    "observed_behavior": "결제 버튼 클릭 시 500 오류가 발생한다.",
    "expected_behavior": null,
    "reproduction": {
      "conditions": [],
      "steps": ["결제 버튼 클릭"]
    },
    "environment": {
      "app_version": "3.14.1",
      "additional": {}
    },
    "affected_surface": {
      "feature": "결제"
    },
    "error_signals": {
      "error_type": "PaymentException",
      "message": "Internal Server Error",
      "error_codes": ["PAY-500"],
      "stack_frames": ["PaymentService.approve"]
    },
    "missing_fields": [
      "EXPECTED_BEHAVIOR",
      "REPRODUCTION_CONDITIONS"
    ]
  },
  "match_decision": {
    "bug_id": 72,
    "action": "REVIEW",
    "matched_issue_id": 19,
    "confidence": 0.82,
    "supporting_reasons": ["오류 유형과 발생 기능이 일치합니다."],
    "contradictions": [],
    "review_reasons": ["정확히 일치하는 오류 코드가 없습니다."],
    "candidate_comparisons": [
      {
        "issue_id": 19,
        "confidence": 0.82,
        "supporting_reasons": ["오류 유형과 발생 기능이 일치합니다."],
        "contradictions": [],
        "missing_information": ["오류 코드"]
      }
    ]
  }
}
```

Issue 후보와 대표 Bug 원문은 내부 state에서만 사용하고 공개 출력에는 후보별 비교 요약만 포함합니다.

### 단일 Bug 색인

`bug_retrieval_indexer` 입력:

```json
{
  "project_id": 3,
  "bug_id": 72,
  "normalized_report": {
    "bug_report_id": 351,
    "observed_behavior": "결제 버튼 클릭 시 500 오류가 발생한다.",
    "error_signals": {
      "error_type": "PaymentException",
      "error_codes": ["PAY-500"],
      "stack_frames": ["PaymentService.approve"]
    }
  }
}
```

같은 snapshot과 embedding model을 다시 호출하면 새 행을 만들지 않고 `UNCHANGED`를 반환합니다.

### 과거 Bug backfill

`bug_retrieval_backfill` 입력:

```json
{
  "project_id": 3,
  "after_bug_id": 0,
  "batch_size": 20
}
```

응답의 `next_after_bug_id`를 다음 요청의 cursor로 사용하고 `has_more=false`까지 반복합니다. 개별 과거 데이터
오류는 `failures`에 남지만 DB·LLM·embedding provider 기술 장애는 run 자체를 실패시킵니다.

### IA 최초 분석 입력

```json
{
  "analysis_job_id": 501,
  "project_id": 3,
  "issue": {
    "issue_id": 19,
    "title": "결제 완료 후 주문 미노출"
  },
  "bugs": [
    {
      "bug_id": 72,
      "normalized_report": {
        "bug_report_id": 351,
        "observed_behavior": "결제 완료 후 주문이 보이지 않는다."
      }
    }
  ],
  "trigger_bug_id": 72
}
```

`issue_reanalyzer`는 같은 필드에 새로운 `analysis_job_id`와 기존 `previous_analysis`를 추가로 요구합니다.
두 그래프의 출력은 `{"issue_analysis": ...}`로 동일합니다.

IA Evidence는 실제 판단에 사용한 코드 snapshot을 1~10줄로 보존합니다. path·symbol·line·change ID는
설명 metadata이며 snapshot을 대신하는 포인터가 아닙니다. Finding은 Evidence ID를, Hypothesis는 Finding
ID를 참조하므로 확인된 사실과 추론이 구조적으로 분리됩니다.

## 분기 정책

- 정상 검색 결과가 0건이면 비교 모델을 호출하지 않고 `CREATE_NEW`
- confidence 0.95 이상이며 현상·영향 영역·강한 오류 신호가 있고 모순과 후보 경합이 없으면 `AUTO_LINK`
- confidence 0.70 이상이지만 자동 연결 조건을 만족하지 못하면 `REVIEW`
- 나머지는 `CREATE_NEW`

강한 오류 신호는 같은 `error_type`과 하나 이상의 같은 `error_code` 또는 `stack_frame`입니다. 1위와 2위
confidence 차이가 0.10 이하이면 자동 연결하지 않습니다.

## 테스트 및 품질 검사

```bash
pytest
ruff check .
ruff format --check .
```

실제 PostgreSQL+pgvector 통합 경로는 선택적으로 실행합니다.

```bash
CLIO_RUN_POSTGRES_TESTS=1 pytest -m postgres
```

검색 평가셋은 실제 DB와 embedding 설정이 있을 때 실행합니다. 설정이 없으면 `SKIPPED`를 출력하며 가짜 점수를
만들지 않습니다.

```bash
python -m clio_agent_graph.retrieval.evaluation evals/issue_retrieval_cases.json
```

## 다음 구현 지점

1. 실제 저장소·심볼·호출 관계·최근 변경을 조사하는 Codebase Exploration Agent
2. Clio Server 이벤트·색인 작업 큐·결과 저장 계약
3. 운영 환경용 영속 체크포인터와 인증 정책

`langgraph dev`는 로컬 개발용 Agent Server입니다. 배포 이미지는 LangGraph CLI의
`langgraph build`로 생성하고, 운영 환경에서는 영속 저장소와 작업 큐를 구성해야 합니다.
