# Clio Agent Graph

Clio의 요청을 `request.type`으로 결정적으로 라우팅하는 Python LangGraph
Agent Server입니다. 현재 구현은 그래프 플로우와 상태 계약에 집중하며, LLM,
API Server, Vector DB 및 Git 연동은 placeholder로 남겨 두었습니다.

## 현재 그래프

```text
START
  → validate_request
  → request.type
      ├─ process_report → Report Processing Graph
      └─ analyze_issue  → Issue Analysis Graph
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

```json
{
  "request_id": "REQ-001",
  "type": "process_report",
  "project_id": "PROJECT-1",
  "payload": {
    "report_id": "REPORT-1"
  }
}
```

지원하는 타입:

- `process_report`
- `analyze_issue`

Pydantic 판별 공용체가 `type`별 payload를 그래프 실행 전에 검증합니다.

## 프로젝트 컨텍스트

`ProjectContextService`는 인터페이스만 존재합니다. 현재 검색 노드는 입력 상태에
이미 제공된 evidence를 전달하거나 빈 목록을 반환합니다. 추후 구현체에서 다음
기능을 연결합니다.

- 프로젝트 snapshot 고정
- 문서 검색
- 코드 검색
- 과거 해결 이슈 검색

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,openai]"
cp .env.example .env
langgraph dev
```

서버가 시작되면 다음 주소를 사용할 수 있습니다.

- API: `http://127.0.0.1:2024`
- API 문서: `http://127.0.0.1:2024/docs`
- 그래프 ID: `clio_agent`

## 테스트 및 품질 검사

```bash
pytest
ruff check .
ruff format --check .
```
