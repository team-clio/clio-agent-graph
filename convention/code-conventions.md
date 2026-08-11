# 코드 컨벤션

## Python 기본 규칙

- Python 3.11 문법과 네 칸 들여쓰기를 사용한다.
- 모든 공개 함수와 의미 있는 내부 함수에 타입 annotation을 작성한다.
- module·함수·변수·테스트는 `snake_case`, class는 `PascalCase`, 상수는
  `SCREAMING_SNAKE_CASE`를 사용한다.
- Ruff의 100자 제한과 `E`, `F`, `I`, `UP`, `B`, `SIM` 규칙을 따른다.
- module docstring은 해당 파일의 책임을 한 문장으로 설명한다.
- import는 표준 라이브러리, 외부 패키지, 프로젝트 패키지 순으로 둔다.

## 계약 모델

- 외부 요청, LLM structured output, persistence 경계에는 Pydantic `BaseModel`을 사용한다.
- 계약 모델은 기본적으로 `ConfigDict(extra="forbid")`를 사용해 알 수 없는 필드를 거부한다.
- immutable snapshot이나 PCM value object는 `frozen=True`도 사용한다.
- 제한된 값은 문자열 상수보다 `StrEnum` 또는 `Literal`로 표현한다.
- 길이, commit 형식, 상호 필드 조건은 `Field`와 validator에서 가능한 빨리 검증한다.
- 모델 간 참조 무결성이나 순번처럼 구조적 규칙도 model validator로 보호한다.

## Port, Service, Adapter

- 외부 기능의 최소 계약은 `ports.py` 또는 역할별 protocol module의 `Protocol`로 정의한다.
- `service.py`는 domain 정책, validation, retry와 use-case 조합을 담당한다.
- `*_adapter.py`, repository 구현은 LangChain, Codex, PostgreSQL, Ollama 같은 기술을 port에
  연결한다.
- 기본 구현은 `defaults.py`, embedding factory, graph factory 또는 application composition
  root에서 선택한다.
- 생성자에서는 가급적 네트워크 연결이나 모델 초기화를 하지 않는다. 실제 호출 시 lazy하게
  만들고 재사용해 import와 graph construction을 안전하게 유지한다.

## Agent와 Tool 권한

- Agent가 받는 Tool은 검색, 조회, 제한된 파일 읽기 같은 read-only 작업만 제공한다.
- 이슈 생성·연결, 분석 저장, PCM commit, 색인 변경, repository 활성화 같은 write는 Graph
  Node가 Service를 직접 호출한다.
- project ID, PCM snapshot, repository commit처럼 신뢰 경계를 정하는 값은 graph가 Tool
  factory closure에 고정한다. 모델이 Tool 인자로 선택하게 하지 않는다.
- Tool 입력과 출력은 작고 명시적으로 유지하며 결과 수, line range, payload 크기를 제한한다.
- repository 읽기는 path traversal과 secret 파일을 차단하고 민감 값을 masking한다.
- 자율 Agent는 model/tool 호출 수와 recursion limit을 둔 bounded loop로 실행한다.
- 최종 응답은 Pydantic structured output으로 검증하며, schema나 설명문을 결과 대신 허용하지 않는다.

## LLM과 prompt

- 모든 일반 LLM 호출은 전역 `CLIO_MODEL=provider:model` 선택을 공유한다.
- 노드별로 별도 모델 환경 변수를 만들지 않는다. base URL, API key env, extra body는 선택한
  전역 모델의 연결 옵션으로만 사용한다.
- provider-native JSON schema에 종속하지 않고 공통 function/tool calling 전략을 사용한다.
- prompt 생성은 `prompts.py`에 두고, adapter는 prompt 호출과 결과 변환에 집중한다.
- 모델 출력 오류는 한 번의 validation feedback retry처럼 명시적이고 제한된 정책으로 처리한다.
- Codex CLI는 선택적인 read-only 코드 탐색 adapter이며 일반 chat model 선택을 대체하지 않는다.

## 오류와 보안

- 기능별 `errors.py`에 의미 있는 예외 계층을 정의한다.
- 설정 누락, 외부 연산 실패, 잘못된 데이터, structured output 실패를 구분한다.
- 광범위한 예외를 조용히 삼키지 않는다. degrade가 설계된 경우에만 fallback과 상태를 명시한다.
- 원본 report는 크기를 제한하고 민감 key를 sanitize한 뒤 prompt에 전달한다.
- credential, remote repository 인증 정보, 서버 관리 경로는 Agent context에 노출하지 않는다.
- 요청과 change set은 재실행을 고려해 idempotent하게 설계한다.

## 배치 위치

| 변경 종류 | 기본 위치 |
|---|---|
| 공개 request/response | `models.py`, `requests.py`, graph input/output state |
| 비즈니스 규칙 | `service.py` |
| 외부 시스템 계약 | `ports.py` 또는 역할별 `Protocol` module |
| provider/DB/CLI 구현 | `*_adapter.py`, `postgres.py`, repository 구현 |
| graph 연결·분기 | `graph.py`, `graphs/`, 작은 `node.py` |
| Agent read API | `context/tools/` |
| 공통 LLM/Agent 실행 | `runtime/` |

