# Report Normalizer(NM) 구현 결과

## 결과 요약

기존 채팅 데모 scaffold를 실제 Clio 도메인 그래프로 교체했다.

```text
START → normalize_report → END
```

NM은 원본 `bug_report_id`를 유지하면서 발생 현상, 기대 동작, 재현 정보, 환경, 영향 기능, 오류 신호와
누락 정보를 `NormalizedReport`로 반환한다. Evidence·원인·코드 검색어·우선순위는 만들지 않는다.

## 구현 내용

- Pydantic 기반 `NormalizeReportInput`, `NormalizationDraft`, `NormalizedReport` 계약
- Java interface 역할의 `NormalizationModel` Protocol
- 구조화 수집 필드를 우선 병합하고 누락 목록을 계산하는 `ReportNormalizer`
- structured output 오류를 한 번만 교정하고 부분 결과 없이 실패하는 정책
- 중첩 raw payload 민감 key 마스킹과 기본 32 KiB 상한
- `CLIO_MODEL`을 최초 호출 때 지연 생성하는 LangChain adapter
- 원문 사실만 추출하고 입력 언어와 기술 식별자를 보존하는 프롬프트
- Fake 모델을 주입할 수 있는 NM LangGraph
- Python 초심자를 위한 한글 docstring과 문법·decorator 설명 주석

## 공개 계약 변경

이전 scaffold의 `messages/request/plan/result` 계약은 제거했다. 그래프 입력은 `bug_report`, 출력은
`normalized_report` 하나다. 상세 JSON 예시는 프로젝트 `README.md`에 기록했다.

## 검증 결과

```text
pytest                  : 19 passed
ruff check .            : 통과
ruff format --check .   : 14 files already formatted
```

테스트는 구조화 입력 우선순위, 결정적 누락 계산, 1회 교정, 부분 결과 금지, provider 오류 전파, 민감정보
마스킹, payload 경계값, 모델 지연 생성, 공개 그래프 입출력을 검증한다. 외부 API는 호출하지 않는다.

## 남은 한계

- 실제 운영 모델의 추출 정확도와 비용은 별도 평가 데이터셋으로 측정해야 한다.
- BugReport 불변 보존과 Agent Graph 호출·결과 저장은 Clio Server 연동 작업에 남아 있다.
- `missing_fields`는 원문에 값이 없다는 뜻이며 해당 버그에 반드시 필요한 정보라는 뜻은 아니다.
- provider 자체의 일시적 오류 재시도와 운영 체크포인터는 이번 범위에 포함하지 않았다.
- RM·IA가 실제로 소비한 뒤 공통 state와 계약 승격 여부를 결정해야 한다.
