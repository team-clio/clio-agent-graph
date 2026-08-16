# PCM 메모리 조회 목록 버그 수정

## 1. 작업 배경

PCM 메모리 inspect 기능이 `task/pcm-inspect-ui` 브랜치에서 clio-agent-graph,
clio-server, clio-admin 세 저장소에 구현됐다. 이 중 clio-agent-graph는 standalone
FastAPI inspect API(`:2025`)와 `ProjectContextReader.list_knowledge`를 추가했다.

실제 로컬 데이터를 조회하면 프로젝트별 PCM Knowledge 목록이 정상적으로 반환되지 않는다.

2026-08-17 기준 `task/pcm-inspect-ui`가 세 저장소 main에 머지됐다
(clio-agent-graph `4084670`, clio-server #22, clio-admin #1). clio-agent-graph의
로컬 main을 최신으로 갱신한 뒤 이 작업 브랜치 `task/pcm-inspect-list-fix`를
main에서 분기했다.

## 2. 현재 상태와 문제

### 증상

- `GET /pcm/projects/{project_id}/knowledge`(에이전트 inspect API)가 데이터가 있는
  프로젝트에서 500 응답을 반환한다.
- clio-admin의 PCM 메모리 화면은 Spring 중계 API를 거쳐 이 엔드포인트를 호출하므로
  목록이 로드되지 않는다.
- snapshot 조회와 Knowledge 상세·검색은 정상 동작한다.

### 원인

`clio-agent-graph`의 `PostgresPCM.list_knowledge`에 비동기 generator 오류가 있다.

```python
return tuple(await self._document_from_row(row) for row in rows)
```

이 코드는 각 row를 await 하는 대신 `await`를 generator 표현식에 적용해
async generator를 만들고, `tuple()`이 이를 순회하다
`TypeError: 'async_generator' object is not iterable`을 던진다.
`3a05f93`(PCM inspect API)에서 추가된 코드이며, rows가 비어 있으면 오류가
드러나지 않는다.

### 확인된 사실

- `clio_pcm` DB에는 프로젝트 4개, Knowledge 29건이 존재한다.
- `read_knowledge`, `search_knowledge`는 PostgresPCM 기준으로 정상 동작한다.
- `InMemoryPCM.list_knowledge`는 정상이며, inspect API 테스트는 in-memory만 사용해
  이 버그를 잡지 못한다.
- `tests/pcm/test_postgres.py`는 snapshot·read·search·restart·fallback을 검증하지만
  `list_knowledge` 호출이 없다.
- clio-agent-graph 전체 pytest는 기존에 문서화된 live LLM flake 1건만 실패한다.

## 3. 개선 방향

- `PostgresPCM.list_knowledge`를 올바른 비동기 수집 방식으로 고친다.
- Postgres 통합 테스트에 목록 조회 회귀 테스트를 추가한다.
- 필요하면 inspect 서버 실행 문서에 환경변수 로딩을 명확히 한다(별도 프로세스는
  `.env`를 자동으로 읽지 않아 in-memory PCM으로 떠 오해를 부르는 가능성이 있다).

## 4. 범위

### 포함 후보

- `PostgresPCM.list_knowledge` 버그 수정
- `tests/pcm/test_postgres.py`에 목록 조회 테스트 추가
- inspect 서버 실행 명령 문서 보강(`--env-file` 또는 env 로드 방법)

### 제외

- PCM 쓰기·검색·상세·snapshot 동작 변경
- Spring·admin 코드 변경
- inspect 서버의 실행 여부(운영 실행은 결과 문서에서 안내만 한다)

## 5. 완료 기준 초안

- PostgresPCM으로 데이터가 있는 프로젝트의 Knowledge 목록이 반환된다.
- 목록이 project 범위와 snapshot revision을 지킨다.
- `pytest -m postgres`의 기존 + 신규 테스트가 통과한다.
- `ruff check .`과 `ruff format --check .`이 통과한다.

## 6. Plan에서 결정할 핵심 항목

1. 브랜치 전략: `task/pcm-inspect-ui`가 main에 머지됐으므로 main에서 분기했다(D1 확정).
2. 수정 범위: 코드+테스트만 / inspect 서버 실행 문서도 함께 갱신
3. 회귀 테스트 위치·형식: 기존 `test_postgres.py` 통합 테스트에 추가
