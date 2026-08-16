# RAG Query Rewrite 개선 실험 개요

## 1. 배경

PCM 검색은 `KnowledgeSearchRequest.query` 하나를 그대로 다음 두 검색 경로에 사용한다.

- vector 검색: 원본 query를 embedding한 뒤 pgvector HNSW에서 유사 chunk를 찾는다.
- keyword 검색: 같은 query를 PostgreSQL `plainto_tsquery('simple', ...)`와 trigram 입력으로 사용한다.

두 경로는 결과를 RRF로 융합하고 같은 `knowledge_id`의 첫 chunk를 최종 Knowledge 결과로 반환한다.
Agent가 Tool 호출 전에 검색어를 다시 표현할 수는 있지만, 원본 질문과 실제 검색어의 관계, 선택한
전략, 실패와 fallback을 재현하는 계약은 없다.

질문과 Knowledge 사이에는 여러 종류의 표현 차이가 존재한다.

- 사용자는 현상을 길게 설명하지만 Knowledge는 짧은 architecture·operation 제목으로 작성된다.
- 한글 설명과 영문 class·method·endpoint·error code가 섞인다.
- 하나의 질문이 여러 component나 근거를 필요로 한다.
- 대화나 분석 문맥을 전제로 한 질문은 단독 검색어로 불완전할 수 있다.
- Agent가 root cause를 추측해 검색어에 넣으면 실제 corpus와 다른 방향으로 drift할 수 있다.

특히 keyword와 vector retriever는 선호하는 query 형태가 다르다. 정확한 symbol·path·error code는 lexical
검색에 중요하지만, 자연어 의미를 풍부하게 만든 문장은 dense retrieval에 유리할 수 있다. 모든 rewrite
결과를 두 채널에 똑같이 넣는 방식은 한쪽을 개선하면서 다른 쪽을 악화시킬 수 있다.

## 2. 문제 정의

Query rewrite는 답을 생성하는 단계가 아니라, **원래 정보 요구를 검색기가 잘 처리할 수 있는 하나 이상의
검색 표현으로 변환하는 단계**다. 다음 두 정확성을 함께 만족해야 한다.

1. **Intent preservation**: 원래 질문의 대상·제약·정확 식별자를 보존한다.
2. **Retriever alignment**: keyword와 vector 검색이 정답 후보를 더 잘 회수하도록 표현을 조정한다.

Rewrite가 지나치게 보수적이면 baseline과 차이가 없고, 지나치게 생성적이면 corpus에 없는 component,
API, 원인 또는 답을 추가한다. 생성된 텍스트는 검색 힌트일 뿐 사실이나 citation으로 사용할 수 없으며,
최종 답변은 실제 PCM 검색 결과에만 근거해야 한다.

## 3. 목표

1. 원본 query를 보존하면서 전략과 검색 채널이 명시된 rewrite 계약을 정의한다.
2. 결정적 정규화, multi-query, decomposition, 생성형 expansion을 독립 후보로 비교한다.
3. exact identifier를 잃지 않으면서 paraphrase·장문·복합 질문의 candidate Recall을 개선한다.
4. 여러 query와 keyword/vector 결과를 중복 편향 없이 결정적으로 융합한다.
5. rewrite 실패·timeout·invalid output 시 원본 검색으로 안전하게 복구한다.
6. 검색 품질뿐 아니라 query drift, 지연, 모델 호출과 downstream task 성능을 함께 측정한다.

실제 채택할 전략, variant 수와 융합 방식은 이 개요에서 확정하지 않고 후속 계획에서 선택한다.

## 4. 불변 조건과 신뢰 경계

- 원본 query는 삭제하거나 덮어쓰지 않는다.
- `project_id`, PCM revision, repository commit과 metadata hard scope는 rewrite 입력·출력으로 변경하지
  않는다.
- filter 선택은 metadata-filter 실험의 책임이며 rewrite가 임의의 SQL/filter 표현을 만들지 않는다.
- 생성된 query·pseudo-document·hypothetical answer는 Knowledge나 evidence가 아니다.
- 최종 citation은 고정 snapshot에서 실제 검색된 Knowledge와 source만 가리킨다.
- 모델 output은 허용된 strategy와 bounded string 목록으로 검증한다.
- rewrite가 실패해도 검색 실패로 위장하지 않고 원본-only fallback을 명시한다.
- 원문, model prompt와 생성 결과를 운영 로그에 그대로 남길지 별도 privacy 정책으로 통제한다.

## 5. 자료 조사와 적용 시사점

### 5.1 Rewrite-Retrieve-Read

[Query Rewriting in Retrieval-Augmented Large Language Models](https://aclanthology.org/2023.emnlp-main.322/)는
질문과 검색기가 필요로 하는 지식 표현 사이의 간극을 줄이기 위해 Rewrite-Retrieve-Read 구조를 제안한다.
LLM rewrite뿐 아니라 retriever와 reader의 downstream feedback에 맞춰 rewriter를 학습하는 방식까지
다룬다.

Clio에서는 학습형 rewriter를 바로 도입하기보다 다음 원칙을 가져온다.

- rewrite를 Agent prompt의 숨은 동작이 아니라 독립 단계로 관찰한다.
- retrieval metric뿐 아니라 최종 IA·분석 성공 여부로 rewrite를 평가한다.
- 같은 rewriter라도 keyword와 vector retriever에서 효과가 다를 수 있으므로 채널별 결과를 남긴다.
- 충분한 golden feedback이 생기기 전에는 trainable rewriter를 후순위 후보로 둔다.

### 5.2 Query2doc와 HyDE

[Query2doc](https://aclanthology.org/2023.emnlp-main.585/)는 LLM이 pseudo-document를 생성하고 이를 원본
query에 붙여 sparse와 dense retrieval의 표현을 확장한다.
[HyDE](https://aclanthology.org/2023.acl-long.99/)는 hypothetical document를 생성해 그 embedding으로
실제 corpus의 문서를 찾는다. HyDE 논문도 hypothetical document가 가짜이며 hallucination을 포함할 수
있음을 명시한다.

Clio 적용 후보는 다음처럼 분리한다.

- Query2doc expansion은 corpus 표현과 lexical gap을 줄일 가능성이 있지만 가상의 기술 용어가 keyword
  검색을 오염시킬 수 있다.
- HyDE는 hypothetical text를 vector embedding에만 사용하고 keyword query와 evidence에는 넣지 않는
  후보가 더 안전하다.
- 두 방법 모두 원본 query stream을 유지하고, 실제 Knowledge가 회수된 뒤 생성물을 폐기한다.
- 일반 웹 지식을 가진 LLM이 Clio 내부 component를 추측하지 않도록 project-specific fact 생성을
  금지하고, identifier hallucination을 별도 평가한다.

### 5.3 Multi-query와 RAG-Fusion

[RAG-Fusion](https://arxiv.org/abs/2402.03367)은 하나의 질문에서 여러 query를 생성하고 각 검색 순위를
RRF로 합치는 접근이다. 서로 다른 표현이 단일 query가 놓친 문서를 회수할 수 있지만, 생성된 query가
원문에서 벗어나면 답이 주제 밖으로 이동할 수 있다고 보고한다.

Clio에는 이미 keyword/vector 융합 RRF가 있으므로 query variant까지 단순히 동일한 RRF 입력으로 추가하면
다음 편향이 생길 수 있다.

- 유사한 variant가 같은 chunk를 반복 회수해 중복 강화한다.
- query 수가 많은 전략이 원본 query보다 자동으로 더 큰 투표권을 가진다.
- keyword·vector channel과 query variant의 기여도를 구분하기 어렵다.

따라서 query별 결과를 먼저 정규화·deduplicate한 뒤 channel-level 또는 query-family-level로 융합하는
후보를 비교한다. variant 수가 달라도 총 가중치가 같도록 normalization하는 방식도 계획에서 검토한다.

### 5.4 Question Decomposition

[Question Decomposition for Retrieval-Augmented Generation](https://aclanthology.org/2025.acl-srw.32/)은
복합·multi-hop 질문을 focused subquery로 나눠 각각 검색하고, 넓어진 후보를 rerank하는 구조를 제안한다.
한 문서에 모든 근거가 함께 존재하지 않는 질문에서 evidence coverage를 높일 수 있다.

Clio에서는 다음 질문에 decomposition 후보가 적합하다.

- 두 component의 책임이나 상호작용을 함께 묻는 질문
- requirement와 architecture 근거를 동시에 요구하는 질문
- 증상, 관련 operation, 해결 이력을 함께 확인해야 하는 질문

단순한 질문까지 무조건 분해하면 검색 횟수와 noise만 늘어난다. decomposition 여부를 먼저 판단하거나,
subquery 수를 제한하고 원본 query 결과와 함께 융합해야 한다. 여러 하위 질문의 정답을 하나의 Top-K로
경쟁시키면 일부 근거가 사라질 수 있으므로 subquery coverage도 평가한다.

### 5.5 생성형 Expansion의 실패 조건

[When do Generative Query and Document Expansions Fail?](https://aclanthology.org/2024.findings-eacl.134/)은
생성형 expansion의 효과가 retriever, dataset domain과 query 유형에 따라 달라 보편적인 개선이 아님을
분석한다. [Searching for Best Practices in RAG](https://aclanthology.org/2024.emnlp-main.981/)도 RAG
모듈을 한 번에 하나씩 비교하고 성능과 효율을 함께 평가한다.

따라서 논문의 평균 개선값이나 특정 prompt를 Clio 기본값으로 복사하지 않는다. 직접 질문, exact-token
질문, paraphrase, 복합 질문, unanswerable 질문을 분리하고 전략별 회귀를 확인한다.

## 6. Rewrite 유형 후보

### 6.1 결정적 정규화

모델 호출 없이 원문에서 검색에 방해되는 형식만 정리한다.

- Unicode와 공백 정규화
- Markdown·로그 wrapper와 반복 문구 정리
- class·method·endpoint·path·error code 후보 추출
- exact token의 원형과 case-folded 보조형 보존
- 너무 긴 현상 설명에서 검색 대상 문장 후보 분리

결정적 정규화는 새로운 synonym이나 project fact를 추가하지 않는다. identifier parser가 언어별 문법을
과도하게 추측하지 않도록 단순 allowlist pattern과 길이 제한을 둔다.

### 6.2 Standalone Rewrite

대화 또는 분석 문맥을 참조하는 질문을 독립적으로 검색 가능한 문장으로 바꾼다. 현재 Tool query는
Agent가 직접 만들기 때문에 이 기능의 실제 필요성을 Agent-only baseline과 비교한다. 문맥에서 명시된
식별자만 추가할 수 있고 새로운 사실은 만들지 않는다.

### 6.3 Multi-query Paraphrase

원래 정보 요구를 유지하는 소수의 표현 변형을 만든다.

- 원본 query는 항상 별도 stream으로 포함한다.
- variant마다 같은 역할을 반복하지 않도록 목적을 부여할 수 있다.
- exact identifier variant와 자연어 semantic variant를 구분한다.
- 최대 개수, 길이, 중복 similarity와 timeout을 제한한다.

### 6.4 Query Decomposition

여러 독립 근거가 필요한 질문만 bounded subquery로 분해한다. 각 subquery는 원문의 어느 부분을 담당하는지
표시하고, 전체 질문에 없는 전제를 추가하지 않는다.

### 6.5 Query2doc·HyDE Expansion

가상의 관련 문서나 답변 형태를 생성해 retrieval 표현으로만 사용한다. Hypothetical text에는 identifier
allowlist 검사와 길이 제한을 적용하고, vector-only 사용 여부를 별도 전략으로 둔다.

### 6.6 Retrieval-aware Iterative Rewrite

첫 검색 결과 또는 실패 유형을 보고 다음 query를 만드는 방식은 후보로 기록하되 v1 우선순위는 낮다.
검색 결과를 다시 입력하므로 지연·비용과 feedback loop가 커지고, 관련 없는 초기 결과가 rewrite를
오염시킬 수 있다. 적용한다면 최대 round 수와 stop reason을 계약으로 제한한다.

## 7. Rewrite 계약 후보

```text
QueryRewritePlan
  original_query
  strategy
  exact_terms
  lexical_queries
  semantic_queries
  subqueries
  hypothetical_texts
  fallback_policy
  rewriter_version
```

각 query 표현은 최소한 다음 provenance를 가진다.

```text
QueryVariant
  variant_id
  text
  role = original | normalized | paraphrase | subquery | hypothetical
  target = keyword | vector | both
  parent_variant_id(optional)
  covered_intents
```

계약 규칙 후보:

- `original_query`는 항상 존재하고 변경하지 않는다.
- `variant_id`와 순서는 결정적이어야 한다.
- 빈 문자열, 원문과 동일한 중복, 최대 길이·개수 초과를 거부한다.
- exact term이 원본·허용 문맥에 없는 경우 generated identifier로 표시하거나 거부한다.
- hypothetical text는 `target=vector`를 기본 후보로 두고 citation 대상에서 제외한다.
- subquery는 원래 intent의 어떤 부분을 담당하는지 구조적으로 표시한다.
- model·prompt·schema version을 실험 결과에 기록한다.

## 8. 검색·융합 전략 후보

| 구분 | 전략 | 목적 | 주요 위험 |
|---|---|---|---|
| 기준선 | Agent가 만든 query 1개로 현재 hybrid 검색 | 현재 성능 측정 | rewrite 선택을 관찰하기 어려움 |
| 후보 A | 원본 + 결정적 정규화 | 낮은 비용으로 exact token 보존 | semantic gap 개선이 제한적 |
| 후보 B | 원본 + bounded multi-query | paraphrase Recall 개선 | 중복 강화와 검색 횟수 증가 |
| 후보 C | 원본 + 선택적 decomposition | multi-evidence coverage 개선 | noise와 일부 subquery 독점 |
| 후보 D | 원본 + vector-only HyDE | dense semantic gap 개선 | hypothetical hallucination |
| 후보 E | Query2doc lexical·dense expansion | corpus 표현 확장 | 가상 기술 용어로 precision 저하 |
| 후보 F | 제한된 iterative rewrite | 초기 검색 실패 복구 | feedback loop·latency·복잡도 |

융합 방식 후보:

1. 모든 query·channel 결과를 하나의 RRF에 넣는다.
2. variant 내부에서 keyword/vector를 융합한 뒤 variant 결과를 다시 융합한다.
3. original과 generated query family에 고정된 총 가중치를 배분한다.
4. chunk별 최고 query score만 사용해 유사 variant의 중복 투표를 막는다.
5. subquery별 최소 evidence quota를 확보한 뒤 나머지를 전역 순위로 채운다.

각 방식은 동일 candidate budget에서 비교한다. query 수가 늘었다는 이유만으로 더 많은 최종 context를
허용하지 않는다.

## 9. 실행과 Fallback

- 결정적 rewriter는 model 없이 항상 실행 가능한 baseline으로 둔다.
- model adapter는 지연 초기화하고 timeout·schema validation·max token을 명시한다.
- 일부 variant만 실패하면 유효한 variant와 원본으로 계속 검색한다.
- 전체 rewrite가 실패하면 원본-only hybrid 검색으로 복구한다.
- vector embedding 실패 시 keyword 경로가 원본 exact term을 계속 사용할 수 있어야 한다.
- stale-index fallback은 hypothetical/vector query를 무시하고 원본·검증된 lexical query만 사용할지
  계획에서 결정한다.
- trace에는 strategy, variant 수, target channel, latency, validation error와 fallback reason을 남긴다.
- 원문과 생성 전문은 기본 metric label에 넣지 않고 hash 또는 안전한 case ID로 연결한다.

## 10. Benchmark 계약

### 10.1 Query Slice

- Knowledge 표현과 거의 같은 직접 질문
- 같은 의미지만 표현이 다른 paraphrase
- 한글 자연어와 영문 식별자가 섞인 질문
- class·method·endpoint·path·error code 중심 질문
- 긴 현상 설명과 부가 조건이 섞인 질문
- 여러 component·requirement·source가 필요한 복합 질문
- 문맥을 참조하는 불완전한 질문
- 모호하거나 정보가 부족한 질문
- corpus에 정답이 없는 unanswerable 질문
- rewrite가 새로운 식별자나 원인을 만들기 쉬운 adversarial 질문

### 10.2 Retrieval 지표

- Recall@5·Recall@8, MRR, nDCG@8
- keyword-only와 vector-only candidate Recall
- original query 대비 새로 회수한 정답 수
- original query가 찾던 정답의 유실률
- subquery별 evidence coverage와 전체 required-evidence coverage
- 관련 없는 Knowledge 유입률과 Precision@K
- 최종 candidate pool의 unique Knowledge 수

### 10.3 Rewrite 정확성 지표

- exact identifier preservation rate
- generated identifier·project fact hallucination rate
- intent coverage와 constraint preservation
- original과 의미가 충돌하는 query drift 비율
- 중복·무효 variant 비율
- decomposition 필요 여부와 subquery 적합성
- unanswerable·모호한 질문에서 불필요한 확장을 하지 않는 abstention rate

### 10.4 Downstream·운영 지표

- IA·분석 task success와 필수 fact/source locator 식별률
- 요청당 rewrite·embedding·검색 호출 수
- rewrite 자체 및 전체 검색 P50/P95
- 입력·출력 token과 추정 비용
- timeout·validation 실패율과 원본 fallback 성공률
- variant별 후보 기여도와 최종 Top-K 생존율

생성형 rewrite 평가는 자동 semantic similarity만으로 통과시키지 않고 사람이 검수한 표본에서 identifier,
intent, hallucination을 확인한다.

## 11. 실험 통제

1. corpus, PCM revision, chunker, embedding model과 metadata 범위를 고정한다.
2. candidate budget, RRF 설정, reranking 여부와 최종 limit을 고정한다.
3. 한 번에 rewrite 전략 하나만 변경한다.
4. 원본-only 결과를 모든 사례에 함께 저장한다.
5. model 후보는 model·version·prompt·temperature와 seed 가능 여부를 기록한다.
6. 동일 query를 반복해 variant와 최종 순위의 변동성을 측정한다.
7. retrieval 개선이 downstream task 개선으로 이어지는지 별도로 확인한다.
8. 유망한 rewrite만 reranking 등 다른 실험과 조합해 상호작용을 재평가한다.

## 12. 범위

### 포함

- query plan과 variant의 Pydantic 계약
- 결정적 normalization·identifier extraction
- 선택적 model rewrite, multi-query, decomposition, Query2doc·HyDE 후보
- lexical query와 semantic query의 분리
- variant별 retrieval과 결정적 fusion
- variant 수·길이·호출·timeout budget
- 원본-only fallback과 관찰 가능한 trace
- retrieval·rewrite 정확성·downstream·비용 benchmark

### 제외

- rewrite model fine-tuning과 reinforcement learning
- 대화 전체를 장기 기억으로 저장하는 conversational memory
- 운영 코드에 무제한 domain synonym 사전 구축
- rewrite가 metadata hard scope나 ACL을 변경하는 기능
- chunking, embedding model, metadata filter와 reranker 자체 변경
- hypothetical text를 Knowledge, answer 또는 citation으로 사용하는 것
- 검색 결과가 없다는 이유로 외부 웹 검색을 수행하는 것

## 13. 채택 Gate 초안

- 원본 query 보존율 100%
- snapshot·citation provenance 불일치 0건
- 허용되지 않은 hard scope 변경 0건
- exact identifier 중심 slice의 정답 유실 0건
- generated project identifier·fact hallucination 0건
- 전체 Recall@8 비회귀
- 목표 slice의 Recall·MRR 또는 required-evidence coverage 개선
- 직접 질문과 unanswerable slice의 중대한 precision 회귀 없음
- timeout·invalid output에서 원본 fallback 성공률 100%
- P95, 호출 수와 token 비용이 계획에서 정한 상한 이내

구체적인 수치와 통계적 기준은 평가셋 크기와 반복 변동을 확인한 뒤 계획에서 고정한다.

## 14. 완료 조건

- 원본과 rewrite variant, target channel, strategy가 계약에 명시된다.
- 같은 입력과 결정적 rewriter는 같은 variant와 순서를 만든다.
- variant 수, 길이, exact term과 subquery 수가 상한을 넘지 않는다.
- model output이 Pydantic으로 검증되고 query drift·identifier hallucination fixture를 통과한다.
- variant별 검색 결과와 fusion 기여도를 재현할 수 있다.
- 실패가 정상 0건으로 위장되지 않고 fallback reason이 노출된다.
- 외부 model 없이 단위·graph smoke test가 실행된다.
- benchmark가 query slice별 품질·지연·비용·downstream 결과를 보고한다.

## 15. 주요 위험

- LLM이 그럴듯한 component·원인·API를 추가하면 틀린 Knowledge가 상위에 오를 수 있다.
- 자연어 축약이 class·method·path·error code를 삭제하면 lexical recall이 급격히 낮아질 수 있다.
- 유사한 multi-query가 같은 chunk를 반복 강화해 다양성을 낮출 수 있다.
- decomposition된 하위 질문이 최종 Top-K를 서로 경쟁하며 필요한 근거 하나를 밀어낼 수 있다.
- HyDE와 Query2doc의 hypothetical text가 실제 Clio corpus 문체와 다를 수 있다.
- Agent가 이미 검색어를 선택하는 구조에서 별도 rewrite가 중복 비용만 만들 수 있다.
- model 기반 rewrite는 latency, 장애 지점과 결과 변동성을 늘린다.
- query trace에 사용자 입력, 로그 또는 내부 식별자가 과도하게 남을 수 있다.
- retrieval metric 개선이 제한된 rerank/context budget 뒤에서 사라질 수 있다.

## 16. 후속 계획에서 결정할 항목

1. v1에 포함할 rewrite 후보와 적용 순서
2. 결정적 normalization과 exact identifier pattern
3. lexical·semantic query를 분리할지 하나의 variant 목록을 사용할지
4. 최대 variant·subquery 수, 길이와 요청당 검색 budget
5. multi-query·channel 결과 fusion과 중복 투표 방지 방식
6. decomposition을 실행하는 조건과 subquery coverage 보장 방식
7. HyDE를 vector-only 후보로 포함할지
8. Query2doc와 iterative rewrite를 후속 실험으로 미룰지
9. model provider·prompt·temperature·timeout과 fallback 계약
10. rewrite trace에서 원문과 생성 결과를 어느 수준까지 보존할지
11. identifier hallucination·query drift의 수작업 평가 절차
12. 품질 이득 대비 허용 가능한 P95·호출 수·token 비용 상한

## 17. 참고 자료

- [Query Rewriting in Retrieval-Augmented Large Language Models](https://aclanthology.org/2023.emnlp-main.322/)
- [Query2doc: Query Expansion with Large Language Models](https://aclanthology.org/2023.emnlp-main.585/)
- [Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE)](https://aclanthology.org/2023.acl-long.99/)
- [RAG-Fusion: a New Take on Retrieval-Augmented Generation](https://arxiv.org/abs/2402.03367)
- [Question Decomposition for Retrieval-Augmented Generation](https://aclanthology.org/2025.acl-srw.32/)
- [When do Generative Query and Document Expansions Fail?](https://aclanthology.org/2024.findings-eacl.134/)
- [Searching for Best Practices in Retrieval-Augmented Generation](https://aclanthology.org/2024.emnlp-main.981/)
