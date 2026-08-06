import pytest

from clio_agent_graph.services.pcm.errors import PCMValidationError
from clio_agent_graph.services.pcm.markdown import MarkdownSourceParser


def test_splits_markdown_by_heading_hierarchy() -> None:
    units = MarkdownSourceParser().parse(
        document_id="requirements",
        revision="1",
        markdown="""
Introductory context.

# Saved Search

Execution behavior.

## Permissions

Only owners can edit.
""",
    )

    assert [unit.heading_path for unit in units] == [
        (),
        ("Saved Search",),
        ("Saved Search", "Permissions"),
    ]
    assert units[-1].content == "Only owners can edit."


def test_does_not_parse_heading_inside_code_fence() -> None:
    units = MarkdownSourceParser().parse(
        document_id="runbook",
        revision="1",
        markdown="""
# Runbook

```markdown
# This is example content
```

Continue the runbook.
""",
    )

    assert len(units) == 1
    assert "# This is example content" in units[0].content


def test_source_unit_identity_is_deterministic() -> None:
    parser = MarkdownSourceParser()
    arguments = {
        "document_id": "requirements",
        "revision": "1",
        "markdown": "# Permissions\n\nOnly owners can edit.",
    }

    first = parser.parse(**arguments)
    second = parser.parse(**arguments)

    assert first == second
    assert first[0].source_unit_id.startswith("dsu_")
    assert first[0].content_hash.startswith("sha256:")


def test_content_change_changes_source_unit_identity() -> None:
    parser = MarkdownSourceParser()

    first = parser.parse(
        document_id="requirements",
        revision="1",
        markdown="# Permissions\n\nOnly owners can edit.",
    )
    second = parser.parse(
        document_id="requirements",
        revision="1",
        markdown="# Permissions\n\nOwners and administrators can edit.",
    )

    assert first[0].source_unit_id != second[0].source_unit_id
    assert first[0].content_hash != second[0].content_hash


def test_rejects_blank_markdown() -> None:
    with pytest.raises(PCMValidationError, match="must not be blank"):
        MarkdownSourceParser().parse(
            document_id="requirements",
            revision="1",
            markdown="   ",
        )
