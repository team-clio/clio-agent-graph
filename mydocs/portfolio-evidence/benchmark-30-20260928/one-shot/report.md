# Clio Benchmark — one-shot

- Run: `20260928T073431Z-64ae54ac`
- Repetition: 1
- Cases: 30
- Mean quality score: **80.56/100**
- Pass rate: **80.0%**

## Quality dimensions

| Dimension | Mean |
|---|---:|
| verdict | 100.0% |
| root_cause | 92.5% |
| code_location | 50.0% |
| evidence_quality | 83.8% |
| reproduction | 54.4% |
| uncertainty | 53.3% |

## Cases

| Suite / case | Score | Result | Duration |
|---|---:|---|---:|
| feature-flags-30 / cache-tenant-leak-detailed | 78.23 | PASS | 32.87s |
| feature-flags-30 / cache-tenant-leak-short | 71.35 | PASS | 28.47s |
| feature-flags-30 / cache-tenant-leak-symptom | 83.85 | PASS | 26.49s |
| feature-flags-30 / cache-false-miss-detailed | 77.92 | PASS | 26.44s |
| feature-flags-30 / cache-false-miss-short | 60.83 | FAIL | 22.53s |
| feature-flags-30 / cache-false-miss-symptom | 68.01 | FAIL | 30.48s |
| feature-flags-30 / auth-role-escalation-detailed | 85.67 | PASS | 26.47s |
| feature-flags-30 / auth-role-escalation-short | 71.67 | PASS | 24.35s |
| feature-flags-30 / auth-role-escalation-symptom | 73.33 | PASS | 26.45s |
| feature-flags-30 / auth-project-scope-detailed | 68.17 | FAIL | 24.32s |
| feature-flags-30 / auth-project-scope-short | 57.50 | FAIL | 28.66s |
| feature-flags-30 / auth-project-scope-symptom | 61.67 | FAIL | 28.38s |
| feature-flags-30 / rollout-boundary-detailed | 100.00 | PASS | 24.37s |
| feature-flags-30 / rollout-boundary-short | 85.00 | PASS | 24.44s |
| feature-flags-30 / rollout-boundary-symptom | 97.50 | PASS | 28.40s |
| feature-flags-30 / rollout-hash-unstable-detailed | 100.00 | PASS | 30.29s |
| feature-flags-30 / rollout-hash-unstable-short | 81.67 | PASS | 26.49s |
| feature-flags-30 / rollout-hash-unstable-symptom | 97.50 | PASS | 30.44s |
| feature-flags-30 / target-country-case-detailed | 85.00 | PASS | 28.34s |
| feature-flags-30 / target-country-case-short | 85.42 | PASS | 26.35s |
| feature-flags-30 / target-country-case-symptom | 81.67 | PASS | 30.44s |
| feature-flags-30 / target-empty-allowlist-detailed | 85.00 | PASS | 28.43s |
| feature-flags-30 / target-empty-allowlist-short | 81.67 | PASS | 26.42s |
| feature-flags-30 / target-empty-allowlist-symptom | 60.83 | FAIL | 24.47s |
| feature-flags-30 / repository-delete-case-detailed | 97.50 | PASS | 28.44s |
| feature-flags-30 / repository-delete-case-short | 78.75 | PASS | 26.40s |
| feature-flags-30 / repository-delete-case-symptom | 97.50 | PASS | 26.46s |
| feature-flags-30 / repository-list-tenant-detailed | 85.42 | PASS | 26.41s |
| feature-flags-30 / repository-list-tenant-short | 79.00 | PASS | 30.40s |
| feature-flags-30 / repository-list-tenant-symptom | 79.29 | PASS | 30.83s |

> Token, model-call and tool-call metrics remain N/A until Agent tracing is connected.
