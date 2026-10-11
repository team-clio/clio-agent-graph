# 코드 검색 결과 순서 — Result

## 완료 범위

| 결정 | 구현 |
|---|---|
| D2 | `classify_search_path`: 확장자·경로 규칙으로 소스·테스트·설정·문서 분류 |
| D1 | `git grep` 전체 매칭을 모은 뒤 분류 우선순위 안에서 파일별로 번갈아 선택 |
| D3 | 문서는 제외하지 않고 코드 뒤에 둔다 (회귀 테스트로 고정) |
| D4 | 파일당 최대 2줄 |
| D5 · F1 | `search_with_stats`가 `total_matches`·`truncated`를 반환하고 `search_repository_code` Tool이 노출. `search`의 목록 반환은 유지 |
| D6 · F2 | Finvibe 3건 + fixture 5케이스 간이 정답 비교 |

`convention/architecture.md`의 repository 검색 설명을 갱신했다. 분석 노드(`nodes/issue_analysis.py`)와 검색어 생성은 바꾸지 않았다.

## 검증

### 자동 테스트

- `pytest`: 323 passed, 3 skipped. `ruff check` 통과, 변경 파일 `ruff format --check` 통과
- 추가 테스트: 파일 분류 14경로, 소스가 알파벳 순으로 앞선 문서보다 먼저 반환, 같은 분류 안 파일 교대,
  문서가 코드 뒤에 유지, 파일당 2줄, Tool의 `total_matches`·`truncated`

### Finvibe 실제 저장소 (배포 구성, 각 1회 실행)

| 버그 | 개선 전 | 개선 후 |
|---|---|---|
| #13 분봉 조회 지연 | Java 인용 0, 문서 14·9 (2회) | Java 인용 6, 문서 4 |
| 캔들 mock 데이터 | Java 0, 문서 43 | 판단 불가: 코드 근거 60건이 분석에 들어갔으나 품질 게이트가 인용 12건을 버림 |
| 최근 일봉 placeholder | Java 3파일 | 판단 불가: 매칭이 mock 데이터 이슈에 연결해 별도 분석 없음 |

#13은 원인 파일의 테스트(`MarketQueryServiceCandleTest`)까지 인용했지만 원인 메서드
`MarketQueryService.calculateMissingCandleTimes`는 여전히 인용하지 못했다. 검색어가 `분봉`, `KIS` 같은 단어라 원인
메서드 이름에 닿지 않는다. 이는 검색어 생성(KAN-23)의 범위다.

### fixture 5케이스 (간이 정답, 공식 점수 아님, 각 1회 실행)

| 케이스 | 개선 전 (파일 / 위치) | 개선 후 (파일 / 위치) |
|---|---|---|
| cache-tenant-leak | ✅ / ✅ | ✅ / ✅ |
| cache-false-miss | ❌ / ✅ | ❌ / ✅ |
| rollout-boundary | ✅ / ✅ | ✅ / ✅ |
| rollout-hash-unstable | 실패 (tool_calls 상한 초과) | ✅ / ✅ |
| repository-list-tenant | ✅ / ❌ | ✅ / ❌ |

둘 다 완료한 4케이스의 결과가 같아 회귀는 보이지 않았다. fixture는 소스 7개뿐이라 개선이 드러날 여지가 작다.
개선 전 rollout-hash 실패는 1회 실행이라 이번 변경과의 인과를 단정하지 않는다.

## 평가 중 발견한 다른 문제 (이번 범위 밖)

1. 품질 게이트가 `knowledge_id` 없는 knowledge 인용 12건을 버렸다. LLM이 코드 근거를 knowledge 유형으로 표기한 것으로 보인다.
2. 원인이 다른 두 버그(mock 데이터, 최근 일봉 placeholder)를 매칭이 한 이슈로 묶었다.
3. 버그는 이슈에 연결되는 시점에 `TRIAGED`가 되며 분석 완료보다 앞선다. 외부에서 분석 완료를 기다리는 쪽은 workflow run 상태를 봐야 한다.
4. embedding context 기본값 1024(#10)도 이 PC의 Docker 메모리 2.85GiB에서는 OOM이 발생했다.

## 남은 과제

- 검색어 생성 개선(KAN-23): 한국어 기능명에서 영어 식별자로 이어지는 검색어
- 공식 oracle로 fixture 30케이스 반복 평가
- 위 "다른 문제" 1~4
