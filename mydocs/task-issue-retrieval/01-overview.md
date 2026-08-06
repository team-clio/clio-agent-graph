# Issue Retrieval Agent 개요

## 1. 작업 배경

Report Matcher(RM)는 새 Bug가 기존 Issue와 같은 문제인지 판단해야 한다. 현재 RM에는 다음 계약과
LangGraph subgraph 자리가 이미 있다.

```text
project_id + bug_id + normalized_report
  → issue_retrieval_subgraph
  → IssueCandidate 최대 5개
```

그러나 실제 검색기는 연결되어 있지 않다. 기본 그래프를 실행하면
`IssueRetrievalNotConfiguredError`가 발생하며, 테스트에서만 Fake 검색기를 주입한다. 이 상태에서는
NM과 RM의 비교·정책 코드는 완성되어 있어도 실제 BugReport 처리 흐름은 후보 검색 단계에서 멈춘다.

이번 작업은 이 빈 자리를 실제 **Issue Retrieval Agent**로 교체하는 작업이다.

## 2. 역할

Issue Retrieval Agent의 책임은 **동일 Issue일 가능성이 있는 후보를 넓고 재현 가능하게 찾는 것**이다.
후보가 정말 같은 Issue인지 최종 판단하지 않는다.

```text
Issue Retrieval Agent: 후보 회수(recall)와 검색 순위
Report Matcher: 후보별 의미 비교와 AUTO_LINK / REVIEW / CREATE_NEW 정책
Clio Server: 실제 Issue 연결·생성 및 데이터 저장
```

따라서 Retrieval Agent는 다음을 수행한다.

- `project_id`로 검색 범위를 제한한다.
- 현재 처리 중인 `bug_id`와 이미 연결된 대상을 검색 결과에서 제외한다.
- 정규화된 현상·영향 영역·오류 신호를 검색 질의로 투영한다.
- 정확 신호, 문자열 검색, 벡터 유사도 결과를 함께 사용한다.
- Bug 검색 결과를 Issue별로 묶고 점수를 계산한다.
- 상위 Issue 최대 5개와 비교에 필요한 대표 Bug 최대 3개를 반환한다.
- 정상적인 0건과 설정 오류·DB 장애·임베딩 장애를 구분한다.

다음은 이 Agent의 책임이 아니다.

- 후보가 동일 Issue인지 LLM으로 최종 판정
- `AUTO_LINK`, `REVIEW`, `CREATE_NEW` 결정
- Issue 또는 Issue-Bug 연결을 DB에 쓰기
- 원인 분석이나 코드 Evidence 생성
- Priority 계산

## 3. 왜 Issue가 아니라 Bug를 먼저 검색하는가

Clio의 실제 데이터 모델에는 `BugEmbedding`과 `IssueBug`가 있다.

```text
새 NormalizedReport
  → 유사한 기존 Bug 검색
  → Bug가 연결된 Issue로 변환
  → 같은 Issue의 Bug hit를 집계
  → 대표 Bug를 포함한 IssueCandidate 생성
```

Issue 제목·요약만 검색하면 서로 다르게 표현된 실제 오류 사례를 놓칠 수 있다. 반면 Bug에는 오류 유형,
정규화 메시지, 최상위 application frame, 발생 횟수 같은 관측 데이터가 있다. 여러 Bug가 하나의 Issue에
연결되는 현재 모델에서도 Bug hit를 Issue로 집계하는 방식이 자연스럽다.

단, 현재 `Bug` 엔티티만으로는 RM의 `RepresentativeBug.normalized_report` 전체를 복원할 수 없다.
재현 절차·환경·영향 영역·오류 코드 등의 정규화 snapshot은 별도로 보존되어 있지 않기 때문이다. 대표 Bug
projection을 어디에 저장하고 어떻게 조회할지는 계획 단계에서 결정해야 한다.

## 4. 목표 구조

Issue Retrieval Agent는 LLM이 임의로 검색 결과를 만드는 노드가 아니라, 여러 검색 수단을 명시적인 상태
흐름으로 조율하는 LangGraph subgraph다.

```text
START
  → build_search_query
  → exact_signal_search ───────┐
  → lexical_search ────────────┼→ fuse_bug_hits
  → vector_search ─────────────┘
  → aggregate_by_issue
  → hydrate_representative_bugs
  → rank_and_limit
  → END
```

구현 단계에서 일부 검색을 한 노드에서 병렬 실행할 수 있지만 각 단계의 계약과 책임은 분리한다.

### 4.1 검색 질의 생성

NM의 `NormalizedReport`에서 검색에 쓸 수 있는 값만 결정적으로 추출한다.

- 관찰된 현상과 기대 동작
- 기능·operation·endpoint·screen
- 오류 유형·메시지·오류 코드·stack frame
- 재현 조건·단계
- 환경

원문에 없는 검색어, root cause, 코드 사실은 생성하지 않는다. LLM을 다시 호출하지 않고 NM 결과를
정해진 형식의 검색 문서로 직렬화한다.

### 4.2 검색 채널

초기 Hybrid Retrieval이 고려할 채널은 다음과 같다.

1. **정확 신호 검색**
   - 동일한 `error_type`
   - 동일한 오류 코드
   - 동일하거나 정규화 가능한 application stack frame
2. **문자열 검색**
   - Bug 제목·설명·정규화 메시지와 관찰된 현상·영향 영역의 유사성
   - PostgreSQL full-text/trigram 또는 서버가 제공하는 동등한 검색 API
3. **벡터 검색**
   - 정규화된 Bug 검색 문서의 embedding 유사도
   - 동일 embedding model과 dimension으로 생성된 기존 `BugEmbedding`만 비교

각 검색 채널의 원점수 범위가 다르므로 원점수를 그대로 더하지 않는다. 순위 결합 방식, 채널별 가중치,
후보 부족 시 fallback은 계획 단계에서 결정하고 설정 객체로 분리한다.

### 4.3 Issue 집계

검색 채널은 Bug hit를 반환하고 Agent가 이를 Issue 단위로 집계한다.

- 같은 Issue의 여러 Bug가 검색되면 한 후보로 합친다.
- 하나의 Bug가 여러 Issue에 연결되는 비정상·과도기 데이터도 결정적으로 처리한다.
- 아직 어떤 Issue에도 연결되지 않은 Bug는 기존 Issue 후보가 될 수 없으므로 제외한다.
- 현재 `bug_id` 자체와 현재 Bug가 이미 연결된 Issue를 제외할지 여부를 명시적으로 정한다.
- 대표 Bug는 최고 검색 기여도, 강한 오류 신호, 최근성·발생 빈도 등을 기준으로 최대 3개 선택한다.
- 최종 후보는 점수 내림차순, 동점 시 안정적인 tie-breaker를 사용해 최대 5개로 제한한다.

## 5. 현재 저장소에서 확인된 기반

### Agent Graph

- `IssueRetrievalRequest`, `IssueRetrievalResponse`, `IssueCandidate` 계약이 존재한다.
- RM 그래프에 `issue_retrieval_subgraph`가 이미 연결되어 있다.
- 검색기는 Fake로 주입할 수 있어 Retrieval Agent를 독립적으로 테스트할 수 있다.
- 현재 Python 의존성에는 PostgreSQL client나 embedding provider가 포함되어 있지 않다.

### Clio Server

- `bugs`, `issues`, `issue_bugs`, `bug_occurrences`, `bug_embeddings` 엔티티가 있다.
- `Bug`에는 title, description, error type, normalized message, top application frame, 발생 횟수와 시간이 있다.
- `BugEmbedding`은 `float[]`, embedding model, dimension, 생성 시각을 저장한다.
- PostgreSQL 이미지는 pgvector를 사용하고 `vector` 확장을 생성한다.
- 현재 활성 코드에는 Bug embedding 생성 서비스, 검색 repository, Retrieval API가 없다.
- `BugOccurrence.rawPayload`는 원본 보존용이며, 정규화 결과 snapshot 저장 계약은 없다.
- 과거 `mydocs/ax-reference`에는 pgvector 검색 실험 기록이 있으나 현재 실행 코드가 아니므로 그대로 의존할 수 없다.

## 6. 해결해야 하는 구조적 문제

### 6.1 데이터 접근 경계

Agent Graph가 Clio DB를 직접 읽으면 검색 쿼리를 빠르게 구현할 수 있지만 Java 서버와 스키마 결합이 커진다.
Clio Server API를 통하면 데이터 소유권이 명확하지만, 검색·대표 Bug hydration·embedding upsert API를 서버에도
새로 구현해야 한다. 어느 쪽이 v1 경계인지 결정해야 한다.

### 6.2 Embedding 생성 책임

검색할 때 새 report의 query embedding이 필요하고, 과거 Bug에도 같은 모델의 embedding이 있어야 한다.
다음 시점과 주체가 아직 정해지지 않았다.

- Bug 생성·갱신 시 누가 embedding을 만든다.
- 기존 Bug backfill은 어떻게 수행한다.
- 모델 변경 시 재색인은 어떻게 구분한다.
- embedding 생성 실패 시 정확·문자열 검색만 허용할지 전체 실행을 실패시킬지 정한다.

### 6.3 대표 Bug의 정규화 snapshot

RM은 자동 연결의 강한 조건을 확인하기 위해 대표 Bug의 `error_type`과 오류 코드 또는 stack frame을 사용한다.
현재 DB의 `Bug`는 이 중 일부만 갖고 있으며 `NormalizedReport` 전체를 저장하지 않는다. 다음 대안이 있다.

- Bug별 정규화 snapshot을 별도 저장한다.
- 대표 `BugOccurrence`를 다시 NM으로 정규화한다.
- RM 후보 계약을 DB가 실제 보유한 비교 projection으로 변경한다.

두 번째 방식은 후보 hydration 때마다 LLM 호출이 발생하고 과거 결과가 모델 변화에 따라 달라질 수 있다.
장기 재현성과 비용을 고려하면 저장 snapshot 또는 명시적 비교 projection이 더 적합해 보이지만, 최종 선택은
계획의 결정 포인트로 남긴다.

### 6.4 정상 0건과 부분 장애

벡터 채널만 실패했는데 정확 검색 결과가 있는 경우 전체 실패로 볼지, degraded 결과를 허용할지 정해야 한다.
어떤 선택이든 “검색 인프라 미설정”을 “후보 없음”으로 반환해서는 안 된다. 후보 없음은 계획된 검색 채널이
정상 실행된 뒤 실제 hit가 0개일 때만 허용한다.

## 7. 이번 작업 범위

### 포함

- Issue Retrieval Agent의 내부 계약과 LangGraph 상태 흐름
- 검색 문서 projection
- 정확·문자열·벡터 검색 port
- Bug hit 결합, Issue 집계, 대표 Bug 선택, 순위 제한
- 실제 운영 adapter 또는 Clio Server API adapter 중 결정된 v1 경로
- embedding 모델·차원 호환성 검사
- 설정·일시 장애·정상 0건을 구분하는 오류 모델
- Fake 저장소·검색기로 독립 실행 가능한 테스트
- 기존 RM 전체 그래프에 실제 Retrieval Agent 연결
- 운영 설정과 데이터 준비 방법 문서화

### 제외

- RM의 LLM 비교·최종 정책 변경
- 실제 Issue 연결·생성
- Codebase Exploration Agent
- Issue root cause 분석
- 대규모 데이터용 ANN 인덱스 최적화
- 운영 품질이 확인되지 않은 로컬 hashing embedding을 실제 semantic model처럼 사용하는 것

## 8. 완료 기준

- 기본 `clio_agent`가 placeholder가 아닌 실제 Issue Retrieval Agent를 사용한다.
- 프로젝트가 다른 Bug/Issue는 후보에 섞이지 않는다.
- 현재 Bug와 제외 대상으로 정한 Issue가 후보에 들어오지 않는다.
- 강한 정확 신호, 문자열 유사도, 벡터 유사도가 정의된 방식으로 결합된다.
- 같은 Issue의 여러 Bug hit가 하나의 Issue 후보로 합쳐진다.
- 후보는 최대 5개, 대표 Bug는 후보당 최대 3개이며 순서가 결정적이다.
- 정상 0건과 기술 실패가 구분된다.
- 외부 DB·embedding API 없이 Fake로 전체 subgraph와 RM 연결 테스트가 가능하다.
- 실제 adapter의 설정 및 지연 생성/연결 동작을 검증한다.
- `pytest`, `ruff check .`, `ruff format --check .`가 통과한다.

## 9. 계획 단계에서 결정할 항목

다음 항목은 overview 확인 후 `02-plan.md`에서 대안과 추천안을 구체화한다.

1. Agent Graph의 데이터 접근 방식: PostgreSQL 직접 접근 / Clio Server API
2. 검색 단위: Bug 검색 후 Issue 집계 / Issue 문서 직접 검색 / 두 방식 병행
3. 대표 Bug 비교 데이터: 정규화 snapshot 저장 / 재정규화 / RM projection 변경
4. embedding provider·모델·dimension과 설정 소유권
5. 과거 Bug embedding 생성 및 모델 변경 시 재색인 정책
6. 정확·문자열·벡터 채널의 구체적 검색 방식
7. 검색 결과 결합 방식과 채널 가중치
8. 대표 Bug 선택 기준과 Issue 점수 집계 방식
9. 현재 Bug 및 이미 연결된 Issue의 제외 규칙
10. 일부 검색 채널 장애 시 실패 또는 degraded 결과 정책
11. 재시도·timeout·후보 pool 크기와 최종 top-k 설정
12. 실제 PostgreSQL/pgvector 경로의 테스트 및 품질 평가 방식
