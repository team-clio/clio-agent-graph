# Report Normalizer(NM) 1차 구현 계획

`01-overview.md` 확인 완료. 이 문서는 NM 수직 슬라이스의 구현 단계와 결정 포인트(N1~N8)를 담는다.
결정은 `03-decisions.md`에 기록하고, 결정에 따른 구현을 작은 커밋으로 나눈다.

## 1. 목표 흐름

```text
NormalizeReportInput(bug_report_id + raw report)
  → source document 구성
  → ReportNormalizer
       ├─ 모델 structured output
       └─ structured output 검증
  → NormalizedReport(bug_report_id 유지)
  → LangGraph state 반영
```

이번 그래프는 NM 하나만 실행한다.

```text
START → normalize_report → END
```

RM·IA를 붙일 때 이 그래프를 확장한다. 채팅 메시지와 고정 실행 계획을 만드는 현재 데모 노드는 제거 후보이며,
구체적인 전환 방식은 N6에서 결정한다.

## 2. 구현 단계

### S1. NM 입력·출력 모델

- 원본 리포트 식별자와 source별 payload를 받는 입력 모델
- NM이 읽을 수 있도록 원본 payload를 안정적인 텍스트로 렌더링하는 로직
- `bug_report_id`, 추출값, 누락 항목, 오류 signature 출력 모델
- 비어 있는 원문과 잘못된 structured output을 거부하는 Pydantic 검증

관련 결정: **N1, N2, N3, N8**

### S2. 모델 호출 경계와 프롬프트

- NM 도메인이 구체적인 모델 SDK를 모르도록 모델 호출 경계 정의
- structured output 스키마와 도메인 결과를 분리
- 원문을 명령이 아닌 비신뢰 데이터로 취급하는 시스템 지침
- 원문에 없는 보충, 번역 과정의 의미 변경, 임의 원인 추론 금지
- 테스트용 fake 모델 구현

관련 결정: **N3, N4, N7, N8**

### S3. source reference 검증과 실패 정책

- 입력과 출력의 `bug_report_id` 연결 유지
- 모델이 식별자를 생성하거나 변경하지 못하도록 애플리케이션에서 주입
- 잘못된 structured output을 정상 결과로 통과시키지 않음
- 결정된 정책에 따라 재시도 또는 명시적 실패

관련 결정: **N1, N5**

### S4. NM 노드와 LangGraph 연결

- NM 전용 최소 state 정의
- 모델/설정을 주입받는 노드 구성
- `START → normalize_report → END` 그래프 조립
- Agent Server 진입점 갱신

관련 결정: **N4, N6, N7**

### S5. 테스트와 문서

- 입력·출력 모델 단위 테스트
- 정상 리포트 fixture
- 주요 정보가 누락된 리포트 fixture
- 잘못된 structured output fixture
- 비어 있는 payload 테스트
- fake 모델 기반 그래프 테스트
- 실제 모델 adapter가 포함되면 API를 호출하지 않는 배선 테스트
- README 구조·실행 예제 갱신

### S6. 결과 정리와 브랜치 병합

- `04-result.md`에 변경, 테스트 결과, 한계 기록
- NM 작업 커밋을 `feature/report-normalizer`에 완결
- 사용자 확인 후 `feature/report-normalizer → taek` 병합
- RM·IA는 각각 `taek`에서 새 작업 브랜치를 생성
- 전체 작업 완료 후에만 `taek → main` 병합

## 3. 결정 포인트

### N1. NM의 원본 연결과 evidence 책임

#### (a) 각 추출값에 원문 pointer·offset·excerpt 저장

- 추출 근거를 세밀하게 추적할 수 있다.
- NM이 조사 evidence까지 소유하게 되고 계약이 복잡해진다.

#### (b) `bug_report_id`만 유지

- NM은 정규화와 원본 계보만 담당한다.
- 후속 에이전트가 필요할 때 식별자로 원본 전체를 다시 읽는다.
- 코드·문서·로그 조사 evidence는 IA와 탐색 에이전트가 만든다.

**결정: (b).** NM에는 pointer·offset·excerpt를 두지 않는다. 원본 BugReport는 변경되지 않게 보존한다는
전제에서 `bug_report_id`만 출력에 유지한다. 조사 evidence의 짧은 코드 스냅샷과 관계 구조는 IA 작업에서 결정한다.

### N2. NM의 최소 출력 계약과 오류 signature 구조

#### (a) 오류 관련 정보를 중심으로 작은 검색 입력만 저장

- 초기 구현은 단순하다.
- 자연어 리포트의 현상·재현·환경 차이를 RM이 다시 해석해야 한다.

#### (b) RM이 비교할 표준 사실 표현을 저장

- `bug_report_id`, 발생 현상, 기대 동작, 재현 정보, 환경, 영향 기능, 오류 신호, 누락 정보를 둔다.
- 오류 신호는 예외 타입·메시지·코드·stack frame으로 분리한다.
- 이미 구조화된 입력은 보존하고 자유 텍스트에서 부족한 사실만 추출한다.

**결정: (b).** NM은 다양한 BugReport를 RM이 비교할 수 있는 표준 사실 표현으로 바꾸는 경계다. 원인·코드
검색어·도메인 후보·우선순위·해결책은 포함하지 않는다.

### N3. 명시되지 않은 정보 처리

#### (a) 모델의 합리적 추론을 허용하고 confidence로 표시

- 풍부한 결과를 얻을 수 있다.
- confidence가 보정되지 않았고, 추론이 후속 단계에서 사실로 소비될 위험이 있다.

#### (b) 명시적 표현과 의미 보존 paraphrase만 허용

- 근거 기반 결과가 분명하다.
- 암묵적인 환경이나 원인을 NM이 보충하지 않는다.

**결정: (b).** NM은 추출기다. 원인 추론은 IA의 책임이며, 찾지 못한 값은 `missing_fields`로 보낸다. 초기에는
LLM 자기평가 confidence를 핵심 계약에 넣지 않는다. 누락 목록은 모델이 아니라 애플리케이션이 최종 결과에서
계산한다.

### N4. 모델 호출 경계

#### (a) NM 서비스가 LangChain `BaseChatModel`을 직접 받음

- 코드가 짧다.
- 도메인 테스트와 structured output 변환이 LangChain 타입에 결합된다.

#### (b) NM 전용 `NormalizationModel` 프로토콜을 두고 adapter에서 LangChain 사용

- fake 테스트가 단순하고 모델 SDK를 교체할 수 있다.
- 얇은 adapter 코드가 추가된다.

**추천: (b).** 포트는 `normalize(source_document) -> NormalizationDraft`만 노출하고, 출력 검증과 최종
`NormalizedReport` 조립은 NM 서비스가 담당한다.

### N5. structured output 검증 실패 정책

#### (a) 즉시 노드 실패

- 실패가 투명하고 호출 횟수가 예측 가능하다.
- 사소한 형식 오류도 전체 실행 실패가 된다.

#### (b) 검증 오류를 피드백해 1회 교정 후 실패

- 복구 가능성과 비용을 제한적으로 균형 잡는다.
- adapter가 교정 요청을 지원해야 한다.

#### (c) 유효한 필드만 부분 반환

- 일부 결과를 보존한다.
- 무엇이 누락됐는지와 모델 실패가 섞이며 후속 단계가 불완전 결과를 정상으로 오해할 수 있다.

**추천: (b).** 최대 1회만 교정하고 다시 실패하면 명시적으로 노드를 실패시킨다. 비어 있는 입력 같은 입력 오류는
모델을 호출하지 않고 즉시 실패한다.

### N6. 현재 데모 그래프 처리

#### (a) 기존 `clio_agent`를 NM 그래프로 교체

- 실제 Clio 도메인 그래프가 하나의 진입점으로 성장한다.
- 기존 채팅 데모 호출 형식은 깨진다.

#### (b) 기존 그래프를 유지하고 `report_normalizer` 그래프를 추가

- 데모 호환성을 유지한다.
- 제품에서 사용하지 않을 그래프와 상태 계약을 계속 관리한다.

**추천: (a).** 현재 그래프는 외부 계약이 아니라 scaffold이며, RM·IA도 같은 `clio_agent`에 이어 붙일 예정이다.
README에서 breaking change를 명시한다.

### N7. 실제 모델 adapter 범위

#### (a) 프로토콜과 fake만 구현

- 계약과 검증에 집중할 수 있다.
- Agent Server에서 실제 NM을 실행할 수 없다.

#### (b) LangChain configurable model adapter까지 구현

- `.env`의 `CLIO_MODEL`을 사용해 실제 실행 가능하다.
- provider integration 패키지와 API key가 런타임에 필요하다.

**추천: (b).** 실제 모델 생성은 지연시켜 테스트 import 시 API key를 요구하지 않게 한다. 테스트는 계속 fake만
사용하고 외부 API를 호출하지 않는다.

### N8. 출력 언어와 원문 보존

#### (a) 모든 추출값을 원문 그대로 저장

- 근거 대조가 쉽다.
- 장황한 표현을 검색 입력으로 다시 정리해야 한다.

#### (b) 설명 필드는 의미 보존 정규화, 기술 식별자는 원문 보존

- 증상·기대 동작·재현 절차는 간결하게 정규화한다.
- 예외 타입, 오류 코드, 파일·심볼, stack frame은 원문을 그대로 둔다.
- 원문에 없는 내용을 새 사실로 추가하지 않는다.

**추천: (b).** 별도 번역은 하지 않고 입력 언어를 유지한다. 후속 검색에서 번역/확장이 필요하면 RM 검색 계획의
책임으로 둔다.

## 4. 추천 결정 요약

| ID | 주제 | 추천 |
|---|---|---|
| N1 | 원본 연결 | `bug_report_id`만 유지, evidence는 후속 조사 책임 |
| N2 | 최소 출력 계약 | RM 비교용 8개 필드, 오류 신호 세분화 |
| N3 | 추론 허용 | 원문 사실만 구조화, 누락은 애플리케이션이 계산 |
| N4 | 모델 경계 | NM 전용 프로토콜 + LangChain adapter |
| N5 | 검증 실패 | 1회 교정 후 명시적 실패 |
| N6 | 그래프 | 기존 `clio_agent`를 NM 그래프로 교체 |
| N7 | 실제 모델 | configurable model adapter 포함 |
| N8 | 언어 | 입력 언어 유지, 기술 식별자는 원문 보존 |

## 5. 예상 커밋 단위

결정 확정 뒤 다음 정도로 분리한다. 구현 중 독립 검증 단위가 달라지면 더 작게 나눌 수 있다.

```text
docs: NM 구현 계획 및 결정 기록
feat: NM 입력·출력 모델
feat: NM 모델 포트와 근거 검증 서비스
feat: NM LangChain adapter와 프롬프트
feat: NM LangGraph 노드 연결
test: NM fixture 및 실패 경로 검증
docs: NM 사용법과 구현 결과
```

## 6. 테스트 기준

다음 명령이 모두 통과해야 한다.

```bash
pytest
ruff check .
ruff format --check .
```

추가로 테스트는 다음 성질을 검증한다.

- 동일한 fake 응답은 동일한 `NormalizedReport`를 만든다.
- 출력의 `bug_report_id`가 입력 식별자와 일치한다.
- 누락 정보는 빈 문자열이 아니라 명시적인 missing field로 표현된다.
- 모델은 원본 payload를 변경하지 않는다.
- 잘못된 structured output은 교정 1회 후에도 유효하지 않으면 실패한다.
- API key가 없는 테스트 환경에서도 import와 그래프 실행 테스트가 가능하다.

## 7. 이번 작업 이후

NM 결과가 안정화되면 작업 브랜치를 `taek`에 병합한다. 다음 RM 작업은 `taek`에서 별도 브랜치를 만들고,
RM이 실제로 요구하는 검색 입력을 확인한 뒤 NM 전용 계약 중 공통으로 승격할 항목을 결정한다.
