# 아키텍처

## 시스템의 역할

Clio Agent Graph는 Python 3.11+와 LangGraph로 구현한 Agent Server다. 버그 리포트
정규화·검색·매칭, 이슈 분석, Project Context Memory(PCM), repository lifecycle을
그래프로 조합한다. 외부 시스템 변경은 Agent가 직접 수행하지 않으며, 상위 Graph Node나
Clio Server가 최종 책임을 가진다.

## 두 종류의 공개 계약

이 저장소에는 서로 자동 변환하지 않는 두 종류의 API가 있다.

### 루트 이벤트 그래프

`src/clio_agent_graph/graph.py`의 `graph`가 안정적인 서버 진입점이다. 문자열 ID와
`request.request_type`을 사용하는 이벤트 계약을 받고 다음처럼 결정적으로 라우팅한다.

```text
START → validate_request → route_request
  ├─ process_report                         → report_processing
  ├─ analyze_issue                          → issue_analysis
  ├─ document_added | document_deleted      → document_sync
  ├─ repository_added | repository_removed  → repository_sync
  └─ repository_changed                     → code_change_sync
각 subgraph → finalize_request → END
```

요청은 `workflows/orchestration/requests.py`의 Pydantic 판별 공용체가 검증한다.
지원하지 않는 타입과 선언되지 않은 필드는 routing 전에 거부한다.
`process_report`는 Clio Server의 Bug 식별자인 `payload.bug_id`를 사용하며, 오케스트레이션
상태와 최종 결과에서도 같은 이름을 유지한다.

### 독립 실행 그래프

Clio Server가 정규화한 숫자 ID와 기능별 payload를 받는 별도 그래프다.

| `langgraph.json` 이름 | 진입점 | 책임 |
|---|---|---|
| `report_matcher` | `reporting/matching/graph.py` | 정규화, 후보 검색, 매칭 제안 |
| `bug_retrieval_indexer` | `reporting/retrieval/graph.py` | 단일 Bug 검색 색인 |
| `bug_retrieval_backfill` | `reporting/retrieval/graph.py` | 기존 Bug batch 색인 |
| `issue_analyzer` | `analysis/graph.py` | 최초 이슈 분석 |
| `issue_reanalyzer` | `analysis/graph.py` | 기존 분석의 새 snapshot 생성 |

독립 Report Matcher는 `AUTO_LINK`, `REVIEW`, `CREATE_NEW`를 제안할 뿐 DB를 직접
변경하지 않는다. 실제 연결·생성은 호출자 또는 상위 오케스트레이터의 책임이다.

## 패키지 구조와 책임

```text
src/clio_agent_graph/
├── graph.py                    # 안정적인 루트 이벤트 entrypoint
├── workflows/
│   ├── orchestration/          # 이벤트 요청, 공유 상태, node, root subgraph
│   ├── reporting/
│   │   ├── normalization/      # 원문 BugReport → 검증된 표준 사실
│   │   ├── retrieval/          # hybrid 검색, 색인, fusion, persistence
│   │   └── matching/           # 후보 비교와 정책 기반 결정
│   └── analysis/               # 코드 탐색, 판단, 재분석
├── context/
│   ├── pcm/                    # project memory, provenance, 영속화
│   ├── tools/                  # snapshot-bound 읽기 전용 Agent Tool
│   ├── repository.py           # commit-addressed Git mirror 접근
│   └── application.py          # 장수 서비스 조립과 수명 주기
└── runtime/                    # LLM, structured output, Agent/Codex 실행
```

## 의존성 방향

```text
entrypoint → workflow graph/node → service → port/model
                                      ↓
                                   adapter
```

- 기능 패키지는 `workflows.orchestration`이나 전역 `ClioState`를 import하지 않는다.
- normalization은 matching에 의존하지 않는다.
- `context`는 orchestration에 의존하지 않는다.
- domain 계약은 Pydantic model과 `Protocol`에 둔다.
- LangChain, PostgreSQL, Ollama, Codex 같은 구현 세부사항은 adapter/repository 뒤에 둔다.
- 기본 구현 선택과 의존성 조립은 `build_*_graph()` 또는 `context/application.py`에서 한다.

이 규칙 중 일부는 `tests/test_architecture.py`가 import 회귀 테스트로 강제한다.

## 주요 workflow

### Report Processing

```text
start_workflow
  → load_and_normalize_report
  → search_issue_candidates
  → match_report
  → apply_match_decision
      ├─ link_existing | needs_review → complete_workflow → END
      └─ create_new → 공통 Issue Analysis Graph → complete_workflow → END
```

신규 이슈 경로는 직접 `analyze_issue` 요청과 같은 분석 subgraph를 재사용한다.
`process_report`는 Clio Server에 workflow를 등록해 `RUNNING`으로 전이한 뒤 모든 쓰기에
같은 run ID를 사용한다. 사람 검토가 필요한 업무 결과도 Server workflow는 `COMPLETED`로
저장한다. 완료된 request replay는 저장된 결과를 반환하며 Agent를 다시 실행하지 않고,
실행 중 예외는 원래 오류를 전파하기 전에 Server workflow를 `FAILED`로 전이한다.

### Issue Analysis

```text
prepare_analysis
  ├─ search_documents ─┐
  ├─ search_code ──────┼→ analyze_issue → plan_resolution → quality_gate
  └─ search_history ───┘                         ├─ passed → save_analysis
                                                 ├─ retry  → analyze_issue
                                                 └─ review → mark_analysis_for_review
```

세 검색은 병렬 fan-out 후 fan-in한다. 분석 시작 시 PCM revision과 활성 repository
commit을 snapshot으로 고정하며, quality gate는 citation이 그 snapshot과 일치하는지
검증한다.

### PCM과 repository

- PCM은 설정이 없으면 개발용 in-memory 구현을, `CLIO_PCM_DATABASE_URL`이 있으면
  PostgreSQL metadata와 immutable Markdown 저장소를 사용한다.
- 문서는 heading 단위 source로 나뉘고 knowledge change set으로 commit된다.
- repository는 server-managed bare Git mirror로 보관하며 검색과 읽기는 고정 commit만 사용한다.
- knowledge 검색은 vector, PostgreSQL FTS, trigram 결과를 RRF로 합친다. 색인 실패 시
  canonical Markdown commit은 유지하고 keyword-only 검색으로 degrade한다.
- repository lifecycle과 repository-derived PCM knowledge reconciliation은 현재 별도 책임이다.
