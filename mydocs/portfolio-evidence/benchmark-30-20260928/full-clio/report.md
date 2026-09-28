# Clio Benchmark — full-clio

- Run: `20260928T065850Z-59223a30`
- Repetition: 1
- Cases: 30
- Mean quality score: **92.68/100**
- Pass rate: **93.3%**

## Quality dimensions

| Dimension | Mean |
|---|---:|
| verdict | 100.0% |
| root_cause | 95.0% |
| code_location | 91.7% |
| evidence_quality | 98.2% |
| reproduction | 71.1% |
| uncertainty | 76.7% |

## Cases

| Suite / case | Score | Result | Duration |
|---|---:|---|---:|
| feature-flags-30 / cache-tenant-leak-detailed | 87.92 | PASS | 38.95s |
| feature-flags-30 / cache-tenant-leak-short | 90.00 | PASS | 34.50s |
| feature-flags-30 / cache-tenant-leak-symptom | 96.67 | PASS | 36.68s |
| feature-flags-30 / cache-false-miss-detailed | 86.67 | PASS | 38.53s |
| feature-flags-30 / cache-false-miss-short | 65.83 | FAIL | 34.46s |
| feature-flags-30 / cache-false-miss-symptom | 88.75 | PASS | 32.45s |
| feature-flags-30 / auth-role-escalation-detailed | 99.17 | PASS | 26.40s |
| feature-flags-30 / auth-role-escalation-short | 100.00 | PASS | 28.37s |
| feature-flags-30 / auth-role-escalation-symptom | 97.50 | PASS | 30.42s |
| feature-flags-30 / auth-project-scope-detailed | 96.04 | PASS | 28.45s |
| feature-flags-30 / auth-project-scope-short | 69.17 | FAIL | 26.41s |
| feature-flags-30 / auth-project-scope-symptom | 86.25 | PASS | 32.47s |
| feature-flags-30 / rollout-boundary-detailed | 100.00 | PASS | 26.40s |
| feature-flags-30 / rollout-boundary-short | 95.83 | PASS | 26.36s |
| feature-flags-30 / rollout-boundary-symptom | 100.00 | PASS | 30.46s |
| feature-flags-30 / rollout-hash-unstable-detailed | 100.00 | PASS | 36.49s |
| feature-flags-30 / rollout-hash-unstable-short | 96.67 | PASS | 30.36s |
| feature-flags-30 / rollout-hash-unstable-symptom | 99.38 | PASS | 32.44s |
| feature-flags-30 / target-country-case-detailed | 90.00 | PASS | 32.48s |
| feature-flags-30 / target-country-case-short | 85.83 | PASS | 30.61s |
| feature-flags-30 / target-country-case-symptom | 97.50 | PASS | 30.46s |
| feature-flags-30 / target-empty-allowlist-detailed | 86.21 | PASS | 34.59s |
| feature-flags-30 / target-empty-allowlist-short | 94.17 | PASS | 28.74s |
| feature-flags-30 / target-empty-allowlist-symptom | 100.00 | PASS | 26.39s |
| feature-flags-30 / repository-delete-case-detailed | 93.67 | PASS | 32.45s |
| feature-flags-30 / repository-delete-case-short | 100.00 | PASS | 58.74s |
| feature-flags-30 / repository-delete-case-symptom | 93.45 | PASS | 34.43s |
| feature-flags-30 / repository-list-tenant-detailed | 100.00 | PASS | 32.39s |
| feature-flags-30 / repository-list-tenant-short | 90.33 | PASS | 36.44s |
| feature-flags-30 / repository-list-tenant-symptom | 93.33 | PASS | 34.62s |

> Token, model-call and tool-call metrics remain N/A until Agent tracing is connected.
