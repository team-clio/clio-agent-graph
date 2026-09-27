# PCM repository sync 개선 검증

- 목표: 반복 실험에서 드러난 repository sync 실패를 재현 가능한 방어로 줄인다.
- 최종 revision: 080774bf7ce45c717f1b4568a5a5d293b345b3de
- 검증 조건: 실행마다 빈 Server DB·Agent DB·PCM 디렉터리
- 사람 리뷰: 리뷰 필요

## 문제

수정 전 반복 과정에서 repository sync가 생성 모델 출력 때문에 실패했다.
관찰한 오류 유형은 다음 두 가지다.

- 이미 존재하거나 같은 change set에서 중복된 logical key
- update/no_change에 금지된 logical_key 또는 누락·충돌한 operation 필드

manifest는 실패 상태와 revision을 보존하며, 런타임 진단 로그로 오류 유형을 확인했다.

## 변경

| 방어 계층 | 변경 |
|---|---|
| 프롬프트 | create/update/no_change의 필수·금지 필드 명시 |
| 생성 검증 | 오류를 모델에 돌려주며 최대 3회 재시도 |
| commit 경합 | 최신 snapshot·후보를 재조회한 뒤 재생성 |
| 경계 정규화 | 의미 없는 비활성 식별자만 제거하고 필수값은 추론하지 않음 |
| 회귀 테스트 | commit 실패 피드백과 식별자 정규화 사례 추가 |

## 최종 revision E2E 결과

| 회차 | sync | 품질 점수 | 실행 시간 |
|---|---|---:|---:|
| 2 | 성공 | 94.17 | 32.63초 |
| 3 | 성공 | 94.17 | 36.56초 |
| 4 | 성공 | 86.67 | 34.65초 |
| 5 | 성공 | 94.17 | 36.62초 |

- repository sync 성공: 4/4
- 분석 완료 및 평가 통과: 4/4
- 평균 품질 점수: 92.30
- 평균 실행 시간: 35.12초
- 전체 Python 회귀 테스트: 통과(3건 skip 포함)

품질 점수 변동은 남아 있으므로 이 결과는 sync 안정화 증거로만 사용한다.

## 증거 위치

- final-revision/r2~r5: manifest, fixture commit, 실제 분석 결과, 차원별 score
- intermediate-failure/manifest.json: 첫 방어만 적용했을 때 남은 실패
- 코드: repository_pipeline.py, pipeline.py, models.py, knowledge_model.py
- 테스트: tests/pcm/test_repository_pipeline.py

## 남은 검증

- 30건 평가셋에서 sync 성공률과 재시도 횟수 분포 측정
- 재시도 횟수·실패 유형을 Prometheus metric으로 노출
- 코드 위치 점수가 50%로 떨어진 4회차 원인 분석
