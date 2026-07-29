# Issue Analyzer(IA) 1차 구현

## 1. 작업 배경

현재 Agent Graph는 BugReport를 NM으로 정규화하고, RM이 기존 Issue 후보와 비교해 다음 action을 제안한다.

```text
START
  → normalize_report
  → issue_retrieval_subgraph
  → judge_issue_match
  → apply_match_policy
  → END
```

RM의 `CREATE_NEW`는 “충분히 같은 기존 Issue를 찾지 못했다”는 뜻일 뿐, 버그가 코드 어디에서 왜 발생했는지는
설명하지 않는다. 새 Issue를 개발자가 처리하려면 관련 파일·함수, 실행 흐름, 최근 변경과 가능한 원인에 대한 다음
단계의 조사가 필요하다.

IA는 이 조사 결과를 조립하는 에이전트다.

## 2. IA의 존재 이유

하나의 오류는 한 줄의 코드만으로 발생하지 않을 수 있다.

```text
Controller 입력 변환
  → Service 상태 변경
  → Repository 저장
  → Event Handler 후속 처리
```

예를 들어 “결제는 완료됐지만 주문 내역에 보이지 않는다”는 현상은 다음처럼 서로 다른 위치가 함께 원인이 될 수
있다.

- 결제 callback에서 주문 상태를 바꾸지 않음
- 트랜잭션 완료 전에 이벤트가 발행됨
- 조회 쿼리가 새 상태를 제외함
- 캐시가 DB 변경 뒤 무효화되지 않음

따라서 IA는 하나의 파일을 임의로 지목하는 모델이 아니라, 여러 코드 근거와 관계를 보고 root cause 후보를
우선순위화하는 역할이어야 한다.

## 3. IA와 Codebase Exploration Agent의 경계

코드 검색과 분석 판단은 분리한다.

```text
Issue context
  → IA가 탐색 요청 구성
  → Codebase Exploration Agent
       ├─ 파일·심볼 검색
       ├─ 코드 본문 검색
       ├─ 호출·의존 관계 확장
       ├─ 관련 테스트 검색
       └─ 최근 변경 검색
  → IA가 탐색 결과를 종합
  → IssueAnalysis
```

### Codebase Exploration Agent

- 실제 저장소와 코드 인덱스를 탐색한다.
- 파일, 심볼, 호출 관계, 관련 테스트, 최근 변경 후보를 반환한다.
- 최종 root cause를 단정하지 않는다.
- 검색 결과가 없다는 사실과 검색 실행 실패를 구분한다.

### Issue Analyzer

- NM의 정규화 결과와 새 Issue 문맥을 바탕으로 탐색 질문을 만든다.
- 코드 탐색 결과에서 확인된 사실을 선택하고 서로 연결한다.
- 하나 이상의 root cause 가설을 우선순위와 함께 만든다.
- 가설을 지지하는 근거와 반대하거나 부족한 정보를 함께 기록한다.
- 수정 방향과 테스트 계획은 만들지 않는다. 이는 RP의 책임이다.

## 4. 현재 서버와 Agent Graph에서 확인한 사실

Clio Server에는 다음 데이터 구조가 있다.

```text
Issue ← IssueBug → Bug
AnalysisJob(project, bug, issue, searchMode)
AnalysisResult(summary, rationale, relatedCode, flows, ...)
ProjectSource(repoUrl, targetBranch, rootPath, syncStatus)
CodeFile → CodeSymbol / CodeChunk
```

다만 현재 Java 서버에는 엔티티만 남아 있고, 과거 Java 분석 파이프라인 구현은 삭제되어 Python Agent Graph로
이관될 예정이다. 참고 문서도 코드 인덱스 전제가 새 요구사항에서 그대로 유효하지 않다고 명시한다.

현재 Python 그래프에는 다음이 없다.

- IA 입력·출력 Pydantic 계약
- 코드 탐색 하위 에이전트 계약과 실제 구현
- 신규 Issue가 생성되는 시점과 IA 호출 시점의 오케스트레이션 계약
- 코드 근거 snapshot 계약
- 확인된 사실과 추론을 구분하는 모델 출력
- 여러 root cause 가설의 우선순위와 신뢰도 정책
- 탐색 부족·부분 성공·하위 에이전트 실패 처리
- `CREATE_NEW` 이후 IA로 이어지는 LangGraph 분기

## 5. Evidence의 방향

NM과 RM은 코드 Evidence를 만들지 않는다. 코드 조사가 실제로 시작되는 IA 단계부터 Evidence가 생긴다.

코드베이스는 시간이 지나며 바뀌므로 라인 번호나 commit ID만 저장하면 장기적으로 근거를 읽지 못할 수 있다.
IA Evidence는 다음 원칙을 따른다.

- 실제 판단에 사용한 코드 본문을 snapshot으로 보존한다.
- snapshot 하나는 최대 10줄로 제한한다.
- 한 버그에 여러 Evidence를 연결할 수 있다.
- 파일 경로·심볼·라인·변경 식별자는 탐색 당시의 설명용 metadata이며 유일한 근거로 사용하지 않는다.
- 코드가 10줄을 넘거나 여러 함수에 걸치면 Evidence를 여러 개로 나누고 관계를 기록한다.
- 원문 코드에서 확인할 수 없는 내용은 Evidence가 아니라 hypothesis에 둔다.

예상 개념 구조:

```text
CodeEvidence
  - evidence_id
  - kind
  - code_snapshot (최대 10줄)
  - file_path / symbol / line metadata
  - observation

RootCauseHypothesis
  - hypothesis_id
  - statement
  - confidence
  - supporting_evidence_ids[]
  - contradicting_evidence_ids[]
  - unknowns[]
```

구체적인 필드와 식별자 생성 책임은 plan의 결정 포인트에서 확정한다.

## 6. 확인된 사실과 추론 구분

IA 결과는 최소 세 층으로 분리해야 한다.

```text
Evidence     실제 코드 snapshot과 탐색 결과
Finding      Evidence에서 직접 확인되는 사실
Hypothesis   여러 Finding을 조합한 발생 원인 추론
```

예시:

```text
Evidence:
  OrderService.completePayment 안에서 status를 PAID로 바꾼다.

Finding:
  해당 메서드에는 OrderHistoryCache 무효화 호출이 없다.

Hypothesis:
  결제 완료 뒤 캐시가 갱신되지 않아 주문 내역에 이전 상태가 노출될 가능성이 있다.
```

“캐시 미갱신이 원인이다”를 확인된 사실로 저장하면 안 된다. IA는 가설의 신뢰도가 높아도 추론이라는 표시를
유지한다.

## 7. IA에서 하지 않을 일

- 실제 코드 저장소·DB를 직접 탐색하는 구현
- Issue 생성 또는 DB 저장
- 코드를 수정하거나 브랜치·PR 생성
- 해결 방법과 작업 순서 결정
- 테스트 계획 확정
- 심각도·긴급도·우선순위 결정
- 원문이나 코드 탐색 결과에 없는 파일·함수·원인 생성

코드 탐색은 Codebase Exploration Agent, 해결 계획은 RP, 우선순위는 PG, 결과 검증은 QG가 담당한다.

## 8. 1차 구현 범위 후보

### 포함 후보

- IA 입력·Evidence·Finding·Hypothesis·최종 분석 계약
- Codebase Exploration Agent의 빈 LangGraph subgraph와 Fake
- 탐색 결과를 종합하는 모델 Protocol과 지연 생성 LangChain adapter
- 후보 ID와 Evidence 참조 무결성 검증
- 사실과 가설이 섞이지 않게 하는 structured output
- 하위 에이전트와 모델의 제한된 재시도
- `CREATE_NEW` 이후 IA 실행을 표현하는 그래프 분기
- Fake 기반 전체 그래프와 다중 Evidence 테스트
- Python 초심자를 위한 한글 docstring과 문법 설명 주석

### 제외 후보

- 실제 저장소 clone·인덱싱·검색
- AST·call graph 구현
- Git provider API 연동
- 실제 Issue/AnalysisResult 저장
- RP·PG·QG 구현
- 운영 데이터 기반 confidence 보정

## 9. Plan에서 결정할 핵심 항목

1. **IA 실행 시점**: `CREATE_NEW` 직후 provisional 분석 / 서버가 Issue 생성 후 별도 실행
2. **IA 입력 단위**: Bug 중심 / 생성된 Issue와 연결 Bug 전체
3. **Codebase Exploration 연결**: 빈 LangGraph subgraph의 구체적인 요청·응답 범위
4. **탐색 방식**: 한 번의 탐색 요청 / 결과를 보고 추가 질문하는 반복 탐색
5. **Evidence 계약**: snapshot과 metadata 필드, 10줄 제한, Evidence ID 생성 책임
6. **Finding·Hypothesis 계약**: 참조 무결성, 복수 가설 수, confidence 의미
7. **최근 변경 정보**: IA 1차 계약에 포함 / Code Explorer 후속 확장으로 연기
8. **RM action별 분기**: `CREATE_NEW`만 IA 실행 / `REVIEW`도 제한 분석
9. **실패·부분 결과 정책**: 재시도 후 전체 실패 / 근거가 확보된 부분 결과 반환
10. **공개 그래프 출력**: NM·RM·IA 모두 반환 / IA 결과 중심 반환

## 10. 완료 기준 초안

- 코드 탐색과 원인 분석 책임이 별도 계약으로 분리된다.
- IA가 여러 코드 Evidence와 관계를 표현할 수 있다.
- 코드 snapshot은 각각 최대 10줄이며 장기 보관 가능한 근거가 된다.
- Finding과 Hypothesis가 다른 타입으로 구분된다.
- 모든 Finding과 Hypothesis의 Evidence 참조가 실제 ID와 일치한다.
- 단일 파일 버그, 여러 계층이 얽힌 버그, 근거 부족, 모순 근거를 테스트한다.
- 실제 코드 탐색기 없이 Fake subgraph로 IA와 그래프 흐름을 검증할 수 있다.
- 하위 에이전트 미설정을 “검색 결과 없음”으로 처리하지 않는다.
