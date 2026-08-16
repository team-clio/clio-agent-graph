# 저장소 작업 지침

## 프로젝트 개요

이 저장소는 Python 3.11+와 LangGraph로 구현한 Clio Agent Server다. 버그 정규화·검색·매칭,
이슈 분석, Project Context Memory(PCM), repository 탐색을 그래프로 조합한다.

주요 코드는 `src/clio_agent_graph/`에 있다.

- `graph.py`: 안정적인 루트 이벤트 진입점
- `workflows/orchestration/`: 요청 라우팅, 공유 상태, 상위 workflow
- `workflows/reporting/`: 버그 정규화, retrieval, matching
- `workflows/analysis/`: 독립 실행 이슈 분석 그래프
- `context/`: PCM, repository 접근, snapshot 기반 읽기 Tool, 서비스 조립
- `runtime/`: 공통 LLM, structured output, bounded Agent 실행
- `tests/`: 기능 계층과 관찰 가능한 동작별 테스트
- `langgraph.json`: 공개 LangGraph entrypoint 설정

## 작업별 컨벤션 읽기

코드를 수정하기 전에 작업 범위를 판단하고 아래 문서를 읽는다. 모든 문서를 매번 읽을 필요는
없지만, 해당되는 문서는 구현 전에 반드시 확인한다. 여러 영역에 걸친 변경이면 관련 문서를
함께 읽는다.

| 작업 상황 | 먼저 읽을 문서 |
|---|---|
| 처음 저장소를 보거나 변경 범위가 불명확함 | `convention/README.md` |
| 공개 그래프 계약, 패키지 책임, 의존성 방향, 새로운 기능 영역 | `convention/architecture.md` |
| LangGraph state, node, edge, routing, subgraph, 병렬 처리 | `convention/workflow-conventions.md` |
| Pydantic 모델, Port/Service/Adapter, Agent Tool, LLM, 오류·보안 | `convention/code-conventions.md` |
| 테스트, 환경 변수, PostgreSQL, 실행·검증, 배포 준비 | `convention/testing-and-operations.md` |

다음 변경은 하나의 문서만 보고 진행하지 않는다.

- 새 workflow나 공개 graph 추가: architecture + workflow + testing
- 외부 API·DB·embedding provider 변경: architecture + code + testing
- Agent Tool 추가: architecture + code + workflow + testing
- RAG retrieval·index·평가 변경: architecture + code + testing
- 전역 규칙을 새로 만들거나 바꾸는 변경: 관련 convention 문서도 구현과 함께 갱신

컨벤션 문서와 현재 코드가 충돌하면 조용히 한쪽을 따르지 않는다. 실제 동작과 변경 목적을
확인하고, 코드와 문서를 같은 변경에서 일치시킨다.

## 핵심 작업 원칙

1. `graph.py`의 루트 이벤트 계약과 `langgraph.json` entrypoint 호환성을 유지한다.
2. 기능 패키지가 `workflows.orchestration`의 전역 state에 의존하지 않게 한다.
3. Agent에는 범위가 제한된 읽기 Tool만 제공한다. 쓰기는 Graph Node가 Service를 호출한다.
4. 외부 시스템은 `Protocol` 뒤에 두고 graph/application 조립 경계에서 구현을 주입한다.
5. 공개 입력, LLM structured output, persistence 경계는 Pydantic으로 엄격하게 검증한다.
6. 분석 과정에서는 PCM revision과 repository commit을 하나의 snapshot으로 고정한다.
7. 동작 변경에는 같은 계층의 회귀 테스트를 추가하고, routing 변경에는 graph 테스트도 추가한다.
8. 기존 코드를 우회하는 임시 호환 계층보다 현재 MVP 계약을 단순하고 명확하게 유지한다.

## 현재 개발 단계의 DB 원칙

현재는 pre-MVP 단계이며 보존해야 할 운영 DB가 없다. 따라서 DB 스키마를 변경할 때는 다음을
기본으로 한다.

- 새 로컬·테스트 DB가 최신 스키마로 생성되는 것을 우선한다.
- 사용되지 않은 과거 스키마를 위한 호환 migration이나 데이터 변환을 자동으로 추가하지 않는다.
- 기존 migration을 배포 호환성 때문에 누적해야 한다고 가정하지 않는다.
- 운영 데이터 보존이나 실제 upgrade 경로가 요구되는 시점에는 별도 요구사항으로 migration
  전략을 다시 결정한다.
- migration 파일을 수정·삭제했다면 로컬 DB를 새로 만들고 fresh install 경로를 검증한다.

## 개발 및 검증 명령

개발 환경 생성과 설치:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
cp .env.example .env
```

주요 명령:

- `langgraph dev`: 로컬 Agent Server 실행
- `pytest`: 전체 테스트 실행
- `ruff check .`: lint 검사
- `ruff format --check .`: formatting 검사
- `ruff format .`: 필요한 경우 formatting 적용

변경 후 기본 검증 순서:

```bash
ruff format --check .
ruff check .
pytest
```

PostgreSQL·pgvector 경계를 변경했을 때만 관련 통합 테스트를 추가로 실행한다. 구체적인 실행
방법은 `convention/testing-and-operations.md`를 따른다.

## 코드 작성 규칙

- 네 칸 들여쓰기, 타입 annotation, Python 3.11+ 문법을 사용한다.
- Ruff의 100자 제한과 설정된 `E`, `F`, `I`, `UP`, `B`, `SIM` 규칙을 따른다.
- module·함수·변수·테스트는 `snake_case`, class는 `PascalCase`, 상수는
  `SCREAMING_SNAKE_CASE`를 사용한다.
- node는 orchestration에 집중하고 복잡한 정책, retry, persistence는 service로 분리한다.
- LangChain, PostgreSQL, Ollama, Codex 같은 구현 세부사항을 domain 계약에 누출하지 않는다.
- 생성자에서 네트워크 연결이나 무거운 모델 초기화를 하지 않고 실제 호출 시 lazy하게 만든다.
- fallback은 의도적으로 설계된 경우에만 사용하고 실패와 정상 0건을 구분한다.

## 테스트 규칙

- 테스트 함수는 `test_<behavior>()` 형식으로 작성한다.
- 구현 메서드명이 아니라 관찰 가능한 조건과 결과가 테스트 이름에 드러나게 한다.
- orchestration node 테스트는 `tests/nodes/`, cross-graph 동작은 `tests/test_graph.py`에 둔다.
- 기능별 테스트 위치는 `convention/testing-and-operations.md`의 표를 따른다.
- 일반 테스트는 live LLM이나 외부 DB에 의존하지 않고 Fake·주입·`monkeypatch`를 사용한다.
- 공개 graph 변경은 실제 입력으로 `invoke()` 또는 `ainvoke()`하여 결과, routing, terminal
  status를 검증한다.
- 오류 경로, 경계값, idempotent replay, snapshot·citation 불일치도 함께 검증한다.

## 커밋과 Pull Request

커밋 제목은 짧고 명령형인 Conventional Commit 스타일을 사용한다.

```text
feat: add tool-calling LLM agents
docs(graph): add Korean code comments
chore: ignore IDE project files
```

하나의 커밋에는 하나의 설명 가능한 목적만 담는다. Pull Request에는 다음을 포함한다.

- 변경된 graph·API·저장 동작
- 변경 이유와 적용한 convention
- 실행한 검증 명령과 결과
- 필요할 때 sample request/response 또는 화면 자료
- DB·설정·외부 서비스에 미치는 영향

## 설정과 보안

- `.env.example`을 설정 키의 기준으로 유지하고 실제 secret 값은 비워 둔다.
- API key, LangSmith token, provider credential을 commit하지 않는다.
- 일반 LLM 호출은 전역 `CLIO_MODEL=provider:model` 선택을 공유한다.
- API key 값과 API key를 담은 환경 변수 이름을 구분한다.
  `CLIO_MODEL_API_KEY_ENV`에는 실제 key가 아니라 `DEEPSEEK_API_KEY` 같은 환경 변수 이름을 둔다.
- 테스트가 개발자의 `.env`에 암묵적으로 의존하지 않도록 환경 변수를 명시적으로 격리한다.
- repository 인증 정보, server-managed 경로, 민감 파일 내용을 Agent context에 노출하지 않는다.
