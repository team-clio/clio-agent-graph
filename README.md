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

## 아직 구현되지 않은 탐색 Agent

이번 버전에는 실제 Hybrid RAG 대신 입출력 계약을 가진 빈 LangGraph subgraph가 들어 있습니다. 기본 그래프에서
RM까지 실행하면 `IssueRetrievalNotConfiguredError`가 발생합니다. 이 동작은 검색 미구현 상태를 정상적인
“후보 없음”으로 오해해 중복 Issue를 생성하지 않기 위한 안전장치입니다.

테스트에서는 `build_issue_retrieval_subgraph(fake_retriever)`로 Fake를 주입합니다. 후속
`taek/issue-retrieval` 작업에서 같은 계약을 지키는 실제 RAG subgraph로 교체합니다.

IA의 Codebase Exploration Agent도 현재는 계약과 placeholder만 있습니다. 실제 탐색이 연결되지 않은 IA
그래프는 `CodeExplorerNotConfiguredError`로 실패합니다. 정상 탐색 결과가 0건인 경우와 설정·기술 실패를
구분하기 위한 동작입니다.

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
- 그래프 ID: `clio_agent`, `issue_analyzer`, `issue_reanalyzer`

`CLIO_MODEL`은 NM·RM·IA가 공유하는 LangChain 모델 식별자입니다. 실제 provider 객체는 각 adapter의 최초
호출 때 지연 생성됩니다.

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

## 다음 구현 지점

1. 실제 Hybrid RAG를 수행하는 Issue Retrieval Agent
2. 실제 저장소·심볼·호출 관계·최근 변경을 조사하는 Codebase Exploration Agent
3. Clio Server 이벤트·결과 저장 계약
4. 운영 환경용 영속 체크포인터와 인증 정책

`langgraph dev`는 로컬 개발용 Agent Server입니다. 배포 이미지는 LangGraph CLI의
`langgraph build`로 생성하고, 운영 환경에서는 영속 저장소와 작업 큐를 구성해야 합니다.
