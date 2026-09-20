# 운영 관측성 구축 계획

> 승인: 2026-09-20

## 문서 정보

- 작성일: 2026-09-20
- 상태: 승인 완료
- 기준 revision: Agent `4aae218`, Server `15ae0e2`
- 선행 문서: [01-overview.md](01-overview.md)

## 목표

Spring의 Agent 실행 요청부터 LangGraph workflow, LLM·Tool, Quality Gate와 결과 저장까지를 요청
단위로 추적한다. dashboard에서 이상을 발견하고 trace·log로 원인을 좁힌 뒤 workflow 상태,
checkpoint와 멱등성 보호를 확인할 수 있게 한다.

실제 운영 트래픽이 없으므로 결과는 `production 안정성`이 아니라 `통제된 장애에서 탐지·추적·
안전 종료를 재현한 운영 준비도`로 표현한다.

## 최신 main 확인 결과

- Server는 `/runs` 또는 `/runs/wait`로 `clio_agent`를 호출한다. `/runs`는 접수 후 실제 graph가
  비동기로 실행되므로 HTTP span만으로 graph 실행 context가 이어진다고 가정할 수 없다.
- `ClioAgentClient`는 auto-configured `RestClient.Builder` 대신 직접 builder를 생성한다. 따라서
  Spring의 자동 trace header 전파를 먼저 보장해야 한다.
- Agent의 `ClioServerClient`는 `urllib` 기반이다. Agent → Server internal API 호출도 current
  context를 header에 명시적으로 주입하거나 검증된 계측을 적용해야 한다.
- Agent가 Server에 workflow를 등록한 뒤 `PENDING → RUNNING → COMPLETED/FAILED`를 요청한다.
  Server에는 시작·완료 시각, checkpoint, 실패 code와 멱등 request hash가 이미 있다.
- Agent에는 `completed_nodes`, 실행 한도 분류와 Quality Gate 결과가 있지만 집계 metric과 공통
  구조화 event는 없다.
- Agent Server에는 업무용 custom metric endpoint를 안정적으로 추가할 공개 확장 지점이 없다.
  Agent metric은 OTLP로 Collector에 push하는 구성이 직접 scrape보다 안전하다.

## 목표 구조

```text
Spring Server
  ├─ Micrometer metric ───────────────→ Prometheus ─→ Grafana
  ├─ OTLP trace ──────────────────────→ Collector ──→ Tempo
  └─ Agent dispatch + trace envelope ─→ LangGraph /runs
                                           │
Clio Agent                                 ├─ workflow/node span
  ├─ OTLP trace·metric ────────────────────┘
  ├─ JSON log + trace_id
  └─ trace header ─────────────────────→ Spring internal API
```

## 관측 계약 초안

- correlation: `trace_id`, `request_id`, `workflow_run_id`, `request_type`
- metric label: `request_type`, `node`, `operation`, `outcome`, `error_kind`, `limit_type`
- 금지 label: request·workflow·project ID, repository 경로, 자유 텍스트
- 금지 payload: prompt·응답, Bug 원문, source code, credential, API key, 개인정보
- error kind: 기존 예외를 `timeout`, `limit`, `dependency`, `validation`, `persistence`,
  `unexpected`처럼 제한된 값으로 매핑하고 원문 메시지는 metric에 넣지 않는다.

## 구현 단계

### 1. 공통 telemetry 계약

- span 이름, attribute, metric, JSON event와 오류 매핑표를 문서화한다.
- Agent에는 no-op 기본값을 가진 telemetry port와 test fake를 둔다.
- Server에는 Micrometer Observation·MeterRegistry 기반 기록 컴포넌트를 둔다.
- exporter가 없거나 관측 기능이 꺼져도 업무 결과가 달라지지 않게 한다.

### 2. 비동기 trace context 연결

- Server의 `ClioAgentClient`가 Spring이 관리하는 HTTP client builder를 사용하게 한다.
- `/runs` 요청 시 current W3C `traceparent`를 업무 payload와 분리된 telemetry envelope로 함께
  전달한다. `/runs/wait`도 같은 계약을 사용한다.
- Agent root에서 envelope를 검증·추출해 `clio.workflow` span의 remote parent로 사용한다.
- envelope가 없으면 새 trace로 시작해 기존 직접 실행·테스트 입력의 호환성을 유지한다.
- Agent의 Server internal API client는 current context를 HTTP header에 주입한다.

### 3. Server workflow 관측

- `clio.agent.dispatch`에 request type, sync mode와 접수 결과를 기록한다.
- workflow 생성·시작·완료·실패·replay와 분석 결과 저장을 observation으로 기록한다.
- DB의 `started_at`, `completed_at`을 기준으로 workflow duration metric을 만든다.
- `RUNNING` workflow의 최대 실행 시간과 기준 초과 건수를 조회 전용 gauge로 노출한다.
- Prometheus endpoint, OTLP trace export와 log correlation 설정을 추가한다.

### 4. Agent graph·LLM·Tool 관측

- graph 조립 시 공통 wrapper로 root와 주요 node span·duration·outcome을 기록한다.
- LLM 공통 runtime에서 model, operation, outcome, duration, token 수와 제한 초과를 기록한다.
- Tool은 이름, outcome, duration과 결과 개수만 기록한다.
- Quality Gate는 passed·retry·needs_review와 citation 거부 사유를 기록한다.
- 병렬 검색은 같은 workflow parent 아래의 sibling span으로 표현한다.

### 5. Collector·dashboard·alert

- OTel Collector, Tempo, Prometheus와 Grafana를 로컬 compose로 실행한다.
- Collector는 Agent OTLP trace를 Tempo로, metric을 Prometheus가 읽을 수 있게 전달한다.
- dashboard는 workflow 결과·지연, node 지연, model·Tool 사용량, retry·review·citation·stuck의
  네 영역으로 구성한다.
- alert는 workflow 실패, 저장 실패, 실행 한도 초과와 stuck처럼 의미가 명확한 조건부터 둔다.
- dashboard JSON, datasource 설정과 alert rule을 version control한다.

### 6. 통제된 장애 검증

1. LLM timeout
2. model 또는 Tool 호출 한도 초과
3. repository 조회 실패
4. citation revision·commit 불일치
5. Server 결과 저장 실패
6. 같은 request ID replay와 다른 payload 충돌
7. 장시간 `RUNNING` workflow 탐지

각 시나리오는 trace ID, 상태 전이, error kind, 마지막 완료 node, checkpoint, alert와 중복 저장
여부를 남긴다. production 경로에 공개 fault flag는 추가하지 않는다.

### 7. 운영 문서와 포트폴리오 증거

- 실행·dashboard 확인·trace 조사·alert 대응 순서를 runbook으로 작성한다.
- 정상 trace, 실패 trace, dashboard와 장애 검증 결과표를 캡처한다.
- 한 사례를 `탐지 → 병목 식별 → 상태·checkpoint 확인 → 안전 종료 확인`으로 정리한다.
- 수치에는 환경, 실행 횟수, 측정 시점과 통제된 실험이라는 제한을 표시한다.

## 저장소별 변경 범위

### `clio-agent-graph` — task 문서 소유

- telemetry envelope 계약, port·OTel adapter와 graph·runtime 계측
- Agent metric·JSON log, 장애 테스트, 관측 stack·dashboard·runbook

### `clio-server` — 연동 구현

- 구현 시작 전 최신 `main`에서 `task/operational-observability` 브랜치 생성
- dispatch context 전달, workflow metric·log, stuck gauge와 Server 테스트
- task 문서를 복제하지 않고 커밋에서 이 Agent task를 참조

## 사용자 결정 항목

### D1. 비동기 context 전달 방식

- A. root input에 검증된 telemetry envelope 추가
- B. request ID만 공통 log에 남기고 trace는 서비스별로 분리

추천: **A**. `/runs` 접수와 실제 graph 실행 사이의 비동기 경계를 결정적으로 연결한다. 공개 graph
입력 계약 변경을 원하지 않고 단일 trace를 포기할 수 있다면 A를 기각한다.

### D2. 1차 관측 표준

- A. OpenTelemetry·Micrometer를 기준으로 하고 LangSmith는 선택 유지
- B. LangSmith를 Agent의 주 관측 도구로 사용하고 Server metric만 별도 구성

추천: **A**. 두 서비스를 vendor-neutral trace로 연결한다. Agent 내부 LLM 분석만 필요하고 구현
기간이 우선이면 A는 과하므로 B를 선택한다.

### D3. 로컬 trace backend

- A. Tempo와 Grafana 사용
- B. Jaeger 독립 UI 사용

추천: **A**. metric에서 trace로 이동하는 조사 흐름을 한 화면에 구성한다. trace 확인만 빠르게
구현한다면 B가 단순하다.

### D4. log 수집 범위

- A. JSON stdout과 trace correlation까지만 구현
- B. Loki를 추가해 Grafana에서 log까지 연결

추천: **A**. 핵심 증거를 trace·metric·안전 종료에 집중한다. metric → trace → log 전환이 필수면
B를 선택한다.

### D5. trace ID 영속화

- A. trace backend와 log에만 저장하고 DB schema 유지
- B. `agent_workflow_runs`에 trace ID 저장

추천: **A**. workflow ID를 trace attribute로 검색할 수 있다. 관리자 UI에서 장기 링크가 필요하면
B가 필요하다.

### D6. Agent 계측 방식

- A. HTTP context는 경계 adapter, graph·LLM·Tool은 공통 wrapper로 명시 계측
- B. Python zero-code 계측을 중심으로 필요한 attribute만 추가

추천: **A**. 업무 의미와 민감정보 제한을 테스트할 수 있다. smoke demo만 필요하면 B가 빠르다.

### D7. 장애 주입과 alert 기준

- A. port fake·test stub과 제한된 인프라 중단, 의미 기반 alert부터 적용
- B. runtime fault flag와 임의 P95·오류율 threshold를 먼저 제공

추천: **A**. 오용 가능한 장애 스위치와 근거 없는 SLA를 피한다. UI에서 장애를 즉시 전환하는
데모나 합의된 SLO가 이미 있다면 B를 재검토한다.

## 검증 순서

1. Agent 계약·민감정보·cardinality 단위 테스트와 graph 테스트
2. Server propagation·workflow metric·stuck gauge 테스트
3. Agent Ruff format·lint·전체 pytest
4. Server compile·전체 test
5. 로컬 정상 trace, dashboard와 7개 장애 시나리오 검증
