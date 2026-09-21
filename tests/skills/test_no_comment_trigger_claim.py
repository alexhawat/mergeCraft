"""No consumer doc may advertise a comment trigger the default workflow lacks.

`scripts/example_workflows/minimal.yml.tpl` documents on-demand runs "without a
comment trigger" and the hardened template declares no comment trigger by
design (issue #72 / D5-D6). Ten `SKILL.md` files, `AGENTS.md`, `README.md` and
the generated `llms-full.txt` nevertheless told users to trigger a review by
commenting `@mergecraft review` (#792) — a comment that does nothing and
reports nothing.

The correction from `pre-0.0.1` #682 (commit 037d118c) reads *"The default
workflow does not listen for `@mergecraft review` comments"*. That sentence
must keep passing: this test flags only the *advertising* form (a "comment"
verb offering the trigger), never the corrective or troubleshooting form. A
broad "the string is absent" check would forbid the corrective sentence too.

`llms-full.txt` is generated from `README.md` and `AGENTS.md`
(`scripts/gen_llms_full.py`); `README.md` is checked directly so a hand-edited
bundle cannot hide the claim its source still makes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.ci.workflow_support import REPO_ROOT

_SKILL_GLOB = "skills/**/mergecraft/SKILL.md"

_SKILL_FILES = tuple(
    sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT).glob(_SKILL_GLOB))
)

# The ten shipped skills, plus the docs that carry the same claim.
_DOCS = (*_SKILL_FILES, "AGENTS.md", "README.md", "llms-full.txt")

# "comment" / "commenting" / "commented" offered within a clause of the marker.
_COMMENT_TRIGGER_RE = re.compile(
    r"\bcomment(?:ing|s|ed)?\b[^.!?]{0,40}`?@mergecraft review`?",
    re.IGNORECASE,
)

# A sentence that negates or de-scopes the trigger is the correction, not the
# advertisement. "Never" / "not" / "does not" / "opt-in" all qualify.
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|none|without|opt[- ]in|doesn't|does not|don't|do not|cannot|can't)\b",
    re.IGNORECASE,
)


def test_the_ten_shipped_skills_were_found() -> None:
    """Guard the parametrisation: a moved glob must fail loudly, not vanish."""
    assert len(_SKILL_FILES) == 10, _SKILL_FILES


def _sentences(text: str) -> list[str]:
    """Flatten markdown whitespace, then split into sentences."""
    return re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))


def _advertised_trigger_sentences(text: str) -> list[str]:
    """Sentences that offer commenting `@mergecraft review` as a trigger."""
    offenders: list[str] = []
    for sentence in _sentences(text):
        if "@mergecraft review" not in sentence:
            continue
        if not _COMMENT_TRIGGER_RE.search(sentence):
            continue
        if _NEGATION_RE.search(sentence):
            continue
        offenders.append(sentence)
    return offenders


@pytest.mark.parametrize("relative", _DOCS)
def test_doc_does_not_advertise_a_comment_trigger(relative: str) -> None:
    path = Path(REPO_ROOT) / relative
    assert path.is_file(), f"missing {relative}"
    offenders = _advertised_trigger_sentences(path.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{relative} advertises triggering a review by commenting "
        f"`@mergecraft review`, which the default workflow does not listen for: "
        f"{offenders[0]!r}"
    )


def test_the_corrective_wording_is_allowed() -> None:
    """The test must not forbid the fix it asks for (Q-D1, Q-D4)."""
    correction = (
        "push; open a PR or run `workflow_dispatch`. The default workflow does "
        "not listen for `@mergecraft review` comments."
    )
    troubleshoot = "This repository's workflow does not listen for `@mergecraft review`."
    assert _advertised_trigger_sentences(correction) == []
    assert _advertised_trigger_sentences(troubleshoot) == []


def test_the_advertising_wording_is_flagged() -> None:
    """The exact pre-fix sentences must fail, so the guard is not vacuous."""
    advertised = (
        "Commit only `.mergecraft/config.yaml` and `.github/workflows/mergecraft.yml`, "
        "push, open a PR (or comment `@mergecraft review`).",
        "**Trigger a review** — open a pull request, comment `@mergecraft review`, "
        "or run the workflow via `workflow_dispatch`.",
        "Tell me I can re-run a review any time by commenting `@mergecraft review`.",
    )
    for sentence in advertised:
        assert _advertised_trigger_sentences(sentence), sentence
