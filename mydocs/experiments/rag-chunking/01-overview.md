# RAG 입력별 Chunking 전략 비교 실험 개요

## 1. 배경

Clio에는 서로 다른 데이터를 다루는 검색·지식 처리 경로가 있다. 이 경로들은 모두 넓은 의미의
RAG 또는 프로젝트 컨텍스트 처리에 참여하지만, 실제 검색 단위와 chunking 목적은 같지 않다.

```text
Bug Retrieval
  NormalizedReport → Bug 검색 문서 → exact + pg_trgm + pgvector

PCM Knowledge Retrieval
  문서 또는 repository-derived Knowledge → Markdown chunk → FTS + trigram + pgvector

Repository Knowledge Ingestion
  Git repository → 코드 Source Unit → LLM Knowledge 추출 → PCM commit

Codebase Exploration
  Issue → repository 목록·검색·부분 읽기 → 코드 Evidence
```

현재 `workflows/reporting/retrieval`은 Bug 하나의 `NormalizedReport`를 하나의 검색 문서로
투영하므로 별도 chunking을 하지 않는다. PCM 검색은 생성된 `KnowledgeDocument`를 heading과
문단 기준의 `KnowledgeChunk`로 나눈다. Repository ingestion은 raw code를 최대 120줄 또는
8,000자 단위의 `RepositorySourceUnit`으로 나누지만, 이 단위는 직접 검색되는 vector chunk가
아니라 LLM이 Knowledge를 생성하기 위한 입력이다. Codebase Exploration은 현재 code vector
index를 사용하지 않고 고정 commit의 repository를 직접 탐색한다.

따라서 하나의 chunking 전략을 모든 경로에 적용하면 입력 구조와 처리 목적의 차이를 잃는다.
공통 조건에서 여러 후보를 비교하되, 최종 전략은 경로별로 선택해야 한다.

## 2. 현재 방식의 한계

### Bug Retrieval

- 증상, 재현 조건, 환경, 오류 신호와 stack frame을 하나의 `search_text`로 합쳐 단일 embedding을
  만든다.
- Bug가 짧고 응집된 경우에는 적절하지만, 긴 report에서는 중요한 오류 신호가 다른 설명에
  희석될 수 있다.
- 개선 대상은 일반적인 text chunking보다 필드별 표현과 점수 집계 방식에 가깝다.

### PCM Knowledge Retrieval

- 현재 `markdown-heading-v1`은 1,800자 제한을 사용하므로 실제 embedding token 수와 차이가 난다.
- 긴 문단, 목록, 표와 fenced code block이 의미 경계와 무관하게 잘릴 수 있다.
- 제목과 heading 경로를 chunk에 추가한 뒤의 최종 입력 크기는 제한에 포함되지 않는다.
- 인접 chunk 문맥이나 작은 검색 단위와 큰 반환 단위를 분리하는 parent-child 구조가 없다.

### Repository Knowledge Ingestion

- 최대 120줄 또는 8,000자 기준은 클래스·메서드·함수 같은 코드 symbol 경계를 보존하지 않는다.
- 선언부와 구현부, 호출부와 관련 테스트가 서로 다른 Source Unit으로 나뉠 수 있다.
- `.md`, `.yaml`, `.toml`, `.sql` 등 구조가 다른 파일도 같은 `_code_chunks()` 경로를 사용한다.
- Source Unit 품질이 나쁘면 이후 Knowledge 추출의 누락·중복·환각으로 이어질 수 있다.

### Codebase Exploration

- 현재는 repository Tool을 이용한 직접 탐색이므로 chunking 전략 비교 대상이 아니다.
- 향후 code vector index를 도입할 경우 별도의 Code RAG 실험으로 다룬다.

## 3. 목표

1. RAG라는 이름 아래 섞여 있는 검색 단위와 Source Unit의 책임을 명확히 구분한다.
2. 현재 구현을 기준선으로 유지하고 경로별 후보 전략을 동일 조건에서 비교한다.
3. 검색 품질뿐 아니라 Knowledge 추출 품질, 입력량, 색인 비용과 지연을 함께 측정한다.
4. 실험 결과를 근거로 각 경로의 기본 전략을 선택한다.
5. 채택 전략이 달라도 공통 metadata와 version 계약으로 재색인과 재현이 가능하게 한다.

## 4. 실험 트랙

### 4.1 Bug Retrieval 표현 비교

Bug는 이미 하나의 완결된 의미 단위이므로 임의의 길이로 나누지 않는다. 대신 다음 검색 표현을
비교한다.

| 구분 | 전략 |
|---|---|
| 기준선 | 전체 `NormalizedReport`를 하나의 `search_text`와 embedding으로 저장 |
| 후보 A | 증상·재현·환경과 오류 신호·stack frame을 필드 그룹별 vector로 분리 |
| 후보 B | 후보 A의 검색 결과를 Bug 또는 Issue 단위로 집계하는 multi-vector 검색 |

이 트랙은 chunker 구현보다 Bug 검색 문서와 embedding persistence 계약 변경에 가깝다. 다른
트랙과 한 변경으로 묶지 않고, 단일 표현의 검색 한계가 평가에서 확인될 때 후속 실험으로 진행한다.

### 4.2 PCM Knowledge Chunking 비교

| 구분 | 전략 |
|---|---|
| 기준선 | heading + 문단 + 1,800자 hard split |
| 후보 A | heading → block → 문장 → token 순서의 recursive split |
| 후보 B | 후보 A + 경계가 강제로 분할된 경우에만 제한된 overlap |
| 후보 C | 작은 child chunk로 검색하고 상위 heading section을 반환하는 parent-child |
| 후속 후보 | 문장 embedding의 의미 변화에 따른 semantic chunking |

Markdown heading, 문단, 목록, 표와 fenced code block을 구조 단위로 인식한다. Token 예산은 제목과
전체 heading 경로를 포함한 최종 embedding 입력에 적용한다. Semantic chunking은 embedding 비용과
경계 threshold 튜닝이 필요하므로 recursive와 parent-child의 한계가 확인된 뒤 검토한다.

### 4.3 Repository Source Unit 비교

| 구분 | 전략 |
|---|---|
| 기준선 | 최대 120줄 또는 8,000자 fixed-line split |
| 후보 A | 언어별 class·function·method 구분자를 사용하는 recursive split |
| 후보 B | parser 또는 AST가 식별한 symbol 단위 split |
| fallback | 지원하지 않는 언어와 parse 실패 파일에만 token/line 제한 적용 |

Symbol이 token 예산을 초과할 때만 내부 block 또는 token 기준으로 재분할한다. 각 Source Unit에는
최소한 다음 provenance를 유지한다.

- `repository_id`, commit SHA, 파일 경로와 언어
- package, class, method 또는 function 이름
- 시작·종료 line과 parent symbol ID
- content hash와 chunker version

문서 파이프라인과 책임이 겹치지 않도록 `.md` 같은 문서형 파일을 Repository Source Unit에 포함할지,
별도 문서 경로로 보낼지 계획 단계에서 결정한다. 설정·schema 파일은 파일 형식별 구조 보존 전략 또는
명시적인 fallback을 사용한다.

## 5. 설계 원칙

- 동일 알고리즘을 강제하지 않고 source type과 목적에 맞는 전략을 선택한다.
- 전략 교체 지점은 공통 chunk 계약 뒤에 두고 provider·parser 세부사항을 domain 모델에 노출하지 않는다.
- 같은 source revision과 설정은 동일한 chunk 순서, ID와 content hash를 만든다.
- chunk에는 원문으로 돌아갈 수 있는 provenance와 parent 관계를 보존한다.
- overlap은 모든 경계에 일괄 적용하지 않고 강제 분할로 문맥 손실이 발생하는 구간에 제한한다.
- embedding 모델, 검색 후보 수, RRF 설정과 reranking은 chunking 비교 동안 고정한다.
- 한 실험에서는 chunking 외 변수를 바꾸지 않는다.

후보 구현은 개념적으로 다음과 같은 교체 가능한 책임으로 분리할 수 있다.

```text
BugSearchDocumentProjector
KnowledgeChunker
  ├─ MarkdownHeadingChunker
  ├─ MarkdownRecursiveChunker
  └─ MarkdownParentChildChunker

RepositorySourceChunker
  ├─ FixedLineSourceChunker
  ├─ LanguageRecursiveSourceChunker
  ├─ SymbolSourceChunker
  └─ FixedSizeFallbackChunker
```

Bug 검색 표현, PCM 검색 chunk와 Repository Source Unit은 목적과 persistence가 다르므로 하나의
`Chunker` 계층으로 억지로 통합하지 않는다. 공통화는 ID·revision·provenance·version 같은 관찰 가능한
계약에 한정한다.

## 6. Benchmark 계약

모든 비교는 공통 corpus와 고정된 snapshot에서 수행한다. 전략별로 동일 embedding model, keyword/vector
후보 수, RRF 설정과 Top-K를 사용한다. 평가 데이터에는 질문뿐 아니라 정답 Bug·Issue, Knowledge,
source locator 또는 코드 symbol을 명시한다.

### Bug Retrieval

- 정답 Issue Recall@5
- MRR과 nDCG@5
- 잘못된 `AUTO_LINK` 및 후보 누락 비율
- Bug당 embedding 수와 검색 P50/P95

### PCM Knowledge Retrieval

- 정답 Knowledge Recall@5, Recall@8
- MRR과 nDCG@8
- 정답 source locator 포함률과 context precision
- 문서당 chunk 수와 전체 embedding token 수
- 색인 시간과 검색 P50/P95
- 경계 질문, 긴 표·목록·코드 블록 질문의 별도 성능

### Repository Knowledge Ingestion

- 기준 Knowledge fact의 추출 recall과 근거 source 일치율
- 누락·중복·근거 없는 Knowledge 비율
- 파일 및 symbol coverage
- repository당 Source Unit 수와 LLM 입력 token 수
- Knowledge 생성 시간과 재처리 비용

전략별 품질을 직접 비교할 수 없는 트랙은 하나의 종합 점수로 합치지 않는다. 검색 chunk는 retrieval
지표로, Repository Source Unit은 Knowledge extraction 지표로 각각 판단한다.

## 7. 범위

### 포함

- 현재 전략을 변경하지 않고 재현 가능한 기준선으로 고정
- PCM Knowledge와 Repository Source Unit의 후보 전략 및 version 추가
- 경로별 공통 평가 corpus와 deterministic benchmark 구축
- token 예산, overlap 적용 조건, parent-child 반환 범위 비교
- 빈 입력, tombstone, 긴 단일 block, 한글·영문 혼합, parser 실패 처리
- chunk ID 결정성, content hash, provenance와 재색인 동작 검증

### 제외

- embedding provider와 dimension 변경
- query rewrite, reranking, metadata filter와 RRF 가중치 튜닝
- Codebase Exploration을 vector RAG로 교체하는 작업
- repository 변경 이벤트의 Knowledge reconciliation 구현
- 모든 경로를 하나의 chunker 구현으로 통합하는 리팩터링
- 실험 결과 없이 기존 기본 전략을 즉시 교체하는 작업

현재는 pre-MVP이므로 운영 migration 호환보다 새 DB에서 전략별 색인을 재현하고 비교하는 것을
우선한다. Persistence schema 변경이 필요한 Bug multi-vector와 parent-child 실험은 각각 별도 계획에서
결정한다.

## 8. 완료 조건

- 세 실험 트랙의 입력, 출력과 평가 지표가 서로 구분되어 있다.
- 기준선과 후보 전략을 같은 corpus와 설정으로 반복 실행할 수 있다.
- 구조 block과 code symbol이 의도치 않게 유실되지 않는다.
- 같은 입력과 설정은 동일한 chunk 또는 Source Unit ID와 순서를 만든다.
- 단위 테스트와 필요한 PostgreSQL 색인 경계 테스트가 통과한다.
- 결과 문서에 품질, 비용, 지연과 실패 사례를 함께 기록한다.
- 후보가 기준선을 이긴 경우에만 기본 전략 변경을 추천한다.

## 9. 주요 위험

- overlap과 parent 확장이 중복 검색 결과와 context 비용을 증가시킬 수 있다.
- 작은 chunk는 검색 정밀도를 높여도 최종 판단에 필요한 문맥을 잃을 수 있다.
- 큰 code symbol과 fenced code block은 구조를 보존한 채 token 제한을 지키기 어렵다.
- 언어별 parser 결과가 다르면 chunk ID 안정성과 fallback 결과가 달라질 수 있다.
- Source Unit 개선이 실제 Knowledge 품질로 이어지지 않으면 parser 복잡도만 증가할 수 있다.
- 여러 트랙을 동시에 구현하면 chunking 외 변수가 섞여 실험 결과의 원인을 설명하기 어려워진다.

## 10. 후속 계획에서 결정할 항목

1. 첫 구현 트랙을 PCM Knowledge와 Repository Source Unit 중 어디로 정할지
2. 실제 tokenizer와 token 추정치 중 어떤 예산 계산을 사용할지
3. Markdown 표·목록·코드 블록의 원자성 우선순위
4. 지원할 코드 언어와 parser, symbol 종류의 최소 범위
5. 큰 symbol 재분할 방식과 fallback 발동 조건
6. `.md`, 설정·schema 파일의 source type 분류와 라우팅 책임
7. overlap 단위와 최대 비율, parent 반환 범위
8. 트랙별 채택 임계치와 허용 가능한 비용 증가율
9. Bug multi-vector와 PCM parent-child에 필요한 persistence 변경 범위
