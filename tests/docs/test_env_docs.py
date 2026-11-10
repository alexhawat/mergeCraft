"""``.env.example`` and the provider tables are generated and checked (W2.3-2, W2.3-3).

``scripts/gen_env_example.py`` and ``scripts/gen_provider_docs.py`` build those
files from the provider catalog and ``docs/cli.md``; ``make docs-check`` fails on
drift. These tests add the contracts the generators cannot express on their own:
the example file ships names only, every name in it is read by something, the
generated tables agree with the seeding code, and no doc contradicts the canonical
prerequisites.
"""

from __future__ import annotations

import re

from mergecraft.config.agent_roster import preferred_model_slug
from mergecraft.models import PROVIDERS
from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import load_script_module

_ENV_EXAMPLE = REPO_ROOT / ".env.example"
_NAME = re.compile(r"^#?\s*([A-Z][A-Z0-9_<>]*)=", re.MULTILINE)


def _env_script():
    return load_script_module(REPO_ROOT / "scripts" / "gen_env_example.py")


def _provider_script():
    return load_script_module(REPO_ROOT / "scripts" / "gen_provider_docs.py")


def _read_corpus(*roots: str) -> str:
    chunks: list[str] = []
    for root in roots:
        path = REPO_ROOT / root
        files = [path] if path.is_file() else [f for f in path.rglob("*") if f.is_file()]
        for file in files:
            if "node_modules" in file.parts or file.suffix in {".pyc", ".png", ".gz"}:
                continue
            chunks.append(file.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def test_env_example_is_generated_and_current() -> None:
    script = _env_script()
    assert script.render() == _ENV_EXAMPLE.read_text(encoding="utf-8")


def test_env_example_ships_names_only() -> None:
    """Copying the file must not change a run: nothing active, nothing with a value."""
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or (line.startswith("#") and "=" not in line):
            continue
        assert line.startswith("# "), f".env.example has an active assignment: {line!r}"
        assert line.rstrip().endswith("="), f".env.example line carries a value: {line!r}"


def test_env_example_has_no_stale_references() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    for stale in ("NOUS_API_KEY", "MEAT_", "OPENAI_API_KEY_MEAT", ".ignorelocal", "OTEL_ENDPOINT="):
        assert stale not in text.replace("MERGECRAFT_OTEL_ENDPOINT=", ""), stale
    assert "CODEX_BASE_URL" not in text


def test_every_env_example_name_is_read_by_something() -> None:
    names = {
        n
        for n in _NAME.findall(_ENV_EXAMPLE.read_text(encoding="utf-8"))
        if "<" not in n and not n.startswith("LLM_PROVIDER_")
    }
    product = _read_corpus("src")
    catalog = {
        name
        for provider in PROVIDERS.values()
        for name in (*provider.env_vars, *provider.managed_credentials)
    }
    contributor = _read_corpus("tests", "scripts", "Makefile", ".pre-commit-config.yaml")
    unread = sorted(
        name
        for name in names
        if name not in catalog
        and not re.search(rf"\b{re.escape(name)}\b", product)
        and not (
            name in {n for n, _ in _env_script().CONTRIBUTOR_KNOBS}
            and re.search(rf"\b{re.escape(name)}\b", contributor)
        )
    )
    assert not unread, f".env.example names variables nothing reads: {unread}"


def test_cli_env_table_rows_are_all_in_env_example() -> None:
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [
        name for name, _, _ in _env_script().cli_env_table_rows() if f"# {name}=" not in text
    ]
    assert not missing, missing


def test_provider_table_recommended_model_is_what_provider_auth_seeds() -> None:
    table = _provider_script().render_provider_table()
    for label, provider in PROVIDERS.items():
        row = next(line for line in table.splitlines() if f"provider auth {label}`" in line)
        assert provider.display_name in row
        if any(model.preferred for model in provider.models.values()):
            assert f"`{preferred_model_slug(label)}`" in row


def test_every_catalog_provider_is_in_the_compatibility_matrix() -> None:
    text = (REPO_ROOT / "docs" / "compatibility-matrix.md").read_text(encoding="utf-8")
    missing = [label for label in PROVIDERS if f"`{label}`" not in text]
    assert not missing, missing


def test_provider_docs_are_current() -> None:
    script = _provider_script()
    for rel, new_text in script._generate().items():
        assert (REPO_ROOT / rel).read_text(encoding="utf-8") == new_text, rel


def test_no_doc_requires_system_python_or_unconditional_gh() -> None:
    """The prerequisite text is generated; hand-written prose must not contradict it."""
    offenders: list[str] = []
    for rel in (
        "README.md",
        "docs/install.md",
        "AGENTS-mergecraft.md",
        "commands/mergecraft-setup.md",
        "skills/mergecraft/SKILL.md",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        outside = re.sub(
            r"<!-- BEGIN:requirements -->.*?<!-- END:requirements -->", "", text, flags=re.DOTALL
        )
        outside = "\n".join(ln for ln in outside.splitlines() if "mergeCraft itself" not in ln)
        for pattern in (
            r"Python \*\*3\.11\+\*\*",
            r"authenticated `?gh`? CLI",
            r"authenticated \[GitHub CLI\]",
        ):
            if re.search(pattern, outside):
                offenders.append(f"{rel}: {pattern}")
    assert not offenders, offenders
