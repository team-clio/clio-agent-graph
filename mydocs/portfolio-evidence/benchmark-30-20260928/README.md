# Clio 30건 비교 실험 증거

- 상태: 완료 — `full-clio`와 `one-shot` 각각 30건, 2026-09-28
- 예상 독자: 포트폴리오 검토자와 실험 재현 담당자
- 사람 리뷰: 리뷰 필요
- 변경 기록: 2026-09-28, 잔액 부족으로 중단된 기록을 보존하고 독립 재실행 결과로 갱신

## 핵심 결과

동일한 합성 Python feature flag 저장소의 결함 10개를 보고 문구 3종으로 표현해 두 프로필에 입력했다. 결과는 [비교 보고서](comparison.md)와 [Figma용 SVG](benchmark-comparison.svg)에 정리했다.

| 지표 | full-clio | one-shot |
|---|---:|---:|
| 평균 품질 점수 / 100 | 92.68 | 80.56 |
| 70점 이상 통과 | 28/30 | 24/30 |
| 분석 평균 소요시간 | 32.8초 | 27.5초 |

이 결과는 30개의 독립 결함이 아니라 **독립 결함 10개 × 표현 3종**에 대한 단일 실행이다. 일반적인 실제 운영 성능이나 개별 구성요소의 기여도로 확대 해석하지 않는다.

## 비교 조건과 원본

| 항목 | 값 또는 위치 |
|---|---|
| Agent 커밋 | `074b8851be04a05c90a6a2f3b94b8e7801f0bd49` |
| Server 커밋 | `8d88a73f02dffaf581c01fe69b2044fcc1e93ebb` |
| Fixture 커밋 | `b30e31e3c83d0faf4e27a38a29498b859d8f7520` |
| 설정 | [full-clio](benchmark.fullclio-30.yaml), [one-shot](benchmark.oneshot-30.yaml) — `experiment.profile`만 다름 |
| 평가 기준 | 비공개 oracle `feature-flags-30.json`(저장소 미포함, SHA-256 `cae296ab4a75a516e80919176dce4424a6a2d9c7a9b02d12296f4219edaa4bb0`), 동일 가중치·70점 통과선·300초 제한 |
| 완료 실행 ID | full-clio `20260928T065850Z-59223a30`; one-shot `20260928T073431Z-64ae54ac` |
| 원본 결과 | [full-clio](full-clio/manifest.json), [one-shot](one-shot/manifest.json) — case별 입력·응답·분석·오류·점수 보존 |
| 재집계 | `python3 compare_runs.py` — 완료 상태, case 일치, 프로젝트 격리, SHA, 오류 검사 포함 |

`full-clio`는 문서·코드·이력 검색과 quality gate를 사용한다. `one-shot`은 코드 검색은 유지하되 문서·이력 검색과 quality gate를 끈 비교 프로필이다. 두 프로필 모두 case마다 별도 Clio 프로젝트를 생성했고, 프로필별 DB·PCM 저장소를 분리했다. `benchmark.json`과 `DATASET.md`는 검색 인덱스에서 제외했다.

## 해석과 제한

- `full-clio`는 짝지은 30건 중 26건에서 더 높았고, 2건은 `one-shot`이 높았으며 2건은 동률이다. `full-clio`도 2건에서 70점 미만이었다.
- 이 점수는 경로·핵심어·인용 무결성 등을 평가하는 deterministic oracle의 결과다. 실제 버그 수정 성공률이나 사람 평가가 아니다.
- 한 번씩만 실행했다. 모델 변동성과 다른 저장소로의 일반화는 검증하지 않았다.
- 문서·이력 검색과 quality gate를 함께 켰거나 껐으므로, 어느 한 기능만의 인과 효과는 말할 수 없다.
- 분석 소요시간은 저장소 동기화 시간을 포함하지 않는다. 토큰·모델 호출 수는 수집되지 않아 비교하지 않는다.

## 제외한 실행

처음 `full-clio` 30건 실행의 평균 82.30점은 같은 프로젝트의 이전 분석 결과를 재사용해 독립 case 성능으로 인용하지 않는다. 이후 case별 격리를 구현했다. 격리된 첫 실행 `20260928T063309Z-033dfb2f`은 13건을 저장한 뒤 14번째 저장소 동기화에서 DeepSeek `402 Insufficient Balance`로 중단됐다. 이 실행의 [manifest와 부분 결과](failed-independent-run/manifest.json)는 실패 기록으로만 보존한다. 충전 후 두 프로필을 새 저장소에서 처음부터 실행했으며, 부분 결과를 합치지 않았다.
