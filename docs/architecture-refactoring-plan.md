# Clio Agent Graph 아키텍처 개선 계획

## 1. 목적

현재 코드베이스는 최상위 폴더가 `workflows`, `context`, `runtime`으로 간결해졌지만,
실제 의존성은 이 구조를 완전히 따르지 않는다. 일부 기능은 새 위치로 이동했을 뿐 기존
결합과 중복 구현을 그대로 유지하고 있다.

이번 개선의 목표는 다음과 같다.

- 폴더 구조와 실제 의존성 방향을 일치시킨다.
- Report Processing과 Issue Analysis의 구형·신형 구현을 하나로 통합한다.
- Agent의 읽기 권한과 Graph Node의 쓰기 권한을 명확하게 유지한다.
- 도메인 계약을 특정 workflow가 독점하지 않도록 소유권을 바로잡는다.
- 프로젝트·이슈·버그 provenance에 하드코딩된 식별자가 들어가지 않게 한다.
- 아키텍처 규칙을 자동 테스트로 보호한다.

## 2. 현재 문제

### 2.1 `context`가 상위 workflow에 의존한다

`context/tools/codebase_exploration.py`가 다음 모듈을 직접 참조한다.

- `workflows.analysis.agentic_explorer`
- `workflows.analysis.models`
- `workflows.reporting.normalization.models`

이로 인해 인프라와 읽기 도구를 제공해야 하는 `context`가 특정 분석 workflow를 조립하는
역할까지 담당한다.

현재 방향:

```text
context → workflows.analysis
context → workflows.reporting
```

목표 방향:

```text
workflows.analysis → context.tools.repository
workflows.analysis → runtime
```

### 2.2 Retrieval과 Matching이 서로 의존한다

Retrieval service가 `matching.models`의 후보·요청 모델을 사용하고, Matching의 retrieval
subgraph는 다시 Retrieval service와 model을 사용한다.

```text
matching → retrieval
    ↑          │
    └──────────┘
```

검색 요청과 검색 결과는 Matching의 내부 계약이 아니라 Reporting pipeline이 공유하는
계약이어야 한다.

### 2.3 구형·신형 workflow가 함께 존재한다

루트 `clio_agent`는 다음 구형 경로를 사용한다.

```text
workflows/orchestration/graphs/report_processing.py
workflows/orchestration/graphs/issue_analysis.py
workflows/orchestration/nodes/*
workflows/orchestration/agents/*
```

독립 공개 그래프는 다음 신형 경로를 사용한다.

```text
workflows/reporting/*
workflows/analysis/*
```

동일한 비즈니스 기능에 서로 다른 모델, 상태, Agent, 정책이 적용될 수 있다. 수정 대상에
따라 동작이 달라지는 것이 가장 큰 유지보수 위험이다.

### 2.4 Code Explorer 입력에 가짜 ID가 들어간다

`context/tools/codebase_exploration.py`가 `project_id`, `issue_id`, `bug_id`,
`bug_report_id`를 모두 `1`로 생성한다. 이는 다음 문제를 일으킬 수 있다.

- 실제 요청과 다른 provenance 생성
- 프로젝트별 검색 범위 및 audit 정보 왜곡
- citation과 외부 저장 결과의 연결 불가능
- 테스트용 값이 운영 경로에 유입

### 2.5 아키텍처 테스트가 실제 규칙을 충분히 검사하지 않는다

현재 테스트는 `context → orchestration`만 금지한다. 다음 잘못된 참조는 검출하지 못한다.

- `context → workflows.analysis`
- `context → workflows.reporting`
- `retrieval → matching → retrieval`
- `runtime → workflow`

### 2.6 개발용 worktree가 Git에 추적된다

`.openclaude/worktrees/agent-aa62630c`가 gitlink로 추적되고 있다. 사용자별 개발 환경이
저장소 이력과 배포 소스에 포함되지 않도록 제거하고 ignore 규칙을 추가해야 한다.

## 3. 목표 아키텍처

```text
src/clio_agent_graph/
├── graph.py
├── workflows/
│   ├── orchestration/
│   │   ├── graph.py
│   │   ├── requests.py
│   │   ├── state.py
│   │   └── adapters.py
│   ├── reporting/
│   │   ├── graph.py
│   │   ├── models.py
│   │   ├── normalization/
│   │   ├── retrieval/
│   │   └── matching/
│   └── analysis/
│       ├── graph.py
│       ├── models.py
│       ├── exploration.py
│       └── judgment.py
├── context/
│   ├── pcm/
│   ├── repository.py
│   └── tools/
│       ├── pcm.py
│       └── repository.py
└── runtime/
    ├── llm.py
    ├── agent_runtime.py
    ├── codex_exec.py
    └── structured_output.py
```

허용할 의존성 방향:

```text
graph.py
   ↓
workflows.orchestration
   ↓
workflows.reporting ───────→ workflows.analysis
   ↓                              ↓
context ports/tools ←─────────────┘
   ↓
context adapters

모든 workflow → runtime
```

금지할 방향:

```text
context → workflows
runtime → workflows
normalization → matching
retrieval → matching
analysis → orchestration
```

## 4. 단계별 실행 계획

### Phase 0. 안전장치와 저장소 정리

작업:

1. `.openclaude/worktrees/agent-aa62630c` gitlink를 저장소에서 제거한다.
2. `.gitignore`에 `.openclaude/worktrees/`를 추가한다.
3. 현재 공개 그래프 6개의 입력·출력 contract regression test를 고정한다.
4. `langgraph.json`의 모든 entrypoint import smoke test를 추가한다.

완료 조건:

- 개발자 로컬 worktree가 `git status`에 나타나지 않는다.
- 구조 변경 전후의 공개 입력·출력이 테스트로 비교 가능하다.

### Phase 1. Code Explorer 소유권 수정

작업:

1. `context/tools/codebase_exploration.py`에서 분석 모델과 graph 조립을 제거한다.
2. 저수준 repository tool은 `context/tools/repository.py`에 유지한다.
3. 고수준 `explore_codebase` Tool factory는 `workflows/analysis/`로 이동한다.
4. `ExplorationRequest`를 실제 graph state에서 전달하도록 변경한다.
5. `project_id=1`, `issue_id=1`, `bug_id=1`, `bug_report_id=1`을 제거한다.
6. snapshot의 project ID와 요청 project ID가 다르면 즉시 실패하도록 검증한다.

완료 조건:

- `context`에서 `workflows` import가 0개다.
- Explorer 결과가 실제 project, issue, bug ID를 보존한다.
- 고정 commit과 PCM revision citation 검증이 계속 통과한다.

### Phase 2. Reporting 공통 계약 추출

작업:

1. 다음 모델을 `workflows/reporting/models.py` 또는 Retrieval 소유 모델로 이동한다.
   - `IssueRetrievalRequest`
   - `IssueRetrievalResponse`
   - `IssueCandidate`
   - `RepresentativeBug`
2. Retrieval service가 `matching.models`를 import하지 않게 한다.
3. Matching은 reporting 공통 계약과 Retrieval port에만 의존하게 한다.
4. 기존 import 경로를 한 번에 변경하고 불필요한 re-export는 만들지 않는다.

목표:

```text
normalization ─┐
retrieval ─────┼→ reporting graph
matching ──────┘
```

완료 조건:

- Retrieval package의 Matching import가 0개다.
- 패키지 의존성 graph에 cycle이 없다.
- 기존 retrieval evaluation 결과와 match policy 테스트가 유지된다.

### Phase 3. 공통 기본 계약 분리

작업:

1. `ContractModel`, `NonEmptyText`처럼 여러 workflow가 쓰는 기반 타입을
   normalization 소유에서 reporting 공통 또는 별도 contract 모듈로 이동한다.
2. Analysis가 normalization 구현 세부사항을 import하지 않게 한다.
3. `NormalizedReport`가 실제로 여러 workflow의 공통 입력이라면 reporting public contract로
   승격한다.

완료 조건:

- Analysis가 `reporting.normalization`을 직접 import하지 않는다.
- 공통 모델은 특정 처리 단계 이름 아래에 위치하지 않는다.

### Phase 4. 루트 Report Processing 통합

작업:

1. 문자열 기반 `ProcessReportRequest`를 신형 Reporting graph 입력으로 변환하는 adapter를
   orchestration에 구현한다.
2. report 원문 조회와 ID 변환은 명시적인 port/service 경계로 만든다.
3. 루트 graph가 `workflows/reporting`의 동일 graph 또는 application service를 호출하게 한다.
4. 결과 action을 기존 루트 응답인 `link_existing`, `needs_review`, `create_new`로 변환한다.
5. 다음 구형 구현을 제거한다.
   - `orchestration/agents/report_processing.py`
   - 대응 구형 node의 정규화·검색·판단 로직

완료 조건:

- 리포트 정규화·검색·매칭 구현이 한 벌만 존재한다.
- 루트 요청과 독립 `report_matcher`가 동일한 match policy를 사용한다.
- 외부 이슈 연결·생성 쓰기는 여전히 Graph Node 경계에만 존재한다.

### Phase 5. Issue Analysis 통합

작업:

1. 문자열 기반 루트 Issue 요청을 신형 Analysis graph 입력으로 변환한다.
2. 직접 분석 요청과 신규 이슈 분석이 동일한 Analysis graph를 호출하게 한다.
3. PCM·repository snapshot을 Analysis input 또는 injected explorer로 전달한다.
4. 기존 quality gate 중 필요한 citation revision 검증을 신형 결과 검증 단계로 이전한다.
5. 다음 구형 구현을 제거한다.
   - `orchestration/agents/issue_analysis.py`
   - `orchestration/graphs/issue_analysis.py`
   - 중복 분석·계획 node

완료 조건:

- Issue 분석 및 재분석의 핵심 orchestration이 한 벌만 존재한다.
- 신규 Report와 직접 Issue 요청이 같은 분석 계약을 사용한다.
- retry, insufficient evidence, needs-review 상태가 명시적으로 매핑된다.

### Phase 6. Composition root와 의존성 주입 정리

작업:

1. `context/application.py`의 service locator 호출을 graph 조립 경계로 이동한다.
2. Graph builder가 필요한 Reader, Writer, Repository, Model을 인자로 받게 한다.
3. 운영 기본 구현은 최상위 composition root에서 한 번만 구성한다.
4. 테스트는 module monkeypatch 대신 fake port를 builder에 주입한다.

완료 조건:

- Node가 `get_application_services()`를 직접 호출하지 않는다.
- import 시점에 LLM Agent 또는 외부 연결 객체가 생성되지 않는다.
- 단위 테스트가 전역 cache 초기화에 의존하지 않는다.

### Phase 7. 상태 계약 최소화

작업:

1. Root state에는 routing과 공통 결과만 둔다.
2. 각 subgraph는 전용 input/output schema를 사용한다.
3. Subgraph 경계마다 명시적인 adapter node로 값을 변환한다.
4. 가능한 `dict[str, Any]`를 Pydantic model 또는 구체 TypedDict로 교체한다.

완료 조건:

- 각 node의 필수 입력이 타입에서 확인된다.
- 존재하지 않는 state key 접근이 정적 검사 또는 입력 검증에서 발견된다.
- Root state에 workflow 내부 임시 필드가 노출되지 않는다.

### Phase 8. 아키텍처 테스트 강화

추가할 규칙:

```text
context !→ workflows
runtime !→ workflows | context
reporting.normalization !→ reporting.matching | reporting.retrieval
reporting.retrieval !→ reporting.matching
analysis !→ orchestration
```

추가 검증:

- Python AST 기반 import dependency 검사
- 전체 package cycle 검사
- `langgraph.json` entrypoint import 검사
- 공개 graph input/output snapshot 검사
- Agent Tool 목록에 write operation이 없는지 검사
- source tree에서 하드코딩된 production ID 패턴 검사

완료 조건:

- 잘못된 의존성을 하나 추가하면 CI가 실패한다.
- 문서에 적힌 의존성 규칙과 테스트 규칙이 일치한다.

## 5. 권장 PR 분리

한 번에 전체를 변경하지 않고 다음 PR로 나누는 것을 권장한다.

1. `chore: remove tracked local worktrees`
2. `refactor(analysis): move code explorer composition into workflow`
3. `refactor(reporting): extract shared retrieval contracts`
4. `refactor(reporting): reuse reporting graph from root orchestration`
5. `refactor(analysis): reuse analyzer graph from root orchestration`
6. `refactor: inject services at graph composition root`
7. `test: enforce architecture dependency rules`
8. `docs: align architecture guide with unified workflows`

각 PR은 독립적으로 테스트를 통과하고 공개 graph contract를 유지해야 한다.

## 6. 검증 명령

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
git diff --check
```

PostgreSQL 변경이 포함된 단계에서는 다음 통합 테스트도 실행한다.

```bash
CLIO_TEST_POSTGRES_URL="$CLIO_PCM_DATABASE_URL" .venv/bin/pytest -m postgres
```

## 7. 최종 완료 정의

다음 조건을 모두 만족하면 아키텍처 통합이 완료된 것으로 본다.

- 최상위 구조와 실제 import 방향이 일치한다.
- Report Normalization, Retrieval, Matching 구현이 각각 한 벌만 존재한다.
- Issue Analysis와 Code Exploration orchestration이 각각 한 벌만 존재한다.
- Root graph와 독립 공개 graph가 같은 핵심 application workflow를 재사용한다.
- `context`와 `runtime`이 workflow에 의존하지 않는다.
- Agent는 snapshot-bound 읽기 Tool만 보유한다.
- 모든 외부 write는 명시적인 Graph Node 또는 application command 경계에서 실행된다.
- 모든 provenance ID와 revision이 실제 요청에서 전달된다.
- 아키텍처 규칙과 공개 API contract가 CI 테스트로 보호된다.

