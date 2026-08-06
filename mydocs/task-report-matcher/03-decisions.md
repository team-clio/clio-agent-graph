# Report Matcher(RM) 결정 기록

## 식별자와 매칭 단위

- `bug_report_id`: NM이 정규화하는 원본 BugReport 식별자
- `bug_id`: fingerprint 병합 뒤 생성된 Bug 식별자
- `project_id`: 검색 범위를 제한하는 프로젝트 식별자
- RM은 `Bug → 기존 Issue`의 동일 root cause 가능성을 판단한다.

## RAG 하위 에이전트

- RM은 실제 검색을 구현하지 않고 입출력 schema가 있는 LangGraph subgraph를 호출한다.
- 요청은 `project_id`, `bug_id`, `normalized_report`를 포함한다.
- 응답은 Issue 후보 최대 5개이며 각 Issue는 대표 Bug 최대 3개를 포함한다.
- 실제 RAG가 연결되지 않은 기본 placeholder는 설정 오류를 발생시킨다.
- 테스트에서는 Fake retrieval subgraph를 주입한다.

## 후보 비교와 정책

- 후보 최대 5개를 한 번의 structured-output 호출로 비교한다.
- LLM은 confidence·일치 근거·모순·부족 정보만 만들고 최종 action은 정책 코드가 결정한다.
- `AUTO_LINK`는 confidence 0.95 이상, 현상과 영향 영역 존재, 강한 오류 신호 일치, 모순 없음,
  1·2위 점수 차이 0.10 초과를 모두 요구한다.
- 강한 오류 신호는 같은 `error_type`과 하나 이상의 같은 `error_code` 또는 `stack_frame`이다.
- confidence 0.70 이상이지만 자동 연결 조건을 만족하지 못하면 `REVIEW`, 나머지는 `CREATE_NEW`다.
- 정상 검색 결과가 0건일 때만 모델 호출 없이 `CREATE_NEW`다.

## 부작용과 실패

- RM은 `MatchDecision`만 반환하고 Issue 연결·생성은 수행하지 않는다.
- 정상 출력에는 `normalized_report`와 `match_decision`을 함께 포함한다.
- RAG와 비교 모델의 일시 실패는 각각 한 번 재시도한다.
- structured output 오류는 검증 피드백으로 한 번 교정한다.
- 두 번째 실패는 정상 결과로 숨기지 않고 구분 가능한 예외로 오케스트레이터에 전달한다.
