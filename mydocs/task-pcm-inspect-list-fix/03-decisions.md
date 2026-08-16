# PCM 메모리 조회 목록 버그 수정 — 결정 기록

## D1. 브랜치 전략

- 결정: `task/pcm-inspect-ui`가 main에 머지됐으므로 main에서
  `task/pcm-inspect-list-fix` 브랜치를 분기한다.
- 근거: 작업 절차 규칙은 항상 main에서 새 브랜치를 파도록 요구하며, inspect API가
  main에 포함된 뒤라 별도 브랜치를 유지할 필요가 없다.

## D2. 수정 범위

- 결정: 코드 수정 + Postgres 회귀 테스트 + inspect 서버 실행 문서 보강(B).
- 근거: 목록 버그가 1차 원인이지만, standalone inspect 서버가 `.env`를 자동으로
  읽지 않아 in-memory PCM으로 실행되는 것도 실제 조회 실패 경로다. 실행 문서에
  `--env-file` 로딩 방법을 명시해 두 원인을 함께 막는다.

## D3. 회귀 테스트 형태

- 결정: 기존 통합 테스트에 간단한 목록 assertion을 추가하고, `list_knowledge` 전용
  통합 테스트로 project 범위·snapshot revision·tombstone 숨김까지 검증한다.
- 근거: 실제 버그는 Postgres 경로에서만 재현된다. 전용 테스트는 앞으로 목록 계약이
  깨졌을 때 즉시 원인을 가리키도록 한다.

## D4. 검증 범위

- 결정: ruff, 일반 pytest, 실제 Postgres 통합 테스트를 모두 실행한다(B).
- 근거: 이 버그는 Postgres `list_knowledge`에만 존재하므로 실제
  `CLIO_TEST_POSTGRES_URL`로 검증해야 완료 기준을 확인할 수 있다.
