# RAG 평가·개선 체계 실험 개요

## 1. 배경

현재 저장소에는 Issue Retrieval용 `Recall@5`, MRR 계산 코드와 2개의 JSON 사례가 있다. 이는 Bug를
Issue 후보로 회수하는 흐름의 최소 검증에는 유용하지만 PCM 지식검색의 chunk, metadata, query,
ranking과 citation 품질을 비교하기에는 범위와 사례 수가 부족하다.

Chunking, Metadata Filter, Reranking, Query Rewrite 브랜치를 독립적으로 개선하려면 같은 corpus와
질문, 같은 실행 조건으로 기준선과 후보를 반복 측정하는 공통 평가 계약이 먼저 필요하다.

## 2. 목표

PCM 지식검색의 품질·근거·비용을 재현 가능하게 측정하는 평가셋과 runner를 만든다. 평가 결과는
“좋아 보인다”는 주관적 판단이 아니라 브랜치별 채택·보류·폐기 결정을 뒷받침하는 비교 자료가 되어야
한다.

## 3. 평가 계층

### 3.1 Retrieval 평가

정답 `knowledge_id`, source locator 또는 허용 가능한 복수 근거가 Top-K에 들어왔는지 측정한다.

- Recall@K
- MRR
- nDCG@K
- Precision@K 또는 관련 없는 결과 비율

### 3.2 Citation·근거 평가

반환된 근거가 고정 snapshot과 일치하고 실제 정답 범위를 가리키는지 측정한다.

- PCM revision 일치율
- source ID·revision·locator 정확도
- 답을 뒷받침하는 근거 포함률
- 근거 없는 답 또는 잘못된 citation 비율

### 3.3 운영 지표

- 색인 시간과 embedding 입력량
- 검색 P50/P95
- 모델·embedding 호출 수, token 또는 추정 비용
- timeout, degraded keyword-only, stale index 발생률

최종 답변의 문장 품질 평가는 retrieval 지표와 분리한다. 초기에는 결정적으로 계산 가능한 retrieval과
citation 지표를 우선하고 LLM-as-a-judge는 보조 분석으로만 검토한다.

## 4. 평가셋 계약

각 사례는 최소한 다음 정보를 가진다.

```text
case_id
query
query_slice
filters(optional)
relevant_knowledge_ids
relevant_source_locators(optional)
forbidden_knowledge_ids(optional)
notes
```

평가 corpus는 고정된 project, PCM revision, 문서 revision과 embedding model 정보를 manifest로
기록한다. 정답이 하나뿐이라고 가정하지 않고 동일한 답을 지지하는 복수 Knowledge를 허용한다.

필수 query slice:

- 직접 표현과 paraphrase
- heading 경계와 긴 문서
- 표·목록·코드 블록
- metadata로 범위를 좁혀야 하는 질문
- class·method·endpoint·error code가 포함된 질문
- 모호한 질문과 정답 없음
- 한글·영문 혼합 질문

## 5. 범위

### 포함

- Pydantic 기반 corpus/evaluation case/result 계약
- PCM 검색 port를 주입할 수 있는 deterministic runner
- slice별 지표와 전체 macro 지표
- 기준선과 후보 결과의 JSON 비교 보고서
- 반복 실행, warm-up, latency 측정 규칙
- 잘못된 fixture, 중복 ID, snapshot 불일치 검증
- 작은 smoke fixture와 확장 가능한 실제 평가 fixture 분리

### 제외

- 평가 결과에 맞춘 검색 알고리즘 구현
- production 사용자 로그의 무단 수집
- LLM judge 점수를 유일한 merge 기준으로 사용
- 서로 다른 embedding model 결과를 같은 실험으로 직접 비교
- 대시보드나 온라인 A/B 테스트 인프라

## 6. 브랜치 비교 절차

1. 평가 corpus와 fixture version을 고정한다.
2. `main` 기준선의 commit SHA와 환경 정보를 기록한다.
3. 각 개선 브랜치에서 동일한 평가 runner와 설정을 사용한다.
4. warm-up 후 같은 반복 횟수로 품질·지연 결과를 JSON으로 저장한다.
5. 한 번에 하나의 RAG 요소만 기준선과 다르게 유지한다.
6. 전체 평균과 query slice별 회귀를 함께 확인한다.
7. 채택 후보만 통합 브랜치에서 조합 효과와 전체 회귀를 다시 측정한다.

평가 runner와 fixture가 안정되면 알고리즘 변경 없이 공통 기준으로 사용할 수 있도록 main 반영 또는
각 실험 브랜치의 동일 commit 적용 방식을 결정한다. 서로 다른 evaluator version의 결과는 직접 비교하지
않는다.

## 7. 채택 Gate 초안

- snapshot·citation 불일치 0건
- 정답 없음 사례의 허위 근거 0건
- 전체 Recall@8 비회귀
- 목표 query slice의 MRR 또는 nDCG 개선
- 비목표 slice의 중대한 회귀 없음
- P95와 호출 비용이 사전에 정한 상한 이내

구체적인 수치와 통계적 판정 방식은 평가 사례 수와 반복 변동을 확인한 후 계획 문서에서 고정한다.

## 8. 완료 조건

- 외부 live LLM 없이 smoke 평가가 실행된다.
- PostgreSQL·embedding을 사용하는 실제 평가는 명시적 설정에서만 실행된다.
- 같은 fixture, commit, 설정은 동일한 품질 지표를 만든다.
- 결과 파일에 commit SHA, fixture version, corpus snapshot, 주요 설정이 포함된다.
- 실패, SKIPPED, 정상 0건이 서로 다른 상태로 기록된다.
- 네 개의 알고리즘 개선 브랜치를 같은 계약으로 비교할 수 있다.

## 9. 주요 위험

- 사례 수가 적거나 쉬우면 변경의 실제 차이를 보여주지 못한다.
- 평가셋에 맞춘 과적합이 일반 질문 성능을 악화시킬 수 있다.
- 정답 Knowledge만 표시하고 source locator를 생략하면 citation 품질을 과대평가할 수 있다.
- 환경과 cache를 고정하지 않으면 latency 비교가 흔들린다.
- evaluator를 변경하면서 과거 결과와 같은 이름으로 저장하면 추세를 잘못 해석할 수 있다.

## 10. 후속 계획에서 결정할 항목

1. 초기 평가 사례 수와 corpus 선정 방식
2. relevant source locator의 표현과 복수 정답 gain
3. nDCG relevance 등급을 binary로 둘지 graded로 둘지
4. latency 반복 횟수, warm-up과 cache 정책
5. 결과 비교 보고서 형식과 merge gate 수치
6. 공통 evaluator를 실험 브랜치에 동일하게 배포하는 방식
