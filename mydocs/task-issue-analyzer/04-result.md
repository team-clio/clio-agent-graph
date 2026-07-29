# Issue Analyzer(IA) 구현 결과

## 공개 그래프

- `issue_analyzer`: 새 Issue의 최초 분석
- `issue_reanalyzer`: 이전 분석과 새 Bug를 사용한 재분석

두 그래프는 Supervisor가 호출하며 `issue_analysis` 공통 결과를 반환한다. 재분석은 이전 결과를 수정하지 않고
새 `analysis_job_id`의 전체 snapshot을 만든다.

## 구현된 내부 구조

```text
공통 IA Orchestrator
  → Initial 또는 Revision Judgment Subagent
  → Codebase Exploration Subgraph
  → Evidence 병합·중복 제거
  → 최대 3회 반복
  → Finding·Hypothesis 초안
  → 참조 검증
  → IssueAnalysis
```

- Judgment Subagent는 상황별 탐색 질문과 판단 초안을 만든다.
- 공통 IA는 탐색 실행, Evidence ID, 상한, 참조 검증과 결과 조립을 담당한다.
- Code Explorer 실제 구현은 후속 작업이며 현재 placeholder는 명시적인 설정 오류를 발생시킨다.

## 장기 보관 근거와 검증

- Evidence snapshot은 1~10줄, 분석당 최대 20개다.
- path·symbol·line·change ID는 snapshot의 설명 metadata다.
- CodeRelation은 실제 Evidence만 연결한다.
- Finding은 Evidence를, Hypothesis는 Finding을 참조한다.
- 가설은 최대 3개이며 confidence는 `LOW`, `MEDIUM`, `HIGH` 근거 강도다.
- 재분석은 이전 Evidence를 자동 계승하지 않고 현재 탐색에서 재확인된 근거만 포함한다.
- RevisionSummary는 이전 가설의 유지·강화·약화·폐기와 새 가설을 기록한다.

## 실패 처리

- Code Explorer와 Judgment 호출은 일시 실패 시 한 번 재시도한다.
- structured output 오류는 검증 피드백으로 한 번 교정한다.
- 기술 실패는 run 실패로 전파한다.
- 세 번의 정상 탐색에서도 Evidence가 없을 때만 `INSUFFICIENT_EVIDENCE`를 반환한다.

## 후속 작업

- 실제 Codebase Exploration Agent 구현
- 저장소 접근 권한과 credential 격리
- AST·호출 그래프·관련 테스트·최근 변경 탐색
- Supervisor와 Clio Server의 AnalysisJob·AnalysisResult 저장 연동
- 운영 평가를 통한 Evidence·탐색 round 상한 조정
