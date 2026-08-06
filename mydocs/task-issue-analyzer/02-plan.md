# Issue Analyzer(IA) 1차 구현 계획

`01-overview.md` 확인 완료. 이 문서는 IA의 구현 단계와 사용자 결정 포인트 I1~I10을 담는다. 결정은
`03-decisions.md`에 하나씩 기록하고, 결정에 따른 구현도 작은 커밋으로 나눈다.

## 1. 목표 구조

IA는 실제 저장소를 직접 검색하지 않고 Codebase Exploration Agent를 LangGraph subgraph로 호출한다. 외부에는
최초 분석과 재분석을 서로 다른 graph ID로 노출하지만, 내부 탐색·병합·검증은 하나의 공통 IA 오케스트레이터가
담당한다.

```text
Supervisor
  ├─ issue_analyzer   → Initial Judgment Subagent
  └─ issue_reanalyzer → Revision Judgment Subagent

공통 IA Orchestrator
  → 판단 subagent가 탐색 질문 생성
  → codebase_exploration_subgraph
  → Evidence 병합·중복 제거
  → 필요하면 최대 3회 반복
  → 판단 subagent가 Finding·Hypothesis 초안 생성
  → 공통 참조 검증
  → IssueAnalysis
```

기술적 실패와 정상적인 근거 부족은 다른 결과다. 실제 Code Explorer가 연결되지 않은 placeholder는 RM의 RAG
placeholder처럼 명시적인 설정 오류를 발생시킨다.

## 2. 구현 단계

### S1. IA 공개 계약

- 분석 작업·프로젝트·Issue·Bug를 식별하는 입력
- 코드 snapshot, 호출 관계, 최근 변경을 표현하는 탐색 결과
- `Evidence → Finding → RootCauseHypothesis` 결과 계약
- 분석 상태와 경고·부족 정보

관련 결정: **I1, I2, I5, I6, I7, I10**

### S2. Codebase Exploration subgraph 경계

- 탐색 질문과 이미 확인한 Evidence를 전달하는 요청 schema
- 코드·심볼·관련 테스트·관계·최근 변경 후보를 반환하는 응답 schema
- 실제 탐색기가 없는 동안 실행을 막는 placeholder
- Fake 탐색 subgraph와 1회 재시도
- snapshot 최대 10줄과 후보 수 상한 검증

관련 결정: **I3, I4, I5, I7, I9**

### S3. 탐색 제어

- NM 결과와 Issue 문맥에서 첫 탐색 목적을 만드는 node
- 결과가 부족할 때 추가 질문을 만드는 node
- 최대 탐색 횟수와 종료 조건
- 같은 질문·Evidence가 반복되는 loop 차단

관련 결정: **I4, I9**

### S4. IA 모델 경계

- Java interface 역할의 `IssueAnalysisModel` Protocol
- 탐색 결과만 사용하는 structured output
- Finding과 Hypothesis 분리
- Evidence ID 외부 참조 금지
- 실제 LangChain adapter 지연 생성
- structured output 검증 오류 1회 교정

관련 결정: **I5, I6, I9**

### S5. 분석 검증과 조립

- Evidence·Finding·Hypothesis ID 중복 검사
- Finding과 Hypothesis의 참조 무결성 검사
- 근거 없는 root cause와 탐색에 없는 파일·심볼 차단
- 신뢰도와 가설 순위 일관성 검사
- 정상 근거 부족 결과의 결정적 조립

관련 결정: **I5, I6, I9**

### S6. LangGraph와 공개 진입점

- 공통 IA state와 조건부 반복 edge
- `issue_analyzer`와 `issue_reanalyzer` 공개 graph ID
- Initial·Revision Judgment subgraph
- Fake NM·RAG·Code Explorer·IA 모델의 end-to-end 테스트

관련 결정: **I1, I8, I10**

### S7. 평가·문서·병합

- 단일 코드 위치, 다중 계층, 모순 근거, 근거 부족 fixture
- 탐색 실패와 모델 실패 재시도 테스트
- README·환경변수·입출력 예시 갱신
- `04-result.md` 작성
- 전체 검사 후 `taek/issue-analyzer → taek/integration` 병합

## 3. 결정 포인트

### I1. IA 실행 시점과 그래프 경계

#### (a) RM의 `CREATE_NEW` 직후 같은 그래프에서 provisional 분석

- 한 실행에서 NM·RM·IA 결과를 모두 얻는다.
- RM은 Issue를 생성하지 않으므로 IA 실행 시점에는 실제 `issue_id`가 없다.
- 서버 저장 실패 시 존재하지 않는 Issue의 분석 결과가 먼저 만들어질 수 있다.

#### (b) 서버가 Issue를 생성한 뒤 IA 전용 그래프를 별도 실행

- 실제 `issue_id`와 `analysis_job_id`를 입력으로 사용할 수 있다.
- RM 결과를 받은 오케스트레이터가 Issue 생성 후 IA를 호출해야 한다.
- NM/RM과 IA가 서로 다른 run이 된다.

**추천: (b).** 현재 Agent Graph는 read-only 판단을 반환하고 DB 변경은 서버가 담당한다. 서버가 `CREATE_NEW`를
반영한 뒤 `issue_analyzer` graph를 호출하면 저장 책임과 분석 책임이 섞이지 않는다.

### I2. IA가 분석할 입력 단위

#### (a) 생성 원인이 된 Bug 하나

- context가 작고 단순하다.
- Issue에 여러 Bug가 묶인 뒤 재분석할 때 전체 현상을 놓칠 수 있다.

#### (b) Issue 정보와 연결 Bug 전체

- Issue의 전체 발생 형태를 볼 수 있다.
- 오래된 Issue는 입력 크기가 무제한으로 커질 수 있다.

#### (c) Issue 정보와 대표 Bug 최대 N개

- 여러 발생 형태를 보되 입력 크기를 제한할 수 있다.
- 대표 Bug 선정 책임이 서버 또는 오케스트레이터에 필요하다.

**추천: (c), 최대 5개.** 새 Issue는 보통 Bug 하나로 시작하지만 같은 계약을 재분석에도 사용할 수 있다.

### I3. Code Explorer 응답 범위

#### (a) 코드 snapshot 목록만

- 계약이 작다.
- 여러 파일이 어떻게 연결되는지 IA가 코드 없이 추측하게 된다.

#### (b) snapshot + 심볼 관계 + 관련 테스트 + 최근 변경

- IA가 다중 코드 흐름과 변경 가능성을 근거로 분석할 수 있다.
- Code Explorer 계약이 처음부터 넓어진다.

#### (c) snapshot + 심볼 관계만, 테스트·변경은 후속

- 핵심 실행 흐름부터 구현할 수 있다.
- 원래 IA 요구사항인 최근 변경과 테스트 단서가 1차 결과에서 빠진다.

**추천: (b).** 실제 검색은 후속 작업이므로 이번에는 필요한 최종 응답 계약을 먼저 고정하고 Fake로 검증한다.

### I4. 탐색 반복 방식

#### (a) 한 번의 탐색 요청

- 흐름과 비용이 예측 가능하다.
- 첫 검색 결과에서 새 심볼이 발견돼도 주변을 추가 조사할 수 없다.

#### (b) IA가 결과를 보고 최대 2회 추가 탐색

- 초기 검색과 관계 확장을 구분할 수 있다.
- 종료 조건과 중복 질문 차단이 필요하다.

#### (c) 충분할 때까지 제한 없이 반복

- 복잡한 문제를 깊게 볼 수 있다.
- 비용·시간 폭주와 무한 loop 위험이 있다.

**추천: (b).** 최초 탐색을 포함해 최대 3회 실행하고, 새 질문이나 새 Evidence가 없으면 즉시 종료한다.

### I5. Evidence ID와 snapshot 계약

#### (a) DB 전역 UUID

- 여러 분석에서 ID 충돌이 없다.
- IA가 DB 식별자 생성 책임을 갖게 된다.

#### (b) 분석 결과 내부 순번 `E1`, `E2`, ...

- 사람이 읽고 참조하기 쉽고 DB 없이 생성할 수 있다.
- 다른 분석 결과의 `E1`과는 별개이므로 반드시 analysis ID와 함께 해석해야 한다.

#### (c) snapshot 내용 hash

- 같은 snapshot의 중복을 찾을 수 있다.
- 공백 변화에도 ID가 바뀌고 사람이 읽기 어렵다.

**추천: (b).** 결과가 보존될 때 이미 `analysis_job_id`가 있으므로 분석 내부 순번이면 충분하다. snapshot은
`splitlines()` 기준 1~10줄로 제한하고 path·symbol·line·change ID는 설명 metadata로만 둔다.

### I6. Finding과 Hypothesis 수·신뢰도

#### (a) confidence 0~1 실수

- 정렬과 threshold 적용이 쉽다.
- 운영 평가 전에는 0.82 같은 숫자가 실제 확률처럼 오해될 수 있다.

#### (b) `LOW`, `MEDIUM`, `HIGH` 등급

- 현재 근거 수준을 정직하게 표현한다.
- 세밀한 정렬에는 추가 우선순위가 필요하다.

**추천: (b).** Hypothesis는 우선순위가 명시된 최대 3개, Finding은 최대 10개로 제한한다. confidence는
근거 강도를 뜻하며 발생 확률이 아니라고 계약에 기록한다.

### I7. 최근 변경 Evidence

#### (a) 1차 계약에 포함

- IA의 원래 요구사항인 최근 변경 조사를 표현할 수 있다.
- commit이 사라질 수 있으므로 ID만 저장해서는 안 된다.

#### (b) Code Explorer 실제 구현 때 추가

- 이번 IA 계약은 작아진다.
- 나중에 Evidence 구조와 모델 prompt가 다시 바뀐다.

**추천: (a).** `CHANGE` Evidence도 변경된 코드 또는 diff snapshot 최대 10줄을 본문으로 보존하고 commit ID는
선택 metadata로만 둔다.

### I8. 어떤 RM action이 IA로 이어지는가

#### (a) `CREATE_NEW`만

- “새 Issue 분석”이라는 IA 책임과 일치한다.
- REVIEW 후보는 사람 판단 전까지 코드 분석을 받지 않는다.

#### (b) `CREATE_NEW`와 `REVIEW`

- 사람 검토에 코드 단서를 함께 제공할 수 있다.
- 기존 Issue 중복 판정과 원인 분석이 동시에 실행돼 비용과 책임이 섞인다.

**추천: (a).** v1은 신규 생성이 확정된 Issue만 분석한다. REVIEW 분석은 운영 필요가 확인되면 후속으로 연다.

### I9. 실패와 근거 부족 정책

#### (a) 모든 부족·실패를 실행 실패 처리

- 성공 결과에는 항상 가설이 있다.
- 관련 코드를 못 찾은 정상 상황도 장애처럼 보인다.

#### (b) 기술 실패만 실패, 정상 검색 0건은 `INSUFFICIENT_EVIDENCE`

- 검색 품질 문제와 시스템 장애를 구분할 수 있다.
- 가설이 없는 정상 결과를 소비자가 처리해야 한다.

#### (c) 이전 탐색 근거가 있으면 부분 결과 반환

- 마지막 추가 탐색 장애에도 일부 정보를 사용할 수 있다.
- 같은 입력이 성공·부분 성공으로 갈리고 결과 신뢰도 해석이 복잡해진다.

**추천: (b).** Code Explorer와 모델은 일시 실패 시 한 번 재시도하고 계속 실패하면 run을 실패시킨다. 정상
응답이지만 Evidence가 없으면 모델을 호출하지 않고 `INSUFFICIENT_EVIDENCE`를 반환한다.

### I10. IA 공개 출력

#### (a) IA 전용 그래프에서 `issue_analysis`만 반환

- 실행 목적과 응답이 명확하다.
- NM·RM 결과는 서버가 별도로 조회해야 한다.

#### (b) `normalized_report`, `match_decision`, `issue_analysis` 모두 반환

- 하나의 응답에서 전체 판단 흐름을 볼 수 있다.
- I1의 별도 실행을 선택하면 이전 run 상태를 다시 전달해야 한다.

**추천: (a).** 별도 IA run은 `analysis_job_id`, `issue_id`, `project_id`를 결과 안에 포함해 추적한다.

## 4. 예상 공개 계약

I1·I2 추천안을 선택할 경우의 IA 전용 그래프 입력 예시다.

```json
{
  "analysis_job_id": 501,
  "project_id": 3,
  "issue": {
    "issue_id": 19,
    "title": "결제 완료 후 주문 내역 미노출",
    "summary": "결제 승인 뒤 주문 내역에서 주문이 보이지 않는다."
  },
  "bugs": [
    {
      "bug_id": 72,
      "normalized_report": {
        "bug_report_id": 351,
        "observed_behavior": "결제 완료 후 주문 내역에 주문이 표시되지 않는다."
      }
    }
  ]
}
```

출력 예시:

```json
{
  "issue_analysis": {
    "analysis_job_id": 501,
    "issue_id": 19,
    "status": "COMPLETED",
    "evidence": [
      {
        "evidence_id": "E1",
        "kind": "CODE",
        "code_snapshot": "order.markPaid();\neventPublisher.publish(...);",
        "file_path": "src/.../PaymentService.java",
        "symbol": "PaymentService.completePayment"
      }
    ],
    "findings": [
      {
        "finding_id": "F1",
        "statement": "결제 완료 메서드는 상태 변경 직후 이벤트를 발행한다.",
        "evidence_ids": ["E1"]
      }
    ],
    "hypotheses": [
      {
        "hypothesis_id": "H1",
        "priority": 1,
        "statement": "이벤트 처리 시점과 트랜잭션 완료 시점의 불일치 가능성이 있다.",
        "confidence": "MEDIUM",
        "supporting_evidence_ids": ["E1"],
        "contradicting_evidence_ids": [],
        "unknowns": ["이벤트 listener의 transaction phase 확인 필요"]
      }
    ]
  }
}
```

필드의 최종 형태는 I1~I10 결정 뒤 고정한다.

## 5. 테스트 계획

- 단일 함수의 명확한 오류 후보
- Controller→Service→Repository에 걸친 다중 Evidence
- 관련 테스트 코드가 가설을 지지하거나 반박하는 경우
- 최근 변경 snapshot이 있는 경우
- 같은 Evidence를 두 탐색 round에서 중복 반환하는 경우
- 새 질문이나 Evidence가 없어 탐색을 조기 종료하는 경우
- 최대 탐색 횟수에서 강제 종료하는 경우
- 정상 Evidence 0건의 `INSUFFICIENT_EVIDENCE`
- Code Explorer 설정 누락과 일시 실패·영구 실패
- 모델 structured output 1회 교정과 두 번째 실패
- 존재하지 않는 Evidence ID 참조 거부
- 중복 Evidence·Finding·Hypothesis ID 거부
- snapshot 0줄·11줄 거부와 정확히 10줄 허용
- 근거에 없는 파일·심볼·가설 참조 거부
- 실제 모델이 최초 호출 전 생성되지 않는지 검증
- Fake Code Explorer와 모델을 주입한 IA LangGraph 입출력 테스트

## 6. 예상 커밋 단위

```text
docs: IA 구현 계획
docs: IA 실행 경계 결정
feat: IA 입력과 분석 결과 계약
feat: Code Explorer subgraph 계약
feat: IA 탐색 반복 제어
feat: IA 모델 포트와 분석 검증
feat: IA LangChain adapter
feat: IA 전용 LangGraph 연결
test: IA 다중 Evidence와 실패 fixture
docs: IA 사용법과 구현 결과
```

## 7. 브랜치 흐름

```text
main
└─ taek/integration
   └─ taek/issue-analyzer
```

IA 완료 후 `taek/issue-analyzer`를 `taek/integration`에 `--no-ff` 병합한다. 공통·NM·RM·IA가 모두
완료된 뒤에만 `taek/integration`을 `main`에 병합한다.
