"""IA와 Code Explorer·판단 subagent가 공유하는 데이터 계약."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from clio_agent_graph.normalization.models import (
    ContractModel,
    NonEmptyText,
    NormalizedReport,
)

EvidenceId = Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]*$")]
FindingId = Annotated[str, StringConstraints(pattern=r"^F[1-9][0-9]*$")]
HypothesisId = Annotated[str, StringConstraints(pattern=r"^H[1-9][0-9]*$")]


class AnalysisStatus(StrEnum):
    """IA가 정상 실행을 마친 뒤의 분석 상태."""

    COMPLETED = "COMPLETED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceKind(StrEnum):
    """코드 탐색에서 확보한 snapshot의 성격."""

    CODE = "CODE"
    TEST = "TEST"
    CHANGE = "CHANGE"


class HypothesisConfidence(StrEnum):
    """확률이 아니라 현재 근거가 가설을 지지하는 강도."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class HypothesisDisposition(StrEnum):
    """재분석에서 이전 가설이 어떻게 달라졌는지 나타내는 상태."""

    RETAINED = "RETAINED"
    STRENGTHENED = "STRENGTHENED"
    WEAKENED = "WEAKENED"
    DROPPED = "DROPPED"


class AnalysisMode(StrEnum):
    """공통 IA가 어떤 판단 subagent를 사용하는지 나타낸다."""

    INITIAL = "INITIAL"
    REVISION = "REVISION"


class JudgmentPhase(StrEnum):
    """판단 subagent가 탐색 질문과 최종 초안 중 무엇을 만들지 구분한다."""

    PLAN = "PLAN"
    ANALYZE = "ANALYZE"


class AnalysisIssue(ContractModel):
    """IA가 조사할 실제 Issue의 최소 문맥."""

    issue_id: int = Field(gt=0)
    title: NonEmptyText
    summary: NonEmptyText | None = None


class AnalysisBug(ContractModel):
    """Issue의 발생 형태를 보여주는 대표 Bug."""

    bug_id: int = Field(gt=0)
    normalized_report: NormalizedReport


class InitialAnalysisInput(ContractModel):
    """최초 Issue 분석 공개 그래프의 입력."""

    analysis_job_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    issue: AnalysisIssue
    bugs: list[AnalysisBug] = Field(min_length=1, max_length=5)
    trigger_bug_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bug_context(self) -> "InitialAnalysisInput":
        """Bug ID 중복을 막고 trigger Bug가 문맥에 포함됐는지 확인한다."""

        _validate_bug_ids(self.bugs, self.trigger_bug_id)
        return self


class Evidence(ContractModel):
    """분석 당시 실제 판단에 사용한 최대 10줄의 코드 snapshot."""

    evidence_id: EvidenceId
    kind: EvidenceKind
    code_snapshot: NonEmptyText
    observation: NonEmptyText
    file_path: NonEmptyText | None = None
    symbol: NonEmptyText | None = None
    start_line: int | None = Field(default=None, gt=0)
    end_line: int | None = Field(default=None, gt=0)
    change_id: NonEmptyText | None = None

    @field_validator("code_snapshot")
    @classmethod
    def limit_snapshot_lines(cls, value: str) -> str:
        """오래 보관할 핵심 코드만 남기도록 snapshot을 1~10줄로 제한한다."""

        line_count = len(value.splitlines())
        if not 1 <= line_count <= 10:
            raise ValueError("code_snapshot must contain between 1 and 10 lines.")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> "Evidence":
        """라인 metadata가 있다면 시작이 끝보다 뒤에 오지 않게 한다."""

        if (
            self.start_line is not None
            and self.end_line is not None
            and self.start_line > self.end_line
        ):
            raise ValueError("start_line must not exceed end_line.")
        return self


class EvidenceCandidate(ContractModel):
    """Code Explorer가 한 탐색 round에서 반환하는 Evidence 후보."""

    candidate_key: NonEmptyText
    kind: EvidenceKind
    code_snapshot: NonEmptyText
    observation: NonEmptyText
    file_path: NonEmptyText | None = None
    symbol: NonEmptyText | None = None
    start_line: int | None = Field(default=None, gt=0)
    end_line: int | None = Field(default=None, gt=0)
    change_id: NonEmptyText | None = None

    @field_validator("code_snapshot")
    @classmethod
    def limit_snapshot_lines(cls, value: str) -> str:
        """탐색 단계부터 10줄을 넘는 후보가 유입되지 않게 한다."""

        return Evidence.limit_snapshot_lines(value)

    @model_validator(mode="after")
    def validate_line_range(self) -> "EvidenceCandidate":
        """Code Explorer 단계에서도 뒤집힌 라인 범위를 거부한다."""

        if (
            self.start_line is not None
            and self.end_line is not None
            and self.start_line > self.end_line
        ):
            raise ValueError("start_line must not exceed end_line.")
        return self


class CodeRelation(ContractModel):
    """두 Evidence가 코드 구조에서 어떤 관계인지 나타낸다."""

    source_evidence_id: EvidenceId
    target_evidence_id: EvidenceId
    relation_type: NonEmptyText


class RelationCandidate(ContractModel):
    """현재 Evidence ID 또는 이번 응답 candidate key를 잇는 관계 후보."""

    source_ref: NonEmptyText
    target_ref: NonEmptyText
    relation_type: NonEmptyText


class Finding(ContractModel):
    """하나 이상의 Evidence에서 직접 확인되는 사실."""

    finding_id: FindingId
    statement: NonEmptyText
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=20)
    referenced_files: list[NonEmptyText] = Field(default_factory=list)
    referenced_symbols: list[NonEmptyText] = Field(default_factory=list)


class RootCauseHypothesis(ContractModel):
    """확인된 Finding들을 조합해 만든 가능한 발생 원인."""

    hypothesis_id: HypothesisId
    priority: int = Field(ge=1, le=3)
    statement: NonEmptyText
    confidence: HypothesisConfidence
    supporting_finding_ids: list[FindingId] = Field(min_length=1, max_length=10)
    contradicting_finding_ids: list[FindingId] = Field(default_factory=list, max_length=10)
    unknowns: list[NonEmptyText] = Field(default_factory=list)


class HypothesisRevision(ContractModel):
    """이전 가설 하나가 재분석에서 어떻게 바뀌었는지 설명한다."""

    previous_hypothesis_id: HypothesisId
    disposition: HypothesisDisposition
    current_hypothesis_id: HypothesisId | None = None
    reason: NonEmptyText


class RevisionSummary(ContractModel):
    """이전 분석과 새 전체 snapshot 사이의 가설 변화."""

    previous_analysis_job_id: int = Field(gt=0)
    hypothesis_revisions: list[HypothesisRevision] = Field(default_factory=list, max_length=3)
    new_hypothesis_ids: list[HypothesisId] = Field(default_factory=list, max_length=3)


class IssueAnalysis(ContractModel):
    """Supervisor가 저장할 IA의 완전한 분석 snapshot."""

    analysis_job_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    issue_id: int = Field(gt=0)
    status: AnalysisStatus
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    relations: list[CodeRelation] = Field(default_factory=list, max_length=30)
    findings: list[Finding] = Field(default_factory=list, max_length=10)
    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list, max_length=3)
    revision_summary: RevisionSummary | None = None
    warnings: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_analysis_graph(self) -> "IssueAnalysis":
        """Evidence→Finding→Hypothesis 참조와 순차 ID를 모두 검사한다."""

        if self.status is AnalysisStatus.INSUFFICIENT_EVIDENCE:
            if self.evidence or self.relations or self.findings or self.hypotheses:
                raise ValueError("INSUFFICIENT_EVIDENCE must not contain analysis facts.")
            return self
        if not self.evidence or not self.findings or not self.hypotheses:
            raise ValueError("COMPLETED analysis requires evidence, findings, and hypotheses.")

        evidence_ids = [item.evidence_id for item in self.evidence]
        finding_ids = [item.finding_id for item in self.findings]
        hypothesis_ids = [item.hypothesis_id for item in self.hypotheses]
        _require_sequential_ids(evidence_ids, "E")
        _require_sequential_ids(finding_ids, "F")
        _require_sequential_ids(hypothesis_ids, "H")
        _require_sequential_priorities(self.hypotheses)

        evidence_id_set = set(evidence_ids)
        finding_id_set = set(finding_ids)
        for relation in self.relations:
            _require_known_refs(
                [relation.source_evidence_id, relation.target_evidence_id],
                evidence_id_set,
                "relation evidence",
            )
        for finding in self.findings:
            _require_known_refs(finding.evidence_ids, evidence_id_set, "finding evidence")
            referenced_evidence = [
                item for item in self.evidence if item.evidence_id in finding.evidence_ids
            ]
            allowed_files = {
                item.file_path for item in referenced_evidence if item.file_path is not None
            }
            allowed_symbols = {
                item.symbol for item in referenced_evidence if item.symbol is not None
            }
            _require_known_refs(
                finding.referenced_files,
                allowed_files,
                "finding file",
            )
            _require_known_refs(
                finding.referenced_symbols,
                allowed_symbols,
                "finding symbol",
            )
        for hypothesis in self.hypotheses:
            _require_known_refs(
                hypothesis.supporting_finding_ids,
                finding_id_set,
                "supporting finding",
            )
            _require_known_refs(
                hypothesis.contradicting_finding_ids,
                finding_id_set,
                "contradicting finding",
            )
        return self


class ReanalysisInput(ContractModel):
    """기존 분석을 새 Bug 기준으로 갱신하는 공개 그래프 입력."""

    analysis_job_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    issue: AnalysisIssue
    bugs: list[AnalysisBug] = Field(min_length=1, max_length=5)
    trigger_bug_id: int = Field(gt=0)
    previous_analysis: IssueAnalysis

    @model_validator(mode="after")
    def validate_revision_context(self) -> "ReanalysisInput":
        """이전 결과와 새 요청이 같은 Issue의 다른 분석 작업인지 확인한다."""

        _validate_bug_ids(self.bugs, self.trigger_bug_id)
        if self.analysis_job_id == self.previous_analysis.analysis_job_id:
            raise ValueError("Reanalysis requires a new analysis_job_id.")
        if self.project_id != self.previous_analysis.project_id:
            raise ValueError("Reanalysis project_id must match the previous analysis.")
        if self.issue.issue_id != self.previous_analysis.issue_id:
            raise ValueError("Reanalysis issue_id must match the previous analysis.")
        return self


class JudgmentContext(ContractModel):
    """Initial·Revision Judgment Subagent가 공유하는 분석 문맥."""

    mode: AnalysisMode
    analysis_job_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    issue: AnalysisIssue
    bugs: list[AnalysisBug] = Field(min_length=1, max_length=5)
    trigger_bug_id: int = Field(gt=0)
    previous_analysis: IssueAnalysis | None = None

    @model_validator(mode="after")
    def validate_mode_context(self) -> "JudgmentContext":
        """최초 분석에는 과거 결과를 금지하고 재분석에는 필수로 요구한다."""

        _validate_bug_ids(self.bugs, self.trigger_bug_id)
        if self.mode is AnalysisMode.INITIAL and self.previous_analysis is not None:
            raise ValueError("Initial analysis must not contain previous_analysis.")
        if self.mode is AnalysisMode.REVISION and self.previous_analysis is None:
            raise ValueError("Revision analysis requires previous_analysis.")
        return self


class ExplorationDirective(ContractModel):
    """판단 subagent가 Code Explorer에 요청할 다음 질문 목록."""

    questions: list[NonEmptyText] = Field(default_factory=list, max_length=5)
    rationale: NonEmptyText | None = None


class ExplorationRequest(ContractModel):
    """공통 IA가 Code Explorer subgraph에 전달하는 한 round 요청."""

    project_id: int = Field(gt=0)
    issue: AnalysisIssue
    bugs: list[AnalysisBug] = Field(min_length=1, max_length=5)
    questions: list[NonEmptyText] = Field(min_length=1, max_length=5)
    existing_evidence: list[Evidence] = Field(default_factory=list, max_length=20)


class ExplorationResponse(ContractModel):
    """Code Explorer가 한 round에서 찾은 근거와 관계 후보."""

    candidates: list[EvidenceCandidate] = Field(default_factory=list, max_length=10)
    relations: list[RelationCandidate] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_candidate_refs(self) -> "ExplorationResponse":
        """응답 내부 candidate key의 중복을 막는다."""

        keys = [candidate.candidate_key for candidate in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("Evidence candidate keys must be unique in one response.")
        return self


class AnalysisDraft(ContractModel):
    """판단 subagent가 Evidence를 근거로 만드는 최종 분석 초안."""

    findings: list[Finding] = Field(min_length=1, max_length=10)
    hypotheses: list[RootCauseHypothesis] = Field(min_length=1, max_length=3)
    revision_summary: RevisionSummary | None = None


def _validate_bug_ids(bugs: list[AnalysisBug], trigger_bug_id: int) -> None:
    """입력 Bug 식별자들의 공통 불변식을 검사한다."""

    bug_ids = [bug.bug_id for bug in bugs]
    if len(bug_ids) != len(set(bug_ids)):
        raise ValueError("Bug IDs must be unique.")
    if trigger_bug_id not in bug_ids:
        raise ValueError("trigger_bug_id must be included in bugs.")


def _require_sequential_ids(values: list[str], prefix: str) -> None:
    """사람이 읽기 쉬운 E1·F1·H1 순번에 빈칸이나 중복이 없게 한다."""

    expected = [f"{prefix}{index}" for index in range(1, len(values) + 1)]
    if values != expected:
        raise ValueError(f"{prefix} IDs must be unique and sequential.")


def _require_sequential_priorities(hypotheses: list[RootCauseHypothesis]) -> None:
    """가설 우선순위가 목록 순서대로 1부터 이어지는지 확인한다."""

    priorities = [item.priority for item in hypotheses]
    if priorities != list(range(1, len(hypotheses) + 1)):
        raise ValueError("Hypothesis priorities must be unique and sequential.")


def _require_known_refs(values: list[str], allowed: set[str], label: str) -> None:
    """모델이 실제 입력에 없는 ID를 참조하지 못하게 한다."""

    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown {label} IDs: {sorted(unknown)}")
