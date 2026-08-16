# RAG Chunking 개선 실험 개요

## 1. 배경

PCM 지식검색은 `KnowledgeDocument`를 검색 단위인 `KnowledgeChunk`로 바꾼 뒤 keyword와
vector 검색에 사용한다. 현재 `MarkdownKnowledgeChunker`는 heading별 section을 만들고,
1,800자를 넘는 section을 문단 경계에서 나눈다. 문단 하나가 제한보다 길면 고정 문자 수로
자르며 각 chunk 앞에 문서 제목과 heading 경로를 붙인다.

이 방식은 결정적이고 단순하지만 다음 한계가 있다.

- token 수가 아닌 문자 수 기준이어서 언어와 코드 비율에 따라 실제 embedding 입력 크기가 달라진다.
- 긴 문단, 표, 목록, 코드 블록이 의미 경계와 무관하게 잘릴 수 있다.
- 인접 chunk 사이의 문맥 연결이 없어서 경계에 걸친 답을 놓칠 수 있다.
- 제목과 heading 문맥을 매 chunk에 추가한 뒤의 최종 크기는 제한에 포함되지 않는다.
- chunk 크기와 검색 품질·색인 비용의 관계를 측정하는 기준선이 없다.

## 2. 목표

문서 구조를 보존하는 chunking 후보를 만들고 현재 방식과 같은 데이터·embedding·검색 설정에서
비교한다. 목표는 단순히 chunk를 더 작게 만드는 것이 아니라, 정답 근거가 검색 상위권에 포함될
확률을 높이면서 색인 크기와 검색 지연 증가를 제한하는 것이다.

## 3. 실험 가설

Markdown의 heading, 문단, 목록, 표, fenced code block을 원자 단위로 인식하고 제한된 overlap을
적용하면 다음 결과를 기대할 수 있다.

1. 경계에 걸친 질문의 Recall@K와 MRR이 현재 기준선보다 높아진다.
2. 검색된 chunk가 정답 source locator를 포함하는 비율이 높아진다.
3. chunk 수와 embedding 비용 증가는 허용 범위 안에 유지된다.

## 4. 범위

### 포함

- 현재 `markdown-heading-v1`을 변경하지 않고 비교 가능한 새 chunker version 추가
- Markdown 구조별 분할 정책과 전체 입력 크기 예산 정의
- overlap 크기와 적용 조건의 설정화
- 빈 문서, tombstone, 긴 단일 블록, 한글·영문 혼합 문서 처리
- chunk ID 결정성, content hash, 재색인 동작 검증
- 기준선과 후보 전략의 품질·비용 benchmark

### 제외

- embedding provider나 dimension 변경
- metadata filter, query rewrite, reranking 변경
- RRF 공식과 검색 SQL 가중치 변경
- 운영 데이터 호환을 위한 migration 누적

현재는 pre-MVP이므로 schema 호환 migration보다 새 DB에서 두 chunker version을 재현 가능하게
비교하는 것을 우선한다.

## 5. 비교 대상

| 구분 | 전략 |
|---|---|
| 기준선 | heading + 문단 + 1,800자 hard split |
| 후보 A | Markdown block-aware + 최종 입력 크기 예산 |
| 후보 B | 후보 A + 제한된 인접 overlap |

후보 수는 구현 단계에서 늘릴 수 있지만, 한 실험에서 chunking 외의 검색 조건은 고정한다.

## 6. Benchmark 계약

공통 평가 corpus와 질문별 정답 `knowledge_id`, source locator 또는 정답 chunk 범위를 준비한다.
각 전략은 동일 snapshot, embedding model, keyword/vector 후보 수, RRF 설정으로 평가한다.

주요 지표:

- Recall@5, Recall@8
- MRR, nDCG@8
- 정답 source locator 포함률
- 문서당 chunk 수와 전체 embedding 입력량
- 색인 시간, 검색 P50/P95
- 경계 질문과 긴 코드·표 질문의 별도 성능

초기 채택 기준은 기준선 대비 Recall@8과 nDCG@8이 악화되지 않고, 경계 질문 성능이 개선되며,
전체 chunk 수 증가가 측정된 이득에 비해 과도하지 않은 것이다. 최종 수치는 평가셋 규모를 확인한
뒤 계획 문서에서 고정한다.

## 7. 완료 조건

- 기준선과 후보 chunker를 설정으로 교체해 같은 corpus를 재색인할 수 있다.
- 구조 블록이 의도치 않게 유실되지 않고 overlap 중복은 명시적으로 추적된다.
- 같은 입력과 설정은 동일한 chunk ID와 순서를 만든다.
- 단위 테스트와 PostgreSQL 색인 경계 테스트가 통과한다.
- 공통 benchmark 결과에 품질, 비용, 지연을 함께 기록한다.
- 결과가 기준선을 이긴 경우에만 merge 후보로 추천한다.

## 8. 주요 위험

- overlap이 keyword 점수와 vector 후보를 중복 강화할 수 있다.
- 지나치게 작은 chunk는 근거를 잘 찾더라도 답변에 필요한 문맥을 잃을 수 있다.
- 코드 블록 전체 보존은 입력 제한을 다시 초과할 수 있다.
- chunker version 변경은 전체 재색인을 요구하므로 실험 비용을 별도로 기록해야 한다.

## 9. 후속 계획에서 결정할 항목

1. 문자 수, token 추정치, 실제 tokenizer 중 어떤 예산을 사용할지
2. 표·목록·코드 블록의 원자성 우선순위
3. overlap 단위와 최대 비율
4. parent heading 문맥을 본문에 포함할지 별도 metadata로 보낼지
5. 채택 임계치와 허용 가능한 색인 비용 증가율
