# PCM 메모리 조회 목록 버그 수정 — 결과

## 완료 사항

`task/pcm-inspect-list-fix` 브랜치를 main에서 분기해 다음 변경을 적용했다.

| 커밋 | 내용 |
|---|---|
| `668d4f9` | overview |
| `8f730bb` | 구현 계획 |
| `fd77589` | 결정 기록(D1~D4) |
| `b26b05b` | `PostgresPCM.list_knowledge` async 수집 버그 수정 + 회귀 테스트 |
| `063d698` | inspect 서버 `.env` 로딩 문서 보강 |

## 원인과 수정

`PostgresPCM.list_knowledge`가 아래 코드에서 async generator를 만들어
`TypeError: 'async_generator' object is not iterable`을 던졌다.

```python
# 수정 전
return tuple(await self._document_from_row(row) for row in rows)
```

각 row를 await하는 list comprehension으로 바꿔 tuple로 반환한다.

```python
# 수정 후
documents = [await self._document_from_row(row) for row in rows]
return tuple(documents)
```

이 경로는 clio-admin PCM 메모리 화면 → Spring 중계 API →
`GET /pcm/projects/{project_id}/knowledge`에 해당하며, 데이터가 있는 프로젝트에서
500을 반환했다. snapshot·상세·검색은 정상이었다.

## 검증

```bash
CLIO_TEST_POSTGRES_URL=... .venv/bin/pytest -q tests/pcm/test_postgres.py \
  tests/pcm/test_inspect_api.py tests/tools/test_pcm.py   # 12 passed
.venv/bin/ruff check src/clio_agent_graph/context/pcm/postgres.py \
  tests/pcm/test_postgres.py                               # passed
.venv/bin/ruff format --check src/clio_agent_graph/context/pcm/postgres.py \
  tests/pcm/test_postgres.py                               # passed
```

실제 inspect 서버로도 확인했다.

```bash
uvicorn --env-file .env clio_agent_graph.context.pcm.inspect_api:app --port 2025
curl http://127.0.0.1:2025/pcm/projects/1/knowledge   # 200, Knowledge 7건
```

전체 `pytest -q`는 기존에 문서화된 live LLM flake 1건
(`test_new_report_persists_complete_analysis_with_repository_citation`,
`needs_review`)만 실패한다. 전체 `ruff check .`·`ruff format --check .`의 잔여
항목도 이 작업 전 파일이며 이 작업에서 변경한 파일은 포함되지 않는다.

## 실행 방법

inspect 서버는 `langgraph dev`와 별도 프로세스이므로 `.env`를 자동으로 읽지 않는다.
영속 PCM 데이터를 보려면 `--env-file .env`를 붙여 실행한다.

```bash
uvicorn --env-file .env clio_agent_graph.context.pcm.inspect_api:app --port 2025
```

## 남은 과제

- 이 브랜치의 PR(base=main)을 열어 머지한다.
- clio-server, clio-admin은 이번 수정 범위가 아니므로 변경이 없다.
- inspect 서버가 실행 중이 아니면 admin 화면 목록이 여전히 로드되지 않는다.
  실행 방법은 README의 PCM Inspect API 섹션에 반영했다.
