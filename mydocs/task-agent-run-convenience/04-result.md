# clio-agent 실행 편의화 — 결과

## 완료 사항

`task/agent-run-convenience` 브랜치에서 다음을 추가했다.

- `Makefile`: `dev` · `inspect` · `infra` · `help`
- `scripts/dev.sh`: `.env` 로드, inspect 서버 백그라운드 시작,
  `langgraph dev` foreground 실행, 종료 시 inspect 정리
- README 로컬 실행에 `make dev` 사용법 추가

## 사용법

```bash
make dev      # PCM inspect 서버(:2025) + langgraph dev(:2024)
make inspect  # inspect 서버만
make infra    # Ollama embedding Docker 시작
```

## 검증

```bash
bash -n scripts/dev.sh        # 문법 통과
make help                     # dev/inspect/infra 표시
inspect 서버 smoke test       # /docs 200
```

ruff 전역 검사에서 남는 E501·I001은 이 작업 전 파일이며 이 작업 변경 파일은
Python 코드가 아니다.

## 남은 과제

- PR(base=main)을 열어 머지한다.
- `make dev`를 실제로 실행해 `langgraph dev`와 inspect 서버가 함께 뜨는지 최종 확인한다
  (로컬 :2024 실행 중과 중복될 수 있어 이번 검증에서는 smoke test로 대체).
