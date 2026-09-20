# Clio 운영 관측성 포트폴리오 실험 결과

## 목적

- 독자: AX·AI Application Development 채용 면접관
- 질문: LLM workflow가 정상·품질 저하·인용 오류·의존성 장애·중복 요청을 운영 환경에서 구분할 수 있는가?
- 측정일: 2026-09-20
- 상태: 로컬 E2E 완료, 실제 운영 트래픽 검증은 별도 필요

## 실험 조건

- 실행 환경: Clio Server + Clio Agent + PostgreSQL + OpenTelemetry Collector
- 관측 도구: Prometheus, Grafana, Tempo
- 실제 모델: `openai:deepseek-v4-flash`
- 임베딩: 로컬에 Ollama가 없어 384차원 결정형 테스트 더블 사용
- 실패 주입: `service.name=clio-controlled-experiment`로 실제 실행과 분리
- 개인정보·업무 payload는 metric과 trace attribute에 저장하지 않음

## 1. 정상 분석

- Bug 5를 실제 `process_report` workflow로 실행했다.
- EXACT·LEXICAL·VECTOR 세 채널 모두 기존 Issue 1을 1위로 검색했다.
- Report Matcher가 신뢰도 0.97로 기존 Issue에 자동 연결했다.
- Issue 분석은 실제 모델 4회, 입력 12,900·출력 4,363 token을 사용했다.
- Quality Gate `passed`, 코드 근거 6건, 구조화 citation 3건을 남겼다.

## 2. Quality Gate 실패

- 고정 입력으로 `retry`와 `needs_review`를 각각 1회 재현했다.
- 최종 분포: `passed=1`, `retry=1`, `needs_review=1`.
- 검토 전환은 `quality_gate`, `quality_or_limit` 사유로 구분된다.

## 3. Citation 실패

- 분석에 묶인 repository snapshot과 다른 commit citation을 주입했다.
- Quality Gate가 citation을 제거하고 `snapshot_mismatch=1`을 기록했다.
- 생성된 문장이 아니라 commit·line 범위가 snapshot과 일치하는지를 검증한다.

## 4. 의존성 장애

- Ollama 임베딩 endpoint 중단을 실제 workflow에서 재현했다.
- 이후 통제 실험에서 dependency workflow·Tool 실패를 각각 1회 계측했다.
- 실패 종료되지 않은 테스트 workflow 10건을 `FAILED`로 종결해 정체 0건을 확인했다.

## 5. 멱등성·재실행

- 같은 `request_id`와 같은 payload를 두 번 전송했을 때 동일 run ID 13을 반환했다.
- 같은 `request_id`에 다른 payload를 보내자 HTTP 409 `CONFLICT`로 거절했다.
- Server metric에 `created=1`, `replayed=1`이 별도로 기록됐다.

## 최종 관측값

| 지표 | 결과 | 해석 |
|---|---:|---|
| Workflow lifecycle 이벤트 | 42 | Server·Agent 상태 전이 누적 |
| 실제 모델 호출 | 4회 성공 | 구조화 분석·계획·위험도 포함 |
| 모델 token | 17,263 | 입력 12,900 / 출력 4,363 |
| Tool 호출 | 성공 1 / 실패 1 | 통제 장애 주입 |
| Quality Gate | 1 / 1 / 1 | pass / retry / review |
| Citation 거절 | 1 | snapshot mismatch |
| Dependency failure | 1 | 통제 장애 주입 |
| 정체 workflow | 0 | 실패 실행 종결 후 gauge 확인 |

## 해석 시 주의사항

- 실패율 26.2%는 안정성 SLO가 아니라 의도적 실패 실험이 포함된 값이다.
- 누적 p95 22.7초는 작은 표본과 실패 실행을 포함하므로 성능 목표로 일반화하지 않는다.
- 임베딩 검색 품질은 실제 Ollama 모델이 아닌 테스트 더블 조건이다.
- 운영 배포 전에는 실모델 임베딩, 장시간 부하, 재시작 후 metric continuity를 추가 검증해야 한다.

## 포트폴리오 사용 권장

- 본문 장표에는 `02-observability-portfolio-slide.png`를 사용한다.
- 부록에는 `01-grafana-operational-dashboard.png`와 이 문서를 함께 둔다.
- 면접에서는 정상 결과보다 실패 분류·검토 전환·멱등성·한계 공개를 중심으로 설명한다.
