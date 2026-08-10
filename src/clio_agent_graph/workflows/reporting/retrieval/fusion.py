"""검색 채널 순위를 결합하고 Bug hit를 Issue 후보로 집계한다."""

from collections import defaultdict

from clio_agent_graph.workflows.reporting.matching.models import IssueCandidate, RepresentativeBug
from clio_agent_graph.workflows.reporting.retrieval.models import (
    BugSearchHit,
    FusedBugHit,
    HydratedIssue,
    RetrievalSettings,
    SearchChannel,
)


def fuse_bug_hits(hits: list[BugSearchHit], settings: RetrievalSettings) -> list[FusedBugHit]:
    """채널마다 다른 원점수 대신 순위를 weighted RRF로 결합한다."""

    weights = {
        SearchChannel.EXACT: settings.exact_weight,
        SearchChannel.LEXICAL: settings.lexical_weight,
        SearchChannel.VECTOR: settings.vector_weight,
    }
    maximum = sum(weights.values()) / (settings.rrf_constant + 1)
    scores: defaultdict[int, float] = defaultdict(float)
    reasons: defaultdict[int, list[str]] = defaultdict(list)
    exact_counts: defaultdict[int, int] = defaultdict(int)
    seen_channel_bug: set[tuple[SearchChannel, int]] = set()

    for hit in hits:
        key = (hit.channel, hit.bug_id)
        if key in seen_channel_bug:
            continue
        seen_channel_bug.add(key)
        scores[hit.bug_id] += weights[hit.channel] / (settings.rrf_constant + hit.rank)
        exact_counts[hit.bug_id] = max(exact_counts[hit.bug_id], hit.exact_signal_count)
        channel_reason = f"{hit.channel.value} 검색 {hit.rank}위"
        for reason in [channel_reason, *hit.matched_signals]:
            if reason not in reasons[hit.bug_id]:
                reasons[hit.bug_id].append(reason)

    fused = [
        FusedBugHit(
            bug_id=bug_id,
            score=min(score / maximum, 1.0),
            reasons=reasons[bug_id],
            exact_signal_count=exact_counts[bug_id],
        )
        for bug_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, -item.exact_signal_count, item.bug_id))
    return fused[: settings.fused_bug_limit]


def aggregate_issue_candidates(
    fused_hits: list[FusedBugHit],
    issues: list[HydratedIssue],
    settings: RetrievalSettings,
) -> list[IssueCandidate]:
    """Bug가 많은 Issue의 편향을 막으며 RM 전용 후보를 만든다."""

    hit_by_bug_id = {hit.bug_id: hit for hit in fused_hits}
    candidates: list[IssueCandidate] = []
    for issue in issues:
        matched = [bug for bug in issue.bugs if bug.bug_id in hit_by_bug_id]
        matched.sort(
            key=lambda bug: (
                -hit_by_bug_id[bug.bug_id].score,
                -hit_by_bug_id[bug.bug_id].exact_signal_count,
                -bug.occurrence_count,
                bug.bug_id,
            )
        )
        if not matched:
            continue
        chosen = matched[: settings.representative_bug_limit]
        hits = [hit_by_bug_id[bug.bug_id] for bug in chosen]
        score = hits[0].score
        if len(hits) >= 2:
            score += hits[1].score * settings.second_hit_bonus
        if len(hits) >= 3:
            score += hits[2].score * settings.third_hit_bonus
        reasons: list[str] = []
        for hit in hits:
            for reason in hit.reasons:
                if reason not in reasons:
                    reasons.append(reason)
        candidates.append(
            IssueCandidate(
                issue_id=issue.issue_id,
                title=issue.title,
                summary=issue.summary,
                status=issue.status,
                retrieval_score=min(score, 1.0),
                retrieval_reasons=reasons,
                representative_bugs=[
                    RepresentativeBug(
                        bug_id=bug.bug_id,
                        normalized_report=bug.normalized_report,
                        occurrence_count=bug.occurrence_count,
                    )
                    for bug in chosen
                ],
            )
        )

    candidates.sort(key=lambda item: (-item.retrieval_score, item.issue_id))
    return candidates[: settings.final_issue_limit]
