# 코드 검색 결과 순서 — Overview

> 승인: 2026-10-11

## 배경

외부 실제 저장소(Finvibe 백엔드, Java 파일 682개)에 버그를 넣어 분석한 결과, 분석 근거가 대부분 Markdown
문서였고 Java 구현 코드는 거의 인용되지 않았다.

| 버그 | 코드 검색 hit | 최종 인용 |
|---|---|---|
| #13 분봉 조회 지연 | 57 | 문서·k6 스크립트만. 원인인 `MarketQueryService.calculateMissingCandleTimes` 미인용 |
| 캔들 mock 데이터 | 57 | 문서만 |
| 최근 일봉 placeholder | 0 (+제공 코드 50) | Java 3개, 나머지 문서 |

## 현재 상태

`RepositoryService.search`(`context/repository.py`)는 snapshot commit에서 `git grep -n -I -i -F`를 실행하고,
출력 순서대로 `limit`(기본 20, 최대 50)개를 채우면 멈춘다. `git grep`은 **경로 알파벳 순**으로 출력한다.

호출 경로는 두 곳이다.

- `issue_analysis.search_code` 노드: 버그 신호로 만든 검색어 최대 5개를 각각 기본 `limit`으로 검색한다.
- Agent Tool `search_repository_code`: 분석 Agent가 검색어와 `limit`을 정한다.

Finvibe 저장소에서 같은 방식으로 측정한 결과는 다음과 같다.

| 검색어 | 전체 매칭 | `.java` 매칭 | 반환되는 앞 20건 |
|---|---|---|---|
| `Candle` | 800 | 672 | 전부 `docs/` |
| `MINUTE` | 283 | 250 | 전부 `docs/` |
| `분봉` | 171 | 26 | 전부 `docs/` |
| `KIS` | 874 | 513 | `README.md` 7, `docs/` 13 |

검색어가 정확해도 `docs/`, `README.md`, `.sisyphus/`처럼 `src/`보다 알파벳 순서가 앞선 경로가 결과를 모두 채운다.

## 문제

1. 결과 순서가 관련성이 아니라 경로 알파벳 순이다. 코드가 많이 매칭돼도 앞쪽 경로의 문서에 밀려 반환되지 않는다.
2. 한 파일의 매칭이 여러 줄이면 그 파일이 결과 상한을 독차지한다. 다른 파일이 들어올 자리가 없다.
3. 결과가 잘렸다는 사실(전체 매칭 수)이 호출자에게 전달되지 않는다. Agent가 검색어를 좁혀야 하는지 판단할 수 없다.

## 개선 방향

- 결과를 상한까지 자르기 전에 전체 매칭을 모아 정렬한다. 소스 코드가 문서보다 먼저, 한 파일이 상한을 독차지하지
  않게 한다.
- 잘림 여부를 결과에 담아 Agent가 검색 전략을 바꿀 수 있게 한다.
- Finvibe 실제 버그와 기존 fixture 벤치마크로 개선 전후를 비교한다.

## 범위

### 포함

- `RepositoryService.search`의 결과 수집·정렬·상한 정책
- `search_repository_code` Tool 응답의 잘림 정보
- 회귀 테스트와 실제 저장소 비교 검증

### 미포함 (후속 작업)

- 검색어 생성 정책(진행 중인 KAN-23 `task/kan-23-code-query-ab`에서 다룬다). 두 작업은 독립적이며, 이 작업이
  머지되면 KAN-23 실험 결과도 코드 hit를 기준으로 의미가 생긴다.
- 코드 의미 검색(embedding), 심볼 인덱스
- PCM 지식 검색 순위

## 참고

- `src/clio_agent_graph/context/repository.py` (`search`)
- `src/clio_agent_graph/context/tools/repository.py` (`search_repository_code`)
- `src/clio_agent_graph/workflows/orchestration/nodes/issue_analysis.py` (`search_code`, `_code_search_queries`)
- Finvibe 원인 문서: `docs/tasks/minute-candle-query-performance/01-overview.md`
