"""Batch GD — README generated-skill copy prompts (#413).

Pins D10: consumer copy instructions in the "Also teach your agent" fenced
prompt and per-agent one-liners must reference generated harness packages from
``skills/harnesses.yaml`` (``skills/<harness>/mergecraft/`` or install
destinations like ``.agents/skills/mergecraft/``), not the source
``skills/mergecraft/`` tree. Jump-nav developer links may keep
``skills/mergecraft/SKILL.md``. Implementation lands in W8.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.ci.workflow_support import read_text
from tests.docs.support import load_harness_manifest

_ALSO_TEACH_HEADING = re.compile(
    r"^###\s+Also teach your agent",
    re.MULTILINE | re.IGNORECASE,
)
_PER_AGENT_DETAILS = re.compile(
    r"<summary>.*?Per-agent one-liners.*?</summary>(.*?)</details>",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_TEXT_BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)
_SOURCE_SKILL_COPY = re.compile(
    r"(?i)(?:copy|cp)\s+(?:the\s+repo'?s?\s+)?skills/mergecraft/",
)
_NUMBERED_SOURCE_SKILL_COPY = re.compile(
    r"(?i)(?:^|\n)\s*\d+\.\s+Copy skills/mergecraft/",
)
_REPO_SOURCE_INTO_DEST = re.compile(
    r"(?i)(?:repo'?s?\s+)?skills/mergecraft/\s+into",
)


def _generated_harness_package_paths(manifest: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for row in manifest.get("harnesses") or []:
        if not isinstance(row, dict):
            continue
        harness_id = row.get("id")
        if not isinstance(harness_id, str):
            continue
        if row.get("fallback") == "agents-md":
            continue
        paths.add(f"skills/{harness_id}/mergecraft/")
    return paths


def _also_teach_prompt_text(readme_text: str) -> str:
    heading = _ALSO_TEACH_HEADING.search(readme_text)
    assert heading, 'README must keep "### Also teach your agent" copy prompt (D10)'
    region = readme_text[heading.end() :]
    match = _FENCED_TEXT_BLOCK.search(region)
    assert match, '"Also teach your agent" must ship a ```text fenced copy prompt (D10)'
    return match.group(1)


def _per_agent_prompts(readme_text: str) -> dict[str, str]:
    details = _PER_AGENT_DETAILS.search(readme_text)
    assert details, "README must keep the per-agent one-liners <details> block (D10)"
    region = details.group(1)
    prompts: dict[str, str] = {}
    sections = re.split(r"\n\*\*([^*]+)\*\*", region)
    if sections and not sections[0].strip():
        sections = sections[1:]
    for index in range(0, len(sections) - 1, 2):
        agent_name = sections[index].strip()
        body = sections[index + 1]
        match = _FENCED_TEXT_BLOCK.search(body)
        if match:
            prompts[agent_name] = match.group(1)
    return prompts


def _source_skill_copy_offenders(text: str) -> list[str]:
    offenders: list[str] = []
    for pattern in (_SOURCE_SKILL_COPY, _NUMBERED_SOURCE_SKILL_COPY, _REPO_SOURCE_INTO_DEST):
        for match in pattern.finditer(text):
            snippet = match.group(0).strip()
            if snippet and snippet not in offenders:
                offenders.append(snippet)
    return offenders


def _references_generated_harness_packages(text: str, *, package_paths: set[str]) -> bool:
    lowered = text.lower()
    if any(path.lower() in lowered for path in package_paths):
        return True
    return "make agent-packages" in lowered


def test_jump_nav_may_link_source_skill_developer_path() -> None:
    """D10: hero jump-nav may keep the in-repo ``skills/mergecraft/SKILL.md`` link."""
    text = read_text("README.md")
    hero = text.split("---", 1)[0]
    assert "[Agent skill](skills/mergecraft/SKILL.md)" in hero, (
        "README hero jump-nav should keep the developer link to skills/mergecraft/SKILL.md (D10)"
    )


def test_also_teach_agent_prompt_does_not_instruct_source_skill_copy() -> None:
    """Consumer copy prompt must not tell readers to copy repo-root skills/mergecraft/."""
    prompt = _also_teach_prompt_text(read_text("README.md"))
    offenders = _source_skill_copy_offenders(prompt)
    assert not offenders, (
        '"Also teach your agent" must not instruct copying source skills/mergecraft/ '
        f"(use skills/<harness>/mergecraft/ per harnesses.yaml): {offenders}"
    )


def test_also_teach_agent_prompt_references_generated_harness_packages() -> None:
    """Consumer copy prompt must name a generated harness package or install destination."""
    manifest = load_harness_manifest()
    prompt = _also_teach_prompt_text(read_text("README.md"))
    assert _references_generated_harness_packages(
        prompt,
        package_paths=_generated_harness_package_paths(manifest),
    ), (
        '"Also teach your agent" must reference skills/<harness>/mergecraft/ from '
        "skills/harnesses.yaml or a declared install destination (D10)"
    )


def test_per_agent_one_liners_do_not_instruct_source_skill_copy() -> None:
    """Per-agent fenced prompts must not instruct copying repo-root skills/mergecraft/."""
    prompts = _per_agent_prompts(read_text("README.md"))
    assert prompts, "per-agent one-liners must include at least one fenced prompt (D10)"
    offenders: list[str] = []
    for agent, prompt in prompts.items():
        for snippet in _source_skill_copy_offenders(prompt):
            offenders.append(f"{agent}: {snippet}")
    assert not offenders, (
        f"per-agent one-liners must not instruct copying source skills/mergecraft/: {offenders}"
    )


@pytest.mark.parametrize(
    "agent_name",
    ["Cursor", "OpenCode"],
)
def test_per_agent_skill_copy_prompts_reference_harness_packages(agent_name: str) -> None:
    """Agents that install the skill must point at generated harness packages."""
    manifest = load_harness_manifest()
    prompts = _per_agent_prompts(read_text("README.md"))
    prompt = prompts.get(agent_name)
    assert prompt is not None, f"missing fenced prompt for {agent_name!r} (D10)"
    assert _references_generated_harness_packages(
        prompt,
        package_paths=_generated_harness_package_paths(manifest),
    ), (
        f"{agent_name} one-liner must reference skills/<harness>/mergecraft/ from "
        "skills/harnesses.yaml or a declared install destination (D10)"
    )
