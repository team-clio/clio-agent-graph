# Clio Agent Graph

Clio의 요청을 `request.request_type`으로 결정적으로 라우팅하는 Python LangGraph
Agent Server입니다. 상위 그래프 흐름과 PCM, Vector DB, commit-addressed Git mirror가
구현되어 있으며 `process_report`의 원문 조회, Issue 반영, 분석 저장은 Clio Server
internal API에 연결되어 있습니다. Memory sync의 revision commit 경계는 아직 Mock입니다.

별도 공개 그래프는 다음 버그 분석 워크플로를 제공합니다.

- Report Normalizer(NM)는 여러 형태의 BugReport를 원문에 근거한 표준 사실로 바꿉니다.
- Report Matcher(RM)는 RAG 하위 에이전트가 찾은 기존 Issue 후보를 비교해 연결 방향을 제안합니다.
- Issue Analyzer(IA)는 코드 탐색 결과를 Evidence·Finding·Hypothesis로 구분해 가능한 원인을 분석합니다.

## 루트 요청 라우터

```text
START
  → validate_request
  → request.request_type
      ├─ process_report → Report Processing Graph
      └─ analyze_issue  → Issue Analysis Graph
      ├─ document_added / document_deleted → Document Sync Graph
      ├─ repository_added / repository_removed → Repository Sync Graph
      └─ repository_changed → Code Change Sync Graph
  → finalize_request
  → END
```

`process_report`가 신규 이슈를 생성하면 직접 `analyze_issue` 요청이 사용하는 것과
동일한 Issue Analysis Graph를 재사용합니다.

### Report Processing Graph

```text
load_and_normalize_report
  → search_issue_candidates
  → match_report
  → apply_match_decision
      ├─ link_existing → END
      ├─ needs_review  → END
      └─ create_new    → Issue Analysis Graph
```

### Issue Analysis Graph

```text
prepare_analysis
  ├─ search_documents ─┐
  ├─ search_code ──────┼→ analyze_issue
  └─ search_history ───┘
      → plan_resolution
      → quality_gate
      → save_analysis 또는 needs_review
```

## 요청 형식

로컬 Agent는 기본적으로 `http://localhost:8080`의 Clio Server internal API를 호출합니다.
다른 주소를 사용할 때는 `CLIO_SERVER_URL`을 설정합니다.

```json
{
  "request_id": "REQ-001",
  "request_type": "process_report",
  "project_id": "PROJECT-1",
  "payload": {
    "bug_id": "72"
  }
}
```

지원하는 타입:

- `process_report`
- `analyze_issue`
- `document_added`, `document_deleted`
- `repository_added`, `repository_removed`
- `repository_changed`

Pydantic 판별 공용체가 `request_type`별 payload를 그래프 실행 전에 검증합니다.

## 프로젝트 컨텍스트

Issue 분석은 요청 시작 시 PCM snapshot을 고정하고, 같은 snapshot에 묶인 읽기 Tool로
장기 지식을 검색·읽기·출처 추적합니다. `document_added` 경로도 실제 PCM vertical slice에
연결되어 있습니다.

정규화된 Markdown을 heading 단위 Source로 나누고, 다른 Agent와 동일한 전역 `CLIO_MODEL`을 사용하는
Knowledge LLM으로 topic과 변경안을 생성한 뒤 PCM revision으로 commit합니다.
`CLIO_PCM_DATABASE_URL`을 설정하면 PostgreSQL metadata와 immutable Markdown 파일에
영속화하고, 설정하지 않으면 개발용 in-memory PCM을 사용합니다. Vector 의미 검색은
Ollama의 `qwen3-embedding:0.6b`와 pgvector를 사용하고, PostgreSQL FTS·trigram 결과를
Reciprocal Rank Fusion으로 결합합니다. PCM은 현재 pgvector schema에 맞게 Qwen3의
사용자 지정 출력 차원을 384로 요청합니다.

```json
{
  "request_id": "REQ-DOC-1",
  "request_type": "document_added",
  "project_id": "PROJECT-1",
  "payload": {
    "document_id": "requirements",
    "revision": "1",
    "title": "Saved Search Requirements",
    "markdown": "# Permissions\n\nOnly owners can edit a saved search."
  }
}
```

Ollama embedding server는 Docker로 실행할 수 있습니다. PostgreSQL은 `clio-server`의 `compose.yaml`이
제공하는 **단일 인스턴스**에 `clio`(비즈니스)와 `clio_pcm`(PCM) 두 DB로 존재하며, PCM 스키마는
에이전트 최초 연결 시 자동 생성됩니다.

```bash
docker compose -f compose.pcm.yaml up -d --wait
```

```dotenv
CLIO_PCM_DATABASE_URL=postgresql://clio:clio@127.0.0.1:5432/clio_pcm
CLIO_PCM_DATA_ROOT=.clio/pcm-data
```

Migration은 영속 PCM 최초 연결 시 numbered SQL 파일을 순서대로 자동 적용합니다.
Docker 통합 테스트는 다음처럼 별도로 실행합니다.

```bash
CLIO_TEST_POSTGRES_URL="$CLIO_PCM_DATABASE_URL" pytest -m postgres
```

Knowledge commit 뒤에는 변경된 Markdown만 heading 단위로 chunking하고 pgvector index를
증분 갱신합니다. 서버 시작 시 `knowledge_index_revision`이 뒤처진 프로젝트는 현재
Markdown에서 자동 backfill합니다. 임베딩이나 indexing이 실패하면 Knowledge commit은
유지되고 최신 canonical Markdown을 대상으로 keyword-only 검색으로 전환됩니다.

Repository는 on-premise PCM data volume 아래 bare Git mirror로 저장됩니다. 등록 요청의
`source_uri`는 HTTPS URL만 허용하며, Graph Node만 이를 사용하므로 Agent에는 remote URL이나
credential을 노출하지 않습니다. private repository DBMS credential lookup은 TODO입니다.
제거 요청은 해당 repository ID로 해시된 server-managed bare mirror와 manifest만 물리적으로
삭제하며, 재시도해도 안전합니다.

```json
{
  "request_id": "REQ-REPO-1",
  "request_type": "repository_added",
  "project_id": "PROJECT-1",
  "payload": {
    "repository_id": "backend",
    "source_uri": "https://git.example.internal/platform/backend.git",
    "branch": "main",
    "commit": "0123456789abcdef0123456789abcdef01234567"
  }
}
```

분석 시작 시 활성 commit을 snapshot에 복사합니다. 코드 검색, 파일 목록, 파일 읽기는 항상 해당
commit을 사용하며, line range/결과 수 제한, 경로 탈출 차단, secret 파일 거부와 값 masking을
적용합니다. Issue Analysis outer agent에는 저수준 파일 시스템 Tool 대신 objective와 선택적
exploration context만 받는 `explore_codebase` Tool이 제공됩니다. 이 Tool은 내부 agentic explorer가
목록·검색·bounded 읽기를 선택하고 structured cited evidence를 반환합니다. `repository_changed`는
현재 active `before_commit`을 검증하고 branch head인 `after_commit`만 활성화합니다.

Repository lifecycle은 repository-derived PCM knowledge를 ingest 또는 삭제하지 않습니다.
해당 knowledge reconciliation은 명시적인 TODO로 남아 있습니다. 따라서 repository provenance를
보존하는 bounded source collection·LLM extraction·PCM commit은 현재 lifecycle 요청에서 수행하지 않습니다.

## Agent · Tool · Service

리포트 처리와 이슈 분석 노드는 `agents/`의 Tool-calling Agent를 통해 읽기 Tool을
호출합니다. `tools/`는 Agent에 노출되는 입력·출력·권한 경계이고, `services/`는
Tool 뒤의 인프라 구현입니다. PCM Tool의 project와 snapshot은 Graph가 closure에
고정하므로 Agent 입력 스키마에는 노출되지 않습니다.

이슈 생성·연결, 분석 저장, 문서·레포지토리 인덱싱 같은 쓰기 작업은 Agent에
노출하지 않고 Graph Node가 Service를 직접 호출합니다. 리포트 매칭·이슈 분석·해결 계획
Agent는 `create_agent` 기반의 실제 Tool-calling loop를 사용합니다. provider 인증은 LangChain integration이
해당 provider의 표준 환경 변수에서 읽습니다.

모든 LLM 호출은 노드별 설정 없이 하나의 `CLIO_MODEL=provider:model` 선택을 공유합니다. 예를 들어
OpenAI를 선택하면 다음과 같습니다.

```dotenv
CLIO_MODEL=openai:gpt-4.1-mini
OPENAI_API_KEY=<provider-key>
```

Anthropic·Google 등은 해당 LangChain provider integration을 설치한 뒤 같은 형식으로 교체합니다. 커스텀
OpenAI 호환 endpoint는 `CLIO_MODEL_BASE_URL`, `CLIO_MODEL_API_KEY_ENV`와 필요 시
`CLIO_MODEL_EXTRA_BODY`를 보조 연결 옵션으로 사용합니다. 이 값들은 다른 모델을 고르는 노드별 설정이
아니라 선택한 전역 모델의 연결 정보입니다.

구조화 출력은 provider-native JSON Schema API에 의존하지 않습니다. 일반 NM·RM·IA·PCM 호출은
LangChain `function_calling`, 자율 Agent의 최종 응답은 `ToolStrategy`를 공통으로 사용합니다. 따라서
LangChain integration과 tool calling을 지원하는 모델이면 동일한 Pydantic 출력 계약과 Tool runtime을
공유합니다. Tool calling을 지원하지 않는 모델은 자율 Tool 선택이 필요한 Clio 실행 모델로 사용할 수
없습니다.

- 프로젝트 snapshot 고정
- PCM Knowledge hybrid 검색
- Knowledge 전체 Markdown 읽기
- 원본 문서·Repository·해결 이슈 provenance 추적
- 고정 commit의 Repository 목록·코드 검색·line-range 파일 읽기
- 결과 citation의 Knowledge revision 및 Repository commit 검증

## 독립 실행 분석 그래프

루트 이벤트 오케스트레이터와 독립 분석 그래프는 서로 다른 공개 계약이다. 루트의
`clio_agent`는 문자열 기반 이벤트 ID와 PCM·repository lifecycle을 다루고, 독립 그래프는
Clio Server가 제공하는 정규화된 숫자 ID 및 분석 payload를 처리한다. 두 계약을 암묵적으로
변환하지 않고 `langgraph.json`의 별도 entrypoint로 유지한다.

의존성 방향은 다음 규칙을 따른다.

```text
graph entrypoint → workflow(graphs, matching, analysis) → node/service → port/model
                                                        ↓
                                                     adapter
```

- 기능 패키지는 상위 workflow의 state를 import하지 않는다.
- 각 subgraph는 전역 `ClioState` 대신 자신의 workflow state만 사용한다.
- Agent에 전달되는 Tool은 읽기 전용이며, 쓰기 작업은 graph node가 수행한다.
- 외부 구현은 service 또는 adapter 뒤에 두고 graph 생성 경계에서 조립한다.

```text
src/clio_agent_graph/
├── graph.py                 # 안정적인 Agent Server 진입점
├── workflows/
│   ├── orchestration/       # 이벤트 요청·상태·노드·root subgraph
│   ├── reporting/           # 정규화·검색·매칭 workflow
│   └── analysis/            # 코드 탐색·판단·재분석 workflow
├── context/
│   ├── pcm/                 # Project Context Memory와 영속화
│   └── tools/               # snapshot-bound 읽기 전용 Agent Tool
└── runtime/                 # LLM·Codex·tool-calling·structured output
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

`bugs`, `issues`, `issue_bugs`는 읽기 전용이며 Python이
`bug_retrieval_documents`, `bug_embeddings`를 소유합니다. 모든 Issue 상태를 검색하고 현재 Bug 및 이미 연결된
Issue는 제외합니다. 대상 Bug의 compatible active index coverage가 100%가 아니면 불완전 검색을 후보 없음으로
숨기지 않고 실패합니다.

`process_report`는 Issue 생성·연결 전에 해당 Bug snapshot을 `bug_retrieval_indexer`로
색인합니다. 기존 데이터는 cursor 방식 `bug_retrieval_backfill` graph로 색인합니다.
기존 occurrence 기반 retrieval schema를 Bug-only schema로 올리면 이전 corpus는 안전하게
폐기되므로, Agent가 새 요청을 받기 전에 backfill을 완료해야 합니다.
테스트에서는 repository와 embedding model 또는 기존 callback Fake를 주입할 수 있습니다.

## Codebase Exploration Agent

IA의 Code Explorer는 ChatGPT로 로그인된 Codex CLI를 읽기 전용으로 실행해 실제 repository에서 1~10줄짜리
Evidence 후보를 수집할 수 있습니다. 탐색기를 설정하지 않은 IA 그래프는
`CodeExplorerNotConfiguredError`로 실패해 정상적인 검색 결과 0건과 설정 실패를 구분합니다.

## 자율 Tool 선택

기본 그래프는 기존의 결정적인 NM·Hybrid Retrieval·RM·IA 경로를 유지합니다. 역할별 Tool을
그래프 빌더에 주입하면 LangChain agent가 현재 입력과 Tool observation을 보고 필요한 Tool, 호출 순서,
추가 조사 여부와 종료 시점을 직접 결정합니다.

```python
report_matching_graph = build_report_matching_graph(
    normalization_tools=[read_report_attachment, lookup_project_glossary],
    retrieval_tools=[search_issues_exact, search_issues_semantic, read_issue],
    matching_tools=[read_representative_bugs, read_issue_history],
)

issue_analyzer_graph = build_issue_analyzer_graph(
    exploration_tools=[
        list_project_repositories,
        search_repository_code,
        read_repository_file,
        search_project_knowledge,
        read_project_knowledge,
    ],
    judgment_tools=[trace_knowledge_sources],
)
```

Tool은 project와 repository snapshot이 closure에 고정된 읽기 전용 Tool로 만드는 것을 원칙으로 합니다.
Agent는 최종 Pydantic schema를 벗어날 수 없고 Tool·모델 호출 및 graph recursion 상한이 적용됩니다.
선택한 Tool 이름과 인자는 graph 내부 state의 `normalization_tool_calls`, `retrieval_tool_calls`,
`matching_tool_calls`, `exploration_tool_calls`, `judgment_tool_calls`에 기록됩니다. 공개 출력에는 이 감사
정보를 포함하지 않습니다.

외부 Tool은 전역으로 선택된 LangChain ChatModel의 tool calling 기능을 사용합니다. Codex CLI는 application
Tool runtime을 대신하지 않으며, 아래의 선택적 읽기 전용 Code Explorer로만 분리해 사용합니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
cp .env.example .env
alembic upgrade head
langgraph dev
```

서버가 시작되면 다음 주소를 사용할 수 있습니다.

- API: `http://127.0.0.1:2024`
- API 문서: `http://127.0.0.1:2024/docs`
- 그래프 ID: `clio_agent`, `report_matcher`, `bug_retrieval_indexer`,
  `bug_retrieval_backfill`, `issue_analyzer`, `issue_reanalyzer`

### PCM Inspect API

PCM 지식과 스냅샷을 읽기 전용으로 노출하는 standalone FastAPI 서버입니다.
Spring 중계 API(`clio-server`)와 admin 화면이 이 서버를 호출합니다.

```bash
uvicorn --env-file .env clio_agent_graph.context.pcm.inspect_api:app --port 2025
```

- API 문서: `http://127.0.0.1:2025/docs`
- 엔드포인트: `GET /pcm/projects/{project_id}/snapshot`,
  `GET /pcm/projects/{project_id}/knowledge`,
  `GET /pcm/projects/{project_id}/knowledge/{knowledge_id}`
- `uvicorn`은 `langgraph dev`와 달리 `.env`를 자동으로 읽지 않으므로 `--env-file .env`
  로 로컬 설정을 로드합니다. `CLIO_PCM_DATABASE_URL`이 없으면 개발용 in-memory PCM으로
  동작해 기존 영속 데이터가 보이지 않습니다.

`CLIO_MODEL`은 루트 Tool-calling Agent, NM, Retrieval Agent, RM, IA와 PCM Knowledge 생성까지 모든 chat
LLM 사용 지점이 공유하는 유일한 모델 식별자입니다. 값을 변경하고 서버를 재시작하면 전체 실행이 새
provider/model을 사용합니다.

Codex CLI는 전역 chat model과 별개인 선택적 Code Explorer입니다. 이를 사용할 때만 ChatGPT Plus·Pro
구독 로그인을 확인하고 탐색기를 활성화합니다.

```bash
codex login status
# 로그인이 안 돼 있으면: codex login
```

```text
CLIO_CODEX_TIMEOUT_SECONDS=300
CLIO_CODE_EXPLORER=codex
CLIO_CODEBASE_PATH=/absolute/path/to/clio-server
```

이 탐색 경로는 `codex exec`를 일회성·읽기 전용으로 실행하며 저장된 ChatGPT OAuth 자격 증명을
사용합니다. `OPENAI_API_KEY`는 Codex 자식 프로세스에 전달하지 않습니다.

Issue Retrieval Agent에는 PostgreSQL과 embedding 설정이 필요합니다. 로컬 기본 구성은
이 저장소의 `compose.pcm.yaml`에서 Ollama와 Qwen3 Embedding 0.6B를 실행합니다.

```text
CLIO_DATABASE_URL=postgresql+psycopg://clio:clio@localhost:5432/clio
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:0.6b
CLIO_OLLAMA_BASE_URL=http://127.0.0.1:11434
CLIO_OLLAMA_TIMEOUT_SECONDS=120
```

아래 명령으로 Ollama만 실행할 수 있습니다.

```bash
docker compose -f compose.pcm.yaml up -d --wait ollama
```

처음 실행하면 image와 약 639MB 모델을 내려받으므로 시간이 걸릴 수 있습니다.
모델은 `clio_ollama` volume에 보존됩니다. Qwen3 query에는 검색 목적에 맞는 영문 instruction을
추가하고, 색인 document에는 instruction을 넣지 않습니다.

DB engine과 embedding provider는 최초 실제 호출 때만 생성됩니다. 설정이 없거나 Ollama가 준비되지 않으면
hash 모델로 조용히 대체하지 않고 retrieval run이 실패합니다. embedding 모델을 변경하면 기존 active 문서도
새 모델로 다시 색인해야 합니다.

테스트에서는 graph factory에 deterministic fake embedding을 주입하며, 실제 기본 실행은
`OLLAMA_EMBEDDING_MODEL`이 없거나 Ollama가 준비되지 않은 경우 구체적인 설정·연결 오류로 실패합니다.

NM의 `raw_payload`는 민감 key를 가린 뒤 모델에 전달하며 기본 상한은 32 KiB입니다.
`CLIO_MAX_RAW_PAYLOAD_BYTES`로 상한을 변경할 수 있습니다.

RM 정책 기본값은 다음 환경변수로 변경할 수 있습니다.

```text
CLIO_RM_AUTO_LINK_THRESHOLD=0.95
CLIO_RM_REVIEW_THRESHOLD=0.70
CLIO_RM_CANDIDATE_MARGIN=0.10
```

## report_matcher 그래프 입출력

입력:

```json
{
  "project_id": 3,
  "bug_id": 72,
  "bug_report": {
    "bug_id": 351,
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
    "bug_id": 351,
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
    "bug_id": 351,
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
        "bug_id": 351,
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
python -m clio_agent_graph.workflows.reporting.retrieval.evaluation evals/issue_retrieval_cases.json
```

## 다음 구현 지점

1. 실제 저장소·심볼·호출 관계·최근 변경을 조사하는 Codebase Exploration Agent
2. Agent retrieval 후보 검색과 root `process_report` 흐름 통합
3. 운영 환경용 영속 체크포인터와 인증 정책

`langgraph dev`는 로컬 개발용 Agent Server입니다. 배포 이미지는 LangGraph CLI의
`langgraph build`로 생성하고, 운영 환경에서는 영속 저장소와 작업 큐를 구성해야 합니다.
