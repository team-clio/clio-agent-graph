# Report Normalizer(NM) 결정 기록

## N1. NM의 원본 연결과 evidence 책임

**결정: NM에는 `bug_report_id`만 유지하고, pointer·offset·excerpt evidence는 두지 않는다.**

NM의 책임은 원본 BugReport를 구조화하고 누락 정보를 표시하는 것이다. 코드·문서·로그를 조사해 Bug의
evidence를 만드는 일은 IA와 탐색 에이전트가 담당한다. NM이 원문의 구절별 evidence까지 만들면 정규화와
조사의 책임이 섞이고 초기 계약이 불필요하게 커진다.

후속 에이전트는 `bug_report_id`로 변경되지 않는 원본 리포트를 다시 읽을 수 있어야 한다. 따라서 이 결정은
원본 BugReport가 immutable하게 보존된다는 전제를 갖는다. BugReport 수정 기능이 필요하면 기존 원본을
덮어쓰지 않고 새 버전 또는 새 원본 레코드로 남긴다.

향후 IA evidence는 NM 계약을 미리 일반화하지 않고, 실제 조사 요구에 맞춰 별도로 설계한다. 여러 코드가 얽힌
버그를 위해 짧은 코드 스냅샷 여러 개와 관계를 표현하는 방향은 IA 작업의 결정 포인트로 넘긴다.

### 구현 영향

- `NormalizeReportInput`과 `NormalizedReport`가 동일한 `bug_report_id`를 가진다.
- 모델에는 식별자 생성을 맡기지 않고 애플리케이션이 결과에 주입한다.
- NM 출력에는 `EvidenceSpan`, JSON Pointer, 문자 offset, excerpt 목록을 만들지 않는다.
- NM 테스트는 evidence 위치가 아니라 식별자 보존, 구조화 출력, 누락 처리와 추론 금지를 검증한다.

## N2. NM의 존재 이유와 최소 출력 계약

**결정: NM은 서로 다른 형식의 BugReport를 RM이 비교할 수 있는 표준 사실 표현으로 변환한다.**

NM이 없으면 RM이 source별 payload 해석과 동일 Bug 판단을 함께 맡게 된다. NM은 수집 형식의 차이를 흡수하되,
원인 조사나 코드 탐색은 하지 않는다. 이미 구조화된 입력값은 그대로 보존하고 자유 텍스트에 포함된 사실만
구조화한다.

최소 출력은 다음 8개 필드다.

| 필드 | 의미 |
|---|---|
| `bug_report_id` | 원본 버그 리포트 식별자 |
| `observed_behavior` | 실제 발생 현상 |
| `expected_behavior` | 원문에 명시된 기대 동작 |
| `reproduction` | 재현 조건과 재현 절차 |
| `environment` | OS·브라우저·기기·앱 버전·배포 환경과 추가 환경값 |
| `affected_surface` | 영향받은 기능·작업·API·화면 |
| `error_signals` | 오류 유형·메시지·오류 코드·stack frame |
| `missing_fields` | 원본에서 확인할 수 없는 중요 정보 |

`expected_behavior`처럼 원문에 없을 수 있는 값은 `null` 또는 빈 목록으로 두고 `missing_fields`에 표시한다.
NM은 코드 evidence, 원인 가설, 기존 Bug 유사도, 코드 검색어, 프로젝트 도메인 후보, 우선순위, 수정·테스트
계획을 만들지 않는다.

### 구현 영향

- 입력 모델은 Clio Server의 수집 계약인 title·description·source·error type·message·stack trace·발생 시각·
  raw payload를 수용한다.
- 출력 모델은 위 8개 최상위 필드와 재현·환경·영향 기능·오류 신호의 하위 구조를 가진다.
- 오류 신호는 `error_type`, `message`, `error_codes`, `stack_frames`로 분리한다.
- 필수값이 없다고 임의 보충하지 않고 누락 상태를 표현할 수 있어야 한다.
