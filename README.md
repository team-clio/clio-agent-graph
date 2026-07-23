# Clio Agent Graph

Clio의 분석·실행 워크플로를 제공하는 Python LangGraph Agent Server입니다.
현재 그래프는 API 키 없이 실행되는 최소 워크플로이며, 각 노드를 LLM·도구 기반
구현으로 교체할 수 있도록 상태 계약과 실행 단계를 분리했습니다.

## 구조

```text
src/clio_agent_graph/
├── configuration.py  # assistant/run 단위 설정
├── graph.py           # Agent Server에 노출되는 compiled graph
├── nodes.py           # 독립적으로 테스트 가능한 노드
└── state.py           # 영속 상태 계약
tests/
langgraph.json         # Agent Server 진입점
pyproject.toml
```

기본 흐름:

```text
START → normalize_request → plan_request → execute_plan → finalize → END
```

## 로컬 실행

Python 3.11 이상이 필요합니다.

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

## 다음 구현 지점

1. `plan_request`: 모델의 structured output으로 실행 계획 생성
2. `execute_plan`: 코드 검색, GitHub, 이슈·문서 조회 등의 도구 실행
3. 조건부 edge: 재시도, evidence check, human-in-the-loop 분기
4. Clio Server와의 이벤트·결과 저장 API 계약
5. 운영 환경용 영속 체크포인터와 인증 정책

`langgraph dev`는 로컬 개발용 Agent Server입니다. 배포 이미지는 LangGraph CLI의
`langgraph build`로 생성하고, 운영 환경에서는 영속 저장소와 작업 큐를 구성해야 합니다.
