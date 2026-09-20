# 운영 관측성 구현 결과

## 문서 정보

- 작성일: 2026-09-20
- 상태: 구현·자동 검증 완료, 포트폴리오 증거 수집 필요
- 기준 브랜치: Agent·Server `task/operational-observability`
- 선행 문서: [02-plan.md](02-plan.md), [03-decisions.md](03-decisions.md)
- 리뷰: 사용자 리뷰 필요

## 결과 요약

Spring Server의 workflow 요청에서 Python Agent의 graph·LLM·Tool·Quality Gate와 Server 재호출까지
W3C trace context를 연결했다. 낮은 cardinality metric, JSON log correlation, Prometheus·Tempo·Grafana
로컬 환경, 12개 패널 dashboard와 4개 의미 기반 alert를 추가했다.

이 결과는 production 성과가 아니라 `통제된 환경에서 추적·탐지할 수 있는 운영 준비도`다. 실제
성공률·P95·복구 시간은 반복 실험 데이터를 수집하기 전까지 주장하지 않는다.

## 구현 내용

### Server

- Spring Boot 4의 OpenTelemetry starter와 OTLP trace export 적용
- 관측 가능한 `RestClient.Builder`와 W3C `traceparent` envelope 전달
- workflow 생성·replay·충돌·상태 전이·실패 종류·실행 시간 metric
- 실행 중 건수, 정체 건수, 최장 실행 시간 gauge
- trace correlation이 포함되는 구조화 JSON log와 `workflow_run_id` 기록
- `/actuator/prometheus` 노출과 workflow duration histogram 적용

### Agent

- 잘못된 context를 거부하되 업무 요청은 새 trace로 계속하는 telemetry envelope 검증
- root workflow·subgraph·주요 node span과 지연·실패 metric
- 실제 LangChain callback 기준 LLM·Tool 호출 결과와 지연 계측
- 모델 token, 실행 한도, Quality Gate, 검토 전환, citation 거절 사유 metric
- Agent → Server 호출 trace header 전파와 내부 API 결과·지연 계측
- prompt·응답·source 원문을 받지 않는 telemetry adapter와 JSON event

### 로컬 관측 환경

- OpenTelemetry Collector → Tempo trace 전송
- Agent OTLP metric과 Server Prometheus endpoint 통합 수집
- Grafana datasource·dashboard 자동 provisioning
- workflow 실패, 저장 실패, 실행 한도, stuck workflow alert
- 실행·조사·장애 검증·증거 캡처 절차를 `observability/README.md`에 기록

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| Agent Ruff | 통과 |
| Agent pytest | 262 passed, 3 skipped |
| Server 전체 Gradle test | 통과 |
| Compose 구성 해석 | 통과 |
| Collector·Tempo·Prometheus·Grafana 실제 기동 | 4개 서비스 정상 |
| Grafana dashboard provisioning | `Clio Operational Evidence`, 12 panels |
| Prometheus alert loading | 4 rules |
| Agent metric scrape target | 정상 |

Server scrape target은 검증 시점에 다른 프로젝트가 로컬 `8080` 포트를 사용해 401을 반환했다. Clio
Server가 실행되지 않은 환경 충돌이며, Clio Server 기동 후 재확인이 필요하다. 사용자 프로세스는
중단하거나 변경하지 않았다.

## 계획 대비 조정

- 기존 bridge 조합 대신 Spring Boot 4 공식 `spring-boot-starter-opentelemetry`를 사용했다.
- 모델 수치는 Agent 실행 횟수로 대체하지 않고 callback에서 실제 개별 LLM 호출을 측정한다.
- baseline 없는 임의 지연·오류율 임계치는 넣지 않았다. 초기 alert는 사건 자체가 명확한 실패·저장
  실패·실행 한도·stuck 조건만 사용한다.
- Loki와 trace ID DB 저장은 결정대로 제외했다.

## 남은 작업

1. 로컬 `8080` 충돌을 해소한 뒤 Clio Server·Agent를 함께 실행한다.
2. 정상 요청과 계획한 7개 장애 시나리오를 고정된 데이터·횟수로 실행한다.
3. dashboard, 정상·실패 trace waterfall, 상태·checkpoint 결과표를 캡처한다.
4. 수집한 실제 값으로 포트폴리오 장표의 수치와 문구를 확정한다.

현재 미완료 항목은 운영 코드가 아니라 실제 실행 데이터와 시각 증거 수집이다.
