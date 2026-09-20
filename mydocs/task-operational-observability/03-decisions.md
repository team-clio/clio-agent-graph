# 운영 관측성 결정 기록

## 문서 정보

- 작성일: 2026-09-20
- 상태: 결정 진행 중
- 선행 문서: [02-plan.md](02-plan.md)
- 리뷰: 사용자 리뷰 진행 중

## D1. 비동기 trace context 전달 방식

- 결정일: 2026-09-20
- 결정: root input에 검증된 telemetry envelope를 추가한다.
- 적용 범위: Spring의 `/runs`·`/runs/wait` 요청과 Agent root workflow 시작 경계

### 근거

- `/runs`의 HTTP 요청 종료와 실제 graph 실행 사이의 비동기 경계에서도 parent context를 보존한다.
- Spring dispatch, Agent workflow와 Agent → Server internal API를 같은 trace에서 확인할 수 있다.
- 업무 payload와 telemetry를 분리해 graph request validation과 보안 규칙을 명시적으로 적용한다.
- envelope가 없는 직접 실행은 새 trace로 시작하게 해 기존 테스트·개발 입력과 호환된다.

### 제외한 대안

`request_id`만 공통 log에 기록하고 서비스별 trace를 분리하는 방식은 공개 graph 계약을 바꾸지
않는다. 그러나 장애 조사 시 여러 화면과 시간대를 수동으로 맞춰야 하고, 포트폴리오에서
end-to-end waterfall을 증명할 수 없어 제외했다.

### 제약과 재검토 조건

- telemetry envelope는 W3C trace context 형식만 허용하고 업무 결과나 민감정보를 담지 않는다.
- 잘못된 context는 업무 요청을 실패시키지 않고 새 trace로 시작하되 검증 실패 event를 남긴다.
- LangGraph Server가 실행 context를 안전하게 전달하는 공식 확장 지점을 제공하면 body envelope를
  그 방식으로 대체할지 재검토한다.

## D2. 1차 관측 표준

- 결정일: 2026-09-20
- 결정: OpenTelemetry와 Micrometer를 공통 관측 표준으로 사용한다.
- 보조 도구: LangSmith 설정은 유지하되 LLM 상세 분석용 선택 기능으로 한정한다.

### 근거

- Spring과 Python Agent가 같은 W3C trace context와 OTLP 전송 규격을 사용할 수 있다.
- trace, metric과 log correlation을 특정 SaaS 계정에 종속하지 않고 로컬에서 재현할 수 있다.
- Server lifecycle과 Agent graph를 하나의 조사 흐름으로 보여줘 포트폴리오의 운영 증거가 된다.
- Spring에서는 Micrometer Observation·MeterRegistry라는 기존 생태계를 그대로 활용한다.

### 제외한 대안

LangSmith를 Agent의 주 관측 도구로 사용하면 LLM·Tool trace를 빠르게 확인할 수 있다. 그러나
Spring workflow와 동일한 trace·dashboard로 연결하기 어렵고 운영 증거가 Agent 내부에 한정되므로
1차 표준에서 제외했다.

### 제약과 재검토 조건

- OpenTelemetry에는 prompt·응답과 source 원문을 기록하지 않는다.
- LangSmith를 켜더라도 end-to-end 상태·지연·실패 수치의 기준은 OpenTelemetry·Micrometer로 둔다.
- 실제 운영에서 LangSmith의 평가·LLM 분석 기능이 핵심 요구가 되면 이중 전송 비용과 retention을
  별도로 결정한다.

## D3. 로컬 trace backend

- 결정일: 2026-09-20
- 결정: Tempo를 trace backend로 사용하고 Grafana에서 조회한다.

### 근거

- Prometheus metric dashboard와 trace 조회를 Grafana 한 화면에서 연결할 수 있다.
- 지연·실패 지표에서 관련 trace로 이동하는 장애 조사 흐름을 포트폴리오로 제시하기 좋다.
- OpenTelemetry Collector의 OTLP 수신 구조를 그대로 유지해 Agent와 Server exporter를 단순화한다.
- trace 전용 기능보다 metric과의 연계를 우선하는 이번 작업 목적에 맞는다.

### 제외한 대안

Jaeger는 독립 trace UI로 빠르게 시작하기 좋지만 metric dashboard와 조사 화면이 분리된다. 이번
작업은 trace 자체보다 `이상 탐지 → 원인 trace 확인` 흐름을 증명하는 것이 목적이므로 제외했다.

### 제약과 재검토 조건

- local compose의 데이터 보존 기간은 개발·시연 목적의 짧은 값으로 두고 운영 retention으로
  간주하지 않는다.
- 실제 배포 환경의 기존 observability backend가 정해지면 Tempo 고정을 해제하고 OTLP 호환성을
  기준으로 교체한다.

## D4. log 수집 범위

- 결정일: 2026-09-20
- 결정: JSON stdout과 trace correlation까지만 구현한다.
- 제외 범위: Loki 수집·저장·조회 구성

### 근거

- 이번 작업의 핵심 증거는 metric, trace와 안전한 workflow 종료다.
- `trace_id`, `request_id`, `workflow_run_id`가 있는 구조화 log면 로컬 장애 조사 증거로 충분하다.
- 별도 log 저장소의 설정·retention·resource 비용을 제외해 구현과 검증 범위를 통제한다.
- stdout은 컨테이너·배포 환경에서 다른 log backend로 전달하기 쉬운 중립적인 출력 경계다.

### 제외한 대안

Loki를 사용하면 Grafana에서 metric → trace → log 이동을 한 화면에 구성할 수 있다. 그러나 현재
목표에 필수적이지 않고 운영 stack과 dashboard 복잡도를 늘리므로 제외했다.

### 제약과 재검토 조건

- log schema와 민감정보 금지 규칙은 자동 테스트로 보호한다.
- 실제 배포에서 중앙 log 검색이 필요하거나 stdout만으로 장애 자료를 보존하기 어려워지면 Loki
  또는 기존 조직의 log backend를 별도 작업으로 추가한다.

## D5. trace ID 영속화

- 결정일: 2026-09-20
- 결정: trace ID를 업무 DB에 저장하지 않는다.
- 저장 위치: Tempo와 JSON log

### 근거

- `workflow_run_id`를 trace attribute로 기록하면 workflow 실행에서 관련 trace를 검색할 수 있다.
- 관측 backend의 retention과 업무 데이터 lifecycle을 분리할 수 있다.
- `agent_workflow_runs` schema와 Server API 계약을 바꾸지 않아 변경 위험이 줄어든다.
- trace가 만료되어도 workflow 상태·checkpoint·결과와 실패 code는 기존 DB에 남는다.

### 제외한 대안

workflow row에 trace ID를 저장하면 관리자 UI에서 trace로 직접 이동하기 쉽다. 그러나 현재 관리자
trace 링크 요구가 없고 DB migration과 API 노출 범위가 늘어나므로 제외했다.

### 제약과 재검토 조건

- trace에는 `workflow_run_id`와 `request_id`를 high-cardinality attribute로만 기록한다.
- 관리자 UI의 장기 trace 링크가 요구되거나 trace 검색이 반복적인 운영 부담이 되면 DB 저장을
  별도 계약 변경으로 재검토한다.
