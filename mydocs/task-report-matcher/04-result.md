# Report Matcher(RM) 구현 결과

## 구현된 흐름

```text
START
  → normalize_report
  → issue_retrieval_subgraph
  → 후보 없음: apply_match_policy
  → 후보 있음: judge_issue_match → apply_match_policy
  → END
```

RM은 `project_id`, `bug_id`, NM 결과를 RAG 하위 에이전트에 전달하고 Issue 후보 최대 5개를 받는다. 각
Issue 후보는 실제 발생 사례인 대표 Bug를 최대 3개 포함할 수 있다.

## 책임 경계

- 실제 Hybrid RAG는 후속 작업이며 현재 기본 subgraph는 명시적인 설정 오류를 발생시킨다.
- LLM은 후보별 일치·모순·정보 부족과 confidence만 반환한다.
- 정책 코드는 `AUTO_LINK`, `REVIEW`, `CREATE_NEW`를 결정한다.
- RM은 DB를 변경하지 않고 오케스트레이터에 `MatchDecision`만 반환한다.
- RAG와 비교 모델은 일시 실패 시 한 번 재시도하며, 두 번째 실패는 정상 판단으로 숨기지 않는다.

## 자동 연결 안전장치

`AUTO_LINK`는 confidence 0.95 이상인 것만으로 결정하지 않는다. 관찰된 현상과 영향 영역이 존재하고,
같은 오류 유형과 오류 코드 또는 stack frame이 대표 Bug에서 확인되며, 모순이 없고 2위 후보와 점수 차이가
0.10보다 커야 한다.

## 후속 작업

- `taek/issue-retrieval`에서 실제 RAG subgraph 구현
- 검색 결과가 이미 연결된 Issue를 제외하도록 `bug_id` 활용
- 검색 recall과 후보 비교 정확도를 별도 평가
- Clio Server에서 MatchDecision에 따른 멱등한 연결·검토·생성 처리
