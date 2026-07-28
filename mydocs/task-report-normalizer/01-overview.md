# Report Normalizer(NM) 1차 구현

## 1. 작업 배경

Clio Agent Graph는 현재 LangGraph Agent Server가 실행되는 최소 골격만 갖고 있다.
현재 그래프는 일반 사용자 요청을 문자열로 정규화한 뒤 고정 계획을 만드는 데모이며, Clio의 실제
버그 분석 도메인 계약이나 에이전트는 아직 없다.

이번 작업은 전체 Agent Graph의 공통 계약을 먼저 확정하지 않고, 첫 번째 업무 에이전트인
**Report Normalizer(NM)** 를 하나의 수직 슬라이스로 구현한다. NM 구현 과정에서 실제로 필요한
입출력과 근거 표현을 확인하고, RM·IA에서도 반복되는 개념만 이후 공통 계약으로 승격한다.

## 2. NM의 역할

NM은 수집된 원본 버그 리포트를 읽고 후속 에이전트가 사용할 수 있는 구조화된 리포트로 변환한다.

추출 대상은 다음과 같다.

- 증상
- 기대 동작
- 재현 절차
- 실행 환경
- 오류 signature
- stack frame 등 코드 탐색 단서
- 누락된 정보

정규화 결과는 입력 원본의 `bug_report_id`와 연결한다. 원문에 없는 정보를 사실처럼 보충하지 않으며,
값을 찾지 못한 경우에는 누락으로 명시한다. 코드·문서·로그를 조사해 Bug의 evidence를 만드는 것은
후속 IA와 탐색 에이전트의 책임으로 둔다.

## 3. 현재 상태

현재 구현은 다음 흐름이다.

```text
START
  → normalize_request
  → plan_request
  → execute_plan
  → finalize
  → END
```

`normalize_request`는 `request` 문자열 또는 마지막 `HumanMessage`만 읽는다. 이름은 비슷하지만
버그 리포트의 의미를 분석하는 NM과는 역할이 다르다.

현재 없는 것은 다음과 같다.

- 원본 리포트 입력 모델
- NM의 구조화 출력 모델
- 원본 BugReport 식별자와 정규화 결과의 연결
- 구조화 출력을 생성하는 모델 호출 경계
- 출력 스키마 검증과 실패 처리
- NM 단독 평가 fixture와 테스트
- NM을 실행하는 실제 도메인 그래프

## 4. 문제

### 4.1 전체 공통 계약을 먼저 설계하기 어렵다

RM과 IA의 실제 데이터 요구가 아직 구현으로 검증되지 않았다. 처음부터 거대한 `GraphState`와 범용
`Evidence` 계층을 만들면 추측에 기반한 추상화가 될 가능성이 크다.

### 4.2 계약 없이 LLM 응답부터 만들 수도 없다

반대로 자유 형식 `dict`나 자연어 응답으로 시작하면 NM 출력이 프롬프트, 그래프 상태, 저장 모델에
동시에 결합된다. 후속 RM 연결 시 필드 의미와 누락 처리 방식을 다시 정의해야 한다.

### 4.3 원본 리포트 계보는 NM 단계부터 필요하다

정규화 결과가 어떤 원본에서 만들어졌는지는 후속 에이전트가 다시 원문을 읽고 검증할 수 있도록 남겨야 한다.
다만 NM이 원문의 각 구절을 별도 evidence로 만들지는 않는다. 변경되지 않는 BugReport를
`bug_report_id`로 참조하고, 조사 evidence는 후속 에이전트가 별도로 만든다.

## 5. 개선 방향

### 5.1 NM 소유의 최소 계약부터 시작한다

이번에는 다음 세 종류의 NM 전용 모델만 정의한다.

```text
NormalizeReportInput(bug_report_id + raw report)
  → ReportNormalizer
  → NormalizedReport(bug_report_id + normalized fields)
```

이 모델을 곧바로 범용 공통 계약으로 선언하지 않는다. RM·IA 구현 중 조사 evidence의 실제 요구가
확인되면 별도 작업에서 공통 `Evidence`와 메인 `GraphState`를 설계한다.

### 5.2 LLM 호출과 NM 도메인 로직을 분리한다

NM은 구체적인 LLM SDK에 직접 결합하지 않는다. 테스트에서 결정적인 fake 구현을 주입할 수 있는
경계를 두고, 모델 응답은 NM 출력 스키마로 검증한다.

### 5.3 BugReport 연결과 출력 구조를 검증한다

입력과 출력의 `bug_report_id`가 동일한지 확인하고, 필수 출력과 누락 정보 표현을 검증한다.
자유 형식 응답이나 원문에 없는 임의 보충은 정상 결과로 저장하지 않는다.

### 5.4 NM을 독립적으로 실행하고 평가할 수 있게 한다

전체 RM·IA 그래프를 기다리지 않고 다음 흐름을 테스트한다.

```text
raw report fixture
  → NM node
  → schema/source-reference validation
  → NormalizedReport
```

## 6. 이번 작업 범위

### 포함

- NM 최소 입력·출력 모델
- 증상·기대 동작·재현 절차·환경·오류 signature·누락 정보 표현
- 원본 `bug_report_id`를 유지하는 source reference
- Report Normalizer 서비스/노드
- 구조화 모델 출력 검증
- LangGraph에서 NM 단독 실행이 가능한 그래프 경로
- fake 모델을 사용한 단위 테스트와 그래프 테스트
- 정상, 필드 누락, 잘못된 structured output, 비어 있는 입력 fixture
- README의 현재 그래프 설명 갱신

### 제외

- RM·IA 구현
- 범용 `Evidence` 및 최종 공통 `GraphState` 확정
- PostgreSQL 읽기·쓰기
- Clio Server와의 이벤트/API 계약
- 운영 체크포인터
- Knowledge Explorer·Code Explorer
- 실제 운영 모델과 프롬프트 튜닝 완료
- 정량 평가 하네스와 대규모 데이터셋

## 7. 완료 기준

- 원본 리포트를 NM 입력 모델로 받아 구조화된 `NormalizedReport`를 반환한다.
- 정규화 결과는 입력 `bug_report_id`를 유지하고 찾지 못한 값은 명시적으로 누락 처리한다.
- LLM의 잘못된 구조화 출력이 조용히 통과하지 않는다.
- 외부 API 키 없이 전체 테스트를 재현할 수 있다.
- 현재 데모 그래프가 NM 중심의 도메인 그래프로 정리된다.
- 이후 RM이 NM 내부 구현을 모르고 출력 계약만 사용할 수 있다.

## 8. Plan에서 결정할 항목

구현 전에 다음 항목을 선택해야 한다.

1. **NM 입력 원문 형식**: 단일 텍스트 중심인지, source별 `raw_payload`를 그대로 받을지
2. **원본 연결 방식**: NM에는 `bug_report_id`만 두고 조사 evidence는 후속 에이전트에서 생성
3. **오류 signature 범위**: 예외 타입·메시지·stack frame을 하나로 둘지 분리할지
4. **모델 호출 경계**: LangChain structured output을 직접 감쌀지 별도 포트를 둘지
5. **검증 실패 처리**: 노드 실패, 제한 재시도, 부분 결과 반환 중 어떤 정책을 사용할지
6. **그래프 전환 방식**: 기존 데모 그래프를 교체할지 별도 NM 그래프를 병행 노출할지
7. **초기 실제 모델 지원**: fake 기반 계약까지만 할지 OpenAI adapter까지 포함할지

## 9. 예상 변경 위치

구체적인 파일 구조는 plan에서 확정하지만 현재 예상은 다음과 같다.

```text
src/clio_agent_graph/
├── graph.py
├── state.py
└── normalization/
    ├── models.py
    ├── normalizer.py
    ├── node.py
    └── prompts.py
tests/
├── normalization/
└── fixtures/
```

## 10. 주요 위험

- Clio Server 입력 계약이 확정되기 전에 NM 입력을 DB 구조에 과도하게 맞출 수 있다.
- BugReport가 수정 가능한 모델이면 식별자만으로 당시 입력을 재현할 수 없으므로 원본 불변 정책이 필요하다.
- 모델 응답 스키마와 도메인 모델을 동일시하면 모델 교체와 검증 정책 변경이 어려워질 수 있다.
- 너무 많은 필드를 첫 버전에 넣으면 NM 평가 기준이 흐려질 수 있다.
- 현재 데모 그래프를 즉시 제거하면 비교 가능한 최소 실행 예제가 사라질 수 있다.
