# Clio 운영 관측성 실행 가이드

## 목적

로컬에서 Clio Server와 Agent Graph의 metric·trace를 한 화면에서 확인한다. 이 구성은 개발·포트폴리오 증거 수집용이며 인증, 장기 보관, 고가용성을 제공하지 않는다.

## 실행

1. 관측성 스택을 시작한다.

   ```bash
   docker compose -f compose.observability.yaml up -d
   ```

2. Server를 `8080` 포트에서 실행한다. 기본 설정으로 `/actuator/prometheus`가 노출되고 trace가 `localhost:4318`로 전송된다.

3. Agent Graph를 아래 환경으로 실행한다.

   ```bash
   CLIO_OTEL_ENABLED=true \
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
   uv run langgraph dev
   ```

4. `http://localhost:3000/d/clio-operations`에서 대시보드를 확인한다. Trace는 Grafana의 Explore에서 Tempo를 선택해 조회한다.

## 대시보드에서 보는 것

카운터와 지연시간은 Grafana에서 선택한 시간 구간(`$__range`)을 기준으로 계산한다. Workflow
완료·실패·지연은 상태 저장의 기준점인 `clio-server`를 사용하고, Node·LLM·Tool·Quality Gate는
실제 실행 주체인 `clio-agent-graph`를 사용한다. 따라서 동일 Workflow를 양쪽에서 중복 집계하지 않는다.

| 질문 | 지표 |
| --- | --- |
| 요청이 실제로 처리됐나? | `clio_workflow_total` |
| 얼마나 느렸나? | `clio_workflow_duration_seconds` p95 |
| 어느 단계가 병목인가? | `clio_node_duration_seconds` p95 |
| 모델 호출이 얼마나 발생했나? | `clio_model_call_total`, `clio_model_token_total` |
| Tool이 실제로 성공했나? | `clio_tool_call_total`, `clio_tool_call_duration_seconds` |
| 품질 검증이 막아냈나? | `clio_quality_gate_total`, `clio_citation_rejected_total` |
| 사람이 봐야 할 결과가 늘었나? | `clio_analysis_needs_review_total` |
| 작업이 멈춰 있나? | `clio_workflow_stuck`, `clio_workflow_running_age_max_seconds` |

요청 ID와 workflow run ID는 metric label에 넣지 않는다. 상세 원인 추적은 같은 시간대의 trace에서 확인한다.
Agent 지연시간 histogram은 5ms부터 30초까지 명시적 구간을 사용해 짧은 Node·Tool 실행의 p95가
수 초로 과대 표시되지 않게 한다. 대시보드 제목·범례와 패널 설명은 포트폴리오 독자를 위해 한국어로 제공한다.

## 의도적 장애 검증

| 시나리오 | 기대 증거 |
| --- | --- |
| 잘못된 `traceparent` 전달 | 새 trace로 안전하게 시작하고 `clio_telemetry_context_invalid_total` 증가 |
| 모델 또는 도구 호출 한도 초과 | `clio_execution_limit_total` 증가, workflow 실패 trace 생성 |
| citation snapshot 불일치 | `clio_citation_rejected_total{reason="snapshot_mismatch"}` 증가 |
| 동일 request ID·다른 payload 재요청 | Server의 `clio_workflow_request_conflict_total` 증가 |
| RUNNING 상태를 정체 기준 이상 유지 | `ClioWorkflowStuck` 알람 활성화 |

## 포트폴리오 증거 캡처

- 전체 대시보드: 처리량, 실패율, p95, 정체 작업이 함께 보이는 화면
- 병목 화면: 가장 느린 node와 해당 시간대 trace waterfall
- 안전장치 화면: limit 또는 citation 오류를 주입한 전후의 counter 변화
- 캡처에는 실행 기간, 요청 수, 테스트 데이터 조건을 함께 적는다.

## 종료

```bash
docker compose -f compose.observability.yaml down
```

데이터까지 초기화하려면 `down -v`가 필요하다. 해당 명령은 저장된 metric·trace·Grafana 상태를 삭제하므로 증거 캡처 후에만 사용한다.
