# Issue Retrieval Agent 결정 기록

## IR1. 데이터 접근

**결정:** Python Agent Graph가 같은 PostgreSQL에 직접 접근한다.

- `bugs`, `issues`, `issue_bugs`, `bug_occurrences`는 읽기 전용이다.
- Retrieval snapshot과 embedding은 Python이 소유한다.
- Issue 연결·생성은 Clio Server만 수행한다.

## IR2. 검색 단위

**결정:** 기존 Bug를 검색한 뒤 연결된 Issue별로 집계한다.

Issue 제목·요약은 검색 문서가 아니라 최종 후보 비교 문맥으로 사용한다.

## IR3. 대표 Bug 데이터

**결정:** `NormalizedReport`를 append-only JSON snapshot으로 보존한다.

검색 때 NM을 다시 실행하지 않는다. 새 정규화 결과가 명시적으로 색인될 때만 새 버전을 만들고 이전 snapshot
본문은 수정하지 않는다.

## IR4. Embedding 모델

**결정:** 전용 `EmbeddingModel` Protocol과 `CLIO_EMBEDDING_MODEL` 설정을 사용한다.

테스트에서만 결정적인 Fake를 사용하며 로컬 hashing embedding을 운영 fallback으로 사용하지 않는다.

## IR5. Snapshot·embedding 생성 시점

**결정:** 수집 요청과 분리된 비동기 indexing을 사용한다.

- 별도 공개 `bug_retrieval_indexer` graph가 한 Bug를 멱등하게 색인한다.
- `bug_retrieval_backfill` graph가 기존 Bug를 cursor 기반 batch로 정규화·색인한다.
- 실제 작업 큐 호출 배선은 Clio Server/Supervisor 연동 작업이 담당한다.

## IR6. 검색 채널

**결정:** exact signal, PostgreSQL `pg_trgm`, pgvector cosine 검색을 함께 사용한다.

검색 문서는 NM 필드만 고정 순서로 직렬화하며 `raw_payload`는 포함하지 않는다.

## IR7. 검색 결과 결합

**결정:** exact 2.0, lexical 1.0, vector 1.0 가중치와 상수 60의 weighted RRF를 사용한다.

이론상 최대 RRF 점수로 나눠 공개 `retrieval_score`를 0~1로 만든다.

## IR8. Issue 점수와 대표 Bug

**결정:** 최고 Bug 점수에 두 번째 0.10, 세 번째 0.05 비율의 제한된 보너스를 더한다.

대표 Bug는 fused score, exact 신호 수, occurrence count, bug ID 순으로 최대 3개 선택한다.

## IR9. 제외 규칙

**결정:** 현재 `bug_id`와 현재 Bug가 이미 연결된 모든 Issue를 제외한다.

모든 검색 SQL은 repository 최하단에서 `project_id`와 제외 조건을 강제한다.

## IR10. 부분 장애

**결정:** 필수 검색 채널 하나라도 기술적으로 실패하면 retrieval 전체를 실패시킨다.

특정 Bug에 compatible embedding이 없는 것은 해당 Bug의 vector hit 없음이다. 하지만 검색 corpus의 active index
coverage가 100%가 아니면 `IndexNotReady`로 실패해 불완전 검색을 신규 Issue로 숨기지 않는다.

## IR11. 실행 상한과 재시도

**결정:** 채널별 Bug 50개, fusion Bug 50개, hydration Issue 20개, 최종 Issue 5개를 기본값으로 한다.

- Issue당 대표 Bug는 최대 3개다.
- 외부 operation은 일시 실패에 한 번만 재시도한다.
- 설정·계약·model/dimension 오류는 재시도하지 않는다.
- subgraph 전체를 다시 실행하는 중복 retry는 제거한다.

## IR12. 검증

**결정:** Fake 기본 테스트, 선택 실행 PostgreSQL 통합 테스트, 실제 모델용 Recall@5·MRR 평가를 함께 둔다.

실제 embedding 설정이 없으면 평가 점수를 만들지 않고 명시적으로 건너뛴다.

## IR13. 스키마 소유와 DB 기술

**결정:** Alembic + SQLAlchemy Core + psycopg + pgvector로 Python migration과 query를 관리한다.

- `bug_retrieval_documents`와 새 `bug_embeddings`를 Python이 소유한다.
- 기존 JPA형 `bug_embeddings`가 있으면 `legacy_bug_embeddings`로 이름을 바꿔 보존한다.
- Clio Server의 기존 `refactor/drop-ai-only-entities` 브랜치를 사용해 Java의 AI 전용 JPA 엔티티를 제거한다.

## IR14. 공개 graph

**결정:** 기존 `clio_agent` 외에 다음 graph를 공개한다.

- `bug_retrieval_indexer`: 단일 NM snapshot 색인
- `bug_retrieval_backfill`: 기존 Bug를 cursor·batch 방식으로 재정규화·색인

## IR15. Issue 상태 범위

**결정:** `OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`를 모두 후보에 포함한다.

해결된 동일 버그의 재발도 기존 Issue 후보로 찾고 상태 정보는 RM 판단 문맥에 포함한다.
