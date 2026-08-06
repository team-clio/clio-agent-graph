# Clio Agent Graph

Clio의 요청을 `request.request_type`으로 결정적으로 라우팅하는 Python LangGraph
Agent Server입니다. 상위 그래프 흐름과 PCM, Vector DB, commit-addressed Git mirror가
구현되어 있으며 아직 연결되지 않은 외부 API Server 쓰기 경계는 Mock으로 분리되어 있습니다.

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

Issue 분석은 요청 시작 시 PCM snapshot을 고정하고, 같은 snapshot에 묶인 읽기 Tool로
장기 지식을 검색·읽기·출처 추적합니다. `document_added` 경로도 실제 PCM vertical slice에
연결되어 있습니다.

정규화된 Markdown을 heading 단위 Source로 나누고, `.env`의 기존 `CLIO_LLM_*` 설정을 사용하는
Knowledge LLM으로 topic과 변경안을 생성한 뒤 PCM revision으로 commit합니다.
`CLIO_PCM_DATABASE_URL`을 설정하면 PostgreSQL metadata와 immutable Markdown 파일에
영속화하고, 설정하지 않으면 개발용 in-memory PCM을 사용합니다. Vector 의미 검색은
로컬 feature-hash embedding과 pgvector를 사용하고, PostgreSQL FTS·trigram 결과를
Reciprocal Rank Fusion으로 결합합니다. 로컬 embedding은 인프라 배선 검증용이며 실제
의미 검색 품질용 모델은 아닙니다.

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

로컬 PostgreSQL과 pgvector는 Docker로 실행할 수 있습니다.

```bash
docker compose -f compose.pcm.yaml up -d --wait
```

```dotenv
CLIO_PCM_DATABASE_URL=postgresql://clio:clio_dev_password@127.0.0.1:55432/clio_pcm
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

Repository는 on-premise PCM data volume 아래 bare Git mirror로 저장됩니다. 등록 요청에는
Graph Node만 사용하는 `source_uri`를 전달하고, Agent에는 remote URL이나 credential을
노출하지 않습니다.

```json
{
  "request_id": "REQ-REPO-1",
  "request_type": "repository_added",
  "project_id": "PROJECT-1",
  "payload": {
    "repository_id": "backend",
    "source_uri": "/srv/git/backend",
    "branch": "main",
    "commit": "0123456789abcdef0123456789abcdef01234567"
  }
}
```

분석 시작 시 활성 commit을 snapshot에 복사합니다. 코드 검색과 파일 읽기는 항상 해당
commit을 사용하며, line range 제한, 경로 탈출 차단, secret 파일 거부와 값 masking을
적용합니다. `repository_changed`는 현재 active `before_commit`을 검증하고 branch head인
`after_commit`만 활성화합니다.

Repository 등록과 commit 변경 뒤에는 bounded source collection을 실행합니다. tracked
text source 중 지원 확장자만 선택하고 파일당 64KB, 기본 30개 파일, 총 120KB, 60개
source unit으로 제한합니다. LLM은 이 source unit에서 architecture·component·operation
지식을 추출하고, 기존 PCM 후보와 비교해 create·update·no-change change set을 만듭니다.
Knowledge provenance에는 다음 정보가 보존됩니다.

- `source_type=repository`
- repository ID와 전체 commit SHA
- 파일 경로와 시작·끝 line
- masking 이후 source content hash

동일 repository event를 재처리하면 기존 Knowledge commit을 반환하므로 LLM 호출과 PCM
revision 증가가 반복되지 않습니다.

## Agent · Tool · Service

리포트 처리와 이슈 분석 노드는 `agents/`의 Tool-calling Agent를 통해 읽기 Tool을
호출합니다. `tools/`는 Agent에 노출되는 입력·출력·권한 경계이고, `services/`는
Tool 뒤의 인프라 구현입니다. PCM Tool의 project와 snapshot은 Graph가 closure에
고정하므로 Agent 입력 스키마에는 노출되지 않습니다.

이슈 생성·연결, 분석 저장, 문서·레포지토리 인덱싱 같은 쓰기 작업은 Agent에
노출하지 않고 Graph Node가 Service를 직접 호출합니다. 리포트 매칭·이슈 분석·해결 계획
Agent는 `create_agent` 기반의 실제 Tool-calling loop만 사용하며, `DEEPSEEK_API_KEY`가
없으면 실행을 시작하지 않고 설정 오류로 실패합니다.

기본값은 DeepSeek의 OpenAI 호환 API입니다. 다른 OpenAI 호환 공급자로 바꾸려면 아래
환경 변수만 변경합니다.

```dotenv
CLIO_LLM_PROVIDER=openai_compatible
CLIO_LLM_MODEL=<provider-model>
CLIO_LLM_BASE_URL=<provider-base-url>
CLIO_LLM_API_KEY_ENV=<environment-variable-containing-key>
```

- 프로젝트 snapshot 고정
- PCM Knowledge hybrid 검색
- Knowledge 전체 Markdown 읽기
- 원본 문서·Repository·해결 이슈 provenance 추적
- 고정 commit의 Repository 목록·코드 검색·line-range 파일 읽기
- 결과 citation의 Knowledge revision 및 Repository commit 검증

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
