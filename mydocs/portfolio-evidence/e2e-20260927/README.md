# Clio E2E 포트폴리오 증거 패키지

- 작성일: 2026-09-27
- 목적: 같은 평가 기준에서 Clio 분석 품질의 전후 차이와 운영 관측 가능성을 검증한다.
- 예상 독자: AX·AI Application Development 채용 면접관
- 상태: 로컬 통제 실험 완료, 반복·확장 실험 필요
- 사람 리뷰: 리뷰 필요

## 한 줄 결과

동일 fixture·oracle·가중치로 실행한 단일 E2E 사례에서 총점이 **77.92점에서 91.25점으로 13.33점 상승**했다. 코드 위치, 재현 계획, 불확실성 처리 점수는 각각 50→100, 66.7→100, 50→100으로 개선됐고, 실행 시간은 30.645초에서 34.752초로 4.107초 증가했다.

## 증거 구조

| 위치 | 내용 | 검증 용도 |
|---|---|---|
| `baseline/` | 2026-09-18 기준 실행의 manifest·summary·report | 개선 전 점수와 실행 조건 확인 |
| `current/` | 2026-09-27 재실행의 manifest·summary·report | 개선 후 점수와 실행 조건 확인 |
| `failures/` | 최종 성공 전 실패한 두 실행의 manifest | 실패를 제외하거나 숨기지 않았음을 확인 |
| `comparison.md` | 비교표, 해석, 제한사항 | 포트폴리오 장표 작성 기준 |
| `../50-final-operational-dashboard.png` | Grafana 운영 대시보드 전체 화면 | 워크플로·모델·품질 게이트 관측 확인 |
| `../51-final-operational-dashboard-crop.png` | 포트폴리오 삽입용 핵심 영역 | 장표에 불필요한 하단 패널 제외 |

## 재현 조건

- Agent: `7816b896acbdd54e00ed15c8bd9f2dcaaf12e3ba`
- Server: `2a56794b5c3380f8514b4615eb5d943f298e8d42`
- Fixture: `ab6286c0b43e92a57a26ace27e1cc46d4de4a009`
- 평가기: `task/benchmark-comparison`의 `1c70901`
- 분석 프로필: `one-shot`
- 통과 기준: 70점
- 사례: `flag-value-changes-after-another-tenant-lookup`
- 현재 실행 ID: `20260927T124510Z-43a9296a`

구체적인 가중치와 환경 변수 이름은 `current/manifest.json`, 항목별 판정 근거는 `current/summary.json`에서 확인한다. 비밀값은 manifest에 기록하지 않았다.

## 신뢰 장치

1. 점수표만 제시하지 않고 실행 ID, Git revision, 평가 설정을 manifest로 보존했다.
2. 총점의 구성 항목과 각 항목의 통과 개수를 summary에 보존했다.
3. 개선 전·후에 같은 oracle과 가중치를 사용했다.
4. 실패 실행도 별도 보존해 성공 결과만 선택적으로 만든 것처럼 보이지 않게 했다.
5. 운영 화면은 결과 수치와 함께 워크플로 실패율, 지연, 모델 호출, 토큰, quality gate, citation rejection을 한 화면에 배치했다.

## 제한사항

- 사례 1건·반복 1회 결과이므로 일반화나 통계적 유의성을 주장하지 않는다.
- LLM 출력의 확률성 때문에 동일 조건 반복 시 점수가 달라질 수 있다.
- 최신 Benchmark `main`은 fixture 계약과 집계 방식이 달라, 기존 77.92점과 같은 평가기로 비교하기 위해 평가기 커밋 `1c70901`을 사용했다.
- 실행 완료 후 Server verification endpoint가 HTTP 500을 반환해 verification 상태는 `unavailable`이었다. 점수 계산은 저장된 분석 결과로 완료됐다.
- Grafana 캡처는 벤치마크 1회와 관측 패널 확인용 후속 워크플로가 포함된 시간 구간이다. 따라서 호출·토큰 수를 벤치마크 1회의 비용으로 해석하지 않는다.
- 실행 후 OTLP exporter에서 수집기 연결 timeout이 발생했다. 캡처 시점 데이터는 표시됐지만 장기 보존성은 별도 개선이 필요하다.

## 다음 검증

- 동일 사례를 최소 5회 반복해 평균·표준편차·최솟값을 산출한다.
- 평가셋을 계획한 30건으로 확장해 결함 유형별 성능을 비교한다.
- verification endpoint 500과 OTLP exporter timeout을 수정한다.
- 토큰·모델 호출 수를 benchmark summary에 직접 기록해 품질 대비 비용을 비교한다.
