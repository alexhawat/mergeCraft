"""No concrete model id is spelled in the agent drivers or the Agents SDK (#1330).

Model ids live in the model catalog (``mergecraft/models.py``). A literal in a
driver drifts from the catalog silently, and a first-party Claude id breaks the
subagents on Bedrock and Vertex. Catalog *aliases* (``anthropic/claude-sonnet``,
``openai/gpt-mini``) are fine; versioned ids are not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "mergecraft"
_SCANNED: Final = (_SRC / "agents", _SRC / "agents_sdk")

# A versioned model id, optionally behind a provider prefix. Catalog aliases
# carry no version and do not match.
_MODEL_ID_RE: Final = re.compile(
    r"^(?:[a-z0-9-]+/)?(?:"
    r"claude-(?:sonnet|opus|haiku|fable)-\d[\w.-]*"
    r"|gpt-(?:\d|4o)[\w.-]*"
    r"|o\d(?:-[\w-]+)?"
    r"|gemini-\d[\w.-]*"
    r")$"
)

# Catalog aliases that happen to look like an id: the alias *is* the catalog key.
_ALLOWED: Final = frozenset({"opencode-go/deepseek-v4.1-flash"})


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _literals() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for root in _SCANNED:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and _MODEL_ID_RE.match(node.value)
                    and node.value not in _ALLOWED
                ):
                    found.append((str(path.relative_to(_SRC)), node.lineno, node.value))
    return found


def test_no_model_id_literal_in_the_agent_drivers() -> None:
    assert _literals() == []


@pytest.mark.parametrize(
    ("value", "is_id"),
    [
        ("claude-sonnet-5", True),
        ("anthropic/claude-opus-4-8", True),
        ("gpt-4o-mini", True),
        ("openai/gpt-5.6-luna", True),
        ("gemini-3.1-pro", True),
        ("anthropic/claude-sonnet", False),
        ("openai/gpt-mini", False),
        ("sonnet", False),
    ],
    ids=[
        "bare-claude",
        "prefixed-claude",
        "gpt-4o",
        "prefixed-gpt",
        "gemini",
        "alias",
        "gpt-alias",
        "portable",
    ],
)
def test_the_lint_pattern_tells_ids_from_aliases(value: str, is_id: bool) -> None:
    assert bool(_MODEL_ID_RE.match(value)) is is_id


def test_claude_subagents_resolve_from_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """First-party: the catalog id; Bedrock/Vertex: Claude Code's portable alias."""
    import json

    from mergecraft.agents.claude import build_agents_json, claude_subagent_model
    from mergecraft.agents.verifier import judge_pin
    from mergecraft.models import resolve_model_slug

    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    catalog = (resolve_model_slug("anthropic/claude-sonnet") or "").split("/", 1)[1]
    assert claude_subagent_model() == catalog

    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    agents = json.loads(build_agents_json())
    assert {spec["model"] for spec in agents.values()} == {"sonnet"}
    # The recorded judge pin is the dispatched value, not a first-party id.
    assert judge_pin(provider="claude").model == "sonnet"


def test_a_bedrock_model_id_route_uses_the_portable_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bedrock/byok`` resolves to ``BEDROCK_MODEL_ID`` with no CLI flag in the parent env."""
    from mergecraft.agents.claude import claude_subagent_model
    from mergecraft.agents.verifier import judge_pin

    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-x-v1:0")
    model = "us.anthropic.claude-sonnet-x-v1:0"

    assert claude_subagent_model(model) == "sonnet"
    assert judge_pin(provider="claude", resolved_model=model).model == "sonnet"
