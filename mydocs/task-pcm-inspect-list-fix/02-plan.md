# PCM 메모리 조회 목록 버그 수정 — 구현 계획

## 1. 단계

1. overview 작성·확정·커밋
2. plan 작성·확정(이 문서)
3. 결정 포인트를 하나씩 결정하고 03-decisions에 기록
4. 결정별 구현·테스트·커밋
5. 04-result 작성·커밋
6. PR(base=main)

## 2. 결정 포인트

### D1. 브랜치 전략

- 선택지: 기존 `task/pcm-inspect-ui`에 수정 / main에서 새 브랜치 분기
- 추천: main에서 분기. inspect API가 main에 머지됐으므로 규칙에 맞는 경로다.
- 상태: 사용자 머지 후 `task/pcm-inspect-list-fix`로 확정.

### D2. 수정 범위

- 선택지 A: 코드 수정 + Postgres 회귀 테스트만
- 선택지 B: A + inspect 서버 실행 문서 보강(`uvicorn`이 `.env`를 자동으로 읽지 않아
  `--env-file` 또는 env 로딩 방법을 README에 명시)
- 추천: B. 오늘 조회가 안 되는 원인은 코드 버그지만, inspect 서버가 in-memory PCM으로
  떠서 데이터가 안 보이는 상황도 실제 재현 경로라 실행 문서를 함께 정리한다.

### D3. 회귀 테스트 형태

- 선택지 A: 기존 `tests/pcm/test_postgres.py`의 첫 통합 테스트에 목록 검증을 추가
- 선택지 B: `list_knowledge` 전용 별도 통합 테스트를 추가
- 추천: A의 흐름 안에 간단한 assertion을 추가하고, B의 전용 테스트로 project 범위·
  snapshot revision·tombstone 숨김까지 별도 검증한다. 두 형태 모두 같은 파일에 두어
  Postgres 통합 테스트 절차를 유지한다.

### D4. 검증 범위

- 선택지 A: ruff + 일반 pytest만
- 선택지 B: A + 실제 Postgres 통합 테스트(`CLIO_TEST_POSTGRES_URL`)
- 추천: B. 이 버그는 실제 Postgres 경로에서만 발생하므로 통합 테스트로 확인한다.

## 3. 구현 계획(결정 후)

### D3 확정 후 구현

- `PostgresPCM.list_knowledge`를 올바른 비동기 수집으로 수정

```python
documents = [await self._document_from_row(row) for row in rows]
return tuple(documents)
```

- `tests/pcm/test_postgres.py`에 목록 조회 회귀 테스트 추가
- 실행 검증:

```bash
ruff format --check .
ruff check .
pytest -q
CLIO_TEST_POSTGRES_URL=... pytest -m postgres
```

### D2가 B로 확정되면 추가

- `README.md`의 PCM Inspect API 섹션에 `.env` 로딩 방법과 in-memory/영속 동작 기준 명시

## 4. 커밋 계획

- `docs: PCM 메모리 조회 목록 버그 overview` (overview 확정 후)
- `docs: PCM 메모리 조회 목록 버그 구현 계획` (plan 확정 후)
- `fix(pcm): make list_knowledge collect async documents` (구현·테스트)
- `docs(pcm): document inspect server env loading` (D2=B일 때)
- `docs: PCM 메모리 조회 목록 버그 result` (완료 후)

## 5. 완료 기준

- PostgresPCM으로 데이터가 있는 프로젝트의 Knowledge 목록이 반환된다.
- 목록이 project 범위와 snapshot revision을 지킨다.
- `pytest -m postgres`의 기존 + 신규 테스트가 통과한다.
- `ruff check .`과 `ruff format --check .`이 통과한다.
- 변경 범위가 overview·plan과 일치한다.
