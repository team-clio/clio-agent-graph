import pytest

from clio_agent_graph.normalization.models import ErrorSignals, NormalizedReport
from clio_agent_graph.retrieval.fusion import aggregate_issue_candidates, fuse_bug_hits
from clio_agent_graph.retrieval.models import (
    BugSearchHit,
    HydratedIssue,
    RetrievalSettings,
    SearchChannel,
    StoredRepresentativeBug,
)


def _hit(
    bug_id: int,
    channel: SearchChannel,
    rank: int,
    *,
    exact_count: int = 0,
) -> BugSearchHit:
    return BugSearchHit(
        bug_id=bug_id,
        channel=channel,
        rank=rank,
        raw_score=0.9,
        matched_signals=[f"{channel.value} 일치"],
        exact_signal_count=exact_count,
    )


def _bug(bug_id: int, occurrence_count: int = 1) -> StoredRepresentativeBug:
    return StoredRepresentativeBug(
        bug_id=bug_id,
        normalized_report=NormalizedReport(
            bug_report_id=bug_id + 100,
            observed_behavior=f"현상 {bug_id}",
            error_signals=ErrorSignals(error_type="PaymentException"),
        ),
        occurrence_count=occurrence_count,
    )


def test_weighted_rrf_favors_exact_and_deduplicates_same_channel_bug() -> None:
    settings = RetrievalSettings()
    result = fuse_bug_hits(
        [
            _hit(1, SearchChannel.EXACT, 1, exact_count=2),
            _hit(1, SearchChannel.EXACT, 2, exact_count=1),
            _hit(2, SearchChannel.LEXICAL, 1),
            _hit(1, SearchChannel.VECTOR, 2),
        ],
        settings,
    )

    assert [item.bug_id for item in result] == [1, 2]
    expected = ((2 / 61) + (1 / 62)) / (4 / 61)
    assert result[0].score == pytest.approx(expected)
    assert result[0].exact_signal_count == 2


def test_issue_aggregation_uses_limited_bonus_and_representative_limit() -> None:
    settings = RetrievalSettings()
    fused = fuse_bug_hits(
        [
            _hit(1, SearchChannel.EXACT, 1, exact_count=2),
            _hit(2, SearchChannel.EXACT, 2, exact_count=1),
            _hit(3, SearchChannel.LEXICAL, 1),
            _hit(4, SearchChannel.VECTOR, 1),
        ],
        settings,
    )
    issues = [
        HydratedIssue(
            issue_id=19,
            title="결제 실패",
            status="CLOSED",
            bugs=[_bug(1), _bug(2), _bug(3), _bug(4)],
        )
    ]

    candidates = aggregate_issue_candidates(fused, issues, settings)

    assert len(candidates) == 1
    assert candidates[0].status == "CLOSED"
    assert len(candidates[0].representative_bugs) == 3
    assert [bug.bug_id for bug in candidates[0].representative_bugs] == [1, 2, 3]
    hit_by_id = {item.bug_id: item for item in fused}
    expected = hit_by_id[1].score + hit_by_id[2].score * 0.1 + hit_by_id[3].score * 0.05
    assert candidates[0].retrieval_score == pytest.approx(min(expected, 1.0))


def test_issue_candidate_order_is_deterministic_on_equal_score() -> None:
    settings = RetrievalSettings()
    fused = fuse_bug_hits(
        [_hit(1, SearchChannel.VECTOR, 1), _hit(2, SearchChannel.VECTOR, 1)],
        settings,
    )
    issues = [
        HydratedIssue(issue_id=20, title="둘", bugs=[_bug(2)]),
        HydratedIssue(issue_id=10, title="하나", bugs=[_bug(1)]),
    ]

    candidates = aggregate_issue_candidates(fused, issues, settings)

    assert [candidate.issue_id for candidate in candidates] == [10, 20]
