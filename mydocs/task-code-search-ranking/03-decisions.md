# 코드 검색 결과 순서 — Decisions

사용자가 plan 승인 시 "추천대로 진행"으로 D1~D6 결정을 위임했다. 각 항목은 plan의 추천안을 따른다.

## D2. 파일 분류 판정

### 결정: A — 확장자와 경로 규칙

- 대안 A: 확장자·경로 규칙으로 소스·테스트·설정·문서를 나눈다. ← 선택
- 대안 B: GitHub Linguist 같은 외부 분류기. 정확하지만 의존성과 이미지 크기가 늘어난다.
- 대안 C: 저장소 등록의 include/exclude만 쓴다. 설정하지 않으면 지금과 같다.

선택 이유: 의존성 없이 결정적으로 동작하고, 실제 문제(문서가 소스를 밀어냄)를 가르는 데 충분하다.

구현 규칙 (`classify_search_path`, 판정 순서대로):
1. 문서: `.md .mdx .rst .adoc .txt`. 테스트 디렉터리 안의 문서도 문서로 본다.
2. 테스트: 경로 조각 `test/ tests/ __tests__/ spec/` 또는 파일명 `test_*`, `*_test.*`, `*Test.*`, `*Tests.*`, `*.spec.*`, `*.test.*`.
3. 설정: `.json .yml .yaml .toml .xml .properties .gradle .ini .cfg .conf`.
4. 그 외는 소스다.

## D1. 결과 정렬 기준

### 결정: C — 분류 우선순위 안에서 파일 단위로 번갈아 채움

- 대안 A: 분류 우선순위 다음 경로 순. 한 파일의 매칭이 많으면 그 파일이 상한을 독차지한다.
- 대안 B: 관련성 점수(파일 내 매칭 수, 식별자 경계, 경로 포함 등). 설명과 검증이 어렵다.
- 대안 C: 분류 우선순위(소스 → 테스트 → 설정 → 문서) 안에서 파일별로 한 줄씩 번갈아 고른다. ← 선택

선택 이유: 결정적이고 설명하기 쉬우며, 경로 순 잘림과 한 파일 독차지를 함께 해결한다.

구현 규칙:
- `git grep` 출력을 상한에서 멈추지 않고 모두 모은 뒤 `_select_search_hits`로 고른다.
- 같은 분류 안의 파일 순서는 저장소 ID, 경로 순이다. 한 파일 안에서는 줄 번호 순이다.

## D3. 문서 매칭의 취급

### 결정: A — 후순위로 둔다

- 대안 A: 소스·테스트·설정이 상한을 채우지 못하면 문서가 뒤에 들어온다. ← 선택
- 대안 B: 기본 제외하고 Tool 인자로만 포함한다. 문서가 정답을 담는 경우를 놓친다.
- 대안 C: `code`·`docs` 그룹으로 나눠 각각 일부를 돌려준다. 응답 계약이 바뀐다.

선택 이유: Finvibe #13처럼 저장소 문서가 원인을 직접 설명하는 경우를 살리면서 코드가 밀리지 않는다.
D1의 정렬로 구현되며, 회귀 테스트로 동작을 고정했다.

## D4. 파일당 상한

### 결정: A — 파일당 2줄

- 대안 A: 파일당 2줄. 기본 `limit` 20에서 최소 10개 파일을 보여 준다. ← 선택
- 대안 B: 파일당 3줄.
- 대안 C: 상한 없음(정렬만 바꾼다). 매칭이 많은 한 파일이 소스 몫을 독차지할 수 있다.

선택 이유: 분석 Agent는 `read_repository_file`로 필요한 파일을 더 읽을 수 있으므로 검색은 넓게 보여 주는 편이 낫다.

구현 규칙: `_SEARCH_HITS_PER_FILE = 2`. 파일마다 앞쪽 줄 번호 2개를 고른다.

## D5. 잘림 정보 노출

### 결정: A — `total_matches`, `truncated`를 Tool 응답에 노출

- 대안 A: 검색 결과에 전체 매칭 수와 잘림 여부를 담아 Tool 응답에 노출한다. ← 선택
- 대안 B: 로그·metric에만 남긴다. Agent의 검색 전략에는 영향이 없다.
- 대안 C: 노출하지 않는다.

선택 이유: 분석 Agent가 검색어를 좁히거나 파일을 직접 읽을지 판단할 근거가 된다.
Tool 설명에도 정렬 순서, 파일당 2줄 상한, `truncated`의 의미를 적었다.

## F1. 잘림 정보를 별도 메서드로 제공 (D5 보완, 구현 중 발견)

### 결정: B — `search`는 목록 반환을 유지하고 `search_with_stats`를 추가

- 대안 A: plan대로 `search`의 반환 타입을 `RepositorySearchResult`로 바꾼다. 분석 노드 `issue_analysis.search_code`도
  함께 바뀐다.
- 대안 B: `search_with_stats`가 `RepositorySearchResult(hits, total_matches, truncated)`를 반환하고, `search`는 그
  `hits`를 반환한다. Tool만 새 메서드를 쓴다. ← 선택

선택 이유: 진행 중인 KAN-23(`task/kan-23-code-query-ab`)이 `nodes/issue_analysis.py`를 81줄 수정하고 있어, 노드를
건드리면 충돌이 커진다. plan D5의 기각 조건에 적어 둔 경로다. 잘림 정보가 필요한 곳은 검색어를 직접 고르는 Agent
Tool이며, 노드는 고정 검색어로 초기 근거만 모으므로 기능 차이가 없다.

`total_matches`는 파일당 상한을 적용하기 전 매칭 줄 수다.

## D6. 평가 방법

### 결정: A — Finvibe 실제 버그 3건 + fixture 회귀

- 대안 A: Finvibe 실제 버그 3건 재분석과 clio-benchmark fixture 회귀를 함께 본다. ← 선택
- 대안 B: Finvibe 3건만.
- 대안 C: 단위 테스트만.

선택 이유: 실제 대형 저장소의 개선과 기존 fixture의 회귀를 함께 확인한다. 실행 비용 때문에 fixture는 사용자 확인을 거쳐
30케이스 대신 결함이 서로 다른 detailed 5케이스로 줄였다.

## F2. fixture 회귀를 간이 정답으로 평가 (D6 보완, 구현 중 발견)

### 결정: A — 간이 정답으로 5케이스 비교 (사용자 결정)

- 대안 A: DATASET의 결함 목록과 fixture 코드로 케이스별 원인 파일·위치를 정하고, 분석이 그 위치를 인용했는지 비교한다. ← 선택
- 대안 B: 공식 oracle 경로를 받아 clio-benchmark로 채점한다.
- 대안 C: fixture 회귀를 후속으로 미룬다.

선택 이유: clio-benchmark 채점용 비공개 oracle(`oracles/feature-flags-30.json`)이 이 PC에 없었다. 공식 점수가 아님을 result에 명시한다.

간이 정답:

| 케이스 | 파일 | 위치 |
|---|---|---|
| cache-tenant-leak-detailed | `src/feature_flags/cache.py` | `_key` |
| cache-false-miss-detailed | `src/feature_flags/service.py` | `if cached:` |
| rollout-boundary-detailed | `src/feature_flags/rollout.py` | `is_in_rollout` |
| rollout-hash-unstable-detailed | `src/feature_flags/rollout.py` | `rollout_bucket` |
| repository-list-tenant-detailed | `src/feature_flags/repository.py` | `list_for_tenant` |

평가 환경 조정: 체험 스택의 Docker 메모리(2.85GiB)에서 embedding 서버가 OOM으로 종료되어, 평가 동안만 `.env`에
`CLIO_OLLAMA_EMBED_CONTEXT_TOKENS=512`를 두었다. 코드 검색과는 무관한 설정이고 두 조건에 같게 적용했다.
