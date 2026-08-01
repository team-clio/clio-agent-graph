# Clio Agent Graph

Clio의 요청을 `request.request_type`으로 결정적으로 라우팅하는 Python LangGraph
Agent Server입니다. 상위 그래프 흐름은 구현되어 있으며, LLM, API Server, Vector DB
및 Git 연동은 명시적인 Mock Service와 TODO로 분리되어 있습니다.

## 현재 그래프

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

```json
{
  "request_id": "REQ-001",
  "request_type": "process_report",
  "project_id": "PROJECT-1",
  "payload": {
    "report_id": "REPORT-1"
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

`ProjectContextService`는 인터페이스를 유지하고, 현재는 `MockClioService`가
결정적인 mock evidence와 sync 결과를 제공합니다. Mock의 모든 외부 연동 지점에는
실제 구현으로 교체할 TODO가 있습니다.

## Agent · Tool · Service

리포트 처리와 이슈 분석 노드는 `agents/`의 Tool-calling Agent를 통해 읽기 Tool을
호출합니다. `tools/`는 Agent에 노출되는 입력·출력·권한 경계이고, `services/`는
Tool 뒤의 인프라 구현입니다. 현재 Tool은 `MockClioService`를 사용합니다.

이슈 생성·연결, 분석 저장, 문서·레포지토리 인덱싱 같은 쓰기 작업은 Agent에
노출하지 않고 Graph Node가 Service를 직접 호출합니다. `DEEPSEEK_API_KEY`가 설정되면
리포트 매칭·이슈 분석·해결 계획 Agent는 `create_agent` 기반의 실제 Tool-calling loop를
사용하고, 키가 없으면 결정적 Mock fallback을 사용합니다.

기본값은 DeepSeek의 OpenAI 호환 API입니다. 다른 OpenAI 호환 공급자로 바꾸려면 아래
환경 변수만 변경합니다.

```dotenv
CLIO_LLM_PROVIDER=openai_compatible
CLIO_LLM_MODEL=<provider-model>
CLIO_LLM_BASE_URL=<provider-base-url>
CLIO_LLM_API_KEY_ENV=<environment-variable-containing-key>
```

- 프로젝트 snapshot 고정
- 문서 검색
- 코드 검색
- 과거 해결 이슈 검색

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
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
