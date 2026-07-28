# Report Matcher(RM) 1차 구현 계획

`01-overview.md` 확인 완료. 이 문서는 RM의 구현 단계와 결정 포인트(R1~R10)를 담는다. 결정은
`03-decisions.md`에 하나씩 기록하고, 결정에 따른 구현을 작은 커밋으로 나눈다.

## 1. 목표 흐름

```text
START
  → normalize_report
  → issue_retrieval_subgraph
  → judge_issue_match
  → apply_match_policy
  → END
```

후보가 없으면 모델을 호출하지 않고 `CREATE_NEW`로 끝낼 수 있다. 후보가 있으면 Match Judge가 후보별 일치·모순을
구조화하고, 애플리케이션 정책이 `AUTO_LINK`, `REVIEW`, `CREATE_NEW`를 최종 결정한다.

## 2. 구현 단계

### S1. RM 계약

- RM 입력 단위와 `bug_report_id`·`bug_id` 의미 확정
- Issue 후보와 후보 안의 대표 Bug 정보 모델
- 검색 점수와 검색 신호 모델
- 모델이 만드는 후보 비교 초안
- 애플리케이션이 만드는 최종 `MatchDecision`

관련 결정: **R1, R2, R9**

### S2. 후보 retrieval subgraph 경계

- RAG 하위 에이전트의 LangGraph 입출력 schema
- `project_id`·`bug_id`·NM 결과를 전달하는 호출 노드
- 실제 RAG가 없는 동안 명시적으로 실패하는 placeholder subgraph
- 테스트용 Fake retrieval subgraph
- Issue 최대 5개와 Issue당 대표 Bug 최대 3개 검증

관련 결정: **R2, R3, R4**

### S3. Match Judge 모델 경계

- Java interface 역할의 `IssueMatchModel` Protocol
- 후보 비교 structured output
- 원문에 없는 root cause나 코드 사실을 만들지 않는 프롬프트
- 입력 언어 유지, 기술 식별자 원문 보존
- 실제 LangChain adapter 지연 생성
- structured output 1회 교정

관련 결정: **R5, R8**

### S4. 결정 정책

- 후보 없음의 결정적 `CREATE_NEW`
- 후보별 모델 비교 결과 검증
- 자동 연결 threshold·검색 신호·모순 차단 규칙
- 정보 부족 시 자동 연결 차단
- 최종 action과 선택된 Issue ID 조립

관련 결정: **R6, R7**

### S5. LangGraph 연결

- `ClioState`에 후보와 RM 결과 추가
- NM 다음 retrieval·judge·policy 노드 연결
- 후보 없음 조건부 edge
- 공개 출력 계약 갱신
- 외부 DB/API 없이 Fake 조합으로 전체 그래프 테스트

관련 결정: **R7, R9**

### S6. 후속 실제 RAG 작업의 연결 지점

실제 Hybrid RAG는 별도 `taek/issue-retrieval` 작업에서 subgraph 내부에 구현한다. RM은 검색 방식이나
PostgreSQL 구조를 알지 않고 확정된 요청·응답 계약으로만 하위 에이전트를 호출한다.

### S7. 평가·문서·병합

- 중복·비중복·모순·정보 부족 fixture
- retrieval과 judgment를 분리 평가할 수 있는 테스트 구조
- README 공개 입출력과 환경변수 갱신
- `04-result.md` 작성
- 전체 테스트·lint 통과 후 `taek/report-matcher → taek/integration` 병합

## 3. 결정 포인트

### R1. RM의 매칭 단위

#### (a) BugReport → 기존 Bug

- 동일 현상의 반복 발생을 합친다.
- 현재 서버의 fingerprint·Bug 생성 책임과 겹칠 수 있다.
- Issue 연결은 별도 단계가 필요하다.

#### (b) Bug → 기존 Issue

- 서버의 fingerprint 병합 이후 RM이 같은 root cause의 작업 단위를 찾는다.
- 현재 `BugOccurrence → Bug → IssueBug → Issue` 스키마와 일치한다.
- NM의 `bug_report_id`가 API의 Bug 식별자인지 명확히 해야 한다.

#### (c) BugReport → Bug와 Bug → Issue를 모두 수행

- 전체 grouping을 Agent Graph에서 통제할 수 있다.
- 서로 다른 동일성 판단 두 개가 한 RM에 섞이고 범위가 커진다.

**추천: (b).** fingerprint 기반 같은 현상 병합은 Clio Server 수집 책임으로 유지하고, RM은 만들어진 Bug를 기존
Issue와 비교한다. Agent Graph 입력에는 `bug_id`를 명시적으로 추가하고 기존 `bug_report_id`와의 관계를 plan
결정 기록에서 고정한다.

### R2. Issue 후보 계약

#### (a) Issue title·summary만 제공

- 작고 단순하다.
- 같은 root cause 판단에 필요한 실제 발생 Bug 정보가 부족하다.

#### (b) Issue + 대표 Bug 목록 제공

- Issue ID·title·summary·status와 해당 Issue의 대표 Bug들을 제공한다.
- 대표 Bug에는 ID·발생 현상·영향 기능·오류 신호·환경·발생 횟수를 포함한다.
- 후보 context가 커지므로 Issue당 대표 Bug 수 제한이 필요하다.

**추천: (b).** Issue당 대표 Bug 최대 3개를 제공한다. 후보 데이터는 저장소 엔티티를 직접 노출하지 않고 RM 전용
Pydantic 모델로 고정한다.

### R3. 이번 작업의 retrieval 구현 범위

#### (a) Protocol + Fake/in-memory만

- RM 판단과 그래프 계약을 먼저 안정화할 수 있다.
- 실제 Agent Server가 기존 Issue를 검색할 수 없는 상태로 끝난다.

#### (b) 실제 Hybrid RAG까지 포함

- exact·lexical·vector 검색의 실제 경로가 완성된다.
- DB schema·embedding 생성·인덱스·연결 설정까지 범위가 커진다.

#### (c) Protocol + 실제 lexical/exact, vector는 후속

- 기본 검색은 실제 동작한다.
- Hybrid RAG라고 부르기에는 vector 경로가 비어 있다.

**결정:** 실제 Hybrid RAG는 별도 `taek/issue-retrieval` 작업으로 분리한다. 이번 작업은 빈 LangGraph
subgraph의 입출력 계약과 Fake를 제공한다. 기본 placeholder가 호출되면 후보 없음으로 가장하지 않고 설정 오류를
발생시킨다.

### R4. 실제 데이터 접근 방식(후속 작업)

R3에서 실제 adapter를 포함하거나 후속 작업을 설계할 때 적용한다.

#### (a) Python이 PostgreSQL을 직접 읽음

- 프로젝트 README의 "같은 PostgreSQL 직접 접근, RAG 테이블은 Python 소유" 방향과 일치한다.
- Java와 Python의 도메인 테이블 쓰기 책임을 엄격히 구분해야 한다.

#### (b) Clio Server API로 후보를 받음

- 도메인 데이터 소유권이 Java에 모인다.
- 검색마다 네트워크 hop이 추가되고 RAG 검색 API를 Java에 만들어야 한다.

이번 RM 구현에서는 결정하지 않는다. RAG subgraph가 데이터 접근을 소유하며 RM은 해당 방식을 알지 않는다.

### R5. 후보 비교 방식

#### (a) 후보 하나당 모델 한 번 호출

- 후보별 context가 작다.
- 비용이 후보 수에 비례하고 상대적 최선 후보 선택이 어렵다.

#### (b) Top-K 후보를 한 번에 비교

- 후보 간 상대 비교와 1등 선택이 가능하다.
- context가 커지지만 top-k 제한으로 제어할 수 있다.

**결정: (b).** Issue 후보 최대 5개를 한 structured output 호출에서 비교한다. 각 Issue는 대표 Bug 최대 3개로
제한한다.

### R6. 최종 분기 정책

#### (a) LLM action을 그대로 사용

- 구현이 단순하다.
- threshold와 안전 정책을 프롬프트가 암묵적으로 소유한다.

#### (b) LLM은 후보별 비교만, 애플리케이션이 action 결정

- 모델은 `match_confidence`, 일치 이유, 모순, 정보 부족을 반환한다.
- 정책 코드가 threshold와 차단 규칙으로 최종 action을 결정한다.

**결정: (b).** 초기 기본값은 다음과 같다.

```text
후보 없음                                      → CREATE_NEW
top confidence >= 0.95
  + error type 일치
  + error code 또는 stack frame 일치
  + observed behavior·affected surface 존재
  + contradiction 없음
  + 1·2위 confidence 차이 > 0.10               → AUTO_LINK
top confidence >= 0.70                         → REVIEW
그 외                                          → CREATE_NEW
```

운영 데이터로 보정하기 전까지 자동 연결은 매우 보수적으로 제한한다. threshold는 환경 설정으로 둔다.

### R7. 부작용 경계

#### (a) RM이 IssueBug 연결과 새 Issue 생성을 직접 수행

- 한 실행에서 상태 변경까지 끝난다.
- QG·사람 검토 전에 DB가 변경될 수 있고 재시도 멱등성이 복잡해진다.

#### (b) MatchDecision 제안만 반환

- Java 서버가 action에 따라 연결·검토 큐·생성을 수행한다.
- Agent Graph는 read-only 판단 서비스로 유지된다.

**결정: (b).** 이번 작업은 제안까지만 반환한다. 실제 쓰기 API와 멱등성은 Server 연동 작업에서 결정한다.

### R8. 모델 실패 정책

#### (a) NM과 동일하게 structured output 1회 교정 후 실패

- 일관되고 부분 판단을 남기지 않는다.

#### (b) rule-based 결과로 fallback

- 가용성은 높다.
- fallback과 모델 경로의 판단 의미가 달라지고 초기 정책이 복잡해진다.

**결정:** 후보 없음은 모델 없이 `CREATE_NEW`. RAG 또는 비교 모델의 일시 실패는 한 번 재시도한다. structured
output 오류는 검증 피드백으로 한 번 교정한다. 두 번째도 실패하면 임의 REVIEW로 숨기지 않고 구분 가능한 예외로
RM 실행을 실패시킨다. RAG 미설정 오류는 재시도하지 않는다.

### R9. 공개 그래프 출력

#### (a) `match_decision`만 반환

- 응답이 작다.
- NM 결과를 다시 보려면 별도 실행 상태 조회가 필요하다.

#### (b) `normalized_report`와 `match_decision` 모두 반환

- 한 응답에서 입력 정규화와 매칭 판단을 함께 검토할 수 있다.
- 결과가 조금 커진다.

**결정: (b).** 디버깅과 관리자 검토를 위해 둘 다 반환한다. 후보 전체는 내부 state에 두고 최종 결과에는 후보별
비교 요약만 포함한다.

### R10. 평가 fixture

최소 다음 유형을 고정 fixture로 만든다.

```text
1. exception type + message + top frame이 같은 강한 중복
2. 같은 기능이지만 오류 유형과 환경이 다른 비중복
3. 표현은 다르지만 현상·재현·오류 흐름이 같은 중복
4. vector/lexical은 유사하지만 중요한 조건이 모순되는 후보
5. 정보가 부족해 자동 연결할 수 없는 리포트
6. 후보가 전혀 없는 신규 이슈
7. 여러 후보가 비슷해 1등을 확정할 수 없는 경우
8. 이미 현재 Bug가 연결된 Issue를 후보에서 제외하는 경우
```

**결정:** 위 8개를 모두 포함한다. retrieval 테스트와 judgment/policy 테스트 fixture를 분리한다.

## 4. 추천 결정 요약

| ID | 주제 | 추천 |
|---|---|---|
| R1 | 매칭 단위 | Bug → Issue |
| R2 | 후보 계약 | Issue + 대표 Bug 최대 3개 |
| R3 | retrieval 범위 | 빈 LangGraph subgraph + Fake, 실제 RAG 별도 작업 |
| R4 | 데이터 접근 | 후속 RAG subgraph 작업에서 결정 |
| R5 | 비교 방식 | Issue Top-5 한 번에 비교 |
| R6 | 분기 정책 | 모델 비교 + 0.95/0.70 보수적 정책 코드 |
| R7 | 부작용 | MatchDecision만 반환 |
| R8 | 모델 실패 | structured output 1회 교정 후 실패 |
| R9 | 그래프 출력 | NM 결과 + MatchDecision |
| R10 | 평가 | 중복·모순·정보 부족 등 8종 fixture |

## 5. 예상 공개 계약

### 그래프 입력

```json
{
  "bug_report": {
    "bug_report_id": 351,
    "title": "결제 실패",
    "description": "결제 버튼을 누르면 500 오류가 발생합니다."
  },
  "bug_id": 72,
  "project_id": 3
}
```

### 그래프 출력

```json
{
  "normalized_report": {
    "bug_report_id": 351
  },
  "match_decision": {
    "bug_id": 72,
    "action": "REVIEW",
    "matched_issue_id": 19,
    "confidence": 0.82,
    "supporting_reasons": ["동일한 PaymentService 오류 유형"],
    "contradictions": [],
    "review_reasons": ["발생 환경 정보가 부족함"]
  }
}
```

구체적인 하위 필드는 결정 후 모델 구현에서 고정한다.

## 6. 예상 커밋 단위

```text
docs: RM 구현 계획 및 결정 기록
feat: RM 후보와 판단 결과 계약
feat: RM retrieval 포트와 검색 projection
feat: RM 모델 포트와 비교 정책
feat: RM LangChain adapter와 프롬프트
feat: RM LangGraph 분기 연결
test: RM fixture와 실패 경로 검증
docs: RM 사용법과 구현 결과
```

## 7. 테스트 기준

```bash
pytest
ruff check .
ruff format --check .
```

외부 API와 DB 없이 Fake 모델·retriever로 전체 그래프를 재현한다. 실제 retrieval adapter를 별도 작업으로 분리하면
이번 RM 완료 기준은 retrieval/judgment/policy 계약과 그래프 배선까지다.

## 8. 브랜치 흐름

```text
main
└─ taek/integration
   └─ taek/report-matcher
```

RM 작업 완료 후 `taek/report-matcher`를 `taek/integration`에 `--no-ff` 병합한다. NM·RM·IA 작업이 모두
완료되기 전에는 `main`에 병합하지 않는다.
