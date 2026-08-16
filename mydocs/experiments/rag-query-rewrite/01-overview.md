# RAG Query Rewrite 개선 실험 개요

## 1. 배경

PCM 검색은 `KnowledgeSearchRequest.query` 하나를 그대로 embedding query와 PostgreSQL
`plainto_tsquery`·trigram 입력으로 사용한다. 질문이 너무 길거나, 지식 문서와 다른 표현을 쓰거나,
코드 식별자와 자연어가 섞이면 정답 Knowledge가 후보에 포함되지 않을 수 있다.

현재 Agent가 Tool 호출 전에 검색어를 스스로 고를 수는 있지만, 어떤 변환을 했는지 재현하거나 원래
질의와 비교할 계약이 없다. 검색 실패와 Agent의 검색어 선택 실패도 구분하기 어렵다.

## 2. 목표

원본 질문을 보존하면서 검색에 적합한 소수의 query variant를 만드는 명시적 rewrite 단계를 추가하고,
paraphrase·장문·코드 식별자 질문의 후보 Recall이 개선되는지 기준선과 비교한다. rewrite가 원문에 없는
프로젝트 사실이나 답을 만들어 검색을 오염시키지 않게 한다.

## 3. 실험 가설

질문을 핵심 자연어, 정확 식별자, 보조 표현으로 제한적으로 분해하고 각 결과를 융합하면 단일 query보다
Recall@K가 높아진다. 원본 query를 항상 포함하고 variant 수와 호출 비용을 제한하면 precision과 지연
악화를 제어할 수 있다.

## 4. 후보 전략

| 구분 | 전략 |
|---|---|
| 기준선 | 원본 query 한 개 |
| 후보 A | 결정적 정규화·식별자 추출·긴 질문 축약 |
| 후보 B | 원본 + 제한된 model rewrite 또는 multi-query |

후보 A는 대소문자·공백 정리, path·symbol·error code 같은 정확 token 보존과 질문의 부가 문구 제거를
중심으로 한다. 후보 B를 사용하면 모델은 검색 질의만 반환하며 root cause, 존재하지 않는 component,
답변 문장을 생성하지 못하도록 structured output으로 제한한다.

## 5. 범위

### 포함

- 원본 query와 rewrite variant를 구분하는 Pydantic 계약
- rewrite service와 선택적 model adapter의 지연 초기화
- variant별 keyword/vector 검색 결과의 결정적 결합
- 최대 variant 수, 길이, timeout, 중복 제거
- rewrite 실패 시 원본 query만 사용하는 명시적 fallback
- rewrite trace의 안전한 관찰 정보와 benchmark

### 제외

- 대화 전체를 장기 기억으로 바꾸는 conversational memory
- 원문에 없는 domain synonym을 운영 코드에 무제한 하드코딩
- chunking, embedding, metadata filter, reranking 변경
- rewrite 결과를 citation 또는 사실 근거로 사용하는 것
- 검색 결과가 없다는 이유로 외부 웹 검색을 수행하는 것

## 6. Architecture 경계

Rewrite는 검색 adapter 내부의 숨은 prompt가 아니라 별도 port/service로 둔다. graph가 고정한 project와
snapshot은 rewrite 입력에 주지 않거나 읽기 전용 context로만 제공한다. 모델 adapter는 query variant만
반환하고 실제 검색, filter 선택, 결과 융합은 service가 결정한다.

실행 결과에는 최소한 원본 사용 여부, 생성된 variant 수, fallback 여부를 남긴다. 민감한 원문 전체나
모델 내부 추론은 로그에 저장하지 않는다.

## 7. Benchmark 계약

평가셋을 다음 query slice로 나누어 결과를 따로 본다.

- 문서 표현과 거의 같은 직접 질문
- 의미는 같지만 표현이 다른 paraphrase
- 긴 현상 설명과 여러 조건이 섞인 질문
- class, method, endpoint, error code가 포함된 질문
- 정보가 부족하거나 모호해 rewrite가 이득을 주면 안 되는 질문

같은 corpus, snapshot, chunker, embedding, filter, RRF와 최종 limit에서 rewrite 전략만 바꾼다.

주요 지표:

- Recall@5/8, MRR, nDCG@8과 query slice별 변화
- 원본 기준 정답 유실률
- 관련 없는 Knowledge 유입률 또는 precision@K
- 요청당 검색 횟수와 모델 호출 수
- 전체 P50/P95, token 또는 추정 비용
- rewrite validation·timeout 실패 시 원본 복구율

## 8. 완료 조건

- 원본 query가 모든 전략에서 보존되고 추적 가능하다.
- 같은 입력과 결정적 rewriter는 같은 variant와 순서를 만든다.
- variant 수와 길이가 계약상 상한을 넘지 않는다.
- model output은 Pydantic으로 검증되고 입력에 없는 식별자 생성 위험을 테스트한다.
- 실패 시 정상 0건으로 위장하지 않고 원본 검색 fallback 여부가 드러난다.
- benchmark가 slice별 품질과 추가 지연·비용을 함께 보고한다.

## 9. 주요 위험

- 잘못된 synonym이나 가상의 component를 추가하면 그럴듯하지만 틀린 결과가 상위에 올 수 있다.
- multi-query가 같은 문서를 여러 번 강화해 다양성을 낮출 수 있다.
- 직접 질문은 rewrite가 오히려 정확 token을 잃게 만들 수 있다.
- 모델 의존 rewrite는 지연과 장애 지점을 늘리고 결과 재현성을 낮춘다.
- query trace가 원본 사용자 입력을 그대로 기록하면 민감 정보가 남을 수 있다.

## 10. 후속 계획에서 결정할 항목

1. 결정적 rewrite에서 보존할 exact token 규칙
2. model rewrite를 실제 후보로 포함할지
3. 최대 variant 수와 variant별 후보 수
4. 여러 query 결과의 RRF 가중치와 중복 강화 방지 방식
5. rewrite trace를 공개 결과, 내부 상태, metric 중 어디까지 노출할지
