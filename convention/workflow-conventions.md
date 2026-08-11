# LangGraph 워크플로 컨벤션

## Graph 구성

- 외부에 노출되는 module-level graph 객체와 별도로 `build_*_graph()` factory를 제공한다.
- factory 인자로 port 구현, subgraph, Tool, 설정을 주입할 수 있게 해 테스트와 운영 adapter를
  같은 graph 구조에서 사용한다.
- 노드 이름은 동작을 나타내는 `snake_case` 동사구로 짓고 state key와 로그에서 그대로
  추적할 수 있게 안정적으로 유지한다.
- 분기는 노드 내부에서 다음 노드를 호출하지 않고 `add_conditional_edges()`와 작은 route
  함수로 표현한다.
- 재사용 가능한 workflow는 compiled subgraph로 만들고 상위 graph의 node로 연결한다.
- 독립 공개 그래프에는 가능하면 `input_schema`와 `output_schema`를 지정해 내부 state를
  API 응답에서 숨긴다.

## State 계약

- graph state는 `TypedDict`로 선언한다. 외부 입력·출력과 내부 누적 상태를 구분한다.
- 루트 orchestration state는 관심사별 state를 합성한다. 기능 subgraph가 전역 state를
  import해 결합도를 높이지 않게 한다.
- 대부분의 내부 state는 `total=False`로 두되, node는 자신의 선행 edge가 보장하는 key만
  읽는다. 공개 input/output은 필수 key를 명시한다.
- 병렬 node가 같은 map을 합칠 때는 `Annotated[..., reducer]`를 사용한다. 현재
  `completed_nodes`는 `operator.or_`로 병합한다.
- node는 state 전체를 복사하지 않고 자신이 변경한 key만 `dict`로 반환한다.
- Pydantic domain 객체를 state에 보관할지 JSON dict로 보관할지는 공개 계약에 맞춘다.
  경계에서는 항상 `model_validate()`와 `model_dump()`로 변환을 명시한다.

## Node 책임

Node는 다음 작업에 집중한다.

1. state에서 입력을 꺼내 Pydantic/domain 계약으로 검증한다.
2. Tool, Agent 또는 Service를 호출한다.
3. 결과와 관찰 가능한 terminal status를 state update로 반환한다.

복잡한 정규화, 정책, 재시도, persistence 로직은 node에 누적하지 않고 service로 옮긴다.
Agent prompt와 provider 호출은 adapter/runtime에 둔다.

## Routing과 종료 상태

- routing은 LLM 판단이 아니라 검증된 enum/literal 또는 정책 결과로 결정적으로 수행한다.
- 모든 루트 workflow는 `status`, `result`, `error` 공통 결과 계약으로 수렴한다.
- 정상 완료, 사람 검토 필요, 실패를 서로 다른 상태로 표현한다. 불확실한 결과를 성공으로
  위장하지 않는다.
- quality gate 재시도는 state의 시도 횟수처럼 명시적이고 bounded한 조건을 사용한다.

## 동시성과 snapshot

- 서로 독립적인 read 작업은 fan-out/fan-in edge로 병렬화한다.
- 병렬 node는 동일 key를 덮어쓰지 않거나 reducer를 선언해야 한다.
- 한 분석 실행에서 context가 흔들리지 않도록 시작 시 snapshot을 resolve한다.
- PCM citation은 knowledge revision을, repository citation은 repository ID와 commit을 포함한다.
- quality gate는 citation의 revision/commit이 실행 snapshot과 다르면 `needs_review`로 보낸다.

## 새 workflow 추가 체크리스트

1. 공개 입력·출력과 domain model을 먼저 정의한다.
2. 외부 의존성은 `Protocol` port로 추상화한다.
3. service와 adapter를 구현하고 factory에서 조립한다.
4. 전용 `TypedDict` state와 작은 node·route 함수를 만든다.
5. `build_*_graph()`를 작성하고 필요한 entrypoint만 `langgraph.json`에 등록한다.
6. node, service, graph routing 및 architecture 회귀 테스트를 추가한다.

