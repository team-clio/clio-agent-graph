# Issue Retrieval Agent 구현 계획

`01-overview.md` 확인 완료. 이 문서는 Issue Retrieval Agent의 구현 단계와 사용자 결정 포인트
IR1~IR12를 담는다. 각 결정은 `03-decisions.md`에 기록하고, 결정에 따른 구현을 작은 커밋으로 나눈다.

## 1. 목표 구조

Issue Retrieval Agent는 NM이 만든 `NormalizedReport`를 검색 문서로 바꾸고, 기존 Bug를 여러 방식으로
검색한 뒤 Issue 후보로 집계하는 LangGraph subgraph다.

```text
START
  → build_search_query
  → search_bug_candidates
       ├─ exact signal search
       ├─ lexical search
       └─ vector search
  → fuse_bug_hits
  → aggregate_by_issue
  → hydrate_representative_bugs
  → rank_and_limit
  → END
```

검색 채널은 서로 독립적인 port로 두어 실제 PostgreSQL adapter와 테스트 Fake를 교체할 수 있게 한다.
Agent는 검색 실행, 결과 결합, 제외 규칙, 상한 검증과 오류 구분을 담당한다. RM은 완성된
`IssueCandidate`만 받아 후보의 동일성을 판단한다.

## 2. 구현 단계

### S1. 내부 검색 계약과 설정

- NM 결과를 검색 가능한 문자열과 exact signal로 바꾸는 `BugSearchQuery`
- 검색 채널이 반환하는 `BugSearchHit`
- Issue·대표 Bug hydration projection
- 채널 종류, 검색 이유, 데이터 준비 상태와 오류 계약
- 후보 pool, 최종 top-k, RRF 상수, timeout과 재시도 설정

관련 결정: **IR2, IR6, IR7, IR11**

### S2. 대표 Bug snapshot 계약

- RM 비교에 필요한 기존 Bug의 정규화 결과 보존 방식
- `bug_id`, `project_id`, 원본 BugReport 식별자와 정규화 snapshot의 관계
- 같은 Bug가 갱신될 때 snapshot과 검색 문서를 교체하는 규칙
- 대표 Bug 최대 3개 hydration

관련 결정: **IR3, IR5, IR8**

### S3. 검색 저장소와 embedding 경계

- Java interface와 비슷한 Python `Protocol`로 repository와 embedding model 정의
- PostgreSQL 연결의 지연 생성과 명시적인 설정 오류
- query embedding 생성
- 기존 embedding의 model·dimension 호환성 검사
- 검색용 snapshot/embedding upsert 또는 조회 adapter
- 테스트용 deterministic Fake

관련 결정: **IR1, IR4, IR5, IR12**

### S4. Hybrid Bug 검색

- `project_id`와 제외 ID를 모든 검색에 강제
- error type·error code·stack frame exact 검색
- 한글과 기술 식별자를 함께 다룰 수 있는 문자열 검색
- pgvector cosine 검색
- 채널별 후보 pool 제한과 결정적 정렬

관련 결정: **IR6, IR9, IR11**

### S5. 결과 결합과 Issue 집계

- 같은 Bug가 여러 채널에 나온 결과를 중복 제거
- 채널별 순위를 하나의 Bug retrieval score로 결합
- Bug hit를 연결된 Issue별로 집계
- Issue 크기가 큰 후보가 단순히 유리해지지 않도록 점수 보정
- Issue별 대표 Bug 최대 3개 선택
- 최종 Issue 최대 5개 및 동점 tie-breaker

관련 결정: **IR2, IR7, IR8, IR9**

### S6. LangGraph subgraph 교체

- 기존 callback placeholder를 실제 내부 state graph로 교체
- 검색 port와 embedding model을 builder에서 주입 가능하게 유지
- 기본 `clio_agent`에 운영 adapter 연결
- 정상 0건, 설정 오류, 외부 장애를 서로 다른 경로로 처리
- 기존 RM retry와 중복되지 않도록 재시도 책임 정리

관련 결정: **IR10, IR11**

### S7. 평가·문서·병합

- exact·lexical·semantic·혼합 검색 fixture
- 다른 프로젝트·현재 Bug·이미 연결된 Issue 제외 fixture
- 여러 Bug가 같은 Issue에 연결된 집계 fixture
- embedding model/dimension 불일치와 부분 인덱스 fixture
- PostgreSQL/pgvector 실제 경로 검증
- README, 환경변수와 데이터 준비 방법 갱신
- `04-result.md`와 개발 순서 갱신
- 전체 검사 후 `taek/issue-retrieval → taek/integration` `--no-ff` 병합

관련 결정: **IR10, IR12**

## 3. 결정 포인트

### IR1. Agent Graph의 데이터 접근 방식

#### (a) PostgreSQL 직접 접근

- Python Agent Graph가 `bugs`, `issue_bugs`, `issues`, `bug_embeddings`를 직접 조회한다.
- 현재 Clio Server README의 “같은 PostgreSQL에 직접 접근” 구조와 일치한다.
- 검색용 SQL과 schema 호환성을 Python도 관리해야 한다.
- Issue 연결·생성 같은 도메인 쓰기는 계속 Clio Server에만 둔다.

#### (b) Clio Server 검색 API

- Java 서버가 데이터 조회와 검색 API를 소유한다.
- Python은 HTTP 계약만 알면 된다.
- 서버에 embedding, exact, lexical, vector 검색과 hydration API를 새로 구현해야 하므로 검색 책임이 두
  프로젝트로 분산된다.

#### (c) 읽기는 DB, 검색 snapshot 쓰기는 Server API

- 소유권을 세밀하게 나눌 수 있다.
- 한 검색 기능이 DB와 HTTP 두 연결에 동시에 의존한다.

**추천: (a).** Agent Graph가 검색 관련 읽기와 AI 소유 테이블인 embedding/snapshot만 관리한다. `issues`,
`issue_bugs`, `bugs`는 읽기 전용으로 취급하고 실제 연결·생성은 Clio Server만 수행한다. repository Protocol로
SQL을 격리해 schema 변경 영향이 retrieval adapter 밖으로 퍼지지 않게 한다.

### IR2. 검색 단위

#### (a) 기존 Bug 검색 후 Issue 집계

- 실제 발생 사례의 오류 신호와 표현을 검색할 수 있다.
- 여러 Bug가 한 Issue에 묶이는 현재 모델과 일치한다.
- 집계·대표 Bug 선정 규칙이 필요하다.

#### (b) Issue 제목·요약을 직접 검색

- 데이터와 쿼리가 단순하다.
- Issue 요약이 짧거나 갱신되지 않으면 실제 오류 사례를 놓친다.

#### (c) Bug와 Issue를 각각 검색해 다시 결합

- Issue 설명과 실제 사례를 모두 사용할 수 있다.
- v1의 채널과 가중치가 지나치게 늘어나 평가가 어려워진다.

**추천: (a).** v1은 기존 Bug를 검색하고 `issue_bugs`를 통해 Issue별로 집계한다. Issue 제목·요약은
최종 후보 hydration과 RM 비교 문맥에만 사용한다. 운영 평가에서 Bug 검색이 놓치는 사례가 확인되면 Issue 직접
검색 채널을 추가한다.

### IR3. 대표 Bug 비교 데이터

#### (a) Bug별 `NormalizedReport` snapshot 저장

- 최초 NM 결과를 그대로 재사용해 과거 판단을 재현할 수 있다.
- 재검색 때 LLM을 호출하지 않는다.
- snapshot을 저장할 테이블과 수명 주기가 필요하다.

#### (b) 대표 `BugOccurrence`를 검색 때마다 NM으로 재정규화

- 새 테이블이 필요 없다.
- 후보마다 LLM 호출이 발생하고 모델·prompt 변경에 따라 과거 Bug 표현이 달라진다.
- retrieval 장애와 NM 장애가 한 실행에 결합된다.

#### (c) RM의 `RepresentativeBug`를 현재 `bugs` 컬럼 수준으로 축소

- 현재 DB만으로 즉시 조회할 수 있다.
- reproduction, environment, affected surface와 오류 코드가 사라져 RM 비교 품질과 자동 연결 조건이 약해진다.

**추천: (a).** 정규화 결과를 불변 JSON snapshot으로 저장하고 검색 문서가 어느 snapshot에서 생성됐는지 함께
추적한다. LLM 재실행은 명시적인 재정규화 작업일 때만 수행하고 기존 snapshot을 조용히 덮어쓰지 않는다.

### IR4. Embedding provider와 설정

#### (a) `CLIO_MODEL`과 같은 chat model 설정을 재사용

- 설정 수가 적다.
- chat model과 embedding model은 API와 dimension이 다르므로 잘못된 결합이다.

#### (b) 전용 `EmbeddingModel` Protocol과 `CLIO_EMBEDDING_MODEL`

- provider를 교체할 수 있고 model·dimension을 명시적으로 검증할 수 있다.
- 운영 설정이 하나 추가된다.

#### (c) 로컬 hashing embedding을 기본값으로 사용

- API key 없이 항상 동작한다.
- hash 충돌 기반 점수는 의미 유사도를 대표하지 않으므로 실제 중복 검색 품질을 오해하게 만든다.

**추천: (b).** query와 저장 embedding 모두 같은 전용 model ID와 dimension을 사용한다. 실제 adapter는 최초
벡터 검색 때 지연 생성하고, 테스트 Fake만 결정적인 벡터를 반환한다. 운영 환경에 의미 embedding 설정이 없으면
로컬 가짜 모델로 숨기지 않고 설정 오류를 낸다.

### IR5. Snapshot·embedding 생성 시점과 재색인

#### (a) Bug 생성 직후 동기 생성

- 다음 report부터 바로 검색할 수 있다.
- NM·embedding provider 장애가 Bug 수집 요청까지 실패시킬 수 있다.

#### (b) 별도 indexing job에서 비동기 생성

- Bug 수집과 AI provider 장애를 분리한다.
- 생성 직후 잠시 검색되지 않는 eventual consistency가 생긴다.
- job 상태·재시도·backfill 실행 경계가 필요하다.

#### (c) 검색 시 lazy 생성

- 실제 검색된 Bug에만 비용을 쓴다.
- embedding이 없는 Bug는 vector 검색으로 발견할 수 없어서 생성 기회 자체를 얻기 어렵다.

**추천: (b).** Clio Server 또는 상위 Supervisor가 NM 완료 결과를 저장한 뒤 indexing job을 요청한다. 저장
레코드에는 `model`, `dimension`, `embedded_at`, 검색 문서 버전과 snapshot 버전을 둔다. 모델이 바뀌면 새 버전으로
backfill하고, 완료 전까지 기존 index를 유지한 뒤 활성 버전을 전환한다. 이번 저장·retrieval 작업에서는 indexer
service와 backfill 가능한 port까지 구현하고 실제 작업 큐 배선은 서버 연동 작업에 남긴다.

### IR6. 검색 채널의 구체적 방식

#### 정확 신호

- 대소문자와 불필요한 공백을 정규화한 `error_type`, 오류 코드, application stack frame의 exact match
- exact 신호가 없는 입력은 정상적으로 이 채널의 hit 0건

#### 문자열

선택지는 PostgreSQL full-text search와 `pg_trgm` 유사도다. 기본 PostgreSQL 사전은 한글 문장에 바로 쓰기
어렵고 기술 식별자·짧은 오류 메시지도 많다.

#### 벡터

- `bug_embeddings.embedding::vector <=> query::vector` cosine distance
- model과 dimension이 같은 활성 index만 검색

**추천:** exact + `pg_trgm` + pgvector의 세 채널을 사용한다. 문자열 검색 문서는 NM 필드를 고정된 순서와
label로 직렬화하고, 민감한 `raw_payload`는 포함하지 않는다. `pg_trgm` 확장은 DB 초기화에 추가하되, SQL이 없는
Fake adapter에서도 같은 orchestration을 검증한다.

### IR7. 검색 결과 결합 방식

#### (a) 원점수 가중합

- 직관적이다.
- exact, trigram, cosine 점수 분포가 달라 가중치가 데이터셋마다 흔들린다.

#### (b) Reciprocal Rank Fusion(RRF)

- 각 채널의 순위만 사용해 점수 범위 차이에 강하다.
- 절대 유사도 차이를 일부 잃는다.

#### (c) 한 채널 우선 후 나머지 fallback

- 설명하기 쉽다.
- 서로 보완해야 하는 hybrid 검색이 사실상 단계식 검색이 된다.

**추천: (b), weighted RRF.** exact 채널의 비중을 semantic·lexical보다 높이고, 이론상 최대 RRF 점수로
나눠 `retrieval_score`를 0~1로 정규화한다. 각 후보의 `retrieval_reasons`에는 기여한 채널과 실제 일치 신호를
남긴다. 구체적인 weight와 RRF 상수는 설정 객체에 두고 fixture 평가로 기본값을 고정한다.

### IR8. Issue 점수와 대표 Bug 선정

#### (a) Issue에 속한 모든 Bug 점수 합산

- 여러 hit가 나온 Issue가 높아진다.
- Bug가 많은 오래된 Issue가 과도하게 유리하다.

#### (b) 최고 Bug 점수만 사용

- Issue 크기에 영향받지 않는다.
- 같은 Issue의 여러 독립 hit가 주는 추가 확신을 버린다.

#### (c) 최고 점수 + 제한된 추가 hit 보너스

- 최고 사례를 중심으로 하되 여러 hit의 지지를 반영한다.
- bonus 상한과 계산 규칙이 필요하다.

**추천: (c).** 최고 Bug fused score를 기본으로 하고, 두 번째·세 번째 hit에만 감소하는 작은 보너스를 더한 뒤
1.0으로 제한한다. 대표 Bug는 fused score 내림차순으로 최대 3개 선택한다. 동점이면 강한 exact 신호 수,
`occurrence_count`, `bug_id` 순서로 결정한다. 최근성은 같은 원인의 오래된 Issue를 놓칠 수 있어 기본 relevance
점수에는 넣지 않는다.

### IR9. 제외 규칙

#### (a) 현재 `bug_id`만 제외

- 자기 자신이 후보가 되는 것을 막는다.
- 현재 Bug가 이미 연결된 Issue가 다른 Bug hit로 다시 나올 수 있다.

#### (b) 현재 Bug와 현재 Bug가 이미 연결된 모든 Issue 제외

- 재실행 시 기존 연결을 새 후보처럼 평가하지 않는다.
- 기존 연결의 적절성을 재검증하는 용도로는 사용할 수 없다.

#### (c) 요청에 제외 목록을 추가해 호출자가 결정

- 재검증 같은 다양한 실행을 지원한다.
- 기본 호출자가 올바른 제외 목록을 만들 책임이 생긴다.

**추천: (b).** 현재 RM 계약과 기존 테스트는 `bug_id`를 이용해 이미 연결된 Issue를 제외하는 것을 전제로 한다.
재검증은 별도 목적의 그래프나 명시적 옵션으로 후속 추가한다. 모든 SQL에서 `project_id`와 제외 조건을 repository
최하단에 강제해 상위 노드 실수로 다른 프로젝트 데이터가 섞이지 않게 한다.

### IR10. 일부 검색 채널 장애 정책

#### (a) 한 채널이라도 기술적으로 실패하면 전체 실패

- “Hybrid 검색 완료”의 의미가 항상 같다.
- exact 결과가 충분해도 embedding provider 장애로 전체 RM이 멈춘다.

#### (b) 남은 채널로 degraded 결과 반환

- 가용성이 높다.
- 현재 응답 계약에는 어떤 채널이 실패했는지 공개 경고가 없고, 0건을 신규 Issue로 오해할 수 있다.

#### (c) exact·lexical은 필수, vector만 선택적

- provider 장애에 강하다.
- 실행마다 검색 품질이 달라질 수 있다.

**추천: (a)를 v1 기본값으로 사용.** 구성된 세 채널 중 기술 실패가 있으면 한 번 재시도 후 구분 가능한 예외로
실패시킨다. 특정 기존 Bug에 compatible embedding이 없는 것은 기술 실패가 아니라 그 Bug의 vector hit가 없는
상태로 본다. 활성 index 전체가 준비되지 않았거나 query embedding을 만들지 못한 상태는 설정·준비 오류다.
향후 degraded mode를 추가하려면 응답에 경고와 실행된 채널 목록을 먼저 계약으로 추가한다.

### IR11. 재시도·timeout·후보 상한

#### 재시도

- 각 외부 operation(DB query, embedding 호출)은 일시 실패에 한 번 재시도
- 설정 오류, 계약 검증 오류, model/dimension 불일치는 재시도하지 않음
- subgraph 전체를 다시 실행하는 중복 retry는 제거

#### 후보 상한

- 채널별 Bug hit pool: 기본 50개
- fusion 뒤 Bug: 기본 50개
- hydration할 Issue pool: 기본 20개
- 최종 Issue: 기존 RM 계약대로 5개
- Issue별 대표 Bug: 기존 RM 계약대로 3개

#### timeout

- DB와 embedding adapter에 별도 timeout을 설정
- 구체적인 초 단위 기본값은 provider와 실제 DB 연결 방식을 확정한 뒤 설정 파일에 기록

**추천:** 위 기본 상한과 operation별 1회 재시도를 사용한다. 전체 subgraph의 무조건 재실행보다 어느 operation이
실패했는지 보존하고, 성공한 embedding API 호출까지 반복하지 않는 편이 안전하다.

### IR12. 테스트와 검색 품질 평가

#### (a) Fake·단위 테스트만

- CI가 빠르고 외부 인프라가 필요 없다.
- 실제 SQL cast, extension, 배열 dimension 오류를 잡지 못한다.

#### (b) 모든 CI에서 실제 PostgreSQL+pgvector 실행

- 운영 SQL을 항상 검증한다.
- Docker 의존성과 실행 시간이 늘어난다.

#### (c) 단위 테스트 + opt-in PostgreSQL 통합 테스트 + 고정 retrieval 평가셋

- 일반 CI는 빠르게 유지하고 실제 adapter를 별도 gate에서 검증한다.
- opt-in 테스트를 실행하지 않으면 SQL 회귀를 놓칠 수 있다.

**추천: (c).** 기본 `pytest`는 Fake로 query projection, fusion, aggregation, 오류 정책과 전체 RM 연결을 검증한다.
실제 PostgreSQL+pgvector 통합 테스트는 명시적인 marker와 환경 설정으로 제공하고, 배포 전 gate에서 실행한다.
또한 정답 Issue가 포함된 고정 fixture에 대해 Recall@5와 MRR을 계산한다. 초기 threshold를 품질 보장처럼
단정하지 않고 결과를 `04-result.md`에 기준선으로 기록한다.

## 4. 추천 결정 요약

| ID | 주제 | 추천 |
|---|---|---|
| IR1 | 데이터 접근 | Python이 PostgreSQL 직접 접근, 도메인 테이블 읽기 전용 |
| IR2 | 검색 단위 | Bug 검색 후 Issue 집계 |
| IR3 | 대표 Bug 데이터 | 불변 `NormalizedReport` snapshot 저장 |
| IR4 | embedding | 전용 Protocol + `CLIO_EMBEDDING_MODEL`, Fake는 테스트 전용 |
| IR5 | indexing | 비동기 job, 버전 기반 backfill·활성 index 전환 |
| IR6 | 검색 채널 | exact + `pg_trgm` + pgvector |
| IR7 | 결합 | exact 가중치가 높은 weighted RRF |
| IR8 | Issue 집계 | 최고 Bug 점수 + 제한된 추가 hit 보너스 |
| IR9 | 제외 | 현재 Bug와 이미 연결된 Issue 제외, project 필터 강제 |
| IR10 | 부분 장애 | v1은 필수 채널 하나라도 실패하면 전체 실패 |
| IR11 | 실행 제한 | operation별 1회 retry, 50 Bug → 20 Issue → 최종 5 Issue |
| IR12 | 검증 | Fake 기본 + opt-in pgvector 통합 + Recall@5/MRR fixture |

## 5. 예상 내부 계약

구체적인 이름과 필드는 결정 후 확정하지만 역할은 다음과 같다.

```text
BugSearchQuery
  - project_id
  - bug_id
  - search_text
  - error_types
  - error_codes
  - stack_frames
  - embedding_model

BugSearchHit
  - bug_id
  - channel
  - rank
  - raw_score
  - matched_signals

IssueHydration
  - issue_id
  - title / summary / status
  - Bug snapshot 목록
  - current Bug와 연결 여부

IssueRetrievalDiagnostics (내부 state)
  - 실행 채널
  - channel별 hit 수
  - 제외된 Bug·Issue 수
  - index model·dimension
```

진단 정보는 기본 공개 응답에 넣지 않고 로그·trace와 내부 state에 둔다. degraded mode를 추가할 때는 사용자에게
검색 품질 저하를 숨기지 않도록 공개 경고 계약을 별도로 결정한다.

## 6. 테스트 계획

- 동일 error type + error code + frame의 exact 후보
- 한글 현상 설명과 기술 식별자가 섞인 lexical 후보
- 표현은 다르지만 의미가 같은 vector 후보
- 세 채널에 중복 등장한 Bug의 RRF 중복 제거
- 여러 Bug hit가 하나의 Issue로 집계되는 경우
- Bug가 많은 Issue가 단순 합산으로 과대 평가되지 않는지 검증
- 서로 다른 프로젝트의 동일 오류가 제외되는지 검증
- 현재 Bug와 이미 연결된 Issue 제외
- 연결되지 않은 Bug hit 제외
- 대표 Bug 3개와 Issue 5개 상한 및 결정적인 동점 순서
- embedding model·dimension 불일치 제외와 활성 index 미준비 오류
- 정상 검색 0건과 DB·provider 기술 실패 구분
- 일시 실패 1회 재시도와 영구 실패
- 설정 오류가 재시도되지 않는지 검증
- 실제 adapter가 import 시 DB 연결·embedding model을 만들지 않는지 검증
- Fake repository·embedding model을 주입한 Retrieval subgraph 및 전체 RM 입출력
- opt-in PostgreSQL에서 `pg_trgm`, pgvector cosine query와 project/exclusion 조건 검증
- 고정 평가셋 Recall@5·MRR 계산

## 7. 예상 커밋 단위

```text
docs: Issue Retrieval Agent 구현 계획
feat: retrieval 검색 query와 hit 계약
feat: Bug 정규화 snapshot과 index 계약
feat: embedding과 검색 repository port
feat: exact lexical vector 검색 adapter
feat: retrieval rank fusion과 Issue 집계
feat: Issue Retrieval LangGraph subgraph 연결
test: retrieval 실패 정책과 전체 RM fixture
test: pgvector 통합과 retrieval 평가 도구
docs: Issue Retrieval Agent 결과와 운영 설정
merge: Issue Retrieval Agent 작업
```

결정 하나가 여러 독립 코드 변경을 요구하면 더 작은 커밋으로 나눈다. 각 커밋은 가능한 한 테스트와 lint가
통과하는 상태로 유지한다.

## 8. 검사 기준

```bash
pytest
ruff check .
ruff format --check .
```

PostgreSQL 통합 테스트는 별도 marker로 실행한다. 정확한 실행 명령은 DB adapter와 테스트 환경 결정 후 README와
`04-result.md`에 기록한다.

## 9. 브랜치 흐름

사용자가 지정한 통합 브랜치 흐름을 따른다.

```text
taek/integration
└─ taek/issue-retrieval
```

완료 후 `taek/issue-retrieval`을 `taek/integration`에 `--no-ff`로 병합한다. 사용자의 별도 지시 전에는
`main`에 병합하지 않는다.
