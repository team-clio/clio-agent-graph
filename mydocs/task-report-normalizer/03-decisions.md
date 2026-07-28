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
