# Report Matcher(RM) 1차 구현

## 1. 작업 배경

Report Normalizer(NM)는 여러 형식의 BugReport를 다음 표준 사실 표현으로 바꾼다.

```text
bug_report_id
observed_behavior
expected_behavior
reproduction
environment
affected_surface
error_signals
missing_fields
```

현재 Agent Graph는 `START → normalize_report → END`까지만 실행한다. 다음 단계인 Report Matcher(RM)는
NM 결과를 프로젝트의 기존 Bug·Issue와 비교하여 기존 작업에 연결할지, 사람의 검토가 필요한지, 새 Issue를
만들지 판단해야 한다.

## 2. RM의 존재 이유

같은 장애가 표현만 다르게 반복될 수 있다.

```text
"결제가 안 돼요"
"POST /payments returns 500"
"NullPointerException at PaymentService.pay"
```

단순 fingerprint나 embedding 점수 하나만으로 동일성을 결정하면 다음 문제가 생긴다.

- 오류 메시지가 같지만 발생 기능과 원인이 다른 경우
- 표현은 다르지만 같은 환경·재현 조건·오류 흐름을 가진 경우
- 기존 Issue와 일부는 일치하지만 중요한 조건이 모순되는 경우
- 리포트 정보가 부족해 자동 연결하면 위험한 경우

RM은 검색기가 찾은 후보를 NM의 표준 필드와 비교하고, 자동화 가능한 경우와 사람 판단이 필요한 경우를
구분하는 역할을 맡는다.

## 3. 현재 데이터 모델에서 먼저 풀어야 할 경계

Clio Server에는 다음 계층이 이미 존재한다.

```text
BugOccurrence(raw_payload)
  → Bug(project + fingerprint, occurrence_count)
  → IssueBug
  → Issue
```

각 질문은 서로 다르다.

1. 새 발생이 기존 `Bug`와 같은 현상인가?
2. 서로 다른 `Bug`가 같은 root cause의 `Issue`에 속하는가?

현재 스키마는 `BugOccurrence`가 생성될 때 이미 `Bug`를 참조하므로 fingerprint 기반 Bug 병합이 RM보다 앞에서
일어나는 구조를 전제한다. 반면 제품 설명의 RM은 "신규 리포트가 어느 기존 Issue와 같은지"를 판단한다.

따라서 1차 RM의 입력 단위를 다음 중 하나로 확정해야 한다.

- 원본 BugReport를 기존 Bug와 먼저 매칭하고 이어서 Issue까지 판단
- 서버가 만든 Bug를 받아 기존 Issue와만 매칭
- 두 단계를 별도 노드 또는 별도 결과로 모두 수행

이 경계를 정하지 않으면 `bug_report_id`, `bug_id`, `issue_id`의 의미와 자동 연결 대상이 계속 섞인다.

## 4. RM의 권장 책임

RM은 검색과 최종 비교를 분리한다.

```text
NormalizedReport
  → Candidate Retriever
       ├─ exact error signal
       ├─ lexical search
       └─ vector similarity
  → Match Judge
  → MatchDecision
```

### Candidate Retriever

기존 후보를 넓게 찾는 검색 컴포넌트다. 후보 누락을 줄이는 것이 목표이며 최종 자동 연결을 결정하지 않는다.
실제 저장소나 검색 엔진과의 결합은 Protocol 뒤로 숨겨 Fake·in-memory 구현으로 테스트 가능해야 한다.

### Match Judge

후보별로 다음 항목을 비교한다.

- 실제 발생 현상
- 기대 동작
- 재현 조건과 절차
- 발생 환경
- 영향받은 기능·작업·API·화면
- 오류 유형·메시지·코드·stack frame
- 서로 일치하는 정보와 모순되는 정보
- NM에서 누락된 정보

검색 점수는 참고 신호이며 동일성 판단 자체가 아니다.

## 5. RM이 만들 결과

최종 분기는 다음 세 가지다.

```text
AUTO_LINK   기존 대상에 자동 연결 가능
REVIEW      후보는 있으나 사람이 확인해야 함
CREATE_NEW  충분히 같은 기존 대상을 찾지 못함
```

결과에는 최소한 다음 정보가 필요하다.

```text
bug_report_id
action
matched_issue_id(optional)
candidate comparisons
confidence
supporting reasons
contradictions
review reasons
```

RM은 DB를 직접 변경하지 않고 연결 또는 생성 **제안**만 반환하는 방향이 안전하다. 실제 `IssueBug` 연결이나
Issue 생성은 결과가 확정된 뒤 별도 애플리케이션 경계에서 수행한다. 이 부작용 경계는 plan에서 결정한다.

## 6. RM에서 하지 않을 일

- 코드베이스를 조사해 root cause 생성
- 코드 Evidence 수집
- 수정 파일·함수 추천
- 해결 계획과 테스트 계획 생성
- 심각도·긴급도·우선순위 결정
- 검색 점수만으로 무조건 자동 연결
- 원본 BugReport 또는 기존 Issue 내용 수정

코드 조사와 root cause는 IA, 해결 방향은 RP, 우선순위는 PG의 책임이다.

## 7. 현재 없는 것

- RM 입력·후보·결과 Pydantic 계약
- 기존 Bug/Issue 후보를 가져오는 retrieval Protocol
- hybrid retrieval의 결합 방식과 top-k 정책
- 후보를 비교하는 모델 Protocol과 LangChain adapter
- 자동 연결·검토·신규 생성 임계치 정책
- 중요한 모순이 있을 때 자동 연결을 차단하는 규칙
- `normalize_report → report_matcher` LangGraph 연결
- 후보 없음·단일 강한 후보·복수 애매 후보·정보 부족 테스트
- 실제 PostgreSQL 또는 Clio Server 연동 경계

## 8. 개선 방향

### 8.1 검색과 판단을 독립적으로 평가한다

```text
Retrieval 평가: 정답 Issue가 후보 Top-K 안에 있는가
Judgment 평가: 주어진 후보에서 올바른 action을 선택하는가
```

두 단계를 한 LLM 호출로 묶으면 후보를 못 찾은 실패와 후보를 잘못 판단한 실패를 구분할 수 없다.

### 8.2 결정론적 정책과 LLM 판단을 함께 사용한다

- exact fingerprint·강한 error signature 같은 신호는 검색과 정책에서 활용
- LLM은 여러 필드의 의미적 일치와 모순을 구조화
- 자동 연결 임계치는 프롬프트가 아니라 애플리케이션 설정으로 관리
- 중요한 모순이나 정보 부족은 confidence가 높아도 REVIEW로 제한

### 8.3 후보 ID를 기준으로 장기 추적한다

RM은 NM처럼 별도 조사 Evidence를 만들지 않는다. 어떤 후보를 어떤 이유로 비교했는지 후보 Bug·Issue 식별자와
판단 결과를 남긴다. 코드 Evidence는 IA가 실제 코드 조사를 시작할 때 만든다.

## 9. 이번 작업 범위 초안

### 포함 후보

- RM 최소 입력·후보·결과 계약
- 후보 retrieval Protocol
- Fake/in-memory 후보 검색을 통한 결정적 테스트
- Match Judge 모델 Protocol과 실제 LangChain adapter
- structured output 검증 및 제한된 교정
- AUTO_LINK·REVIEW·CREATE_NEW 분기 정책
- NM 다음에 RM을 실행하는 LangGraph
- Python 초심자를 위한 한글 docstring과 문법 설명 주석

### plan에서 범위를 결정할 항목

- 실제 pgvector/PostgreSQL hybrid retrieval까지 이번에 구현할지
- Clio Server API를 통해 후보를 받을지 Python이 같은 DB를 직접 조회할지
- RM이 Bug 매칭과 Issue 매칭을 모두 할지 Issue 매칭만 할지
- 실제 연결·Issue 생성 부작용까지 수행할지 제안만 반환할지

### 제외 후보

- IA와 코드 탐색
- Issue 생성 이후 분석
- 운영 데이터 기반 임계치 자동 튜닝
- 관리자 검토 UI
- priority queue 갱신
- 온라인 학습 루프

## 10. 완료 기준 초안

- RM의 입력 단위와 Bug·Issue 경계가 명확하다.
- 후보 검색과 후보 비교가 별도 계약으로 분리된다.
- 동일 입력과 Fake 모델로 분기를 재현할 수 있다.
- 강한 후보, 모순 후보, 후보 없음, 정보 부족을 각각 올바르게 분기한다.
- 검색 점수만으로 자동 연결되지 않는다.
- NM 결과가 RM으로 전달되고 최종 그래프 출력에 `MatchDecision`이 포함된다.
- 외부 API 없이 전체 테스트가 실행된다.
- 실제 모델 adapter를 import해도 최초 호출 전에는 API key를 요구하지 않는다.

## 11. Plan에서 결정할 핵심 항목

1. **매칭 단위**: BugReport→Bug, Bug→Issue, 또는 두 단계
2. **후보 형태**: Bug 후보와 Issue 후보에 어떤 정보를 제공할지
3. **검색 범위**: retrieval Protocol만 / 실제 hybrid RAG까지
4. **데이터 접근**: PostgreSQL 직접 접근 / Clio Server API
5. **판단 구조**: 후보별 개별 비교 / 여러 후보 동시 비교
6. **분기 정책**: AUTO_LINK·REVIEW 임계치와 모순 차단 규칙
7. **부작용 경계**: 제안만 반환 / 실제 연결·생성까지 수행
8. **모델 실패 정책**: 교정·fallback·실패 처리
9. **그래프 출력**: NM 결과와 RM 결과를 모두 반환할지
10. **평가 fixture**: 어떤 유형의 중복·비중복 사례를 기준으로 삼을지

## 12. 주요 위험

- Bug와 Issue의 책임이 정리되지 않으면 중복 병합과 root cause grouping이 섞인다.
- 초기 운영 데이터 없이 confidence 임계치를 고정하면 자동 연결의 정밀도를 과신할 수 있다.
- vector similarity가 높은 후보가 반드시 같은 원인은 아니다.
- Issue title·summary만 검색하면 해결 전 Issue의 정보가 부족해 후보 검색 품질이 낮을 수 있다.
- 실제 DB 연동까지 한 작업에 넣으면 RM 판단 품질보다 인프라 구현이 범위를 지배할 수 있다.
- 기존 Java `BugEmbedding`과 Python이 소유할 RAG 데이터의 책임이 중복될 수 있다.
