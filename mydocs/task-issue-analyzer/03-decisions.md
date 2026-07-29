# Issue Analyzer(IA) 결정 기록

## I1. 실행 경계

- Supervisor가 실제 Issue 생성 이후 IA를 호출한다.
- 최초 분석과 재분석은 각각 `issue_analyzer`, `issue_reanalyzer` 공개 그래프로 분리한다.
- IA는 RM action, 서버 이벤트, DB 쓰기를 직접 처리하지 않는다.

## I2. Bug 문맥

- 두 그래프 모두 대표 Bug를 1개 이상 5개 이하로 받는다.
- `trigger_bug_id`는 입력 Bug 목록에 반드시 포함한다.
- 재분석은 이전 `IssueAnalysis`와 새 Bug를 함께 받는다.

## I3·I7. Code Explorer 응답

- 코드 snapshot, 심볼·호출 관계, 관련 테스트, 최근 변경 snapshot을 포함한다.
- snapshot은 1~10줄이며 path·symbol·line·change ID는 설명용 metadata다.
- 실제 Code Explorer는 후속 작업으로 두고 이번에는 placeholder와 Fake를 구현한다.

## I4. 반복 탐색

- 최초 탐색을 포함해 Code Explorer를 최대 3회 호출한다.
- 한 요청의 질문은 최대 5개, 응답 Evidence 후보는 최대 10개다.
- 반복 질문을 제거하고 새 질문이 없으면 조기 종료한다.

## I5. Evidence 식별과 재분석 버전

- 공통 IA가 분석 결과 내부 순번 `E1`, `E2`, ...를 결정적으로 부여한다.
- 한 결과의 Evidence는 최대 20개이며 `analysis_job_id + evidence_id`로 식별한다.
- 재분석은 이전 결과를 수정하지 않고 새 `analysis_job_id`의 전체 snapshot을 만든다.
- 이전 Evidence는 질문 생성 참고로만 사용하며 현재 Code Explorer에서 재확인된 근거만 새 결과에 넣는다.

## I6. Finding과 Hypothesis

- Finding은 최대 10개, RootCauseHypothesis는 우선순위가 있는 최대 3개다.
- confidence는 `LOW`, `MEDIUM`, `HIGH`이며 발생 확률이 아니라 근거 강도다.
- Finding은 Evidence를 참조하고 Hypothesis는 Finding을 참조한다.

## I8. 실행 관리

- Supervisor가 최초 분석과 재분석 필요 여부를 판단해 해당 공개 그래프를 호출한다.
- IA 내부는 호출 원인을 다시 판단하지 않는다.

## I9. 실패와 근거 부족

- Code Explorer와 판단 모델의 일시 실패는 한 번 재시도한다.
- structured output 오류는 검증 피드백으로 한 번 교정한다.
- 계속되는 기술 실패는 run 실패로 전파한다.
- 정상 탐색에서 Evidence를 찾지 못한 경우만 `INSUFFICIENT_EVIDENCE`를 반환한다.

## I10. 공개 출력

- 두 그래프 모두 `issue_analysis` 하나를 반환한다.
- 재분석 결과에만 이전 가설별 유지·강화·약화·폐기와 신규 가설을 담은 `revision_summary`를 포함한다.
- Evidence와 Finding은 이전 결과와 ID 매핑하지 않고 새 snapshot으로 제공한다.

## 추가 결정. 공통 IA와 판단 subagent

- 탐색 실행·중복 제거·상한·참조 검증·결과 조립은 공통 IA가 담당한다.
- Initial·Revision Judgment Subagent는 상황별 탐색 질문과 최종 판단 초안을 만든다.
- 두 subagent는 같은 Protocol 형태를 따르되 별도 prompt와 adapter를 사용한다.
- 분석 결과에는 Evidence 최대 20개, CodeRelation 최대 30개를 보존한다.
