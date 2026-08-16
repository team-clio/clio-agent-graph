# RAG Metadata Filter 개선 실험 개요

## 1. 배경

PCM 검색은 graph가 전달한 `ProjectContextSnapshot`의 `project_id`, `pcm_revision`,
`knowledge_index_revision`을 기준으로 검색 범위를 고정한다. Agent가 호출하는
`search_project_knowledge`에는 추가로 `knowledge_types`가 노출되어 있다.

하지만 현재 PostgreSQL hybrid 검색은 keyword와 vector 경로에서 각각 `limit * 4`개의 후보를 먼저
가져오고 RRF로 융합한 뒤, Python에서 `knowledge_types`가 맞지 않는 결과를 제거한다. 특정 유형이
전체 corpus에서 적을수록 관련 결과가 후보 제한 밖으로 밀린 뒤 사후 필터링되어 다음 문제가 생길 수
있다.

- 필터 범위 안에 정답이 있어도 반환 수가 `limit`보다 작아진다.
- filtered Recall과 MRR이 후보 overfetch 크기에 불필요하게 의존한다.
- 관련 없는 후보를 DB에서 읽고 융합하므로 검색·context 비용이 증가한다.
- keyword, vector, stale-index fallback의 필터 적용 시점과 동작이 다르다.

`KnowledgeDocument.sources`에는 `source_type`, `source_id`, `source_revision`, `locator`가 저장되고,
문서 source에는 heading path, repository source에는 path와 line 범위가 존재한다. 그러나 현재 검색
계약은 이 metadata를 filter로 표현하지 못한다. `pcm_document_revisions.source_metadata`에는 자유 형식
JSONB가 저장되지만 Knowledge·chunk 검색 색인으로 전달되는 정규화 계약은 아직 없다.

이번 실험은 metadata를 embedding 내용에 섞는 실험이 아니라, **검색 가능한 후보 집합을 구조화된
조건으로 안전하게 제한하는 방법**을 비교한다.

## 2. 문제 정의

Metadata filter는 vector similarity나 keyword relevance가 표현하기 어려운 명시적 범위를 지정한다.
예를 들어 다음 질의는 의미 유사도만으로 처리하는 것보다 구조화된 범위가 필요하다.

- architecture Knowledge만 검색한다.
- 특정 repository에서 추출된 Knowledge만 검색한다.
- `src/payment/` 경로에 근거가 있는 Knowledge만 검색한다.
- 특정 문서 또는 heading 아래의 requirement만 검색한다.

필터는 결과를 더 정확하게 만들 수 있지만 잘못 적용하면 정답을 후보 집합에서 완전히 제거한다. 따라서
다음 두 문제를 함께 해결해야 한다.

1. **Filtered retrieval correctness**: 필터를 만족하는 가장 가까운 Top-K를 빠짐없이 반환한다.
2. **Filter selection correctness**: Agent 또는 query parser가 필요한 필터만 선택하고 불확실할 때
   올바르게 abstain한다.

Metadata filter는 접근 제어와 같지 않다. Snapshot·project·허용 source처럼 신뢰 경계가 정한 범위는
반드시 강제하지만, 검색 품질을 위한 `knowledge_type`·path 필터는 잘못 선택될 수 있는 relevance
조건이다. 이번 실험 결과를 ACL 구현으로 간주하지 않는다.

## 3. 목표

1. 지원 필드와 논리 연산이 명시된 typed filter 계약을 정의한다.
2. keyword, vector, fallback에서 같은 의미의 필터를 후보 생성 전에 적용한다.
3. restrictive filter에서도 가능한 경우 요청한 Top-K를 채우고 정답 Recall을 보존한다.
4. 필터가 없는 검색과 snapshot·citation provenance를 회귀시키지 않는다.
5. 필터 선택 오류, 검색 품질, query latency와 index 비용을 함께 측정한다.
6. 명시적 필터와 LLM이 추론한 필터를 분리해 각각의 효용과 위험을 비교한다.

구체적인 filter 필드, 저장 구조, ANN 보완 방식은 이 개요에서 확정하지 않고 후속 계획에서 선택한다.

## 4. 현재 Metadata와 신뢰 경계

| 구분 | 현재 위치 | 소유자 | 실험에서의 의미 |
|---|---|---|---|
| `project_id` | `ProjectContextSnapshot` | graph/runtime | 항상 강제하는 hard scope |
| `pcm_revision` | `ProjectContextSnapshot` | graph/runtime | 항상 강제하는 hard scope |
| active index generation | PCM project/index | PCM service | 현재 snapshot과 맞는 vector generation만 허용 |
| repository commit | snapshot 및 source revision | graph/ingestion | Agent가 임의로 변경할 수 없는 provenance |
| `knowledge_type` | Knowledge revision | ingestion/model, allowlist | 현재 Agent가 선택 가능한 relevance filter |
| `source_type` | `SourceReference` | ingestion | document/repository/resolved issue 범위 후보 |
| `source_id` | `SourceReference` | ingestion | 특정 문서·repository·issue 범위 후보 |
| `source_revision` | `SourceReference` | ingestion/snapshot | provenance 검증용, 일반 Agent filter 여부는 미정 |
| document heading | source locator 및 chunk heading | parser/chunker | exact 또는 prefix filter 후보 |
| repository path·line | source locator | repository ingestion | path prefix 후보, line range 검색은 후순위 |
| `source_metadata` | document revision JSONB | 외부 입력 | 아직 검색 계약이 없으므로 v1 직접 노출에 주의 |

`project_id`, snapshot revision, active generation과 repository commit은 모델이 선택하거나 완화할 수 없는
강제 범위로 유지한다. Agent가 선택 가능한 필드는 별도의 allowlist로 제한한다.

## 5. 자료 조사와 적용 시사점

### 5.1 Pre-filter와 Post-filter

[Weaviate의 filtered search 문서](https://weaviate.io/developers/weaviate/concepts/filtering)는 vector
검색 뒤 결과를 제거하는 post-filter가 반환 개수를 예측하기 어렵고 restrictive filter에서 정답을 전혀
얻지 못할 수 있다고 설명한다. 반대로 eligible ID 집합을 먼저 만든 뒤 검색하는 pre-filter는 결과가
필터와 겹치도록 보장한다.

Clio의 현재 `knowledge_types` 처리는 application-level post-filter에 가깝다. 최소 후보는 keyword와
vector SQL 모두에 같은 predicate를 넣는 pre-filter pushdown이다. 다만 PostgreSQL 쿼리의 논리적
`WHERE`와 ANN index 내부 탐색이 완전히 같은 의미는 아니므로 pgvector 동작을 별도로 검증해야 한다.

### 5.2 pgvector의 Filtered ANN 제약

[pgvector 공식 문서](https://github.com/pgvector/pgvector)는 approximate index 검색에서 filter가 index
scan 이후 적용될 수 있어 결과가 부족해질 수 있다고 명시한다. pgvector 0.8.0 이상은 원하는 결과 수를
채우거나 탐색 상한에 도달할 때까지 더 탐색하는 iterative index scan을 제공한다. 공식 문서는 또한
일반 B-tree index, 낮은 cardinality 값별 partial HNSW index, 다수 값일 때 partitioning을 검토하고,
approximate 결과를 exact search와 비교해 recall을 모니터링할 것을 권한다.

Clio의 vector HNSW index는 `pcm_chunk_embeddings.embedding`에 있고 필터 metadata는 join 대상인
Knowledge revision과 chunk/source에 분산되어 있다. SQL predicate를 추가한 것만으로 충분한 후보가
반환되는지 `EXPLAIN (ANALYZE, BUFFERS)`와 exact filtered Top-K 비교로 확인해야 한다. 필요한 경우 다음
후보를 비교한다.

- iterative scan과 `hnsw.ef_search` 조정
- 단계적으로 후보 수를 늘리는 adaptive overfetch
- 매우 좁은 필터에서는 filtered subset exact scan
- 자주 쓰는 저 cardinality metadata의 denormalization·partial index·partitioning

### 5.3 Filter-aware Vector Index 연구

[ACORN](https://doi.org/10.1145/3654923)은 vector와 structured predicate를 함께 검색할 때 일반 HNSW의
filtered subgraph가 단절되거나 비효율적으로 탐색되는 문제를 다룬다. 임의 predicate에서도 filter를
통과하는 이웃으로 탐색을 확장하는 방식이며, filter와 vector가 낮게 상관될 때의 성능 문제를 강조한다.

[Filtered-DiskANN](https://dl.acm.org/doi/10.1145/3543507.3583552)은 label filter를 고려한 ANN graph 구성과
탐색을 다룬다. 두 논문을 Clio에 직접 구현하는 것은 이번 실험 범위를 넘지만, 다음 benchmark 설계의
근거로 사용한다.

- filter selectivity를 여러 구간으로 나누어 측정한다.
- vector relevance와 metadata가 잘 맞는 경우와 무관한 경우를 분리한다.
- 필터를 만족하는 exact Top-K를 기준으로 ANN recall을 계산한다.
- 단일 filter뿐 아니라 여러 metadata 조합에서 graph 탐색이 무너지지 않는지 확인한다.

### 5.4 Metadata Index와 저장 형태

[PostgreSQL JSONB 문서](https://www.postgresql.org/docs/17/datatype-json.html)는 `jsonb_ops`와
`jsonb_path_ops` GIN index가 지원하는 연산과 유연성·성능 차이를 설명한다.
[Qdrant의 payload index 문서](https://qdrant.tech/documentation/manage-data/indexing/)도 실제로 필터하는
필드만 typed index로 만들고, cardinality 추정치를 query planning에 사용하는 방식을 제시한다.

Clio에서 자유 형식 `sources` JSONB 전체에 하나의 범용 GIN index를 추가하는 방법과 자주 쓰는
`source_type/source_id/path`를 정규화하는 방법을 모두 후보로 둔다. 특히 하나의 Knowledge에 여러
source가 있으므로 `source_type`과 `source_id`가 **같은 SourceReference에서 동시에 일치해야 하는지**를
계약으로 고정해야 한다. 독립적인 JSON 조건이 서로 다른 source 원소에 매칭되는 오류를 허용하면 안 된다.

### 5.5 Query에서 Filter 추출

[LangChain SelfQueryRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/self_query/base/SelfQueryRetriever)는
LLM이 자연어 질의를 semantic query와 structured metadata filter로 분해하는 대표적인 방법이다.
[Multi-Meta-RAG](https://arxiv.org/abs/2406.13213)은 query에서 추출한 source metadata로 database를
필터링해 multi-hop 검색을 개선하는 방식을 제안한다.

Clio에는 이미 Agent tool의 typed `knowledge_types` 인자가 있으므로 바로 범용 self-query 언어를
도입할 필요는 없다. 다음 세 후보를 분리해 비교한다.

1. graph 또는 사용자가 명시적으로 제공한 filter만 사용한다.
2. Agent가 allowlist 안의 typed filter를 tool argument로 선택한다.
3. 별도 query parser가 semantic query와 filter를 structured output으로 생성한다.

모델이 추론한 filter는 잘못된 범위 축소 가능성이 있으므로 confidence 숫자만 신뢰하지 않는다. 필터를
선택할 근거가 없을 때 `null`을 반환하는 abstention, 허용 값 검증, 0건 또는 낮은 coverage일 때의 제한적
relaxation을 함께 평가한다. Hard scope는 어떤 경우에도 완화하지 않는다.

## 6. Typed Filter 계약 후보

v1은 임의 SQL, JSONPath, 재귀 Boolean expression을 받지 않고 업무상 필요한 필드만 명시한다.

```text
KnowledgeSearchFilter
  knowledge_types?: tuple[KnowledgeType, ...]
  source_types?: tuple[SourceType, ...]
  source_ids?: tuple[str, ...]
  repository_path_prefixes?: tuple[str, ...]
  document_heading_prefixes?: tuple[tuple[str, ...], ...]
```

기본 의미 후보는 다음과 같다.

- 같은 필드의 여러 값은 OR로 처리한다.
- 서로 다른 필드는 AND로 처리한다.
- source 관련 필드가 함께 주어지면 하나 이상의 **동일 source 원소**가 모든 source 조건을 만족해야 한다.
- `None`은 해당 필터를 적용하지 않는다는 의미다.
- 빈 목록은 허용하지 않거나 명시적인 validation error로 처리한다. `None`과 빈 결과 집합을 혼동하지 않는다.
- path는 정규화된 repository-relative POSIX path만 허용하고 `..`, 절대 경로와 비정상 prefix를 거부한다.
- heading은 문자열 포함 검색이 아니라 정규화된 heading path의 exact/prefix 의미를 사용한다.
- 값 개수, 문자열 길이와 filter 조합 수에 상한을 둔다.

Filter에는 출처도 기록할 수 있다.

```text
filter_origin = graph | explicit | agent | query_parser
```

`filter_origin`은 SQL 의미를 바꾸지 않지만, relaxation 가능 여부와 평가 slice를 구분하는 데 사용한다.

## 7. 검색 전략 후보

| 구분 | 전략 | 목적 | 주요 위험 |
|---|---|---|---|
| 기준선 | `limit * 4` 후보 생성 후 Python post-filter | 현재 동작 측정 | 결과 부족과 Recall 손실 |
| 후보 A | keyword·vector SQL predicate pushdown | 필터 밖 후보를 ranking 전에 제거 | HNSW 내부 탐색은 여전히 부족할 수 있음 |
| 후보 B | 후보 A + adaptive overfetch | 요청 Top-K가 찰 때까지 후보 확대 | latency와 DB 호출 수 증가 |
| 후보 C | 후보 A + pgvector iterative scan | 단일 ANN query에서 추가 탐색 | 버전·planner·scan 상한 의존 |
| 후보 D | selectivity 기반 exact/ANN 전환 | 매우 좁은 subset의 정확도 보존 | cardinality 추정과 분기 복잡도 |
| 후보 E | hot metadata 정규화·index·denormalization | filter와 ANN의 실행계획 개선 | schema·write amplification 증가 |
| 후보 F | 저 cardinality 값별 partial HNSW 또는 partition | 반복되는 고정 범위 검색 최적화 | index 수와 운영 복잡도 증가 |
| 후보 G | Agent/self-query filter + 제한적 relaxation | 자연어 범위 자동 추출 | 잘못된 필터가 정답을 제거 |

후보 A는 correctness의 최소 조건이다. B, C, D는 filtered ANN의 결과 부족을 해결하는 대안으로 먼저
개별 비교하고, E와 F는 corpus 규모와 실행계획상 필요성이 확인될 때만 검토한다. G는 저장·검색
최적화와 별도의 filter-selection 실험으로 분리한다.

## 8. 검색 경로별 동일성 계약

### 8.1 Keyword 검색

- snapshot 조건과 typed filter를 chunk candidate SQL에 함께 적용한다.
- filter를 통과한 후보만 keyword score와 Top-K 제한에 참여한다.
- source filter join으로 한 Knowledge의 여러 chunk가 중복 증폭되지 않도록 `EXISTS` 또는 동등한
  semi-join 의미를 사용한다.

### 8.2 Vector 검색

- keyword와 완전히 같은 filter 의미를 사용한다.
- filtered exact Top-K를 oracle로 두고 HNSW 결과의 Recall을 측정한다.
- iterative scan, overfetch 또는 exact 전환 뒤에도 cosine distance 순서를 검증한다.
- 요청 수보다 결과가 적다면 실제 eligible row 부족인지 ANN 탐색 중단인지 구분해 기록한다.

### 8.3 RRF와 Knowledge 집계

- 각 retrieval 경로가 filter를 적용한 뒤 순위를 만들고, 그 결과만 RRF로 융합한다.
- 동일 Knowledge의 여러 chunk는 현재처럼 Knowledge 단위로 집계하되 filter를 만족한 chunk/source의
  provenance를 잃지 않는다.
- vector와 keyword 중 한 경로만 필터 밖 결과를 포함하는 상태를 허용하지 않는다.

### 8.4 Stale-index Fallback와 In-memory 구현

- canonical Markdown fallback과 in-memory PCM도 PostgreSQL과 동일한 typed filter 계약을 구현한다.
- fallback이 느리더라도 hard scope와 filter correctness를 완화하지 않는다.
- 정상 0건, ANN 탐색 부족, stale-index fallback, validation error와 DB 오류를 서로 다른 상태로 기록한다.

## 9. 저장·Index 후보

### 9.1 Knowledge Type

`knowledge_type`은 정규화된 열이고 값 종류가 적으므로 가장 먼저 SQL pushdown과 일반 B-tree/복합
snapshot index 효과를 확인한다. corpus 규모와 query pattern이 정당화할 때만 type별 partial HNSW를
검토한다.

### 9.2 Source Metadata

두 저장 전략을 비교 후보로 둔다.

1. `sources` JSONB에 containment/jsonpath predicate와 GIN index를 사용한다.
2. `(project_id, knowledge_id, knowledge_revision, source_ordinal, source_type, source_id,
   source_revision, path, heading_path, ...)` 형태의 정규화된 source 검색 테이블을 둔다.

JSONB는 migration 범위가 작지만 같은 source 원소의 복합 조건, path prefix와 planner 추정이 복잡하다.
정규화 테이블은 계약과 index가 명확하지만 commit·revision 변경 시 쓰기와 무결성 관리가 늘어난다.

### 9.3 Chunk·Embedding Denormalization

HNSW index가 있는 embedding relation까지 자주 쓰는 filter key를 복제하면 ANN scan의 predicate 적용이
단순해질 수 있다. 반면 source가 여러 개인 Knowledge를 chunk row에 배열로 복제하면 중복과 갱신 비용이
커진다. 실제 `EXPLAIN`과 benchmark로 join 방식의 문제가 확인되기 전에는 적용을 확정하지 않는다.

### 9.4 자유 형식 Source Metadata

`pcm_document_revisions.source_metadata`는 schema가 정해지지 않았고 현재 Knowledge source/chunk와 직접
연결된 검색 필드가 아니다. v1에서는 그대로 Agent에게 노출하지 않는다. 필요한 field가 확인되면 ingest
시점에 검증·정규화한 allowlisted metadata로 승격하는 별도 계획을 세운다.

## 10. Benchmark 계약

### 10.1 평가 사례

같은 query에 대해 filter 유무의 정답 집합을 모두 정의한다.

- 필터 없는 일반 질문
- 하나의 `knowledge_type`이 정답 범위를 좁히는 질문
- 여러 type 중 하나를 허용하는 질문
- 특정 source type/source ID가 필요한 질문
- repository path와 document heading prefix 질문
- 여러 source를 가진 Knowledge의 same-source 의미를 검증하는 질문
- 복수 필드 AND와 필드 내부 OR 조합
- filter를 만족하는 문서는 있으나 vector query와 metadata의 상관이 낮은 질문
- filter 결과가 0건이어야 하는 질문
- Agent/query parser가 filter를 선택하지 않아야 하는 모호한 질문
- 잘못 추론한 soft filter를 완화했을 때만 정답이 복구되는 질문

Filter selectivity는 최소한 다음 bucket으로 나눈다. 경계값은 corpus 분포를 확인한 뒤 계획에서 고정한다.

- unfiltered 또는 매우 넓은 범위
- 10~50%
- 1~10%
- 1% 미만
- eligible row 0건

### 10.2 Retrieval 지표

- filtered Recall@5·Recall@8
- filtered MRR와 nDCG@K
- 필터를 만족하는 exact Top-K 대비 ANN Recall@K
- 필터 밖 결과 leakage 비율
- 요청 `limit` 충족률
- 필터로 인한 false-exclusion rate
- 필터가 없는 기존 질의의 비회귀

### 10.3 Filter Selection 지표

- filter field/value exact match
- 불필요한 필터를 만들지 않는 abstention accuracy
- hard scope 변경 시도 거부율
- relaxation으로 정답이 복구된 비율
- relaxation으로 원하지 않는 범위가 유입된 비율
- 명시적·Agent·query parser origin별 지표

### 10.4 운영 지표

- keyword·vector 경로별 eligible row와 실제 scan row 수
- initial candidate 수와 adaptive retry 횟수
- 검색 P50/P95와 timeout 비율
- `EXPLAIN (ANALYZE, BUFFERS)`의 index 선택, rows removed by filter와 buffer read
- exact/ANN 전환 비율과 iterative scan 상한 도달률
- SQL 후보 수, 최종 context 문자 수와 LLM 입력 token
- index 크기, build/backfill 시간과 write amplification

정확성 gate를 먼저 통과한 후보만 latency와 비용을 비교한다.

## 11. 실험 통제

1. corpus, PCM revision, index generation과 commit SHA를 고정한다.
2. query, embedding model, chunking, keyword scoring, RRF와 최종 `limit`을 고정한다.
3. 한 번에 filter 적용 또는 ANN 보완 전략 하나만 변경한다.
4. exact filtered search를 정답 oracle로 기록한다.
5. cold/warm cache와 반복 횟수를 구분한다.
6. 전체 평균뿐 아니라 filter field, selectivity, correlation, origin slice를 함께 보고한다.
7. 유망한 단일 후보만 통합해 조합 효과를 다시 측정한다.

## 12. 범위

### 포함

- `KnowledgeSearchRequest`의 typed filter 모델
- graph hard scope와 relevance filter의 분리
- keyword, vector, stale-index fallback, in-memory 구현의 의미 일치
- 가능한 filter의 candidate-generation pushdown
- pgvector filtered ANN의 overfetch·iterative·exact 전환 비교
- source JSONB, 정규화 열·테이블과 관련 index 검토
- filter serialization, validation, provenance와 snapshot 테스트
- 명시적·Agent/self-query filter 선택 실험 후보
- 품질·leakage·지연·index 비용 benchmark

### 제외

- 자유 형식 SQL·JSONPath 또는 범용 재귀 filter DSL
- 사용자별 ACL과 권한 관리 시스템
- snapshot project/revision/commit을 Agent가 선택하거나 완화하는 기능
- chunking, embedding, RRF, reranking과 query rewrite 자체의 변경
- ACORN·Filtered-DiskANN 같은 새로운 ANN index 알고리즘 직접 구현
- Issue Retrieval의 Bug scope와 검색 문서 계약 변경

## 13. 채택 Gate 초안

- filter 밖 결과 leakage 0건
- snapshot·citation provenance 불일치 0건
- hard scope 완화 또는 우회 0건
- 정상 0건과 오류·탐색 부족을 명확히 구분
- filtered Recall@8 비회귀
- 필터 없는 질의의 Recall@8·MRR 비회귀
- restrictive filter의 요청 limit 충족률 개선 또는 실제 eligible row 부족 증명
- P95, retry 수와 index 비용이 계획에서 정한 상한 이내

구체적인 수치와 통계적 판정 방식은 평가 사례 수와 corpus 분포를 확인한 후 계획에서 고정한다.

## 14. 완료 조건

- 지원 filter와 AND/OR/same-source/empty 의미가 Pydantic 계약과 문서에 명시된다.
- 모든 PCM 검색 경로가 동일한 filter conformance test를 통과한다.
- filter가 keyword·vector Top-K 제한과 RRF 이전에 적용된다.
- filtered exact oracle과 ANN 결과를 비교하는 benchmark가 존재한다.
- filter 적용 후에도 PCM revision과 source provenance가 유지된다.
- filter origin과 relaxation 여부가 결과 또는 trace에 기록된다.
- 정상 0건, validation error, stale fallback, ANN 탐색 부족과 DB 오류가 구분된다.
- 단위 테스트와 필요한 PostgreSQL 통합 테스트가 통과한다.
- benchmark 결과가 selectivity별 품질·leakage·지연·비용 변화를 보여준다.

## 15. 주요 위험

- SQL predicate를 추가하고 이를 ANN pre-filter로 오해하면 HNSW 결과 부족을 놓칠 수 있다.
- restrictive filter에서는 HNSW보다 exact scan이 빠를 수 있어 하나의 전략을 모든 질의에 강제하면
  성능이 악화될 수 있다.
- source JSONB 조건이 index를 사용하지 못하거나 서로 다른 source 원소에 잘못 매칭될 수 있다.
- filter 조합이 복잡해지면 Agent와 query parser의 false exclusion이 증가한다.
- 0건마다 자동으로 filter를 풀면 사용자 의도와 hard scope를 침범할 수 있다.
- keyword와 vector 경로의 filter 의미가 다르면 RRF 점수를 신뢰할 수 없다.
- metadata를 chunk·embedding row에 과도하게 복제하면 index와 revision 갱신 비용이 커진다.
- filterable field를 계속 추가하면 검색 계약이 외부 입력의 불안정한 schema에 종속될 수 있다.
- 평가 corpus가 작으면 partial index나 partitioning의 운영 비용을 정당하게 비교할 수 없다.

## 16. 후속 계획에서 결정할 항목

1. v1 allowlist에 `knowledge_type` 외 어떤 source·locator 필드를 포함할지
2. `KnowledgeSearchFilter`의 정확한 Pydantic 구조와 filter origin 표현
3. 복수 값 OR, 복수 필드 AND와 same-source 의미
4. 빈 목록, 잘못된 값, path·heading 정규화와 최대 조건 수
5. source JSONB GIN과 정규화 검색 테이블 중 선택
6. vector filter predicate를 어느 relation에 저장·적용할지
7. adaptive overfetch, pgvector iterative scan, selectivity 기반 exact 전환 중 구현 후보
8. `hnsw.ef_search`, scan 상한과 retry budget
9. Agent/self-query filter를 v1에 포함할지 별도 실험으로 둘지
10. soft filter relaxation 조건과 hard scope 비완화 보장 방식
11. selectivity bucket, exact oracle, 반복 횟수와 cache 정책
12. filtered Recall, limit 충족률, latency와 index 비용의 merge gate 수치

## 17. 참고 자료

- [pgvector: Filtering, Iterative Index Scans, Partial Indexing and Partitioning](https://github.com/pgvector/pgvector)
- [PostgreSQL JSONB Indexing](https://www.postgresql.org/docs/17/datatype-json.html)
- [ACORN: Performant and Predicate-Agnostic Search Over Vector Embeddings and Structured Data](https://doi.org/10.1145/3654923)
- [Filtered-DiskANN: Graph Algorithms for Approximate Nearest Neighbor Search with Filters](https://dl.acm.org/doi/10.1145/3543507.3583552)
- [Weaviate: Filtered Vector Search](https://weaviate.io/developers/weaviate/concepts/filtering)
- [Qdrant: Payload Index and Filterable HNSW](https://qdrant.tech/documentation/manage-data/indexing/)
- [LangChain SelfQueryRetriever](https://reference.langchain.com/python/langchain-classic/retrievers/self_query/base/SelfQueryRetriever)
- [Multi-Meta-RAG: Improving RAG for Multi-Hop Queries using Database Filtering with LLM-Extracted Metadata](https://arxiv.org/abs/2406.13213)
