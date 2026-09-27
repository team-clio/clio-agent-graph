# Clio 프로필 공정 A/B 실험

- 실행일: 2026-09-27
- 상태: 1건·1회 비교 완료, 반복·확장 실험 필요
- 목적: 같은 코드와 fixture에서 검색·검증 파이프라인의 효과를 분리해 확인한다.
- 예상 독자: AX·AI Application Development 채용 면접관
- 사람 리뷰: 리뷰 필요

## 결론

동일 Agent·Server·fixture·oracle·모델 조건에서 `one-shot`은 86.67점, `full-clio`는 100점을 기록했다. `full-clio`는 **+13.33점** 높았고 실행 시간은 30.624초에서 32.610초로 **1.986초(6.5%) 증가**했다.

현재 결과는 사례 1건·반복 1회이므로 파이프라인의 일반 성능으로 해석하지 않는다.

## 통제 조건

| 조건 | 값 |
|---|---|
| Agent revision | `47aa8ac32cf60ad379bc421f45fadb3a37bc7be9` |
| Server revision | `2a56794b5c3380f8514b4615eb5d943f298e8d42` |
| Fixture revision | `ab6286c0b43e92a57a26ace27e1cc46d4de4a009` |
| 모델 | `openai:deepseek-v4-flash` |
| 평가기 | `task/benchmark-comparison`의 `1c70901` |
| 평가 사례 | `flag-value-changes-after-another-tenant-lookup` |
| 실행 격리 | 프로필별 빈 Server DB·Agent DB·PCM 디렉터리 |

## 실제 실행 경로

- `one-shot`: `prepare_analysis → search_code → analyze_issue → plan_resolution → assess_risk → save_analysis`
- `full-clio`: `prepare_analysis → search_documents + search_code + search_history → analyze_issue → plan_resolution → quality_gate → assess_risk → save_analysis`
- 단순 프로필은 `CLIO_BENCHMARK_MODE=true`일 때만 실행된다.
- 그래프 노드 구성이 다른지는 `tests/test_analysis_profile.py`가 검증한다.

## 결과

| 지표 | one-shot | full-clio | 변화 |
|---|---:|---:|---:|
| 종합 점수 | 86.67 | 100.00 | **+13.33점** |
| 통과율 | 100% | 100% | 동일 |
| 판정 정확성 | 100 | 100 | 동일 |
| 원인 분석 | 100 | 100 | 동일 |
| 코드 위치 식별 | 50 | 100 | **+50점** |
| 근거 품질 | 100 | 100 | 동일 |
| 재현 계획 | 66.7 | 100 | **+33.3점** |
| 불확실성 처리 | 50 | 100 | **+50점** |
| 실행 시간 | 30.624초 | 32.610초 | +1.986초 |

가중치 기준 총점 상승분은 코드 위치 `+7.50`, 재현 계획 `+3.33`, 불확실성 `+2.50`으로 합계 `+13.33점`이다.

## 출력이 달라진 이유

`one-shot`은 초기 코드 검색에서 README 근거만 확보했다. 구현 본문이 없으므로 캐시 키 결함을 가설로 남겼고 confidence는 0.55였다.

`full-clio`는 PCM 문서·코드 지식과 이력을 함께 검색하고 Quality Gate를 실행했다. 그 결과 다음 구현 근거를 확보했다.

- `src/feature_flags/cache.py`: `FeatureFlagCache._key`가 `tenant_id`를 제외함
- `src/feature_flags/repository.py`: 저장소는 `(tenant_id, flag_name.casefold())` 키 사용
- `src/feature_flags/service.py`: 오염된 캐시 값이 우선 반환되는 cache-aside 경로
- `tests/test_feature_flags.py`: `tenant-alpha` 이후 `tenant-beta` 값 격리 조건

이 근거를 사용해 정확한 파일·심볼, 테스트 경로와 두 tenant를 포함한 재현 계획을 작성했고 confidence는 0.84가 됐다.

## 원본 증거

- `one-shot/manifest.json`: 실행 설정과 revision
- `one-shot/summary.json`: 총점과 차원별 점수
- `one-shot/cases/.../result.json`: 실제 저장된 분석 결과
- `one-shot/cases/.../score.json`: 사례별 판정 결과
- `full-clio/`: 동일 구조의 full-clio 원본

## 제한사항과 다음 단계

- LLM 확률성을 통제하지 못했으므로 프로필당 최소 5회 반복이 필요하다.
- 평가 사례를 계획한 30건으로 늘려 결함 유형별 평균·표준편차를 산출해야 한다.
- 두 실행 모두 verification endpoint의 read-only transaction 오류로 `verification_status=unavailable`이었다. 점수는 저장된 분석 결과를 사용해 계산됐다.
- 토큰·모델 호출 수가 benchmark summary에 연결되지 않아 이번 비교의 비용 분석은 실행 시간만 가능하다.
- 포트폴리오에는 “단일 사례 1회 결과”라고 명시하고, 반복 실험 전에는 일반화된 성능 향상으로 표현하지 않는다.
