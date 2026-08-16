# RAG Reranking 개선 실험 개요

## 1. 배경

PCM hybrid 검색은 vector와 keyword 결과를 Reciprocal Rank Fusion(RRF)으로 합친 뒤 점수가 높은
chunk부터 순회한다. 같은 `knowledge_id`의 첫 chunk만 최종 결과로 남기므로 현재 순위는 각 검색
채널의 상대 순위와 안정적인 `chunk_id` tie-breaker에 주로 의존한다.

RRF는 점수 범위가 다른 채널을 안전하게 합치지만, 질문과 근거의 세밀한 관련성, 제목 일치,
질문에 대한 답변 가능성은 판단하지 않는다. 후보 회수에는 성공했어도 관련성이 낮은 chunk가
상위 context를 차지할 수 있다.

## 2. 목표

기존 hybrid 검색을 후보 생성 단계로 유지하고, 제한된 후보만 별도 reranker로 재정렬한다. 최종
Top-K의 관련성과 근거 품질이 개선되는지 측정하되 latency, 모델 비용, 장애 시 동작을 함께 비교한다.

## 3. 실험 가설

RRF 상위 후보에 query-chunk 관련성을 다시 평가하면 후보 Recall을 유지하면서 Top-1 정확도,
MRR과 nDCG가 개선된다. 다만 reranking 후보 수를 제한하고 실패 정책을 명시해야 실시간 Agent
흐름에 사용할 수 있다.

## 4. 후보 전략

| 구분 | 전략 |
|---|---|
| 기준선 | vector + keyword RRF 순위 |
| 후보 A | 결정적 feature reranker: RRF, 제목·heading, keyword coverage 등 |
| 후보 B | 선택적 cross-encoder 또는 작은 relevance model reranker |

LLM에게 자유 형식 순위를 생성하게 하는 방식은 재현성·비용 때문에 기본 후보로 두지 않는다. 모델
방식을 선택한다면 입력 후보 ID를 고정하고 structured score, timeout, batch size와 fallback을 둔다.

## 5. 범위

### 포함

- 후보 생성과 최종 순위를 구분하는 port/service 계약
- rerank 후보 수와 최종 결과 수의 독립 설정
- 동일 Knowledge의 여러 chunk를 rerank 전후 어느 시점에 합칠지 비교
- 결정적 tie-breaker와 score 의미 정의
- reranker timeout·오류 시 기존 RRF 순위로의 명시적 degrade
- 기준선 대비 품질·지연·비용 benchmark

### 제외

- chunking, embedding model, metadata filter, query rewrite 변경
- 검색 결과가 없을 때 외부 지식을 생성하는 fallback
- citation revision과 repository snapshot 계약 변경
- Issue Matcher의 AUTO_LINK/REVIEW 정책 변경

## 6. Architecture 경계

Reranker의 최소 계약은 기술 독립적인 `Protocol`로 두고, feature 기반 구현과 모델 adapter를 분리한다.
PostgreSQL adapter는 넓은 후보를 반환하는 책임만 가지며 reranking 정책을 SQL에 숨기지 않는다.
조립은 application 또는 search service 경계에서 수행하고 일반 테스트는 Fake reranker로 실행한다.

Reranker가 반환할 수 있는 대상은 입력 후보 ID로 제한한다. 결과에 없는 후보를 새로 만들거나 source
provenance를 바꾸지 못하게 검증한다.

## 7. Benchmark 계약

같은 corpus, query, snapshot, chunker, embedding과 metadata 범위에서 RRF 후보 목록을 고정하고
reranking 전략만 바꾼다. 후보 집합에 정답이 없는 사례는 후보 생성 실패로 따로 집계해 reranker의
실패로 계산하지 않는다.

주요 지표:

- candidate Recall@20 또는 실제 rerank 후보 수
- 최종 Recall@5/8, Top-1 accuracy, MRR, nDCG@8
- 정답 source locator의 상위 노출률
- 검색 전체 P50/P95와 reranker 자체 지연
- 요청당 모델 호출 수, token 또는 추정 비용
- timeout·adapter 실패 시 기준선 복구율

채택 후보는 기준선의 Recall을 악화시키지 않으면서 MRR 또는 nDCG를 유의미하게 개선해야 한다.
모델 기반 후보는 품질 이득이 추가 지연과 운영 의존성을 정당화할 때만 추천한다.

## 8. 완료 조건

- candidate retrieval과 reranking이 별도 계약과 관찰 가능한 상태로 분리된다.
- 동일 입력과 동일 reranker는 결정적인 최종 순서를 만든다.
- reranker는 snapshot과 citation provenance를 변경하지 않는다.
- 오류·timeout 시 RRF fallback 사용 여부가 결과와 로그에서 구분된다.
- 외부 모델 없이 단위·graph 테스트가 실행된다.
- benchmark가 후보 회수 실패와 순위 실패를 분리해 보고한다.

## 9. 주요 위험

- RRF 후보 수가 작으면 reranker가 정답을 복구할 수 없다.
- 같은 Knowledge의 유사 chunk가 후보를 점유하면 문서 다양성이 줄어든다.
- cross-encoder의 한글·코드 도메인 성능이 일반 벤치마크와 다를 수 있다.
- fallback을 조용히 사용하면 운영 품질 저하를 알아채기 어렵다.
- relevance score를 확률처럼 해석하면 downstream 정책이 과도하게 신뢰할 수 있다.

## 10. 후속 계획에서 결정할 항목

1. rerank 전 후보 수와 Knowledge별 최대 chunk 수
2. feature 기반 후보의 점수 구성과 normalization
3. 모델 기반 후보를 포함할지, 포함한다면 provider와 batch 계약
4. timeout과 fallback을 결과 계약에 어떻게 노출할지
5. 품질 이득 대비 허용 가능한 P95·비용 상한
