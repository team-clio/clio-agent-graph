# RAG Metadata Filter 개선 실험 개요

## 1. 배경

PCM 검색은 graph가 고정한 `project_id`, `pcm_revision`으로 snapshot 범위를 제한한다. 요청자는
`knowledge_types`도 지정할 수 있지만, 현재 PostgreSQL hybrid 검색에서는 vector·keyword 후보를
먼저 제한한 다음 Python에서 knowledge type을 제외한다.

따라서 특정 유형만 찾는 질의에서는 관련 결과가 SQL의 후보 제한 밖으로 밀린 뒤 필터링되어 최종
결과 수와 Recall이 불필요하게 낮아질 수 있다. source에는 `source_type`, `source_id`, revision,
locator가 있지만 검색 계약은 이를 안전한 filter로 표현하지 못한다.

## 2. 목표

검색 전에 적용되는 명시적 metadata filter 계약을 만들고, 관련 없는 후보의 유입을 막으면서 필터
범위 안의 Recall과 지연 시간이 개선되는지 기준선과 비교한다. project와 snapshot은 계속 graph가
고정하며 Agent가 신뢰 경계를 임의로 바꿀 수 없게 한다.

## 3. 실험 가설

허용된 metadata를 keyword·vector 후보 생성 단계에 동일하게 적용하면 다음 결과를 기대할 수 있다.

1. 좁은 범위 검색에서 정답이 후보 제한 전에 탈락하는 현상이 줄어든다.
2. 필터 밖 결과가 반환되는 leakage가 0이 된다.
3. 후보 집합 감소로 검색 지연과 후속 context 크기가 줄어든다.

## 4. 초기 Filter 계약 후보

- `knowledge_types`: domain rule, requirement, architecture 등
- `source_types`: document, repository, resolved issue
- `source_ids`: graph가 허용한 문서·repository·issue 식별자
- locator의 검증된 상위 필드: repository path prefix 또는 document heading 범위

임의 JSONPath나 SQL 조각은 받지 않는다. project ID, PCM revision, repository commit은 기존처럼
snapshot에서 가져오며 모델이 검색 인자로 선택하지 않는다. 복수 필드의 AND/OR 의미와 빈 목록의
의미는 Pydantic 계약으로 고정한다.

## 5. 범위

### 포함

- `KnowledgeSearchRequest`의 typed filter 모델
- keyword, vector, stale-index fallback에 동일한 filter 의미 적용
- 가능한 filter를 SQL candidate generation 전에 pushdown
- source JSONB 또는 정규화된 열에 필요한 index 검토
- 필터 serialization, validation, 결과 provenance 테스트
- 필터 유무에 따른 품질·지연 benchmark

### 제외

- 자유 형식 metadata expression 언어
- 권한 시스템이나 사용자별 ACL 구현
- chunking, embedding, RRF, reranking, query rewrite 변경
- Issue Retrieval의 `project_id`·Bug scope 계약 변경

ACL은 별도 보안 요구사항이다. 이번 실험의 filter를 접근 통제 수단으로 과장하지 않는다.

## 6. 비교 대상

| 구분 | 전략 |
|---|---|
| 기준선 | project/snapshot SQL 제한 + knowledge type 사후 필터 |
| 후보 A | knowledge type을 keyword·vector SQL에 사전 적용 |
| 후보 B | 후보 A + source type/source ID의 typed 사전 필터 |

모든 후보는 같은 corpus, query, embedding, chunking, 후보 수와 RRF 설정을 사용한다.

## 7. Benchmark 계약

평가 사례는 필터가 없는 일반 질문과 필터가 정답 범위를 좁히는 질문, 잘못된 필터로 정상 0건이
되어야 하는 질문을 함께 포함한다.

주요 지표:

- filtered Recall@5, Recall@8, MRR
- 필터 밖 결과 leakage 비율
- 요청 limit 충족률
- SQL 후보 수와 후속 context 문자 수
- 검색 P50/P95
- filter가 없는 기존 질의의 비회귀

정확성 gate는 leakage 0과 snapshot 불일치 0이다. 성능 개선은 정확성 gate를 통과한 후보끼리만
비교한다.

## 8. 완료 조건

- 지원 filter와 조합 의미가 Pydantic 계약과 문서에 명시된다.
- 모든 검색 경로가 같은 filter를 적용한다.
- filter 적용 후에도 citation의 PCM revision과 source provenance가 유지된다.
- 정상 0건과 설정·DB 오류가 구분된다.
- 단위 테스트와 필요한 PostgreSQL 통합 테스트가 통과한다.
- benchmark가 기준선 대비 품질, leakage, 지연 변화를 보여준다.

## 9. 주요 위험

- JSONB source filter가 index를 사용하지 못하면 후보는 정확해도 지연이 증가할 수 있다.
- filter 조합 의미가 복잡해지면 Agent가 잘못된 범위를 선택해 정답을 배제할 수 있다.
- keyword와 vector 경로의 filter 구현이 달라지면 융합 결과를 신뢰할 수 없다.
- source가 여러 개인 Knowledge에서 `모든 source`와 `하나 이상의 source` 의미가 혼동될 수 있다.

## 10. 후속 계획에서 결정할 항목

1. v1에서 지원할 metadata allowlist
2. 복수 값과 복수 필드의 AND/OR 의미
3. source filter용 JSONB index와 정규화 테이블 중 선택
4. Agent가 직접 선택 가능한 filter와 graph가 고정할 filter의 경계
5. 잘못된 과도 필터를 완화할지 명시적으로 0건을 반환할지
