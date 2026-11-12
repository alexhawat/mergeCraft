"""W2.4 — onboarding pages, the five-minute README, and the author-gate limit.

Pins #1352 (troubleshooting, upgrade, cost, architecture, uninstall pages and the
extended glossary), #1351 (README shortened around a quickstart), and #1310
(``docs/trust-policy.md`` states what ``sandboxTrustedAuthors`` does not establish).
Every ``mergecraft`` command shown in the new pages is resolved against the real
Typer app so a documented command or flag cannot be invented.
"""

from __future__ import annotations

import re
import shlex

import click
import pytest
import typer.main
import yaml

from mergecraft.cli.app import app
from tests.ci.workflow_support import REPO_ROOT, read_text
from tests.docs.test_landing_readme import _section_body

NEW_PAGES = (
    "docs/troubleshooting.md",
    "docs/upgrade.md",
    "docs/cost.md",
    "docs/architecture.md",
    "docs/uninstall.md",
    "docs/agents.md",
)
COMMAND_PAGES = (*NEW_PAGES, "README.md")
GLOSSARY_ANCHORS = (
    "jev",
    "roster",
    "lens",
    "lane",
    "receipts",
    "evidence-packet",
    "terminal-verdict",
)
README_LINE_BUDGET = 300
_FENCE = re.compile(r"```(?:bash|sh|shell|text)?\n(.*?)```", re.DOTALL)


def _manifest_paths() -> set[str]:
    data = yaml.safe_load((REPO_ROOT / "docs" / "manifest.yaml").read_text(encoding="utf-8"))
    return {row["path"] for row in data["pages"]}


def _documented_commands(text: str) -> list[str]:
    """Return fenced shell lines that start with ``mergecraft ``."""
    commands: list[str] = []
    for block in _FENCE.findall(text):
        for raw in block.splitlines():
            line = raw.strip()
            if line.startswith("mergecraft "):
                commands.append(line.split("  #", 1)[0].split(" # ", 1)[0].strip())
    return commands


def _resolve(command: str) -> str | None:
    """Return an error string when *command* names a subcommand or flag that does not exist."""
    try:
        tokens = shlex.split(command)[1:]
    except ValueError:
        return None
    current: click.Command = typer.main.get_command(app)
    index = 0
    while isinstance(current, click.Group) and index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            break
        child = current.get_command(click.Context(current), token)
        if child is None:
            return f"unknown command {token!r} in {command!r}"
        current = child
        index += 1
    if tokens[:2] == ["workflow", "sync"] and not {"--check", "--apply"} & set(tokens):
        return f"`workflow sync` needs --check or --apply in {command!r}"
    known = {opt for param in current.params for opt in (*param.opts, *param.secondary_opts)}
    known.add("--help")
    for token in tokens[index:]:
        if token.startswith("-") and token.split("=", 1)[0] not in known:
            return f"unknown option {token!r} in {command!r}"
    return None


def test_new_pages_exist_and_are_manifested() -> None:
    manifested = _manifest_paths()
    for rel in NEW_PAGES:
        assert (REPO_ROOT / rel).is_file(), f"missing {rel}"
        assert rel in manifested, f"docs/manifest.yaml must register {rel}"


def test_new_pages_are_linked_from_the_docs_index_and_readme() -> None:
    index = read_text("docs/README.md")
    readme = read_text("README.md")
    for rel in NEW_PAGES:
        name = rel.removeprefix("docs/")
        assert f"]({name})" in index, f"docs/README.md must link {rel}"
        assert f"]({rel})" in readme, f"README.md must link {rel}"


def test_new_pages_follow_the_page_template() -> None:
    for rel in NEW_PAGES:
        text = read_text(rel)
        assert text.startswith("# "), f"{rel} needs an H1"
        assert "**Audience:**" in text, f"{rel} needs the Audience line"
        assert "\n## See also\n" in text, f"{rel} needs a See also section"


@pytest.mark.parametrize("page", COMMAND_PAGES, ids=[p.replace("/", "-") for p in COMMAND_PAGES])
def test_documented_commands_exist_in_the_cli(page: str) -> None:
    commands = _documented_commands(read_text(page))
    errors = [err for cmd in commands if (err := _resolve(cmd))]
    assert not errors, f"{page} documents commands the CLI does not have: {errors}"


def test_commands_are_actually_checked() -> None:
    """Guard the checker: it must find commands and reject an invented flag."""
    assert _documented_commands(read_text("docs/troubleshooting.md"))
    assert _resolve("mergecraft workflow sync --apply") is None
    assert _resolve("mergecraft provider disable openai --scope both") is None
    assert _resolve("mergecraft workflow sync --bogus") is not None
    assert _resolve("mergecraft nonsense") is not None
    assert _resolve("mergecraft workflow sync") is not None


def test_glossary_defines_the_audit_terms() -> None:
    text = read_text("docs/glossary.md")
    missing = [a for a in GLOSSARY_ANCHORS if f'<span id="{a}"></span>' not in text]
    assert not missing, f"docs/glossary.md missing terms: {missing}"
    assert 'id="checks"' in text, (
        "glossary must explain the mergecraft vs mergecraft-approval checks"
    )


def test_readme_quickstart_is_the_first_section_and_is_short() -> None:
    text = read_text("README.md")
    first_h2 = re.search(r"^## (.+)$", text, re.MULTILINE)
    assert first_h2 is not None, "README has no H2"
    assert first_h2.group(1).startswith("Quickstart"), (
        "the Quickstart must be the first H2 of the README"
    )
    assert len(text.splitlines()) <= README_LINE_BUDGET, (
        f"README grew past {README_LINE_BUDGET} lines; move prose to docs/"
    )
    quickstart = _section_body(text, r"Quickstart")
    assert quickstart is not None
    for command in (
        "uv tool install mergecraft-action==",
        "mergecraft init",
        "mergecraft provider auth",
        "mergecraft workflow sync --apply",
        "mergecraft doctor",
    ):
        assert command in quickstart, f"quickstart must show `{command}`"
    # The credential step must precede the workflow wiring step.
    assert quickstart.index("mergecraft provider auth") < quickstart.index("workflow sync --apply")


def test_agent_prompts_moved_out_of_the_readme() -> None:
    readme = read_text("README.md")
    assert 'id="for-agents"' in readme, "the #for-agents anchor must survive as a pointer"
    assert "docs/agents.md" in readme
    assert "Also teach your agent" not in readme
    assert "Also teach your agent" in read_text("docs/agents.md")


def test_trust_policy_states_the_author_gate_limit() -> None:
    text = read_text("docs/trust-policy.md")
    assert "closes that gap" not in text
    section = text.split("### What the author gate does and does not establish", 1)
    assert len(section) == 2, "trust-policy.md must have the limits section"
    body = " ".join(section[1].split("\n### ", 1)[0].lower().split())
    for needle in ("free-form", "does not check commit signatures", "does not stop an author"):
        assert needle in body, f"limits section must state: {needle}"
    assert "sandboxTrustedAuthors" in text.split("**Residual risks**", 1)[1][:600]


def test_documented_check_names_are_produced_by_the_scaffold() -> None:
    """`mergecraft` / `mergecraft-approval` are posted when the scaffold's `status_checks` is on."""
    from mergecraft.utils import status_checks

    assert status_checks.APPROVAL_CHECK == "mergecraft-approval"
    scaffold = read_text("src/mergecraft/data/example_workflows/minimal.yml.tpl")
    assert "status_checks: enabled" in scaffold
    for page in ("docs/glossary.md", "docs/uninstall.md", "docs/troubleshooting.md"):
        for name in set(re.findall(r"`(mergecraft(?:-approval)?)`", read_text(page))):
            assert name in {"mergecraft", status_checks.APPROVAL_CHECK}, name


@pytest.mark.parametrize("page", NEW_PAGES, ids=[p.replace("/", "-") for p in NEW_PAGES])
def test_new_pages_have_no_unclosed_markdown_links(page: str) -> None:
    for number, line in enumerate(read_text(page).splitlines(), start=1):
        stripped = re.sub(r"\]\([^)\s]*\)", "", line)
        assert "](" not in stripped, f"{page}:{number} has a link missing its closing paren"
