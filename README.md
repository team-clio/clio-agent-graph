# Clio Agent Graph

Clio의 버그 분석 워크플로를 제공하는 Python LangGraph Agent Server입니다.
첫 번째 노드인 Report Normalizer(NM)는 서로 다른 형식의 BugReport를 후속 RM이 비교할 수 있는
표준 사실 표현으로 바꿉니다.

## 구조

```text
src/clio_agent_graph/
├── graph.py           # Agent Server에 노출되는 compiled graph
├── state.py           # 공개 입출력과 내부 graph state
└── normalization/
    ├── models.py      # NM 입출력 Pydantic 계약
    ├── ports.py       # Java interface 역할의 모델 Protocol
    ├── service.py     # 병합·누락 계산·입력 보호
    ├── prompts.py     # 사실 추출 프롬프트
    ├── langchain_adapter.py
    └── node.py
tests/
langgraph.json         # Agent Server 진입점
pyproject.toml
```

기본 흐름:

```text
START → normalize_report → END
```

NM은 원문에 없는 사실을 추론하지 않습니다. 입력의 `error_type`, `message`, `stack_trace`는 모델이
다시 작성하지 않고 우선 보존하며, 비어 있는 정보는 애플리케이션이 `missing_fields`로 계산합니다.

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

`CLIO_MODEL`에 사용할 LangChain 모델 식별자를 설정합니다. 실제 provider 패키지와 API key는 최초
NM 호출 시 필요합니다. `raw_payload`는 일반적인 민감 key 값을 가린 뒤 모델에 전달하며 기본 상한은
32 KiB입니다. 상한은 `CLIO_MAX_RAW_PAYLOAD_BYTES`로 변경할 수 있습니다.

## 그래프 입출력

입력:

```json
{
  "bug_report": {
    "bug_report_id": 351,
    "title": "결제 실패",
    "description": "결제 버튼을 누르면 500 오류가 발생합니다.",
    "error_type": null,
    "message": "Internal Server Error",
    "stack_trace": [],
    "raw_payload": {
      "appVersion": "3.14.1"
    }
  }
}
```

출력:

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
      "error_type": null,
      "message": "Internal Server Error",
      "error_codes": ["500"],
      "stack_frames": []
    },
    "missing_fields": [
      "EXPECTED_BEHAVIOR",
      "REPRODUCTION_CONDITIONS",
      "ERROR_TYPE",
      "STACK_TRACE"
    ]
  }
}
```

실제 응답에서는 각 하위 모델의 선택 필드가 `null`로 함께 직렬화될 수 있습니다.

## 테스트 및 품질 검사

```bash
pytest
ruff check .
ruff format --check .
```

## 다음 구현 지점

1. Report Matcher(RM) 후보 검색과 자동 연결·검토·신규 분기
2. Issue Analyzer(IA)와 Code Explorer
3. Clio Server 이벤트·결과 저장 계약
4. 운영 환경용 영속 체크포인터와 인증 정책

`langgraph dev`는 로컬 개발용 Agent Server입니다. 배포 이미지는 LangGraph CLI의
`langgraph build`로 생성하고, 운영 환경에서는 영속 저장소와 작업 큐를 구성해야 합니다.
