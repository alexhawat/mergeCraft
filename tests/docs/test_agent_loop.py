"""W9 / #383 — agent-loop reference workflow (``docs/agent-loop.md``).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
(Batch DD). W9.1 landed — xfail markers removed.

D16: nothing under ``skills/``. D6: do not treat AGENTS.md / README.md as
this contract. D12: the page may cite both ``protocol_version`` and
``schema_version``.
"""

from __future__ import annotations

import re

import yaml

from tests.ci.workflow_support import REPO_ROOT

AGENT_LOOP_RELPATH = "docs/agent-loop.md"
AGENT_LOOP_DOC = REPO_ROOT / AGENT_LOOP_RELPATH
MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"

_DOCUMENTED_EVENTS = (
    "run_started",
    "phase",
    "finding",
    "verdict",
    "run_finished",
)
_NAMED_EXITS = ("0", "10", "11", "12", "20", "30", "40", "50", "2")
_LOOP_STEPS = (
    "change",
    "review",
    "finding",
    "decide",
)


def _page_text() -> str:
    assert AGENT_LOOP_DOC.is_file(), (
        f"W9.1 must ship {AGENT_LOOP_RELPATH} (not AGENTS.md, README.md, or skills/)"
    )
    return AGENT_LOOP_DOC.read_text(encoding="utf-8")


def _manifest_pages() -> list[dict[object, object]]:
    assert MANIFEST.is_file(), "docs/manifest.yaml must exist"
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    pages = data.get("pages")
    assert isinstance(pages, list), "docs/manifest.yaml must define a pages: list"
    return [row for row in pages if isinstance(row, dict)]


def test_agent_loop_page_exists_under_docs() -> None:
    """Happy: the loop ships as ``docs/agent-loop.md``, not under ``skills/``."""
    assert AGENT_LOOP_DOC.is_file(), f"missing {AGENT_LOOP_RELPATH}"
    rel = AGENT_LOOP_DOC.relative_to(REPO_ROOT).as_posix()
    assert rel == AGENT_LOOP_RELPATH
    assert not rel.startswith("skills/"), rel


def test_agent_loop_is_not_a_skill_or_landing_page() -> None:
    """Edge: D16 / D6 — the loop must not live in skills/, AGENTS.md, or README.md."""
    assert not (REPO_ROOT / "skills" / "agent-loop.md").is_file()
    assert AGENT_LOOP_DOC.is_file()
    skills_loop = (
        list((REPO_ROOT / "skills").rglob("*agent-loop*"))
        if (REPO_ROOT / "skills").is_dir()
        else []
    )
    assert skills_loop == [], f"D16: do not create skills/** loop docs: {skills_loop}"


def test_agent_loop_describes_the_five_step_loop() -> None:
    """Happy: change → review → consume findings → decide → review the new diff."""
    text = _page_text().casefold()
    for token in _LOOP_STEPS:
        assert token in text, f"loop page must describe step involving {token!r}"
    assert "diff" in text
    assert "consume" in text or "consumes" in text or "finding" in text


def test_agent_loop_names_review_agent_and_jsonl_events() -> None:
    """Happy: names ``mergecraft review --agent`` and the five JSONL events."""
    text = _page_text()
    collapsed = re.sub(r"\s+", " ", text)
    assert "mergecraft review" in collapsed
    assert "--agent" in collapsed
    for event in _DOCUMENTED_EVENTS:
        assert event in text, f"loop page must name JSONL event {event!r}"


def test_agent_loop_points_at_exit_codes() -> None:
    """Happy: cites ``docs/EXIT-CODES.md`` (or EXIT-CODES) and named exits."""
    text = _page_text()
    assert (
        "EXIT-CODES" in text or "exit-codes" in text.casefold() or "exit codes" in text.casefold()
    )
    for code in _NAMED_EXITS:
        assert re.search(rf"\b{re.escape(code)}\b", text), (
            f"loop page must mention named exit {code} (contract, not a full table dump)"
        )


def test_manifest_includes_agent_loop_row() -> None:
    """Happy: append-only manifest row for ``docs/agent-loop.md``.

    Any matching row is enough (need not be last — lane B also appends).
    Existing rows must not be required to change.
    """
    pages = _manifest_pages()
    matching = [row for row in pages if row.get("path") == AGENT_LOOP_RELPATH]
    assert matching, (
        f"docs/manifest.yaml must include an append-only row with path: {AGENT_LOOP_RELPATH}"
    )
    row = matching[0]
    for field in ("audience", "template", "purpose"):
        value = row.get(field)
        assert isinstance(value, str), f"agent-loop manifest row needs {field}: str"
        assert value.strip(), f"agent-loop manifest row needs non-empty {field}:"


def test_agent_loop_cites_d12_version_fields() -> None:
    """Edge: both ``protocol_version`` and ``schema_version`` survive (D12 adapter)."""
    text = _page_text()
    assert "protocol_version" in text
    assert "schema_version" in text
