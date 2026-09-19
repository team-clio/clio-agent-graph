# 운영 관측성 구축 Overview

> 승인: 2026-09-19

## 문서 정보

- 작성일: 2026-09-19
- 상태: 승인 완료
- 예상 독자: Clio Agent·Server 개발자와 포트폴리오 검토자
- 리뷰: 사용자 리뷰 필요

## 배경

Clio는 한 요청에서 Spring Server의 workflow lifecycle, Python Agent의 LangGraph node,
LLM·Tool 호출, Quality Gate, 결과 저장을 연속해서 실행한다. 현재는 workflow 상태와 checkpoint,
Agent의 `completed_nodes`, 제한 초과와 `NEEDS_REVIEW` 처리처럼 실패를 안전하게 종료할 기반이
있다. 그러나 요청 전체를 하나의 trace로 연결하거나 지연·실패·재시도·검토 전환을 집계하는 운영
증거는 부족하다.

포트폴리오에서는 기능 구현만큼 다음 질문에 답할 수 있어야 한다.

1. 요청이 느리거나 실패했을 때 어느 단계에서 문제가 발생했는가?
2. LLM·Tool 호출량과 실행 제한, Quality Gate 재시도는 어떻게 확인하는가?
3. 실패 후 checkpoint와 상태가 보존되고 중복 요청이 안전하게 처리되는가?
4. 운영자가 dashboard와 alert에서 이상을 발견하고 trace·log로 원인을 좁힐 수 있는가?

## 현재 상태

### 이미 있는 기반

- Server의 `AgentWorkflowRun`은 요청 ID·hash, 상태, checkpoint, 결과, 실패 코드와 시작·완료
  시각을 저장한다.
- 같은 요청 ID의 재호출은 hash를 비교해 멱등 replay와 충돌을 구분한다.
- Agent state의 `completed_nodes`로 완료된 graph 단계를 확인할 수 있다.
- Agent 실행 한도 초과는 model·tool·recursion 유형으로 구분하며 분석 근거를 보존한 채
  `NEEDS_REVIEW`로 전환할 수 있다.
- Quality Gate는 결과 계약과 citation의 revision·commit 무결성을 검사한다.
- Server에는 Spring Boot Actuator가 포함되어 있고 Agent에는 선택적 LangSmith 설정이 있다.

### 부족한 부분

- Server와 Agent 사이에 공통 trace context와 식별자 규칙이 없다.
- workflow·node·LLM·Tool·Quality Gate를 잇는 span과 공통 구조화 log가 없다.
- 처리량, 성공·실패·검토 비율, 지연, token·호출량, 실행 한도 초과를 집계하는 metric이 없다.
- stuck workflow와 저장 실패를 탐지하는 dashboard·alert·runbook이 없다.
- 실패 시나리오를 의도적으로 재현해 상태 전이와 복구 가능성을 검증한 자료가 없다.

## 문제

현재 구조는 최종 상태와 일부 실행 흔적을 남기지만, 여러 서비스의 기록을 요청 단위로 연결하기
어렵다. 문제가 발생하면 로그를 수동으로 맞춰 보아야 하며 어느 node·외부 호출이 병목인지,
실패가 안전하게 종료되었는지, 같은 문제가 반복되는지 빠르게 판단하기 어렵다.

실제 운영 트래픽이 없는 상태에서 일반적인 성공률이나 SLA를 주장하면 신뢰도가 낮다. 따라서 이
작업은 운영 성과를 과장하지 않고, 통제된 장애 주입으로 탐지·추적·안전 종료가 실제로 동작함을
검증하는 데 초점을 둔다.

## 개선 방향

- 한 요청의 Server → Agent → LLM·Tool → Quality Gate → 저장 흐름을 단일 trace로 연결한다.
- metric label은 낮은 cardinality로 제한하고 요청 식별자는 trace와 log에만 기록한다.
- prompt·응답 원문, repository credential, source 원문, 개인정보는 telemetry에 남기지 않는다.
- 기존 workflow 상태와 실패 코드를 관측 계약의 기준으로 재사용한다.
- 성공 경로뿐 아니라 timeout, 호출 한도, repository 장애, citation 불일치, 저장 실패, 중복 요청을
  검증한다.
- 포트폴리오에는 trace waterfall, dashboard, 장애 조사 사례와 장애 주입 결과를 근거로 제시한다.

## 작업 범위

### 포함

- Server·Agent 공통 correlation ID, trace context, event, failure code 계약
- workflow·node·LLM·Tool·Quality Gate·결과 저장 tracing
- workflow 결과·지연, node 지연·실패, 모델·Tool 호출, 품질 검증 metric
- 민감정보를 제외한 JSON 구조화 log
- Prometheus·Grafana와 trace backend의 로컬 관측 환경
- dashboard, 최소 alert 규칙, 장애 조사 runbook
- 통제된 장애 주입 시나리오와 자동·수동 검증
- 포트폴리오에 사용할 관측성 증거의 수집 기준

### 제외

- 실제 운영 SLA·SLO 확정과 장기간 production 성과 주장
- prompt·응답 원문을 저장하는 LLM 감사 시스템
- 사용자 행동 분석, 제품 BI, 비용 청구 기능
- benchmark 점수의 통계적 신뢰도 개선
- workflow 재시도 정책 자체의 전면 재설계
- hosted observability 서비스의 운영 계정·배포 구성

## 완료 기준

1. Server와 Agent의 동일 요청을 하나의 trace에서 확인할 수 있다.
2. workflow·node·LLM·Tool·Quality Gate의 지연과 결과가 span 또는 metric으로 관측된다.
3. metric에 request ID·workflow ID 같은 고유 식별자를 label로 사용하지 않는다.
4. 구조화 log에서 trace ID와 workflow ID로 관련 기록을 검색할 수 있다.
5. dashboard에서 결과 분포, 지연, 호출량, 검토·제한·stuck 상태를 확인할 수 있다.
6. 정한 장애 시나리오마다 상태 전이, 실패 코드, 마지막 완료 node, checkpoint 보존과 alert 결과를
   재현할 수 있다.
7. telemetry에서 secret, prompt·응답 원문, source 원문과 개인정보가 노출되지 않는다.
8. Agent와 Server의 기존 테스트가 통과하고 관측 기능이 꺼져도 핵심 업무 흐름이 유지된다.

## 주요 위험

- span·metric을 node마다 직접 작성하면 업무 코드에 관측 코드가 과도하게 섞일 수 있다.
- 식별자나 자유 텍스트를 metric label로 사용하면 cardinality와 저장 비용이 급증한다.
- LLM 입력·출력을 편의상 기록하면 source code와 개인정보가 유출될 수 있다.
- 로컬 장애 주입 결과를 실제 production 안정성으로 표현하면 성과가 과장된다.
- LangSmith와 OpenTelemetry의 책임이 겹치면 추적 기준이 이중화될 수 있다.
- Server와 Agent의 trace propagation 방식이 다르면 단일 요청이 여러 trace로 분리될 수 있다.

## 포트폴리오 표현 원칙

- `운영 성과`가 아니라 `운영 준비도와 통제된 장애 검증`으로 표현한다.
- 성공 화면 하나보다 정상·실패 trace와 원인 규명 과정을 함께 제시한다.
- 수치에는 환경, 시나리오, 실행 횟수와 측정 시점을 표시한다.
- 실제로 수집하지 않은 P95, 비용 절감률, 복구 시간은 추정해 쓰지 않는다.

## 후속 작업

- baseline을 충분히 수집한 뒤 SLI와 alert threshold를 조정한다.
- 실제 배포 환경이 정해지면 retention, sampling, 접근 제어와 비용 정책을 별도 결정한다.
- 운영 트래픽이 생기면 통제된 검증 결과와 실제 incident 데이터를 분리해 관리한다.
