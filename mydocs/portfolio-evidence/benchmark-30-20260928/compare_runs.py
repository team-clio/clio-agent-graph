"""Validate and print the paired 30-case benchmark comparison.

Run from any directory: python compare_runs.py
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parent
PROFILES = ("full-clio", "one-shot")
SUFFIXES = ("-detailed", "-short", "-symptom")


def load(profile: str) -> dict:
    run_dir = ROOT / profile
    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    assert manifest["status"] == "completed", (profile, manifest["status"])
    assert manifest["case_count"] == summary["case_count"] == 30
    assert summary["profile"] == profile

    cases = {case["case_id"]: case for case in summary["cases"]}
    assert len(cases) == 30
    projects = set()
    fixture_shas = set()
    for case_id in cases:
        result_path = run_dir / "cases" / "feature-flags-30" / case_id / "result.json"
        result = json.loads(result_path.read_text())
        assert result["execution_error"] is None, (profile, case_id)
        projects.add(result["project"]["id"])
        fixture_shas.add(result["fixture_commit_sha"])
    assert len(projects) == 30, (profile, "project reuse")
    assert len(fixture_shas) == 1, (profile, fixture_shas)
    return {"manifest": manifest, "summary": summary, "cases": cases, "sha": fixture_shas.pop()}


def defect(case_id: str) -> str:
    return next(case_id[: -len(suffix)] for suffix in SUFFIXES if case_id.endswith(suffix))


def main() -> None:
    full, baseline = (load(profile) for profile in PROFILES)
    assert full["sha"] == baseline["sha"]
    assert set(full["cases"]) == set(baseline["cases"])
    a, b = full["summary"], baseline["summary"]
    pairs = [(full["cases"][case_id], baseline["cases"][case_id]) for case_id in sorted(full["cases"])]
    wins = sum(x["score"] > y["score"] for x, y in pairs)
    losses = sum(x["score"] < y["score"] for x, y in pairs)
    ties = 30 - wins - losses

    print(f"Fixture SHA: `{full['sha']}`")
    print(f"Run IDs: `{a['run_id']}` / `{b['run_id']}`")
    print("| 지표 | full-clio | one-shot | 차이 |")
    print("|---|---:|---:|---:|")
    print(f"| 평균 점수 / 100 | {a['mean_score']:.2f} | {b['mean_score']:.2f} | {a['mean_score'] - b['mean_score']:+.2f}p |")
    print(f"| 통과율 (70점 이상) | {a['pass_rate']:.1%} | {b['pass_rate']:.1%} | {(a['pass_rate'] - b['pass_rate'])*100:+.1f}%p |")
    print(f"| 분석 평균 소요시간 | {a['efficiency']['mean_duration_seconds']:.1f}s | {b['efficiency']['mean_duration_seconds']:.1f}s | {a['efficiency']['mean_duration_seconds'] - b['efficiency']['mean_duration_seconds']:+.1f}s |")
    print(f"Paired outcomes: full-clio better {wins}, one-shot better {losses}, tie {ties}.")
    print("| 결함 그룹 (각 3건) | full-clio | one-shot | 차이 |")
    print("|---|---:|---:|---:|")
    for name in sorted({defect(case_id) for case_id in full["cases"]}):
        selected = [(x, y) for x, y in pairs if defect(x["case_id"]) == name]
        x_mean = mean(x["score"] for x, _ in selected)
        y_mean = mean(y["score"] for _, y in selected)
        print(f"| {name} | {x_mean:.2f} | {y_mean:.2f} | {x_mean - y_mean:+.2f}p |")
    print("| 보고 문구 (각 10건) | full-clio | one-shot | 차이 |")
    print("|---|---:|---:|---:|")
    for suffix in SUFFIXES:
        selected = [(x, y) for x, y in pairs if x["case_id"].endswith(suffix)]
        x_mean = mean(x["score"] for x, _ in selected)
        y_mean = mean(y["score"] for _, y in selected)
        print(f"| {suffix[1:]} | {x_mean:.2f} | {y_mean:.2f} | {x_mean - y_mean:+.2f}p |")
    for label, summary in (("full-clio", a), ("one-shot", b)):
        durations = [case["efficiency"]["duration_seconds"] for case in summary["cases"]]
        print(f"{label} median analysis duration: {median(durations):.1f}s")


if __name__ == "__main__":
    main()
