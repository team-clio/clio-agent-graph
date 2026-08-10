"""가벼운 의존성 규칙으로 package 경계의 회귀를 막는다."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "clio_agent_graph"


def _imports(package: str) -> set[str]:
    imported: set[str] = set()
    for path in (PACKAGE_ROOT / package).rglob("*.py"):
        tree = ast.parse(path.read_text())
        imported.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
    return imported


def test_normalization_does_not_depend_on_matching_workflow() -> None:
    assert not any(
        module.startswith("clio_agent_graph.workflows.reporting.matching")
        for module in _imports("workflows/reporting/normalization")
    )


def test_context_does_not_depend_on_orchestration_layer() -> None:
    forbidden = "clio_agent_graph.workflows.orchestration"
    assert not any(module.startswith(forbidden) for module in _imports("context"))
