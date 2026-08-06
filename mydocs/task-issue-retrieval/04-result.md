# Issue Retrieval Agent 구현 결과

## 완료된 흐름

```text
NormalizedReport
  → exact / pg_trgm / pgvector 병렬 검색
  → exact 2.0, lexical 1.0, vector 1.0 weighted RRF
  → Bug hit를 Issue별 집계
  → 대표 Bug 최대 3개
  → Issue 후보 최대 5개
  → RM 비교·정책
```

기존 callback placeholder는 Fake 호환 경계로 남겼고 기본 `clio_agent`는 실제 PostgreSQL·embedding adapter를
사용한다. 실제 객체와 연결은 최초 invoke까지 지연된다.

## 저장과 공개 graph

- Alembic이 `bug_retrieval_documents`, `bug_embeddings`, `vector`, `pg_trgm`을 관리한다.
- 기존 JPA형 `bug_embeddings`는 `legacy_bug_embeddings`로 이름을 바꿔 보존한다.
- `NormalizedReport` 본문은 append-only version snapshot으로 남기고 active 표시만 전환한다.
- 같은 document hash·embedding model은 `UNCHANGED`로 멱등 처리한다.
- `bug_retrieval_indexer`가 단일 NM 결과를 색인한다.
- `bug_retrieval_backfill`이 기존 Bug를 기본 20개, 최대 100개 cursor batch로 재정규화·색인한다.
- Python은 도메인 테이블을 읽기만 하며 Issue 연결·생성은 수행하지 않는다.

## 안전 정책

- project, 현재 Bug, 이미 연결된 Issue 제외를 SQL에서 강제한다.
- OPEN·IN_PROGRESS·RESOLVED·CLOSED Issue를 모두 검색한다.
- eligible Bug의 compatible active index coverage가 100%가 아니면 `RetrievalIndexNotReadyError`로 실패한다.
- 세 검색 채널 중 하나의 기술 실패도 후보 없음으로 숨기지 않는다.
- 외부 operation은 한 번 재시도하고 설정·데이터·dimension 오류는 재시도하지 않는다.
- raw payload는 검색 문서에 넣지 않는다.

## 검증 결과

- 기본 test suite: 99개 수집, 98 passed, PostgreSQL 선택 테스트 1 skipped
- 실제 `pgvector/pgvector:pg16` 선택 테스트: passed
  - legacy table 보존과 Alembic migration
  - exact signal SQL
  - 한글·기술 문자열 `pg_trgm`
  - pgvector cosine 순위
  - CLOSED Issue와 대표 Bug hydration
- `ruff check .`: passed
- `ruff format --check .`: passed
- 실제 embedding 설정이 없는 평가 실행: 의도대로 `SKIPPED`

## 남은 연동

- Clio Server/Supervisor가 NM 완료 뒤 `bug_retrieval_indexer`를 비동기로 호출해야 한다.
- 운영 전 `bug_retrieval_backfill`을 `has_more=false`까지 완료해야 한다.
- Clio Server의 `refactor/drop-ai-only-entities` 브랜치를 사용해 Java의 AI 전용 JPA entity를 제거한다.
- 실제 프로젝트 평가 데이터로 Recall@5·MRR 기준선을 수집하고 weight·threshold를 보정한다.
