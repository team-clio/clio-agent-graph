# Clio Agent Graph 아키텍처·컨벤션

이 폴더는 현재 구현을 기준으로 프로젝트의 구조와 변경 원칙을 설명한다. 새로운 기능을
추가할 때는 먼저 공개 그래프 계약을 고른 뒤, 의존성 방향과 권한 경계를 지키는 것을
기본 원칙으로 삼는다.

## 문서 목록

- [architecture.md](architecture.md): 공개 그래프, 계층 구조, 주요 실행 흐름
- [workflow-conventions.md](workflow-conventions.md): LangGraph state·node·subgraph 설계 규칙
- [code-conventions.md](code-conventions.md): 모델, port, service, adapter, Tool 및 오류 처리 규칙
- [testing-and-operations.md](testing-and-operations.md): 테스트 배치, 설정, 실행 및 검증 규칙

## 가장 중요한 원칙

1. `graph.py`는 안정적인 루트 이벤트 진입점으로 유지한다.
2. 기능 패키지는 상위 orchestration state에 의존하지 않는다.
3. Agent에는 bounded read Tool만 노출하고, 쓰기는 Graph Node가 Service를 호출해 수행한다.
4. 외부 구현은 `Protocol` 뒤에 두고 graph 생성 경계에서 주입한다.
5. 공개 입력과 LLM 출력은 Pydantic으로 엄격하게 검증한다.
6. 분석 중에는 PCM revision과 repository commit을 snapshot으로 고정한다.
7. 동작 변경에는 같은 계층의 단위 테스트와 필요 시 graph 회귀 테스트를 함께 추가한다.

