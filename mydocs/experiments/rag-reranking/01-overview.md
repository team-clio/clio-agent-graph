# RAG Reranking 개선 실험 개요

## 1. 배경

PCM PostgreSQL hybrid 검색은 vector와 keyword 경로에서 각각 `limit * 4`개의 chunk 후보를 가져온 뒤
Reciprocal Rank Fusion(RRF)으로 결합한다. 현재 RRF 점수는 각 채널의 상대 순위
`1 / (rank_constant + rank)`를 더해 계산하고, 동점은 `chunk_id`로 결정한다.

융합된 chunk를 순회하면서 같은 `knowledge_id`의 첫 chunk만 남기므로 최종 결과는 사실상 다음 순서로
결정된다.

1. keyword와 vector가 회수한 chunk 순위
2. RRF로 합쳐진 chunk 순위
3. 각 Knowledge에서 처음 등장한 대표 chunk
4. 요청 `limit`까지의 Knowledge

RRF는 서로 다른 점수 척도를 학습 없이 안정적으로 결합하는 좋은 candidate-fusion baseline이지만,
질문과 chunk를 함께 읽고 다음 내용을 직접 판단하지는 않는다.

- 이 chunk가 질문에 실제 답할 수 있는가
- 제목·heading의 일치가 본문과 같은 의미인가
- 정확한 class·method·endpoint·error code가 같은 맥락에서 사용되는가
- 여러 chunk가 같은 Knowledge의 중복 내용인지
- 최종 분석에 필요한 서로 다른 근거가 충분히 포함되는가

따라서 정답 chunk가 후보에는 들어왔지만 RRF 상위에 오르지 못하거나, 같은 Knowledge의 유사 chunk가
candidate budget을 점유해 최종 context 품질이 낮아질 수 있다.

## 2. 문제 정의

Reranking은 넓게 회수한 candidate 집합을 query와 다시 비교해 최종 context 순서를 정하는 단계다.
Reranker는 후보 밖 정답을 새로 찾을 수 없으므로 두 실패를 반드시 분리해야 한다.

1. **Candidate generation failure**: 정답이 rerank 후보 집합에 없음
2. **Ranking failure**: 정답은 후보에 있지만 최종 Top-K에 없거나 너무 낮음

또한 relevance와 diversity는 같은 목표가 아니다. query와 가장 비슷한 chunk만 반복 선택하면 정확해
보이지만 서로 다른 component·requirement·source가 필요한 질문에서 evidence coverage가 낮아질 수 있다.
이번 실험은 relevance reranking과 중복 제거·다양성 선택을 별도 단계와 지표로 비교한다.

## 3. 목표

1. candidate retrieval, relevance scoring, Knowledge aggregation과 final selection을 분리한다.
2. 현재 RRF, 결정적 feature, cross-encoder, LLM reranker와 diversity 후보를 같은 candidate에서 비교한다.
3. candidate Recall을 유지하면서 Top-1, MRR, nDCG와 evidence coverage를 개선한다.
4. 같은 Knowledge의 여러 chunk를 어느 시점에 집계할지 실험으로 결정한다.
5. 모델 timeout·오류·invalid output 시 RRF 순위로 안전하게 복구한다.
6. 품질 이득과 reranker latency, token, model 크기와 운영 의존성을 함께 측정한다.

구체적인 reranker, candidate 수, score fusion과 diversity 적용 여부는 후속 계획에서 선택한다.

## 4. 불변 조건과 신뢰 경계

- reranker 입력은 고정 snapshot에서 실제로 회수한 candidate로 제한한다.
- reranker는 새로운 chunk·Knowledge·source ID를 만들 수 없다.
- `project_id`, PCM revision, repository commit과 metadata hard scope를 변경하지 않는다.
- candidate의 content, title, heading과 provenance를 수정하지 않는다.
- reranker score를 확률이나 AUTO_LINK confidence로 재해석하지 않는다.
- citation은 reranker가 생성한 설명이 아니라 원래 candidate의 source를 유지한다.
- 동일 score의 tie-breaker와 fallback 순서는 결정적이어야 한다.
- reranker가 실패해도 정상 0건으로 위장하지 않고 RRF fallback 사용 여부를 기록한다.

## 5. 자료 조사와 적용 시사점

### 5.1 RRF는 Candidate Fusion Baseline

[Reciprocal Rank Fusion](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)은
여러 retrieval system의 순위를 점수 calibration 없이 결합하는 단순하고 강한 방법이다. Clio의 현재
RRF는 vector와 keyword의 상호 보완을 보존하는 baseline으로 유지한다.

다만 RRF 점수는 query-document relevance의 절대값이 아니고, 입력 rank list와 `rank_constant`에 의해
정해진다. RRF를 없애고 reranker 하나로 대체하기보다 다음 2-stage 구조를 기본 후보로 둔다.

1. keyword·vector + RRF로 넓은 candidate를 회수한다.
2. 제한된 candidate만 더 비싼 relevance model로 재정렬한다.

### 5.2 Cross-encoder Reranking

[Passage Re-ranking with BERT](https://arxiv.org/abs/1901.04085)는 query와 passage를 하나의 입력으로
함께 인코딩해 relevance를 평가하는 대표적인 cross-encoder 접근이다.
[Document Ranking with a Pretrained Sequence-to-Sequence Model](https://aclanthology.org/2020.findings-emnlp.63/)의
monoT5는 query-document relevance를 sequence-to-sequence 방식으로 평가한다.

독립적으로 embedding한 vector 유사도와 달리 cross-encoder는 query와 chunk token 사이의 세밀한
상호작용을 볼 수 있어 reranking에 적합하다. 대신 모든 query-candidate pair를 실행해야 하므로
candidate 수에 따라 비용이 선형으로 증가하고, 모델 최대 길이에서 chunk가 잘릴 수 있다.

Clio에서는 query와 다음 표현을 함께 입력하는 후보를 비교한다.

- title + heading + matched chunk
- title + heading + chunk + 제한된 source metadata
- 너무 긴 chunk의 query-aware window 또는 고정 앞부분

현재 chunk content에는 title과 heading이 이미 prefix로 포함되므로 입력을 중복 구성하지 않도록 계약을
명확히 한다.

### 5.3 다국어·기술 문서 모델

Clio query와 Knowledge는 한글 자연어, 영문 기술 용어와 code identifier가 섞일 수 있다. 영어 MS MARCO
성능만으로 모델을 선택하지 않고 한글·영문 혼합 fixture에서 검증해야 한다.

[BGE reranker 모델 카드](https://huggingface.co/BAAI/bge-reranker-v2-m3)는 query와 passage를 함께 입력해
relevance score를 반환하는 multilingual reranker 후보를 제공한다. 이는 비교 후보이지 기본 채택을
의미하지 않는다. 모델 크기, 라이선스, 다운로드·배포, CPU/GPU latency, 최대 token과 현재 Ollama 중심
runtime과의 통합 비용을 함께 평가한다.

### 5.4 LLM Reranking

[RankGPT](https://aclanthology.org/2023.emnlp-main.923/)는 생성형 LLM이 문서 목록의 relevance 순서를
직접 만들 수 있음을 보이고, 큰 후보 목록을 처리하기 위한 sliding-window ranking과 작은 모델로의
distillation을 연구한다.
[Pairwise Ranking Prompting](https://aclanthology.org/2024.findings-naacl.97/)은 pointwise·listwise
prompt의 어려움을 줄이기 위해 후보 쌍 비교를 사용한다.
[RankRAG](https://proceedings.neurips.cc/paper_files/paper/2024/hash/db93ccb6cf392f352570dd5af0a223d3-Abstract-Conference.html)은
ranking data를 섞어 instruction-tuning한 LLM이 context ranking과 answer generation을 함께 수행하는
방식을 제안한다.

Clio의 후보는 다음처럼 구분한다.

- **Pointwise**: 각 candidate를 독립 scoring한다. 병렬화와 fallback이 쉽지만 후보 간 비교 정보가 없다.
- **Pairwise**: 두 candidate를 비교한다. 비교 품질은 높을 수 있지만 호출 수가 크게 증가한다.
- **Listwise**: 여러 candidate ID의 순열을 한 번에 반환한다. 전역 비교가 가능하지만 입력 순서 편향,
  context 길이와 invalid permutation 위험이 있다.

범용 LLM을 기본 reranker로 확정하지 않는다. 외부 호출 비용과 변동성이 크고, 기술 domain에서 그럴듯한
설명을 relevance로 오인할 수 있다. 사용한다면 입력 candidate ID만 반환하는 structured output,
permutation 검증, timeout과 RRF fallback을 둔다.

### 5.5 Position Bias

[Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/)은 긴 context에서 관련 정보의 위치가 모델
성능에 영향을 주며 가운데 위치에서 성능이 낮아질 수 있음을 보인다.
[Permutation Self-Consistency](https://aclanthology.org/2024.naacl-long.129/)는 listwise ranking 입력
순서를 여러 번 섞고 결과를 집계해 position bias를 줄이는 방법을 제안한다.

따라서 LLM listwise 후보는 다음을 반드시 평가한다.

- 같은 candidate를 다른 입력 순서로 제공했을 때의 순위 안정성
- RRF 상위 후보를 앞에 둔 경우와 무작위 순서의 차이
- candidate 수와 window 경계에 따른 결과 변화
- permutation self-consistency의 품질 이득 대비 추가 호출 비용

### 5.6 Relevance와 Diversity

[Maximal Marginal Relevance](https://doi.org/10.1145/290941.291025)는 query relevance와 이미 선택한
문서와의 novelty를 함께 고려해 중복을 줄이는 고전적인 diversity reranking 방법이다.

PCM에서는 같은 Knowledge의 인접 chunk나 같은 source를 반복 선택할 수 있으므로 relevance reranker 뒤에
다음 final-selection 후보를 둘 수 있다.

- Knowledge별 최대 chunk 수 제한
- 동일 content hash 또는 높은 chunk similarity deduplication
- MMR 기반 relevance-diversity 절충
- 복합 질문에서 source·Knowledge coverage quota

MMR은 relevance model을 대체하지 않는다. 먼저 relevance score를 만든 뒤 제한된 final context 안에서
중복을 조정하는 별도 단계로 평가한다.

## 6. Reranking 단위 후보

### 6.1 Chunk-first

RRF 상위 chunk를 그대로 rerank한 후 최종 단계에서 Knowledge로 집계한다.

장점:

- 질문에 직접 답하는 passage를 세밀하게 찾을 수 있다.
- 같은 Knowledge 안에서도 더 나은 matched content를 선택할 수 있다.

위험:

- 한 Knowledge의 유사 chunk가 rerank budget을 많이 사용한다.
- chunk relevance가 높아도 Knowledge 전체가 질문에 적합하지 않을 수 있다.

### 6.2 Knowledge-first

RRF 후보를 먼저 Knowledge별로 집계한 뒤 대표 chunk 또는 여러 chunk를 묶어 rerank한다.

장점:

- 후보 다양성과 unique Knowledge coverage를 보존한다.
- 최종 결과 계약과 평가 단위가 일치한다.

위험:

- 잘못 선택한 대표 chunk 때문에 관련 Knowledge 점수가 낮아질 수 있다.
- 여러 chunk를 묶으면 model input이 길어진다.

### 6.3 Hierarchical

Knowledge별 chunk 수를 제한한 candidate를 rerank하고, chunk score를 Knowledge score로 집계한 뒤 최종
matched chunk를 선택한다. 집계 함수 후보는 max, top-N 평균, RRF score와의 결합이다. 복잡도가 높으므로
chunk-first/Knowledge-first baseline보다 실제 개선될 때만 선택한다.

## 7. Reranker 계약 후보

```text
RerankRequest
  query
  candidates
  candidate_limit
  final_limit
  strategy
  timeout
```

```text
RerankCandidate
  candidate_id
  chunk_id
  knowledge_id
  knowledge_revision
  title
  heading_path
  content
  retrieval_rank
  retrieval_score
  retrieval_channels
  sources
```

```text
RerankItem
  candidate_id
  rerank_rank
  rerank_score
  score_kind
```

```text
RerankTrace
  strategy
  model_id
  model_version
  candidate_count
  truncated_count
  latency_ms
  fallback_used
  failure_reason
```

계약 규칙:

- 결과 `candidate_id` 집합은 입력의 부분집합이어야 한다.
- 중복·알 수 없는 ID와 누락이 허용되는지를 strategy별로 고정한다.
- score가 logit, margin, probability-like sigmoid, ordinal feature인지 `score_kind`로 구분한다.
- model score를 서로 다른 reranker 사이에서 직접 비교하지 않는다.
- tie는 기존 retrieval rank와 `chunk_id`로 결정적으로 해소한다.
- content truncation 여부와 실제 model input hash를 trace에서 재현 가능하게 한다.
- provenance는 입력 candidate에서만 복사하고 model output에서 받지 않는다.

## 8. 후보 전략

| 구분 | 전략 | 목적 | 주요 위험 |
|---|---|---|---|
| 기준선 | 현재 keyword·vector RRF | 강한 무학습 fusion 기준 | 세밀한 relevance 판단 없음 |
| 후보 A | 결정적 feature reranker | 낮은 비용·재현성 | 수작업 weight 과적합 |
| 후보 B | local multilingual cross-encoder | query-chunk 상호작용 평가 | model 배포·추론 latency |
| 후보 C | hosted rerank API | 빠른 도입과 강한 model 비교 | 외부 의존·비용·privacy |
| 후보 D | LLM pointwise | 독립 scoring과 병렬화 | calibration·호출 비용 |
| 후보 E | LLM pairwise/listwise | 후보 간 직접 비교 | O(N²) 또는 position bias |
| 후보 F | reranker score + RRF score fusion | baseline 신호 보존 | score normalization 필요 |
| 후보 G | relevance rerank + MMR/dedup | 중복 감소·coverage 개선 | 최상위 relevance 희생 |

결정적 feature 후보에는 다음 신호를 검토할 수 있다.

- 기존 RRF rank
- query token의 title·heading·body coverage
- exact identifier와 path·error code 일치
- keyword와 vector 양쪽에서 회수되었는지
- 동일 Knowledge chunk 중복과 source coverage

weight는 직관으로 확정하지 않고 학습용·평가용 case를 분리해 sweep한다. feature 계산이 retrieval
알고리즘 변경으로 확대되지 않도록 rerank candidate 안의 정보만 사용한다.

## 9. Candidate 생성·최종 선택 Pipeline 후보

```text
keyword candidates ─┐
                    ├─ RRF candidate fusion
vector candidates  ─┘
                         ↓
                 candidate dedup/cap
                         ↓
                 relevance reranker
                         ↓
              Knowledge aggregation
                         ↓
             optional diversity selection
                         ↓
                  final Top-K
```

단계별 결정 항목:

- 각 retrieval channel에서 몇 개를 가져올지
- RRF 뒤 실제 rerank candidate 수
- Knowledge별 최대 chunk 수와 representative 선택
- reranker 이전과 이후 중 언제 exact duplicate를 제거할지
- reranker score만 사용할지 RRF와 결합할지
- final context를 relevance 순으로 둘지 diversity를 반영할지

Candidate Recall@N이 낮은 경우 N 또는 retriever를 먼저 개선해야 하며 reranker 결과로 문제를 감추지
않는다. 반대로 N을 무제한으로 늘리면 cross-encoder 비용과 noise가 커지므로 quality-latency curve로
선택한다.

## 10. Model 선택 기준

- 한글, 영문과 혼합 query의 relevance 성능
- class·method·endpoint·path·error code 보존 능력
- query-passage 최대 token과 truncation 방식
- CPU·GPU·Apple Silicon에서의 batch latency와 memory
- model weight 크기, license와 배포 방식
- offline 실행 가능 여부와 network 장애 의존성
- batch scoring, async cancellation과 timeout 지원
- score 정의와 version pinning 가능 여부

일반 benchmark 순위만으로 채택하지 않고 동일한 Clio golden candidate set에서 비교한다. embedding
provider와 reranker provider를 반드시 같게 맞출 필요는 없다.

## 11. Fallback과 관찰성

- reranker가 비활성화되면 현재 RRF 순위를 그대로 반환한다.
- timeout·model load·network·invalid output을 서로 다른 failure reason으로 기록한다.
- 일부 candidate score만 실패한 경우 전체 RRF fallback 또는 성공 candidate만 사용 중 하나를 계약으로
  고정한다. 조용한 부분 순위는 허용하지 않는다.
- listwise output은 입력 ID의 permutation 또는 허용된 subset인지 검증한다.
- candidate가 0개·1개면 불필요한 model 호출을 생략한다.
- trace에는 candidate 수, model input truncation, batch 수, latency와 fallback 여부를 남긴다.
- query와 chunk 전문을 일반 metric label에 기록하지 않는다.
- 외부 provider 사용 시 source content 전송 범위와 privacy 정책을 명시한다.

## 12. Benchmark 계약

### 12.1 평가 사례

- 제목·heading exact match가 중요한 질문
- 자연어 paraphrase로만 관련성을 알 수 있는 질문
- 한글 query와 영문 기술 문서가 연결되는 질문
- class·method·endpoint·path·error code 질문
- 같은 Knowledge에 유사 chunk가 많은 질문
- 여러 Knowledge·source 근거가 필요한 복합 질문
- top RRF chunk가 표면적으로 유사하지만 답할 수 없는 hard negative
- 긴 chunk 뒤쪽에 정답 근거가 있는 질문
- 후보에 정답이 없는 retrieval failure
- 정답이 여러 개인 graded relevance 질문
- corpus에 근거가 없는 unanswerable 질문

### 12.2 Candidate와 순위 지표

- candidate Recall@N과 candidate oracle nDCG
- 최종 Recall@5·Recall@8
- Top-1 accuracy, MRR, nDCG@5·nDCG@8
- 정답 source locator의 상위 노출률
- candidate에 정답이 있을 때의 conditional MRR·nDCG
- hard-negative demotion rate
- RRF 대비 정답 promotion·demotion count

### 12.3 Diversity·Context 지표

- final Top-K의 unique Knowledge 수
- 동일 Knowledge·source chunk 중복률
- required evidence·source coverage
- MMR 또는 cap으로 제거된 정답 비율
- 최종 context 문자·token 수
- 위치별 evidence 이용률과 downstream answer accuracy

### 12.4 안정성·운영 지표

- reranker 자체 및 전체 검색 P50/P95
- candidate 수별 latency·memory curve
- batch 수, model 호출 수와 token·추정 비용
- timeout·invalid output·fallback 비율
- 동일 입력 반복 시 순위 일치도
- listwise 입력 permutation에 대한 순위 안정성
- model load·warm-up 시간과 cold-start

### 12.5 Downstream 지표

- IA·분석 task success
- 필수 fact·constraint·component·source locator 식별률
- 근거 없는 분석 또는 잘못된 citation 비율
- reranking 전후 answer faithfulness와 context precision

후보 집합에 정답이 없는 사례는 reranker 실패율에 섞지 않고 candidate generation failure로 별도 보고한다.

## 13. 실험 통제

1. corpus, PCM revision, query, chunker, embedding model과 metadata 범위를 고정한다.
2. keyword·vector candidate와 RRF 순위를 fixture로 저장해 모든 reranker에 동일하게 제공한다.
3. candidate N, final K와 model input 길이를 명시한다.
4. 한 번에 reranker 또는 aggregation/diversity 요소 하나만 변경한다.
5. model·version·runtime·device·batch·precision과 warm/cold 조건을 기록한다.
6. 동일 candidate를 반복 평가해 nondeterminism을 측정한다.
7. 전체 평균뿐 아니라 언어, exact token, hard negative, multi-evidence slice를 함께 본다.
8. 유망 후보만 query rewrite 등 다른 개선과 조합해 candidate 분포 변화에 따른 성능을 재평가한다.

## 14. 범위

### 포함

- candidate retrieval과 reranking을 분리하는 Protocol·Pydantic 계약
- chunk-first, Knowledge-first, hierarchical aggregation 후보
- 결정적 feature, cross-encoder와 LLM reranker 후보
- candidate 수·batch·input length와 final K 설정
- score 의미, tie-breaker와 RRF score fusion 후보
- Knowledge cap, dedup과 MMR diversity 후보
- timeout·오류 시 명시적 RRF fallback
- 품질·coverage·안정성·latency·비용 benchmark

### 제외

- chunking, embedding model, metadata filter와 query rewrite 자체 변경
- reranker 학습·fine-tuning·distillation
- 새로운 검색 결과를 생성하는 generative fallback
- citation revision과 repository snapshot 계약 변경
- Issue Matcher의 AUTO_LINK·REVIEW 정책 또는 confidence 변경
- model score를 권한·정답 확률로 사용하는 것

## 15. 채택 Gate 초안

- candidate 외 ID 생성 0건
- snapshot·citation provenance 불일치 0건
- candidate Recall@N 측정과 retrieval/ranking failure 분리
- 최종 Recall@8 비회귀
- 목표 slice의 MRR·nDCG 또는 required-evidence coverage 개선
- exact identifier와 직접 질문 slice의 중대한 회귀 없음
- timeout·invalid output에서 RRF fallback 성공률 100%
- 동일 deterministic 후보의 순위 재현율 100%
- LLM listwise 후보는 입력 permutation 안정성이 계획 기준 이상
- P95, memory, token·호출 비용이 계획에서 정한 상한 이내

구체적인 개선 폭과 통계적 기준은 평가 사례 수와 반복 변동을 확인한 뒤 계획에서 고정한다.

## 16. 완료 조건

- retrieval candidate, rerank score와 final result가 별도 계약으로 표현된다.
- reranker는 입력 candidate와 provenance를 변경하거나 새로운 ID를 만들 수 없다.
- aggregation 단위와 Knowledge별 chunk cap의 의미가 문서와 테스트에 고정된다.
- 같은 입력과 결정적 reranker는 같은 최종 순서를 만든다.
- model input truncation, batch와 score kind를 재현할 수 있다.
- 오류·timeout·invalid output과 RRF fallback이 결과와 trace에서 구분된다.
- 외부 model 없이 unit·graph smoke test가 실행된다.
- benchmark가 candidate failure, ranking failure, diversity와 downstream 결과를 분리해 보고한다.

## 17. 주요 위험

- candidate N이 작으면 어떤 reranker도 정답을 복구할 수 없다.
- N을 과도하게 늘리면 model latency와 noise가 품질 이득을 상쇄한다.
- 같은 Knowledge의 유사 chunk가 candidate와 final context를 점유할 수 있다.
- representative chunk를 먼저 고르면 실제 정답 passage가 reranker 입력에서 사라질 수 있다.
- cross-encoder가 한글·영문 혼합과 code identifier를 일반 자연어와 다르게 처리할 수 있다.
- 긴 chunk truncation으로 정답 근거가 model input에서 제거될 수 있다.
- feature weight와 candidate N을 같은 평가셋에 맞추면 과적합된다.
- LLM listwise ranking은 position bias, invalid permutation과 결과 변동성이 있다.
- reranker score를 확률처럼 해석하면 downstream 정책이 과도하게 신뢰할 수 있다.
- relevance만 최대화하면 multi-evidence 질문의 diversity와 coverage가 낮아질 수 있다.
- 외부 rerank API는 source content privacy와 장애 의존성을 늘린다.
- fallback을 조용히 사용하면 운영 품질 저하를 발견하기 어렵다.

## 18. 후속 계획에서 결정할 항목

1. v1 candidate N, final K와 retrieval channel별 후보 수
2. chunk-first, Knowledge-first, hierarchical 중 비교할 aggregation 단위
3. Knowledge별 최대 chunk 수와 representative 선택 방식
4. 결정적 feature reranker의 신호와 weight 탐색 범위
5. local multilingual cross-encoder 후보와 실행 runtime
6. hosted API·LLM reranker를 실제 비교에 포함할지
7. pointwise, pairwise, listwise 중 허용할 LLM ranking 형식
8. reranker score만 사용할지 RRF score와 결합할지
9. dedup, MMR 또는 evidence quota를 final selection에 포함할지
10. model input의 title·heading·content 구성과 truncation 방식
11. timeout, partial failure와 fallback 결과 계약
12. 품질 이득 대비 허용 가능한 P95·memory·비용 상한

## 19. 참고 자료

- [Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)
- [Passage Re-ranking with BERT](https://arxiv.org/abs/1901.04085)
- [Document Ranking with a Pretrained Sequence-to-Sequence Model](https://aclanthology.org/2020.findings-emnlp.63/)
- [BAAI/bge-reranker-v2-m3 Model Card](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [Is ChatGPT Good at Search? Investigating LLMs as Re-Ranking Agents](https://aclanthology.org/2023.emnlp-main.923/)
- [Large Language Models are Effective Text Rankers with Pairwise Ranking Prompting](https://aclanthology.org/2024.findings-naacl.97/)
- [RankRAG: Unifying Context Ranking with Retrieval-Augmented Generation in LLMs](https://proceedings.neurips.cc/paper_files/paper/2024/hash/db93ccb6cf392f352570dd5af0a223d3-Abstract-Conference.html)
- [Lost in the Middle: How Language Models Use Long Contexts](https://aclanthology.org/2024.tacl-1.9/)
- [Found in the Middle: Permutation Self-Consistency Improves Listwise Ranking](https://aclanthology.org/2024.naacl-long.129/)
- [The Use of MMR, Diversity-Based Reranking for Reordering Documents](https://doi.org/10.1145/290941.291025)
