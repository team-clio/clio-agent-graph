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
