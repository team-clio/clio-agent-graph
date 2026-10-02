"""Benchmark에서 비교할 Issue Analysis 실행 프로필 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from clio_agent_graph.observability.benchmark import benchmark_mode_enabled


class AnalysisProfile(StrEnum):
    """동일 분석 계약에서 근거 수집과 검증 구성을 구분한다."""

    ONE_SHOT = "one-shot"
    REPOSITORY_AGENT = "repository-agent"
    FULL_CLIO = "full-clio"


@dataclass(frozen=True)
class AnalysisTopology:
    """프로필별로 실제 graph에 연결할 검색·검증 단계."""

    search_documents: bool
    search_code: bool
    search_history: bool
    quality_gate: bool


_TOPOLOGIES = {
    AnalysisProfile.ONE_SHOT: AnalysisTopology(
        search_documents=False,
        search_code=True,
        search_history=False,
        quality_gate=False,
    ),
    AnalysisProfile.REPOSITORY_AGENT: AnalysisTopology(
        search_documents=False,
        search_code=False,
        search_history=False,
        quality_gate=False,
    ),
    AnalysisProfile.FULL_CLIO: AnalysisTopology(
        search_documents=True,
        search_code=True,
        search_history=True,
        quality_gate=True,
    ),
}


@dataclass(frozen=True)
class AnalysisProfileSettings:
    """프로세스 시작 시 고정되는 분석 프로필과 benchmark 보호 조건."""

    profile: AnalysisProfile = AnalysisProfile.FULL_CLIO
    benchmark_mode: bool = False

    @property
    def topology(self) -> AnalysisTopology:
        return _TOPOLOGIES[self.profile]

    def __post_init__(self) -> None:
        if self.profile is not AnalysisProfile.FULL_CLIO and not self.benchmark_mode:
            raise ValueError("Simplified analysis profiles require CLIO_BENCHMARK_MODE=true.")

    @classmethod
    def from_env(cls) -> AnalysisProfileSettings:
        raw_profile = os.getenv("CLIO_ANALYSIS_PROFILE", AnalysisProfile.FULL_CLIO.value)
        try:
            profile = AnalysisProfile(raw_profile.strip().casefold())
        except ValueError as exc:
            supported = ", ".join(profile.value for profile in AnalysisProfile)
            raise ValueError(f"CLIO_ANALYSIS_PROFILE must be one of: {supported}.") from exc
        return cls(
            profile=profile,
            benchmark_mode=benchmark_mode_enabled(),
        )
