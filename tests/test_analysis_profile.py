import pytest

from clio_agent_graph.workflows.orchestration.analysis_profile import (
    AnalysisProfile,
    AnalysisProfileSettings,
)
from clio_agent_graph.workflows.orchestration.graphs.issue_analysis import (
    build_issue_analysis_graph,
)


def test_full_clio_is_the_default_operating_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIO_ANALYSIS_PROFILE", raising=False)
    monkeypatch.delenv("CLIO_BENCHMARK_MODE", raising=False)

    settings = AnalysisProfileSettings.from_env()

    assert settings.profile is AnalysisProfile.FULL_CLIO
    assert settings.benchmark_mode is False


@pytest.mark.parametrize("profile", ["one-shot", "repository-agent"])
def test_simplified_profile_requires_benchmark_mode(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv("CLIO_ANALYSIS_PROFILE", profile)
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "false")

    with pytest.raises(ValueError, match="require CLIO_BENCHMARK_MODE=true"):
        AnalysisProfileSettings.from_env()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("one-shot", AnalysisProfile.ONE_SHOT),
        ("repository-agent", AnalysisProfile.REPOSITORY_AGENT),
        ("full-clio", AnalysisProfile.FULL_CLIO),
    ],
)
def test_profile_is_fixed_from_process_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: AnalysisProfile
) -> None:
    monkeypatch.setenv("CLIO_ANALYSIS_PROFILE", raw)
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "true")

    assert AnalysisProfileSettings.from_env().profile is expected


def test_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIO_ANALYSIS_PROFILE", "experimental")

    with pytest.raises(ValueError, match="must be one of"):
        AnalysisProfileSettings.from_env()


def test_invalid_benchmark_flag_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIO_BENCHMARK_MODE", "sometimes")

    with pytest.raises(ValueError, match="must be a boolean"):
        AnalysisProfileSettings.from_env()


@pytest.mark.parametrize(
    ("profile", "expected_nodes"),
    [
        (AnalysisProfile.ONE_SHOT, {"search_code"}),
        (AnalysisProfile.REPOSITORY_AGENT, set()),
        (
            AnalysisProfile.FULL_CLIO,
            {"search_documents", "search_code", "search_history", "quality_gate"},
        ),
    ],
)
def test_profile_builds_only_selected_graph_nodes(
    profile: AnalysisProfile, expected_nodes: set[str]
) -> None:
    graph = build_issue_analysis_graph(
        AnalysisProfileSettings(profile=profile, benchmark_mode=True)
    )
    nodes = set(graph.get_graph().nodes)
    optional = {"search_documents", "search_code", "search_history", "quality_gate"}

    assert nodes & optional == expected_nodes
    assert {"analyze_issue", "plan_resolution", "assess_risk", "save_analysis"} <= nodes
